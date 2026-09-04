"""The detector: scans an account's Elastic IPs and emits a Proposal + ApprovalRequest
for every one with no association.

Note on ``subject_id``: an allocation id here is an opaque, detector-defined string
(see ``client.py``), not a UUID - the same shape as ``stripe_recovery.detector``'s
charge ids and ``wallet_guard.detector``'s approval ids. It lives in the Snapshot
instead, per ADR-0008. ``requested_amount_pence`` is left unset - there's no currency
amount fetched here, and inventing one would be a fabricated number, not evidence.

An optional ``Critic`` (ADR-0021) adds a second opinion to the Snapshot before it's
hashed - ``FakeCritic`` by default, so nothing here changes unless a caller opts in.
The critique is stored, never acted on: this detector's own "no association" check is
still the entire condition for proposing anything, unconditionally.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from ephor.actions import Proposal, ProposalStore
from ephor.approvals import ApprovalRequest, ApprovalStore

from cloud_waste.client import CloudClient
from cloud_waste.critic import Critic


@dataclass(frozen=True)
class WasteCandidate:
    proposal: Proposal
    approval: ApprovalRequest


async def scan_for_unassociated_addresses(
    client: CloudClient,
    proposals: ProposalStore,
    approvals: ApprovalStore,
    *,
    requester_id: uuid.UUID,
    now: datetime,
    expires_at: datetime,
    critic: Critic | None = None,
) -> list[WasteCandidate]:
    """Scan once, propose releasing every address with no association. Unconditional,
    not an allow-list against a set of values - "no association" is the entire
    condition, per ADR-0020.
    """
    found: list[WasteCandidate] = []
    for address in await client.list_addresses():
        if address.association_id is not None or address.instance_id is not None:
            continue

        proposal = await proposals.create(
            action_type="release_address",
            parameters={"allocation_id": address.id},
            risk_level="low",
            evidence={"public_ip": address.public_ip},
            created_at=now,
        )
        snapshot: dict[str, object] = {
            "action_type": "release_address",
            "allocation_id": address.id,
            "public_ip": address.public_ip,
            "reason": (
                f"{address.public_ip} has no association - no instance and nothing "
                "else is using it"
            ),
        }
        if critic is not None:
            critique = await critic.critique(
                {"public_ip": address.public_ip, "allocation_id": address.id}
            )
            snapshot["llm_critique"] = critique.as_snapshot_field()
        approval = await approvals.create(
            proposal_id=proposal.id,
            subject_type="elastic_ip",
            requester_id=requester_id,
            action_type="release_address",
            risk_level="low",
            idempotency_key=f"release-{address.id}",
            snapshot_json=snapshot,
            created_at=now,
            expires_at=expires_at,
        )
        found.append(WasteCandidate(proposal=proposal, approval=approval))
    return found
