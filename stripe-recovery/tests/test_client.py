import pytest

from stripe_recovery.client import ChargeNotFoundError, FailedCharge, FakeStripeClient


async def test_list_failed_charges_only_returns_failed_ones() -> None:
    client = FakeStripeClient(
        [
            FailedCharge(
                id="ch_1", amount_pence=100, customer_id="cus_a", decline_code="x"
            ),
        ]
    )
    await client.confirm_payment_intent("ch_1", idempotency_key="k1")
    assert await client.list_failed_charges() == []


async def test_confirm_payment_intent_marks_the_charge_succeeded() -> None:
    client = FakeStripeClient(
        [
            FailedCharge(
                id="ch_1",
                amount_pence=100,
                customer_id="cus_a",
                decline_code="insufficient_funds",
            ),
        ]
    )
    result = await client.confirm_payment_intent("ch_1", idempotency_key="k1")
    assert result.status == "succeeded"


async def test_confirm_payment_intent_dedups_on_idempotency_key() -> None:
    client = FakeStripeClient(
        [
            FailedCharge(
                id="ch_1",
                amount_pence=100,
                customer_id="cus_a",
                decline_code="insufficient_funds",
            ),
        ]
    )
    first = await client.confirm_payment_intent("ch_1", idempotency_key="k1")
    second = await client.confirm_payment_intent("ch_1", idempotency_key="k1")
    assert first == second


async def test_confirm_payment_intent_raises_for_an_unknown_charge() -> None:
    client = FakeStripeClient()
    with pytest.raises(ChargeNotFoundError):
        await client.confirm_payment_intent("nonexistent", idempotency_key="k1")


async def test_get_confirmed_is_none_before_any_confirmation() -> None:
    client = FakeStripeClient()
    assert await client.get_confirmed("ch_1", idempotency_key="k1") is None


async def test_get_confirmed_returns_the_result_after_confirmation() -> None:
    client = FakeStripeClient(
        [
            FailedCharge(
                id="ch_1",
                amount_pence=100,
                customer_id="cus_a",
                decline_code="insufficient_funds",
            ),
        ]
    )
    confirmed = await client.confirm_payment_intent("ch_1", idempotency_key="k1")
    result = await client.get_confirmed("ch_1", idempotency_key="k1")
    assert result == confirmed
