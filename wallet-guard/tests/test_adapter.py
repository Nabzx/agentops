import pytest
from ephor.effects import PermanentEffectError

from wallet_guard.adapter import WalletGuardAdapter
from wallet_guard.client import INFINITE_ALLOWANCE, FakeChainClient, TokenApproval

OWNER = "0xOwner"


def _client(allowance: int = INFINITE_ALLOWANCE) -> FakeChainClient:
    return FakeChainClient(
        [
            TokenApproval(
                id="appr_1",
                owner_address=OWNER,
                token_address="0xToken",
                token_symbol="USDC",
                spender_address="0xSpender",
                allowance=allowance,
            )
        ]
    )


def _action(approval_id: str = "appr_1") -> dict[str, str]:
    return {"approval_id": approval_id, "owner_address": OWNER}


async def test_check_completed_is_none_before_any_execution() -> None:
    adapter = WalletGuardAdapter(_client())
    assert await adapter.check_completed(_action(), "key-1") is None


async def test_check_completed_returns_the_effect_after_execution() -> None:
    client = _client()
    adapter = WalletGuardAdapter(client)
    first = await adapter.execute(_action(), "key-1")
    completed = await adapter.check_completed(_action(), "key-1")
    assert completed is not None
    assert completed.effect_id == first.effect_id
    assert completed.raw == first.raw


async def test_revalidate_true_for_a_still_active_approval() -> None:
    adapter = WalletGuardAdapter(_client())
    assert await adapter.revalidate(_action()) is True


async def test_revalidate_false_for_an_approval_already_revoked() -> None:
    client = _client()
    await client.revoke_approval("appr_1", idempotency_key="other-key")
    adapter = WalletGuardAdapter(client)
    assert await adapter.revalidate(_action()) is False


async def test_revalidate_false_for_an_unknown_approval() -> None:
    adapter = WalletGuardAdapter(FakeChainClient())
    assert await adapter.revalidate(_action("does_not_exist")) is False


async def test_execute_returns_an_effect_on_success() -> None:
    adapter = WalletGuardAdapter(_client())
    effect = await adapter.execute(_action(), "key-1")
    assert effect.effect_id == "appr_1"
    assert effect.raw["allowance"] == 0


async def test_execute_is_idempotent_across_repeated_calls() -> None:
    """occurred_at legitimately differs per call; what proves idempotency is that the
    real-world outcome (effect_id, raw) never changes.
    """
    client = _client()
    adapter = WalletGuardAdapter(client)
    first = await adapter.execute(_action(), "key-1")
    second = await adapter.execute(_action(), "key-1")
    assert first.effect_id == second.effect_id
    assert first.raw == second.raw


async def test_execute_raises_permanent_error_for_an_unknown_approval() -> None:
    adapter = WalletGuardAdapter(FakeChainClient())
    with pytest.raises(PermanentEffectError):
        await adapter.execute(_action("does_not_exist"), "key-1")


def test_wallet_guard_adapter_declares_itself_idempotent() -> None:
    assert WalletGuardAdapter.is_idempotent is True
