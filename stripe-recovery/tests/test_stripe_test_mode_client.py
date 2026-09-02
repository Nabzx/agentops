"""StripeTestModeClient, per ADR-0013.

No real network call anywhere in this file - the SDK's own resource methods are
monkeypatched to return canned objects, exactly the testing decision ADR-0013 made.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
import stripe

from stripe_recovery.client import (
    ChargeNotFoundError,
    StripeRecoverySettings,
    StripeTestModeClient,
)


def _settings(key: str = "sk_test_abc123") -> StripeRecoverySettings:
    return StripeRecoverySettings.model_validate({"secret_key": key})


def _payment_intent(**overrides: Any) -> stripe.PaymentIntent:
    fields: dict[str, Any] = {
        "id": "pi_1",
        "object": "payment_intent",
        "amount": 4700,
        "customer": "cus_alice",
        "status": "requires_payment_method",
        "last_payment_error": {
            "code": "card_declined",
            "decline_code": "insufficient_funds",
        },
    }
    fields.update(overrides)
    return stripe.PaymentIntent.construct_from(fields, "sk_test_dummy")


class _FakePage:
    """Stands in for the SDK's ListObject - just enough to satisfy
    ``auto_paging_iter()`` the way ``StripeTestModeClient`` calls it.
    """

    def __init__(self, items: list[stripe.PaymentIntent]) -> None:
        self._items = items

    def auto_paging_iter(self) -> AsyncIterator[stripe.PaymentIntent]:
        return self._iter()

    async def _iter(self) -> AsyncIterator[stripe.PaymentIntent]:
        for item in self._items:
            yield item


def test_looks_live_flags_a_live_key() -> None:
    assert _settings("sk_live_abc").looks_live() is True
    assert _settings("rk_live_abc").looks_live() is True
    assert _settings("sk_test_abc").looks_live() is False


def test_refuses_to_build_with_a_live_key() -> None:
    with pytest.raises(ValueError, match="live-looking"):
        StripeTestModeClient(_settings("sk_live_abc123"))


def test_builds_with_allow_live_explicitly_set() -> None:
    # Never used in this repo, but the escape hatch itself should work as documented.
    StripeTestModeClient(_settings("sk_live_abc123"), allow_live=True)


async def test_list_failed_charges_keeps_only_retryable_shaped_intents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = StripeTestModeClient(_settings())
    page = _FakePage(
        [
            _payment_intent(id="pi_retryable"),
            _payment_intent(
                id="pi_hard_decline",
                last_payment_error={
                    "code": "card_declined",
                    "decline_code": "stolen_card",
                },
            ),
            _payment_intent(id="pi_succeeded", status="succeeded"),
            _payment_intent(id="pi_no_error", last_payment_error=None),
        ]
    )

    async def fake_list_async(**_: Any) -> _FakePage:
        return page

    monkeypatch.setattr(
        client._client.v1.payment_intents, "list_async", fake_list_async
    )

    charges = await client.list_failed_charges()

    # Every candidate the real Stripe account might return comes back - the detector
    # (not this client) is what filters by the ADR-0011 allow-list. This client's own
    # job is narrower: only intents that are actually still failed with a decline code.
    assert {c.id for c in charges} == {"pi_retryable", "pi_hard_decline"}
    retryable = next(c for c in charges if c.id == "pi_retryable")
    assert retryable.decline_code == "insufficient_funds"
    assert retryable.amount_pence == 4700
    assert retryable.customer_id == "cus_alice"


async def test_confirm_payment_intent_returns_the_succeeded_intent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = StripeTestModeClient(_settings())
    confirmed = _payment_intent(status="succeeded", last_payment_error=None)
    seen_options: dict[str, Any] = {}

    async def fake_confirm_async(intent_id: str, options: Any = None) -> Any:
        seen_options["intent_id"] = intent_id
        seen_options["options"] = options
        return confirmed

    monkeypatch.setattr(
        client._client.v1.payment_intents, "confirm_async", fake_confirm_async
    )

    result = await client.confirm_payment_intent("pi_1", idempotency_key="key-1")

    assert result.status == "succeeded"
    assert seen_options["intent_id"] == "pi_1"
    assert seen_options["options"] == {"idempotency_key": "key-1"}


async def test_confirm_payment_intent_raises_charge_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = StripeTestModeClient(_settings())

    async def fake_confirm_async(*_: Any, **__: Any) -> Any:
        # stripe's error classes aren't fully typed themselves.
        raise stripe.InvalidRequestError(  # type: ignore[no-untyped-call]
            "No such payment_intent", param="intent"
        )

    monkeypatch.setattr(
        client._client.v1.payment_intents, "confirm_async", fake_confirm_async
    )

    with pytest.raises(ChargeNotFoundError):
        await client.confirm_payment_intent("pi_missing", idempotency_key="key-1")
