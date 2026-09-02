"""Approval request, Snapshot, Decision - see CONTEXT.md "The action loop".

A human approves a frozen, hashed Snapshot of exactly what an Action will do before it
executes. ``ApprovalRequest``/``Decision`` are structural Protocols (see ``ephor.audit``
for why); ``ApprovalStore`` is the interface any backing store implements.
``InMemoryApprovalStore`` is the zero-setup implementation this package ships with.

The Snapshot itself is an opaque ``dict`` - the core hashes, stores and re-verifies it,
but never interprets what's inside. Each detector decides its own Snapshot shape.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    SUPERSEDED = "superseded"
    EXECUTION_PENDING = "execution_pending"
    EXECUTED = "executed"
    EXECUTION_FAILED = "execution_failed"


# Legal status transitions. Anything not listed is rejected (e.g. rejected->approved,
# expired->approved, executed->pending, cancelled->approved are all impossible).
APPROVAL_TRANSITIONS: dict[ApprovalStatus, frozenset[ApprovalStatus]] = {
    ApprovalStatus.PENDING: frozenset(
        {
            ApprovalStatus.APPROVED,
            ApprovalStatus.REJECTED,
            ApprovalStatus.EXPIRED,
            ApprovalStatus.CANCELLED,
            ApprovalStatus.SUPERSEDED,
        }
    ),
    ApprovalStatus.APPROVED: frozenset({ApprovalStatus.EXECUTION_PENDING}),
    ApprovalStatus.EXECUTION_PENDING: frozenset(
        {ApprovalStatus.EXECUTED, ApprovalStatus.EXECUTION_FAILED}
    ),
    ApprovalStatus.EXECUTION_FAILED: frozenset({ApprovalStatus.EXECUTION_PENDING}),
}

TERMINAL_APPROVAL_STATUSES: frozenset[ApprovalStatus] = frozenset(
    {
        ApprovalStatus.REJECTED,
        ApprovalStatus.EXPIRED,
        ApprovalStatus.CANCELLED,
        ApprovalStatus.SUPERSEDED,
        ApprovalStatus.EXECUTED,
    }
)


def is_valid_approval_transition(source: str, destination: str) -> bool:
    try:
        allowed = APPROVAL_TRANSITIONS.get(ApprovalStatus(source), frozenset())
    except ValueError:
        return False
    return destination in allowed


class ApprovalDecisionType(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    CANCEL = "cancel"
    EXPIRE = "expire"
    RETRY_AUTHORISED = "retry_authorised"


class SnapshotError(Exception):
    """Raised when a stored Snapshot fails hash verification (tampered or corrupt)."""


class SelfDecisionError(Exception):
    """Raised when a Requester attempts to decide their own Approval request."""


def canonical_snapshot_json(snapshot: dict[str, Any]) -> str:
    """Deterministic, sorted-key JSON of a Snapshot dict."""
    return json.dumps(snapshot, sort_keys=True, ensure_ascii=True, default=str)


def compute_snapshot_hash(snapshot: dict[str, Any]) -> str:
    """SHA-256 over the Snapshot's canonical JSON.

    The Snapshot is opaque to the core: whatever a detector puts in it, hashed as-is.
    """
    return hashlib.sha256(canonical_snapshot_json(snapshot).encode("utf-8")).hexdigest()


def verify_snapshot(snapshot: dict[str, Any], stored_hash: str) -> None:
    """Recompute the Snapshot's hash and compare. Raises SnapshotError on mismatch."""
    if compute_snapshot_hash(snapshot) != stored_hash:
        raise SnapshotError("snapshot hash mismatch (tampered or corrupt)")


def assert_not_self_decision(*, requester_id: uuid.UUID, actor_id: uuid.UUID) -> None:
    """The Requester may never decide (approve/reject/retry) their own request."""
    if requester_id == actor_id:
        raise SelfDecisionError("the requester may not decide their own request")


class Decision(Protocol):
    """One immutable record of a human's approve/reject/cancel/expire/retry decision."""

    @property
    def id(self) -> uuid.UUID: ...
    @property
    def approval_request_id(self) -> uuid.UUID: ...
    @property
    def decision(self) -> str: ...
    @property
    def actor_role(self) -> str: ...
    @property
    def previous_status(self) -> str: ...
    @property
    def new_status(self) -> str: ...
    @property
    def created_at(self) -> datetime: ...
    @property
    def actor_id(self) -> uuid.UUID | None: ...
    @property
    def reason(self) -> str | None: ...


