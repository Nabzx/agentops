import pytest
from ephor.effects import PermanentEffectError

from stripe_recovery.adapter import StripeAdapter
from stripe_recovery.client import FailedCharge, FakeStripeClient


def _client(decline_code: str = "insufficient_funds") -> FakeStripeClient:
    return FakeStripeClient(
        [
            FailedCharge(
                id="ch_1",
                amount_pence=4700,
                customer_id="cus_a",
                decline_code=decline_code,
            )
        ]
    )


async def test_check_completed_is_none_before_any_execution() -> None:
    adapter = StripeAdapter(_client())
    assert await adapter.check_completed({"charge_id": "ch_1"}, "key-1") is None


async def test_check_completed_returns_the_effect_after_execution() -> None:
    client = _client()
    adapter = StripeAdapter(client)
    first = await adapter.execute({"charge_id": "ch_1"}, "key-1")
    completed = await adapter.check_completed({"charge_id": "ch_1"}, "key-1")
    assert completed is not None
    assert completed.effect_id == first.effect_id
    assert completed.raw == first.raw


async def test_check_completed_is_none_for_an_unknown_charge() -> None:
    adapter = StripeAdapter(FakeStripeClient())
    result = await adapter.check_completed({"charge_id": "does_not_exist"}, "key-1")
    assert result is None


async def test_revalidate_true_for_a_still_failed_retryable_charge() -> None:
    adapter = StripeAdapter(_client())
    assert await adapter.revalidate({"charge_id": "ch_1"}) is True


async def test_revalidate_false_for_a_charge_that_already_succeeded() -> None:
    client = _client()
    await client.confirm_payment_intent("ch_1", idempotency_key="other-key")
    adapter = StripeAdapter(client)
    assert await adapter.revalidate({"charge_id": "ch_1"}) is False


async def test_revalidate_false_for_a_non_retryable_decline_code() -> None:
    adapter = StripeAdapter(_client(decline_code="stolen_card"))
    assert await adapter.revalidate({"charge_id": "ch_1"}) is False


async def test_revalidate_false_for_an_unknown_charge() -> None:
    adapter = StripeAdapter(FakeStripeClient())
    assert await adapter.revalidate({"charge_id": "does_not_exist"}) is False


async def test_execute_returns_an_effect_on_success() -> None:
    adapter = StripeAdapter(_client())
    effect = await adapter.execute({"charge_id": "ch_1"}, "key-1")
    assert effect.effect_id == "ch_1"
    assert effect.raw["status"] == "succeeded"


async def test_execute_is_idempotent_across_repeated_calls() -> None:
    """occurred_at legitimately differs per call (it's "when we asked"); what proves
    idempotency is that the real-world outcome (effect_id, raw) never changes.
    """
    client = _client()
    adapter = StripeAdapter(client)
    first = await adapter.execute({"charge_id": "ch_1"}, "key-1")
    second = await adapter.execute({"charge_id": "ch_1"}, "key-1")
    assert first.effect_id == second.effect_id
    assert first.raw == second.raw


async def test_execute_raises_permanent_error_for_an_unknown_charge() -> None:
    adapter = StripeAdapter(FakeStripeClient())
    with pytest.raises(PermanentEffectError):
        await adapter.execute({"charge_id": "does_not_exist"}, "key-1")


def test_stripe_adapter_declares_itself_idempotent() -> None:
    assert StripeAdapter.is_idempotent is True


def test_permanent_effect_error_is_importable_from_ephor() -> None:
    assert issubclass(PermanentEffectError, Exception)
