"""The two scans this package runs - one per resource type, emitting a Proposal +
ApprovalRequest for anything worth proposing.

Note on ``subject_id``: an allocation/instance id here is an opaque, detector-defined
string (see ``client.py``), not a UUID - the same shape as
``stripe_recovery.detector``'s charge ids and ``wallet_guard.detector``'s approval ids.
It lives in the Snapshot instead, per ADR-0008. ``requested_amount_pence`` is left
unset on both - there's no currency amount fetched here, and inventing one would be a
fabricated number, not evidence.

An optional ``Critic`` (ADR-0021) adds a second opinion to the Snapshot before it's
hashed - ``FakeCritic`` by default, so nothing here changes unless a caller opts in.
For unassociated addresses, the critique is stored but never acted on - "no
association" is still the entire condition, unconditionally. For idle instances, the
rule's own threshold is still what decides whether to propose at all (ADR-0022) - the
Critic never gets veto power over that either; it only ever adds judgement a human
reads alongside the same evidence.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from ephor.actions import Proposal, ProposalStore
from ephor.approvals import ApprovalRequest, ApprovalStore
from ephor.critic import Critic

from cloud_waste.client import (
    IDLE_CPU_PERCENT_THRESHOLD,
    IDLE_NETWORK_BYTES_THRESHOLD,
    CloudClient,
)


@dataclass(frozen=True)
class WasteCandidate:
    proposal: Proposal
    approval: ApprovalRequest


@dataclass(frozen=True)
class IdleInstanceCandidate:
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


async def scan_for_idle_instances(
    client: CloudClient,
    proposals: ProposalStore,
    approvals: ApprovalStore,
    *,
    requester_id: uuid.UUID,
    now: datetime,
    expires_at: datetime,
    critic: Critic | None = None,
) -> list[IdleInstanceCandidate]:
    """Scan once, propose stopping every running instance below both the CPU and
    network thresholds (ADR-0022). Unlike the address check, this is a judgement-call
    heuristic, not a boolean - the evidence handed to a Critic includes the instance's
    age and tags, not just "flagged as idle", so a genuine second opinion is possible
    (ADR-0022 finding 5).
    """
    found: list[IdleInstanceCandidate] = []
    for instance in await client.list_instances():
        if instance.state != "running":
            continue
        if instance.avg_cpu_percent > IDLE_CPU_PERCENT_THRESHOLD:
            continue
        if instance.avg_network_bytes > IDLE_NETWORK_BYTES_THRESHOLD:
            continue

        age_days = (now - instance.launch_time).days
        proposal = await proposals.create(
            action_type="stop_instance",
            parameters={"instance_id": instance.id},
            risk_level="low",
            evidence={
                "avg_cpu_percent": instance.avg_cpu_percent,
                "avg_network_bytes": instance.avg_network_bytes,
                "age_days": age_days,
                "tags": instance.tags,
            },
            created_at=now,
        )
        snapshot: dict[str, object] = {
            "action_type": "stop_instance",
            "instance_id": instance.id,
            "avg_cpu_percent": instance.avg_cpu_percent,
            "avg_network_bytes": instance.avg_network_bytes,
            "age_days": age_days,
            "tags": instance.tags,
            "reason": (
                f"average CPU {instance.avg_cpu_percent:.1f}% and network "
                f"{instance.avg_network_bytes:,.0f} bytes are both below the "
                "low-utilisation thresholds (ADR-0022)"
            ),
        }
        if critic is not None:
            critique = await critic.critique(
                {
                    "instance_id": instance.id,
                    "avg_cpu_percent": instance.avg_cpu_percent,
                    "avg_network_bytes": instance.avg_network_bytes,
                    "age_days": age_days,
                    "tags": instance.tags,
                }
            )
            snapshot["llm_critique"] = critique.as_snapshot_field()
        approval = await approvals.create(
            proposal_id=proposal.id,
            subject_type="ec2_instance",
            requester_id=requester_id,
            action_type="stop_instance",
            risk_level="low",
            idempotency_key=f"stop-{instance.id}",
            snapshot_json=snapshot,
            created_at=now,
            expires_at=expires_at,
        )
        found.append(IdleInstanceCandidate(proposal=proposal, approval=approval))
    return found
