"""The detector: scans failed charges, classifies decline codes against ADR-0011's
allow-list, and emits a Proposal + ApprovalRequest for each retryable one.

Note on ``subject_id``: Stripe's own charge ids are strings (``ch_...``), not UUIDs, so
they don't fit ``ApprovalRequest.subject_id: uuid.UUID | None``. Rather than change that
core type for one detector, the charge id lives in the Snapshot instead (exactly what
an opaque, detector-defined Snapshot is for, per ADR-0008) - ``subject_type`` alone
("stripe_charge") is enough to say what kind of thing this is about.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from ephor.actions import Proposal, ProposalStore
from ephor.approvals import ApprovalRequest, ApprovalStore

from stripe_recovery.client import RETRYABLE_DECLINE_CODES, StripeClient


@dataclass(frozen=True)
class RecoveryCandidate:
    proposal: Proposal
    approval: ApprovalRequest


async def scan_for_recoverable_charges(
    client: StripeClient,
    proposals: ProposalStore,
    approvals: ApprovalStore,
    *,
    requester_id: uuid.UUID,
    now: datetime,
    expires_at: datetime,
) -> list[RecoveryCandidate]:
    """Scan once, propose a retry for every charge whose decline code is retryable."""
    found: list[RecoveryCandidate] = []
    for charge in await client.list_failed_charges():
        if charge.decline_code not in RETRYABLE_DECLINE_CODES:
            continue

        proposal = await proposals.create(
            action_type="retry_charge",
            parameters={"charge_id": charge.id},
            risk_level="low",
            evidence={
                "decline_code": charge.decline_code,
                "amount_pence": charge.amount_pence,
            },
            created_at=now,
        )
        snapshot = {
            "action_type": "retry_charge",
            "charge_id": charge.id,
            "customer_id": charge.customer_id,
            "amount_pence": charge.amount_pence,
            "decline_code": charge.decline_code,
            "reason": (
                f"decline code '{charge.decline_code}' is on the retryable "
                "allow-list (ADR-0011)"
            ),
        }
        approval = await approvals.create(
            proposal_id=proposal.id,
            subject_type="stripe_charge",
            requester_id=requester_id,
            action_type="retry_charge",
            risk_level="low",
            idempotency_key=f"retry-{charge.id}",
            snapshot_json=snapshot,
            created_at=now,
            expires_at=expires_at,
            requested_amount_pence=charge.amount_pence,
        )
        found.append(RecoveryCandidate(proposal=proposal, approval=approval))
    return found
