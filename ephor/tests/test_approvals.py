import uuid
from datetime import UTC, datetime, timedelta

import pytest

from ephor.approvals import (
    ApprovalDecisionType,
    ApprovalRequest,
    ApprovalStatus,
    ApprovalTransitionError,
    InMemoryApprovalStore,
    SelfDecisionError,
    SnapshotError,
    assert_not_self_decision,
    compute_snapshot_hash,
    is_valid_approval_transition,
    verify_snapshot,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


# --- state machine --------------------------------------------------------------
def test_pending_can_move_to_any_first_decision() -> None:
    for destination in (
        ApprovalStatus.APPROVED,
        ApprovalStatus.REJECTED,
        ApprovalStatus.EXPIRED,
        ApprovalStatus.CANCELLED,
        ApprovalStatus.SUPERSEDED,
    ):
        assert is_valid_approval_transition(ApprovalStatus.PENDING, destination)


def test_terminal_statuses_never_move_again() -> None:
    for terminal in (
        ApprovalStatus.REJECTED,
        ApprovalStatus.EXPIRED,
        ApprovalStatus.CANCELLED,
        ApprovalStatus.SUPERSEDED,
    ):
        assert not is_valid_approval_transition(terminal, ApprovalStatus.APPROVED)
        assert not is_valid_approval_transition(terminal, ApprovalStatus.PENDING)


def test_approved_only_moves_to_execution_pending() -> None:
    assert is_valid_approval_transition(
        ApprovalStatus.APPROVED, ApprovalStatus.EXECUTION_PENDING
    )
    assert not is_valid_approval_transition(
        ApprovalStatus.APPROVED, ApprovalStatus.EXECUTED
    )


def test_execution_failed_can_be_retried_but_not_reopened_to_pending() -> None:
    assert is_valid_approval_transition(
        ApprovalStatus.EXECUTION_FAILED, ApprovalStatus.EXECUTION_PENDING
    )
    assert not is_valid_approval_transition(
        ApprovalStatus.EXECUTION_FAILED, ApprovalStatus.PENDING
    )


def test_unknown_status_string_is_never_a_valid_source() -> None:
    assert not is_valid_approval_transition(
        "not_a_real_status", ApprovalStatus.APPROVED
    )


# --- snapshot hashing -------------------------------------------------------------
def test_snapshot_hash_is_deterministic() -> None:
    snapshot = {"action_type": "retry_charge", "amount_pence": 4700}
    assert compute_snapshot_hash(snapshot) == compute_snapshot_hash(dict(snapshot))


def test_verify_snapshot_passes_when_untampered() -> None:
    snapshot = {"action_type": "retry_charge", "amount_pence": 4700}
    verify_snapshot(snapshot, compute_snapshot_hash(snapshot))  # does not raise


def test_verify_snapshot_detects_tampering() -> None:
    snapshot = {"action_type": "retry_charge", "amount_pence": 4700}
    stored_hash = compute_snapshot_hash(snapshot)
    tampered = {**snapshot, "amount_pence": 99999}
    with pytest.raises(SnapshotError):
        verify_snapshot(tampered, stored_hash)


# --- self-approval rule ------------------------------------------------------------
def test_requester_cannot_decide_their_own_request() -> None:
    same_id = uuid.uuid4()
    with pytest.raises(SelfDecisionError):
        assert_not_self_decision(requester_id=same_id, actor_id=same_id)


def test_a_different_actor_may_decide() -> None:
    assert_not_self_decision(requester_id=uuid.uuid4(), actor_id=uuid.uuid4())  # ok


# --- InMemoryApprovalStore ---------------------------------------------------------
async def _pending_request(store: InMemoryApprovalStore) -> ApprovalRequest:
    return await store.create(
        proposal_id=uuid.uuid4(),
        subject_type="test_subject",
        requester_id=uuid.uuid4(),
        action_type="retry_charge",
        risk_level="medium",
        idempotency_key="act-abc123",
        snapshot_json={"amount_pence": 4700},
        created_at=NOW,
        expires_at=NOW + timedelta(hours=48),
    )


async def test_create_sets_pending_status_and_a_matching_hash() -> None:
    store = InMemoryApprovalStore()
    request = await _pending_request(store)
    assert request.status == ApprovalStatus.PENDING
    assert request.snapshot_hash == compute_snapshot_hash(request.snapshot_json)


async def test_get_returns_none_for_an_unknown_id() -> None:
    store = InMemoryApprovalStore()
    assert await store.get(uuid.uuid4()) is None


async def test_list_open_only_returns_pending_requests() -> None:
    store = InMemoryApprovalStore()
    pending = await _pending_request(store)
    decided = await _pending_request(store)
    await store.transition(decided.id, destination=ApprovalStatus.REJECTED)

    open_requests = await store.list_open()
    assert [r.id for r in open_requests] == [pending.id]


async def test_transition_rejects_an_illegal_move() -> None:
    store = InMemoryApprovalStore()
    request = await _pending_request(store)
    await store.transition(request.id, destination=ApprovalStatus.APPROVED)

    with pytest.raises(ApprovalTransitionError):
        await store.transition(request.id, destination=ApprovalStatus.PENDING)


async def test_transition_records_decided_at() -> None:
    store = InMemoryApprovalStore()
    request = await _pending_request(store)
    decided_at = NOW + timedelta(minutes=5)
    updated = await store.transition(
        request.id, destination=ApprovalStatus.APPROVED, decided_at=decided_at
    )
    assert updated.decided_at == decided_at


async def test_list_due_for_expiry_only_returns_pending_past_their_expiry() -> None:
    store = InMemoryApprovalStore()
    expired = await store.create(
        proposal_id=uuid.uuid4(),
        subject_type="test_subject",
        requester_id=uuid.uuid4(),
        action_type="retry_charge",
        risk_level="low",
        idempotency_key="act-expired",
        snapshot_json={},
        created_at=NOW - timedelta(hours=100),
        expires_at=NOW - timedelta(hours=1),
    )
    not_yet = await _pending_request(store)

    due = await store.list_due_for_expiry(now=NOW)
    assert [r.id for r in due] == [expired.id]
    assert not_yet.id not in [r.id for r in due]


async def test_append_decision_and_list_decisions_round_trip() -> None:
    store = InMemoryApprovalStore()
    request = await _pending_request(store)
    decision = await store.append_decision(
        approval_request_id=request.id,
        decision=ApprovalDecisionType.APPROVE,
        actor_role="supervisor",
        previous_status=ApprovalStatus.PENDING,
        new_status=ApprovalStatus.APPROVED,
        created_at=NOW,
        actor_id=uuid.uuid4(),
    )
    decisions = await store.list_decisions(request.id)
    assert decisions == [decision]