class ApprovalRequest(Protocol):
    """The read shape of one Approval request, per ADR-0008's generic Snapshot shape."""

    @property
    def id(self) -> uuid.UUID: ...
    @property
    def proposal_id(self) -> uuid.UUID: ...
    @property
    def subject_type(self) -> str: ...
    @property
    def requester_id(self) -> uuid.UUID: ...
    @property
    def status(self) -> str: ...
    @property
    def action_type(self) -> str: ...
    @property
    def risk_level(self) -> str: ...
    @property
    def idempotency_key(self) -> str: ...
    @property
    def snapshot_json(self) -> dict[str, object]: ...
    @property
    def snapshot_hash(self) -> str: ...
    @property
    def created_at(self) -> datetime: ...
    @property
    def expires_at(self) -> datetime: ...
    @property
    def subject_id(self) -> uuid.UUID | None: ...
    @property
    def requested_amount_pence(self) -> int | None: ...
    @property
    def maximum_allowed_amount_pence(self) -> int | None: ...
    @property
    def approved_amount_pence(self) -> int | None: ...
    @property
    def decided_at(self) -> datetime | None: ...


class ApprovalStore(Protocol):
    """The persistence interface any backing store implements. See ADR-0009."""

    async def create(
        self,
        *,
        proposal_id: uuid.UUID,
        subject_type: str,
        requester_id: uuid.UUID,
        action_type: str,
        risk_level: str,
        idempotency_key: str,
        snapshot_json: dict[str, object],
        created_at: datetime,
        expires_at: datetime,
        subject_id: uuid.UUID | None = None,
        requested_amount_pence: int | None = None,
        maximum_allowed_amount_pence: int | None = None,
    ) -> ApprovalRequest: ...

    async def get(self, approval_id: uuid.UUID) -> ApprovalRequest | None: ...

    async def list_open(
        self, *, subject_type: str | None = None, limit: int = 50, offset: int = 0
    ) -> list[ApprovalRequest]: ...

    async def list_due_for_expiry(
        self, *, now: datetime, limit: int = 50
    ) -> list[ApprovalRequest]: ...

    async def transition(
        self,
        approval_id: uuid.UUID,
        *,
        destination: str,
        decided_at: datetime | None = None,
        approved_amount_pence: int | None = None,
    ) -> ApprovalRequest:
        """Move an Approval to a new status. Raises on an illegal transition."""
        ...

    async def append_decision(
        self,
        *,
        approval_request_id: uuid.UUID,
        decision: str,
        actor_role: str,
        previous_status: str,
        new_status: str,
        created_at: datetime,
        actor_id: uuid.UUID | None = None,
        reason: str | None = None,
    ) -> Decision: ...

    async def list_decisions(
        self, approval_request_id: uuid.UUID
    ) -> list[Decision]: ...


@dataclass(frozen=True)
class InMemoryApprovalRequest:
    """A concrete ``ApprovalRequest`` - the shape ``InMemoryApprovalStore`` returns."""

    id: uuid.UUID
    proposal_id: uuid.UUID
    subject_type: str
    requester_id: uuid.UUID
    status: str
    action_type: str
    risk_level: str
    idempotency_key: str
    snapshot_json: dict[str, object]
    snapshot_hash: str
    created_at: datetime
    expires_at: datetime
    subject_id: uuid.UUID | None = None
    requested_amount_pence: int | None = None
    maximum_allowed_amount_pence: int | None = None
    approved_amount_pence: int | None = None
    decided_at: datetime | None = None


@dataclass(frozen=True)
class InMemoryDecision:
    id: uuid.UUID
    approval_request_id: uuid.UUID
    decision: str
    actor_role: str
    previous_status: str
    new_status: str
    created_at: datetime
    actor_id: uuid.UUID | None = None
    reason: str | None = None


class ApprovalTransitionError(Exception):
    """Raised when a requested status transition is not legal from the current one."""


