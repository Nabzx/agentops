import uuid
from datetime import UTC, datetime, timedelta

from ephor.actions import InMemoryProposalStore
from ephor.approvals import ApprovalStatus, InMemoryApprovalStore, verify_snapshot

from cloud_waste.client import ElasticIp, FakeCloudClient
from cloud_waste.critic import FakeCritic
from cloud_waste.detector import WasteCandidate, scan_for_unassociated_addresses

NOW = datetime(2026, 1, 1, tzinfo=UTC)
REQUESTER = uuid.uuid4()


async def _scan(client: FakeCloudClient) -> list[WasteCandidate]:
    return await scan_for_unassociated_addresses(
        client,
        InMemoryProposalStore(),
        InMemoryApprovalStore(),
        requester_id=REQUESTER,
        now=NOW,
        expires_at=NOW + timedelta(hours=48),
    )


async def test_only_unassociated_addresses_are_proposed() -> None:
    client = FakeCloudClient(
        [
            ElasticIp(
                id="unassociated",
                public_ip="203.0.113.1",
                association_id=None,
                instance_id=None,
            ),
            ElasticIp(
                id="associated",
                public_ip="203.0.113.2",
                association_id="eipassoc-1",
                instance_id="i-123",
            ),
        ]
    )
    candidates = await _scan(client)
    assert [c.approval.snapshot_json["allocation_id"] for c in candidates] == [
        "unassociated"
    ]


async def test_an_address_with_only_an_instance_id_is_not_proposed() -> None:
    """Belt and braces: either field alone being set means something is using it."""
    client = FakeCloudClient(
        [
            ElasticIp(
                id="half-associated",
                public_ip="203.0.113.1",
                association_id=None,
                instance_id="i-123",
            )
        ]
    )
    assert await _scan(client) == []


async def test_no_addresses_means_no_candidates() -> None:
    candidates = await _scan(FakeCloudClient())
    assert candidates == []


async def test_a_candidates_approval_starts_pending_and_carries_the_evidence() -> None:
    client = FakeCloudClient(
        [
            ElasticIp(
                id="eipalloc-1",
                public_ip="203.0.113.1",
                association_id=None,
                instance_id=None,
            )
        ]
    )
    [candidate] = await _scan(client)
    assert candidate.approval.status == ApprovalStatus.PENDING
    assert candidate.approval.requested_amount_pence is None
    assert candidate.approval.snapshot_json["public_ip"] == "203.0.113.1"
    assert candidate.proposal.action_type == "release_address"


async def test_no_critic_means_no_critique_in_the_snapshot() -> None:
    """The default, unchanged path - nothing here should ever surprise an existing
    caller that doesn't pass a critic (ADR-0021).
    """
    client = FakeCloudClient(
        [
            ElasticIp(
                id="eipalloc-1",
                public_ip="203.0.113.1",
                association_id=None,
                instance_id=None,
            )
        ]
    )
    [candidate] = await _scan(client)
    assert "llm_critique" not in candidate.approval.snapshot_json


async def test_a_critic_adds_its_critique_to_the_hashed_snapshot() -> None:
    client = FakeCloudClient(
        [
            ElasticIp(
                id="eipalloc-1",
                public_ip="203.0.113.1",
                association_id=None,
                instance_id=None,
            )
        ]
    )
    [candidate] = await scan_for_unassociated_addresses(
        client,
        InMemoryProposalStore(),
        InMemoryApprovalStore(),
        requester_id=REQUESTER,
        now=NOW,
        expires_at=NOW + timedelta(hours=48),
        critic=FakeCritic(),
    )
    critique = candidate.approval.snapshot_json["llm_critique"]
    assert isinstance(critique, dict)
    assert critique["recommendation"] == "proceed"
    assert critique["model"] == "fake"
    # It's part of the same hashed record as the proposal itself (ADR-0021 point 2) -
    # not a separate, unverified annotation bolted on afterward.
    verify_snapshot(candidate.approval.snapshot_json, candidate.approval.snapshot_hash)


async def test_proposal_and_approval_are_linked_by_id() -> None:
    client = FakeCloudClient(
        [
            ElasticIp(
                id="eipalloc-1",
                public_ip="203.0.113.1",
                association_id=None,
                instance_id=None,
            )
        ]
    )
    [candidate] = await _scan(client)
    assert candidate.approval.proposal_id == candidate.proposal.id
