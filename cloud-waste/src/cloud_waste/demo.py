"""The propose -> approve -> execute -> audit loop, end to end, on fake data.

Run with: ``uv run python -m cloud_waste.demo``

No AWS account, no boto3, nothing real. Same shape as ``stripe_recovery.demo`` and
``wallet_guard.demo`` - the point of this package is proving that shape holds for a
third, genuinely different kind of Adapter.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from ephor.actions import InMemoryProposalStore
from ephor.approvals import ApprovalStatus, InMemoryApprovalStore
from ephor.audit import InMemoryAuditStore
from ephor.outbox import InMemoryOutboxStore

from cloud_waste.adapter import CloudWasteAdapter
from cloud_waste.client import ElasticIp, FakeCloudClient
from cloud_waste.detector import scan_for_unassociated_addresses

REQUESTER_ID = uuid.uuid4()
SUPERVISOR_ID = uuid.uuid4()


async def main() -> None:
    now = datetime.now(UTC)
    client = FakeCloudClient(
        [
            ElasticIp(
                id="eipalloc-forgotten",
                public_ip="203.0.113.42",
                association_id=None,
                instance_id=None,  # unassociated - nothing is using it
            ),
            ElasticIp(
                id="eipalloc-in-use",
                public_ip="203.0.113.7",
                association_id="eipassoc-live",
                instance_id="i-0123456789abcdef0",  # attached - left alone
            ),
        ]
    )
    adapter = CloudWasteAdapter(client)
    proposals = InMemoryProposalStore()
    approvals = InMemoryApprovalStore()
    outbox = InMemoryOutboxStore()
    audit = InMemoryAuditStore()

    # 1. Propose: scan the account for unassociated addresses.
    candidates = await scan_for_unassociated_addresses(
        client,
        proposals,
        approvals,
        requester_id=REQUESTER_ID,
        now=now,
        expires_at=now + timedelta(hours=48),
    )
    print(
        f"1. scanned the account -> {len(candidates)} unassociated address(es) proposed"
    )
    for c in candidates:
        print(f"   - {c.approval.snapshot_json['public_ip']} has no association")

    if not candidates:
        print("\nNo unassociated addresses found - nothing to approve or execute.")
        return

    candidate = candidates[0]
    approval = candidate.approval
    await audit.append(
        event_type="approval_requested",
        actor_role="agent",
        subject_type="approval",
        correlation_id=approval.idempotency_key,
        summary="release requested by the cloud-waste detector",
        occurred_at=now,
        subject_id=approval.id,
    )

    # 2. Approve: a supervisor decides. The requester could never do this (ADR-0009).
    await approvals.transition(approval.id, destination=ApprovalStatus.APPROVED)
    await approvals.append_decision(
        approval_request_id=approval.id,
        decision="approve",
        actor_id=SUPERVISOR_ID,
        actor_role="supervisor",
        previous_status=ApprovalStatus.PENDING,
        new_status=ApprovalStatus.APPROVED,
        created_at=now,
    )
    approval = await approvals.transition(
        approval.id, destination=ApprovalStatus.EXECUTION_PENDING
    )
    print(f"\n2. approved by a supervisor -> {approval.status}")
    await audit.append(
        event_type="approval_approved",
        actor_role="supervisor",
        subject_type="approval",
        correlation_id=approval.idempotency_key,
        summary="approved by supervisor",
        occurred_at=now,
        subject_id=approval.id,
        actor_user_id=SUPERVISOR_ID,
    )

    # 3. Execute: exactly once, through the durable outbox.
    job = await outbox.create(
        proposal_id=candidate.proposal.id,
        action_type="release_address",
        payload_json={"allocation_id": approval.snapshot_json["allocation_id"]},
        idempotency_key=approval.idempotency_key,
        next_attempt_at=now,
    )
    claimed = await outbox.claim_batch(
        worker_id="demo-worker", now=now, lease_seconds=60, batch_size=1
    )
    assert [j.id for j in claimed] == [job.id]
    attempt = await outbox.start_attempt(
        job_id=job.id,
        worker_id="demo-worker",
        previous_status=job.status,
        lease_expires_at=job.lease_expires_at,
        now=now,
    )
    action = dict(job.payload_json)
    if not await adapter.revalidate(action):
        raise RuntimeError("address is no longer unassociated")
    effect = await adapter.execute(action, job.idempotency_key)
    await outbox.mark_succeeded(job.id, now=now)
    await outbox.finish_attempt(attempt.id, result_status="succeeded", now=now)
    await approvals.transition(approval.id, destination=ApprovalStatus.EXECUTED)
    print(f"3. executed -> effect {effect.effect_id}, {effect.raw}")

    # 4. Audit: prove it, don't just log it.
    entry = await audit.append(
        event_type="action_executed",
        actor_role="system",
        subject_type="executed_action",
        correlation_id=approval.idempotency_key,
        summary=f"released {approval.snapshot_json['public_ip']}",
        occurred_at=now,
        metadata={"effect_id": effect.effect_id, **effect.raw},
    )
    verification = await audit.verify_chain()
    print(f"4. audited -> entry #{entry.sequence}, chain intact: {verification.ok}")


if __name__ == "__main__":
    asyncio.run(main())
