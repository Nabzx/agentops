import uuid
from datetime import UTC, datetime, timedelta

from ephor.actions import InMemoryProposalStore
from ephor.approvals import ApprovalStatus, InMemoryApprovalStore, verify_snapshot
from ephor.critic import FakeCritic

from wallet_guard.client import INFINITE_ALLOWANCE, FakeChainClient, TokenApproval
from wallet_guard.detector import RevocationCandidate, scan_for_risky_approvals

NOW = datetime(2026, 1, 1, tzinfo=UTC)
REQUESTER = uuid.uuid4()
OWNER = "0xOwner"


async def _scan(
    client: FakeChainClient, critic: FakeCritic | None = None
) -> list[RevocationCandidate]:
    return await scan_for_risky_approvals(
        client,
        InMemoryProposalStore(),
        InMemoryApprovalStore(),
        owner_address=OWNER,
        requester_id=REQUESTER,
        now=NOW,
        expires_at=NOW + timedelta(hours=48),
        critic=critic,
    )


async def test_only_unlimited_allowances_are_proposed() -> None:
    client = FakeChainClient(
        [
            TokenApproval(
                id="appr_unlimited",
                owner_address=OWNER,
                token_address="0xA",
                token_symbol="USDC",
                spender_address="0xSpenderA",
                allowance=INFINITE_ALLOWANCE,
            ),
            TokenApproval(
                id="appr_finite",
                owner_address=OWNER,
                token_address="0xB",
                token_symbol="DAI",
                spender_address="0xSpenderB",
                allowance=500,
            ),
        ]
    )
    candidates = await _scan(client)
    assert [c.approval.snapshot_json["approval_id"] for c in candidates] == [
        "appr_unlimited"
    ]


async def test_no_approvals_means_no_candidates() -> None:
    candidates = await _scan(FakeChainClient())
    assert candidates == []


async def test_a_candidates_approval_starts_pending_and_carries_the_evidence() -> None:
    client = FakeChainClient(
        [
            TokenApproval(
                id="appr_1",
                owner_address=OWNER,
                token_address="0xA",
                token_symbol="USDC",
                spender_address="0xSpender",
                allowance=INFINITE_ALLOWANCE,
            )
        ]
    )
    [candidate] = await _scan(client)
    assert candidate.approval.status == ApprovalStatus.PENDING
    assert candidate.approval.requested_amount_pence is None
    assert candidate.approval.snapshot_json["token_symbol"] == "USDC"
    assert candidate.approval.snapshot_json["allowance"] == str(INFINITE_ALLOWANCE)
    assert candidate.proposal.action_type == "revoke_approval"


async def test_proposal_and_approval_are_linked_by_id() -> None:
    client = FakeChainClient(
        [
            TokenApproval(
                id="appr_1",
                owner_address=OWNER,
                token_address="0xA",
                token_symbol="USDC",
                spender_address="0xSpender",
                allowance=INFINITE_ALLOWANCE,
            )
        ]
    )
    [candidate] = await _scan(client)
    assert candidate.approval.proposal_id == candidate.proposal.id


async def test_no_critic_means_no_critique_in_the_snapshot() -> None:
    """The default, unchanged path - nothing here should ever surprise an existing
    caller that doesn't pass a critic (ADR-0021/ADR-0023).
    """
    client = FakeChainClient(
        [
            TokenApproval(
                id="appr_1",
                owner_address=OWNER,
                token_address="0xA",
                token_symbol="USDC",
                spender_address="0xSpender",
                allowance=INFINITE_ALLOWANCE,
            )
        ]
    )
    [candidate] = await _scan(client)
    assert "llm_critique" not in candidate.approval.snapshot_json


async def test_a_critic_adds_its_critique_to_the_hashed_snapshot() -> None:
    client = FakeChainClient(
        [
            TokenApproval(
                id="appr_1",
                owner_address=OWNER,
                token_address="0xA",
                token_symbol="USDC",
                spender_address="0xSpender",
                allowance=INFINITE_ALLOWANCE,
            )
        ]
    )
    [candidate] = await _scan(client, critic=FakeCritic())
    critique = candidate.approval.snapshot_json["llm_critique"]
    assert isinstance(critique, dict)
    assert critique["recommendation"] == "proceed"
    assert critique["model"] == "fake"
    # Part of the same hashed record as the proposal itself (ADR-0021 point 2).
    verify_snapshot(candidate.approval.snapshot_json, candidate.approval.snapshot_hash)


async def test_a_different_owners_approvals_are_never_scanned() -> None:
    client = FakeChainClient(
        [
            TokenApproval(
                id="appr_other",
                owner_address="0xSomeoneElse",
                token_address="0xA",
                token_symbol="USDC",
                spender_address="0xSpender",
                allowance=INFINITE_ALLOWANCE,
            )
        ]
    )
    assert await _scan(client) == []
