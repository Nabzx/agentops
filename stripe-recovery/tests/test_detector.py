import uuid
from datetime import UTC, datetime, timedelta

from ephor.actions import InMemoryProposalStore
from ephor.approvals import ApprovalStatus, InMemoryApprovalStore, verify_snapshot
from ephor.critic import FakeCritic

from stripe_recovery.client import FailedCharge, FakeStripeClient
from stripe_recovery.detector import RecoveryCandidate, scan_for_recoverable_charges

NOW = datetime(2026, 1, 1, tzinfo=UTC)
REQUESTER = uuid.uuid4()


async def _scan(
    client: FakeStripeClient, critic: FakeCritic | None = None
) -> list[RecoveryCandidate]:
    return await scan_for_recoverable_charges(
        client,
        InMemoryProposalStore(),
        InMemoryApprovalStore(),
        requester_id=REQUESTER,
        now=NOW,
        expires_at=NOW + timedelta(hours=48),
        critic=critic,
    )


async def test_only_retryable_decline_codes_are_proposed() -> None:
    client = FakeStripeClient(
        [
            FailedCharge(
                id="ch_soft",
                amount_pence=100,
                customer_id="cus_a",
                decline_code="insufficient_funds",
            ),
            FailedCharge(
                id="ch_hard",
                amount_pence=200,
                customer_id="cus_b",
                decline_code="stolen_card",
            ),
        ]
    )
    candidates = await _scan(client)
    assert [c.approval.snapshot_json["charge_id"] for c in candidates] == ["ch_soft"]


async def test_no_charges_means_no_candidates() -> None:
    candidates = await _scan(FakeStripeClient())
    assert candidates == []


async def test_a_candidates_approval_starts_pending_and_carries_the_evidence() -> None:
    client = FakeStripeClient(
        [
            FailedCharge(
                id="ch_1",
                amount_pence=4700,
                customer_id="cus_a",
                decline_code="try_again_later",
            )
        ]
    )
    [candidate] = await _scan(client)
    assert candidate.approval.status == ApprovalStatus.PENDING
    assert candidate.approval.requested_amount_pence == 4700
    assert candidate.approval.snapshot_json["decline_code"] == "try_again_later"
    assert candidate.proposal.action_type == "retry_charge"


async def test_proposal_and_approval_are_linked_by_id() -> None:
    client = FakeStripeClient(
        [
            FailedCharge(
                id="ch_1",
                amount_pence=100,
                customer_id="cus_a",
                decline_code="processing_error",
            )
        ]
    )
    [candidate] = await _scan(client)
    assert candidate.approval.proposal_id == candidate.proposal.id


async def test_no_critic_means_no_critique_in_the_snapshot() -> None:
    """The default, unchanged path - nothing here should ever surprise an existing
    caller that doesn't pass a critic (ADR-0021/ADR-0023).
    """
    client = FakeStripeClient(
        [
            FailedCharge(
                id="ch_1",
                amount_pence=100,
                customer_id="cus_a",
                decline_code="processing_error",
            )
        ]
    )
    [candidate] = await _scan(client)
    assert "llm_critique" not in candidate.approval.snapshot_json


async def test_a_critic_adds_its_critique_to_the_hashed_snapshot() -> None:
    client = FakeStripeClient(
        [
            FailedCharge(
                id="ch_1",
                amount_pence=100,
                customer_id="cus_a",
                decline_code="processing_error",
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
