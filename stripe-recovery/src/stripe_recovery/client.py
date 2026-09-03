"""The seam between this flagship and Stripe's API.

``StripeClient`` is a small Protocol; ``FakeStripeClient`` is an in-memory stand-in
seeded with fake charges, so this whole package runs with zero setup and no Stripe
account - that stays the default everywhere in this repo. ``StripeTestModeClient`` wraps
the official Stripe SDK against the same Protocol, per ADR-0013; it's only reached when
a caller sets ``STRIPE_RECOVERY_SECRET_KEY`` and asks for it explicitly.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Protocol

import stripe
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Decline codes considered safe to retry, per ADR-0011. An allow-list, never a
# deny-list: an unrecognised or future decline code is never treated as retryable.
RETRYABLE_DECLINE_CODES: frozenset[str] = frozenset(
    {"insufficient_funds", "try_again_later", "processing_error"}
)


@dataclass(frozen=True)
class FailedCharge:
    """A charge, as Stripe's own API would describe it. ``status`` starts "failed" and
    becomes "succeeded" once a retry lands.
    """

    id: str
    amount_pence: int
    customer_id: str
    decline_code: str
    status: str = "failed"


class StripeClient(Protocol):
    """The interface the detector and Adapter talk to. A real implementation would wrap
    the Stripe Python SDK behind this same shape.
    """

    async def list_failed_charges(self) -> list[FailedCharge]: ...

    async def confirm_payment_intent(
        self, charge_id: str, *, idempotency_key: str
    ) -> FailedCharge:
        """Re-confirm the PaymentIntent behind ``charge_id`` (ADR-0011 - never create a
        new one). Stripe itself dedups on ``idempotency_key``: calling this twice with
        the same key returns the same result, never a second real charge attempt.
        """
        ...

    async def get_confirmed(
        self, charge_id: str, *, idempotency_key: str
    ) -> FailedCharge | None:
        """Has this idempotency key already confirmed this PaymentIntent? Honestly,
        for a real Stripe-backed client, there's no cheaper answer than re-issuing the
        same ``confirm`` call and relying on Stripe's own dedup to make it safe - see
        ADR-0018 for why this still has to exist as its own method rather than being
        folded into ``confirm_payment_intent``, and why a worker must only call this
        on a retry, never a genuine first attempt.
        """
        ...


class ChargeNotFoundError(Exception):
    """Raised when an operation targets a charge id that doesn't exist."""


class FakeStripeClient:
    """An in-memory stand-in for Stripe. No network access, ever."""

    def __init__(self, charges: list[FailedCharge] | None = None) -> None:
        self._charges: dict[str, FailedCharge] = {c.id: c for c in (charges or [])}
        self._confirmed_keys: dict[str, FailedCharge] = {}

    def seed(self, charge: FailedCharge) -> None:
        self._charges[charge.id] = charge

    async def list_failed_charges(self) -> list[FailedCharge]:
        return [c for c in self._charges.values() if c.status == "failed"]

    async def confirm_payment_intent(
        self, charge_id: str, *, idempotency_key: str
    ) -> FailedCharge:
        if idempotency_key in self._confirmed_keys:
            return self._confirmed_keys[idempotency_key]  # Stripe's own dedup
        charge = self._charges.get(charge_id)
        if charge is None:
            raise ChargeNotFoundError(f"no such charge {charge_id}")
        succeeded = dataclasses.replace(charge, status="succeeded")
        self._charges[charge_id] = succeeded
        self._confirmed_keys[idempotency_key] = succeeded
        return succeeded

    async def get_confirmed(
        self, charge_id: str, *, idempotency_key: str
    ) -> FailedCharge | None:
        # Genuinely cheap here, unlike the real Stripe client - a dict lookup, not a
        # network call. charge_id is accepted for interface parity with the real
        # client, which needs it to safely re-issue confirm.
        return self._confirmed_keys.get(idempotency_key)