class InMemoryApprovalStore:
    """A process-local, in-memory ``ApprovalStore``. Not durable across restarts."""

    def __init__(self) -> None:
        self._requests: dict[uuid.UUID, InMemoryApprovalRequest] = {}
        self._decisions: list[InMemoryDecision] = []

    async def create(
        self,
        *,
        proposal_id: uuid.UUID,
        subject_type: str,
        requester_id: uuid.UUID,
        action_type: str,
        risk_level: str,
        idempotency_key: str,
        snapshot_json: dict[str, object],
        created_at: datetime,
        expires_at: datetime,
        subject_id: uuid.UUID | None = None,
        requested_amount_pence: int | None = None,
        maximum_allowed_amount_pence: int | None = None,
    ) -> ApprovalRequest:
        request = InMemoryApprovalRequest(
            id=uuid.uuid4(),
            proposal_id=proposal_id,
            subject_type=subject_type,
            subject_id=subject_id,
            requester_id=requester_id,
            status=ApprovalStatus.PENDING,
            action_type=action_type,
            risk_level=risk_level,
            idempotency_key=idempotency_key,
            snapshot_json=snapshot_json,
            snapshot_hash=compute_snapshot_hash(snapshot_json),
            created_at=created_at,
            expires_at=expires_at,
            requested_amount_pence=requested_amount_pence,
            maximum_allowed_amount_pence=maximum_allowed_amount_pence,
        )
        self._requests[request.id] = request
        return request

    async def get(self, approval_id: uuid.UUID) -> ApprovalRequest | None:
        return self._requests.get(approval_id)

    async def list_open(
        self, *, subject_type: str | None = None, limit: int = 50, offset: int = 0
    ) -> list[ApprovalRequest]:
        rows = [
            r for r in self._requests.values() if r.status == ApprovalStatus.PENDING
        ]
        if subject_type is not None:
            rows = [r for r in rows if r.subject_type == subject_type]
        ordered = sorted(rows, key=lambda r: r.created_at)
        return list(ordered[offset : offset + limit])

    async def list_due_for_expiry(
        self, *, now: datetime, limit: int = 50
    ) -> list[ApprovalRequest]:
        rows = [
            r
            for r in self._requests.values()
            if r.status == ApprovalStatus.PENDING and r.expires_at <= now
        ]
        return list(sorted(rows, key=lambda r: r.expires_at)[:limit])

    async def transition(
        self,
        approval_id: uuid.UUID,
        *,
        destination: str,
        decided_at: datetime | None = None,
        approved_amount_pence: int | None = None,
    ) -> ApprovalRequest:
        current = self._requests.get(approval_id)
        if current is None:
            raise KeyError(f"no approval request {approval_id}")
        if not is_valid_approval_transition(current.status, destination):
            raise ApprovalTransitionError(
                f"cannot move approval from {current.status} to {destination}"
            )
        updated = dataclasses.replace(
            current,
            status=destination,
            decided_at=decided_at if decided_at is not None else current.decided_at,
            approved_amount_pence=(
                approved_amount_pence
                if approved_amount_pence is not None
                else current.approved_amount_pence
            ),
        )
        self._requests[approval_id] = updated
        return updated

    async def append_decision(
        self,
        *,
        approval_request_id: uuid.UUID,
        decision: str,
        actor_role: str,
        previous_status: str,
        new_status: str,
        created_at: datetime,
        actor_id: uuid.UUID | None = None,
        reason: str | None = None,
    ) -> Decision:
        row = InMemoryDecision(
            id=uuid.uuid4(),
            approval_request_id=approval_request_id,
            decision=decision,
            actor_id=actor_id,
            actor_role=actor_role,
            reason=reason,
            previous_status=previous_status,
            new_status=new_status,
            created_at=created_at,
        )
        self._decisions.append(row)
        return row

    async def list_decisions(self, approval_request_id: uuid.UUID) -> list[Decision]:
        rows = [
            d for d in self._decisions if d.approval_request_id == approval_request_id
        ]
        return sorted(rows, key=lambda d: d.created_at)


__all__ = [
    "APPROVAL_TRANSITIONS",
    "TERMINAL_APPROVAL_STATUSES",
    "ApprovalDecisionType",
    "ApprovalRequest",
    "ApprovalStatus",
    "ApprovalStore",
    "ApprovalTransitionError",
    "Decision",
    "InMemoryApprovalRequest",
    "InMemoryApprovalStore",
    "InMemoryDecision",
    "SelfDecisionError",
    "SnapshotError",
    "assert_not_self_decision",
    "canonical_snapshot_json",
    "compute_snapshot_hash",
    "is_valid_approval_transition",
    "verify_snapshot",
]
