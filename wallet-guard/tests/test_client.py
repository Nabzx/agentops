import pytest

from wallet_guard.client import (
    INFINITE_ALLOWANCE,
    ApprovalNotFoundError,
    FakeChainClient,
    TokenApproval,
)

OWNER = "0xOwner"


def _approval(**overrides: object) -> TokenApproval:
    defaults: dict[str, object] = {
        "id": "appr_1",
        "owner_address": OWNER,
        "token_address": "0xToken",
        "token_symbol": "USDC",
        "spender_address": "0xSpender",
        "allowance": INFINITE_ALLOWANCE,
    }
    defaults.update(overrides)
    return TokenApproval(**defaults)  # type: ignore[arg-type]


async def test_list_approvals_only_returns_active_ones_for_the_owner() -> None:
    client = FakeChainClient(
        [_approval(id="mine"), _approval(id="not_mine", owner_address="0xOther")]
    )
    await client.revoke_approval("mine", idempotency_key="k1")
    assert await client.list_approvals(OWNER) == []


async def test_revoke_approval_zeroes_the_allowance() -> None:
    client = FakeChainClient([_approval()])
    result = await client.revoke_approval("appr_1", idempotency_key="k1")
    assert result.allowance == 0


async def test_revoke_approval_dedups_on_idempotency_key() -> None:
    client = FakeChainClient([_approval()])
    first = await client.revoke_approval("appr_1", idempotency_key="k1")
    second = await client.revoke_approval("appr_1", idempotency_key="k1")
    assert first == second


async def test_revoke_approval_raises_for_an_unknown_id() -> None:
    client = FakeChainClient()
    with pytest.raises(ApprovalNotFoundError):
        await client.revoke_approval("nonexistent", idempotency_key="k1")


async def test_two_distinct_keys_revoke_two_distinct_approvals_independently() -> None:
    """A fresh idempotency key must never resolve to another key's already-recorded
    outcome - each commits to its own nonce, revoking its own approval.
    """
    client = FakeChainClient([_approval(id="a"), _approval(id="b", token_symbol="DAI")])
    revoked_a = await client.revoke_approval("a", idempotency_key="key-a")
    revoked_b = await client.revoke_approval("b", idempotency_key="key-b")
    assert revoked_a.id == "a"
    assert revoked_b.id == "b"
    assert revoked_a.allowance == 0
    assert revoked_b.allowance == 0