class StripeRecoverySettings(BaseSettings):
    """Where a real secret key comes from - env vars, per ADR-0003. Never construct
    this with anything committed to the repo; ``.env`` is git-ignored, only
    ``.env.example`` (with a placeholder) is checked in.
    """

    model_config = SettingsConfigDict(env_prefix="STRIPE_RECOVERY_", extra="ignore")

    secret_key: SecretStr

    def looks_live(self) -> bool:
        """Sandbox is enforced by the key's own prefix, never a separate flag
        (ADR-0003) - a live-looking key is refused unless a caller explicitly opts in.
        """
        return self.secret_key.get_secret_value().startswith(("sk_live_", "rk_live_"))


class StripeTestModeClient:
    """Wraps the official Stripe SDK against the PaymentIntents API, per ADR-0013.

    Stripe has no "list failed charges" endpoint, and the list side has to agree with
    the execute side about which object it's talking about - so both read and write a
    PaymentIntent, never the legacy Charge object. ``FailedCharge.id`` here is a
    PaymentIntent id (``pi_...``), not a Charge id - opaque to everything above this
    client, same as any other detector-defined identifier (ADR-0008).
    """

    def __init__(
        self, settings: StripeRecoverySettings, *, allow_live: bool = False
    ) -> None:
        if settings.looks_live() and not allow_live:
            raise ValueError(
                "refusing to build a StripeTestModeClient with a live-looking secret "
                "key (sk_live_/rk_live_); pass allow_live=True explicitly if that's "
                "really intended - nothing in this repo ever does"
            )
        self._client = stripe.StripeClient(settings.secret_key.get_secret_value())

    @staticmethod
    def _customer_id(customer: str | stripe.Customer | None) -> str:
        # `customer` is a plain id unless the caller asked Stripe to expand it into a
        # full Customer object - this client never does, but the SDK's type covers both.
        if isinstance(customer, str):
            return customer
        return customer.id if customer is not None else ""

    async def list_failed_charges(self) -> list[FailedCharge]:
        # No status filter exists on the list endpoint (checked against the SDK's own
        # PaymentIntentListParams) - filtering on status and decline_code happens here,
        # client-side, on every page.
        found: list[FailedCharge] = []
        page = await self._client.v1.payment_intents.list_async(params={"limit": 100})
        async for intent in page.auto_paging_iter():
            if intent.status != "requires_payment_method":
                continue
            error = intent.last_payment_error
            if error is None or error.decline_code is None:
                continue
            found.append(
                FailedCharge(
                    id=intent.id,
                    amount_pence=intent.amount,
                    customer_id=self._customer_id(intent.customer),
                    decline_code=error.decline_code,
                    status="failed",
                )
            )
        return found

    async def confirm_payment_intent(
        self, charge_id: str, *, idempotency_key: str
    ) -> FailedCharge:
        try:
            intent = await self._client.v1.payment_intents.confirm_async(
                charge_id, options={"idempotency_key": idempotency_key}
            )
        except stripe.InvalidRequestError as exc:
            raise ChargeNotFoundError(f"no such charge {charge_id}") from exc
        error = intent.last_payment_error
        return FailedCharge(
            id=intent.id,
            amount_pence=intent.amount,
            customer_id=self._customer_id(intent.customer),
            decline_code=error.decline_code if error and error.decline_code else "",
            status=intent.status,
        )

    async def get_confirmed(
        self, charge_id: str, *, idempotency_key: str
    ) -> FailedCharge | None:
        # Honestly not cheaper than confirm_payment_intent - Stripe has no separate
        # "look up by idempotency key" endpoint. Re-issuing confirm with the same key
        # is safe (Stripe's own dedup returns the original result, not a new attempt)
        # and is the only way to learn what that key actually did. See ADR-0018 -
        # a worker must never call this on a genuine first attempt for exactly this
        # reason: it's a real call, not a free read.
        result = await self.confirm_payment_intent(
            charge_id, idempotency_key=idempotency_key
        )
        return result if result.status == "succeeded" else None
