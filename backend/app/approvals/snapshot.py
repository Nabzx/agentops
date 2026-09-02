"""Approval snapshot model, canonical hashing and verification (S6).

The snapshot is the immutable, redacted *basis* of an approval: the exact action, order,
amount, deterministic eligibility outcome and policy evidence a decision (and later
execution) must match. The hash is computed over the action-relevant fields only, so a
text-only change to volatile metadata never changes it, but any action-relevant change
(amount, order, action type, rule result, citations, versions, idempotency key,
requester, workflow version) does.

Deciding *which* fields are hash-relevant for this app's own Snapshot shape (excluding
volatile ones like ``snapshot_created_at``) is domain-specific business logic that stays
here - the core has no business knowing about draft responses or policy citations. The
actual canonicalise-and-hash *mechanism* is shared with ``ephor.approvals`` since #36,
rather than reimplemented, per ADR-0008/0009.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from typing import Any

from ephor.approvals import SnapshotError
from ephor.approvals import compute_snapshot_hash as _ephor_compute_snapshot_hash
from ephor.approvals import verify_snapshot as _ephor_verify_snapshot
from pydantic import BaseModel, ConfigDict, Field

SNAPSHOT_SCHEMA_VERSION = "approval-snapshot-v1"

# Volatile metadata excluded from the integrity hash (assigned after / around creation).
_HASH_EXCLUDE = frozenset({"approval_request_id", "snapshot_created_at"})

# Re-exported so existing call sites (`from app.approvals.snapshot import
# SnapshotError`) keep working unchanged - the definition's home is now ephor.approvals.
__all__ = [
    "SNAPSHOT_SCHEMA_VERSION",
    "ApprovalSnapshot",
    "SnapshotError",
    "build_business_idempotency_key",
    "compute_snapshot_hash",
    "hash_text",
    "verify_snapshot",
]


class ApprovalSnapshot(BaseModel):
    """The canonical, serialisable basis of one approval request."""

    model_config = ConfigDict(extra="forbid")

    snapshot_schema_version: str = SNAPSHOT_SCHEMA_VERSION
    approval_request_id: uuid.UUID | None = None
    proposed_action_id: uuid.UUID
    workflow_run_id: uuid.UUID
    workflow_name: str
    workflow_version: str
    ticket_id: uuid.UUID
    customer_id: uuid.UUID | None = None
    order_id: uuid.UUID | None = None
    action_type: str
    requested_amount_pence: int | None = None
    maximum_allowed_amount_pence: int | None = None
    risk_level: str
    required_role: str | None = None
    approval_required: bool
    idempotency_key: str
    eligibility_outcome: str
    reason_codes: list[str] = Field(default_factory=list)
    rule_versions: dict[str, str] = Field(default_factory=dict)
    policy_citation_ids: list[str] = Field(default_factory=list)
    policy_version_ids: list[str] = Field(default_factory=list)
    policy_content_hashes: list[str] = Field(default_factory=list)
    evidence_support_status: str = "unknown"
    evidence_conflict_status: str = "none"
    draft_response_hash: str
    proposed_action_created_at: datetime
    requester_user_id: uuid.UUID
    snapshot_created_at: datetime

    def hash_relevant_fields(self) -> dict[str, Any]:
        """This app's own Snapshot content, minus the fields excluded from the hash."""
        data = self.model_dump(mode="json")
        for key in _HASH_EXCLUDE:
            data.pop(key, None)
        return data


def compute_snapshot_hash(snapshot: ApprovalSnapshot) -> str:
    """Deterministic SHA-256 over the snapshot's action-relevant fields."""
    return _ephor_compute_snapshot_hash(snapshot.hash_relevant_fields())


def verify_snapshot(
    snapshot_json: dict[str, object], stored_hash: str
) -> ApprovalSnapshot:
    """Rebuild a snapshot from stored JSON and verify its hash (raises on mismatch)."""
    try:
        snapshot = ApprovalSnapshot.model_validate(snapshot_json)
    except ValueError as exc:
        raise SnapshotError("approval snapshot is structurally invalid") from exc
    _ephor_verify_snapshot(snapshot.hash_relevant_fields(), stored_hash)
    return snapshot


def hash_text(text: str) -> str:
    """SHA-256 of a text field (e.g. the draft response body)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_business_idempotency_key(
    *, action_type: str, order_id: uuid.UUID | None, amount_pence: int | None
) -> str:
    """Deterministic business-action idempotency key (no timestamps).

    Includes the amount so an approved-amount reduction produces a new key; a text-only
    response edit leaves it unchanged.
    """
    amount = amount_pence if amount_pence is not None else "none"
    basis = f"{action_type}|{order_id or 'none'}|{amount}"
    digest = hashlib.sha256(basis.encode("utf-8")).hexdigest()[:32]
    return f"act-{digest}"
