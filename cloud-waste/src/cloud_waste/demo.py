"""The propose -> approve -> execute -> audit loop, end to end, on fake data by
default - twice, once per resource type this package knows about.

Run with: ``uv run python -m cloud_waste.demo``

No AWS account, no boto3, nothing real, by default. Same shape as
``stripe_recovery.demo`` and ``wallet_guard.demo`` - the point of this package is
proving that shape holds for a third, genuinely different kind of Adapter, twice over.

The cloud client (ADR-0024) is opt-in the same way ``stripe-recovery``'s real client
is: ``CLOUD_WASTE_AWS_REGION`` unset (the default, and always true in CI) means the
zero-setup ``FakeCloudClient``, seeded below. Setting it means a real ``AwsCloudClient``
against whatever's actually in that AWS account/region - ``allow_live`` still defaults
to ``False`` even then, so nothing gets released or stopped for real without also
passing ``allow_live=True`` explicitly, which nothing in this repo ever does.

The Critic (ADR-0021, extended to every detector by ADR-0023) is opt-in the same way:
``EPHOR_CRITIC_API_KEY`` unset (the default, and always true in CI) means
``FakeCritic`` - no network call, no cost. Setting it means a real, paid call to
Claude on every proposal scanned here.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta

from ephor.actions import InMemoryProposalStore
from ephor.approvals import ApprovalStatus, InMemoryApprovalStore
from ephor.audit import InMemoryAuditStore
from ephor.critic import Critic, FakeCritic
from ephor.effects import Adapter, Effect
from ephor.outbox import InMemoryOutboxStore

from cloud_waste.adapter import CloudWasteAdapter, IdleInstanceAdapter
from cloud_waste.client import (
    AwsCloudClient,
    CloudClient,
    CloudWasteAwsSettings,
    ElasticIp,
    FakeCloudClient,
    Instance,
)
from cloud_waste.critic import ClaudeCritic, ClaudeCriticSettings
from cloud_waste.detector import (
    scan_for_idle_instances,
    scan_for_unassociated_addresses,
)

REQUESTER_ID = uuid.uuid4()
SUPERVISOR_ID = uuid.uuid4()


def _build_critic() -> Critic:
    """Real Claude when EPHOR_CRITIC_API_KEY is set (see ADR-0021) - a real, paid
    call on every proposal. FakeCritic, free and canned, otherwise.
    """
    if os.environ.get("EPHOR_CRITIC_API_KEY"):
        print("Using a real Claude critic (API key set via env - this costs money).\n")
        return ClaudeCritic(ClaudeCriticSettings.model_validate({}))
    return FakeCritic()


def _build_client(now: datetime) -> CloudClient:
    """Real AWS when CLOUD_WASTE_AWS_REGION is set (see ADR-0024) - reads whatever's
    actually in that account, never mutates without allow_live=True (never passed
    here). The zero-setup fake, seeded with a demo-shaped mix of resources, otherwise.
    """
    region = os.environ.get("CLOUD_WASTE_AWS_REGION")
    if region:
        print(f"Using a real AWS account in {region} (region set via env).\n")
        return AwsCloudClient(CloudWasteAwsSettings(region=region))

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
    client.seed_instance(
        Instance(
            id="i-idle-for-weeks",
            state="running",
            launch_time=now - timedelta(days=90),
            tags={"env": "unknown"},
            avg_cpu_percent=1.2,  # below both thresholds - idle
            avg_network_bytes=10_000,
        )
    )
    client.seed_instance(
        Instance(
            id="i-busy-web-server",
            state="running",
            launch_time=now - timedelta(days=200),
            tags={"env": "prod"},
            avg_cpu_percent=42.0,  # well above threshold - left alone
            avg_network_bytes=2_000_000_000,
        )
    )
    return client


def _print_critique(snapshot: dict[str, object]) -> None:
    critique = snapshot.get("llm_critique")
    if isinstance(critique, dict):
        print(
            f"     critic ({critique['model']}) says: {critique['recommendation']}"
            f" - {critique['reasoning']}"
        )


async def _approve_and_execute(
    approvals: InMemoryApprovalStore,
    outbox: InMemoryOutboxStore,
    audit: InMemoryAuditStore,
    adapter: Adapter,
    *,
    approval_id: uuid.UUID,
    proposal_id: uuid.UUID,
    action_type: str,
    payload_json: dict[str, object],
    idempotency_key: str,
    now: datetime,
    requested_summary: str,
    executed_summary: str,
    step: int,
) -> Effect:
    """Steps 2-4 of the loop - approve, execute exactly once, audit - identical
    regardless of which resource type or Adapter is behind it. Steps 2-4 are
    parameterised here rather than duplicated per resource type.
    """
    await audit.append(
        event_type="approval_requested",
        actor_role="agent",
        subject_type="approval",
        correlation_id=idempotency_key,
        summary=requested_summary,
        occurred_at=now,
        subject_id=approval_id,
    )

    # 2. Approve: a supervisor decides. The requester could never do this (ADR-0009).
    await approvals.transition(approval_id, destination=ApprovalStatus.APPROVED)
    await approvals.append_decision(
        approval_request_id=approval_id,
        decision="approve",
        actor_id=SUPERVISOR_ID,
        actor_role="supervisor",
        previous_status=ApprovalStatus.PENDING,
        new_status=ApprovalStatus.APPROVED,
        created_at=now,
    )
    approval = await approvals.transition(
        approval_id, destination=ApprovalStatus.EXECUTION_PENDING
    )
    print(f"\n{step + 1}. approved by a supervisor -> {approval.status}")
    await audit.append(
        event_type="approval_approved",
        actor_role="supervisor",
        subject_type="approval",
        correlation_id=idempotency_key,
        summary="approved by supervisor",
        occurred_at=now,
        subject_id=approval_id,
        actor_user_id=SUPERVISOR_ID,
    )

    # 3. Execute: exactly once, through the durable outbox.
    job = await outbox.create(
        proposal_id=proposal_id,
        action_type=action_type,
        payload_json=payload_json,
        idempotency_key=idempotency_key,
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
        raise RuntimeError("action is no longer valid")
    effect = await adapter.execute(action, job.idempotency_key)
    await outbox.mark_succeeded(job.id, now=now)
    await outbox.finish_attempt(attempt.id, result_status="succeeded", now=now)
    await approvals.transition(approval_id, destination=ApprovalStatus.EXECUTED)
    print(f"{step + 2}. executed -> effect {effect.effect_id}, {effect.raw}")

    # 4. Audit: prove it, don't just log it.
    entry = await audit.append(
        event_type="action_executed",
        actor_role="system",
        subject_type="executed_action",
        correlation_id=idempotency_key,
        summary=executed_summary,
        occurred_at=now,
        metadata={"effect_id": effect.effect_id, **effect.raw},
    )
    verification = await audit.verify_chain()
    print(
        f"{step + 3}. audited -> entry #{entry.sequence}, chain intact: "
        f"{verification.ok}"
    )
    return effect


async def main() -> None:
    now = datetime.now(UTC)
    client = _build_client(now)
    address_adapter = CloudWasteAdapter(client)
    instance_adapter = IdleInstanceAdapter(client)
    critic = _build_critic()
    proposals = InMemoryProposalStore()
    approvals = InMemoryApprovalStore()
    outbox = InMemoryOutboxStore()
    audit = InMemoryAuditStore()

    print("--- part 1: unassociated Elastic IPs (ADR-0020) ---\n")

    address_candidates = await scan_for_unassociated_addresses(
        client,
        proposals,
        approvals,
        requester_id=REQUESTER_ID,
        now=now,
        expires_at=now + timedelta(hours=48),
        critic=critic,
    )
    print(
        f"1. scanned the account -> {len(address_candidates)} unassociated "
        "address(es) proposed"
    )
    for c in address_candidates:
        print(f"   - {c.approval.snapshot_json['public_ip']} has no association")
        _print_critique(c.approval.snapshot_json)

    if address_candidates:
        address_candidate = address_candidates[0]
        await _approve_and_execute(
            approvals,
            outbox,
            audit,
            address_adapter,
            approval_id=address_candidate.approval.id,
            proposal_id=address_candidate.proposal.id,
            action_type="release_address",
            payload_json={
                "allocation_id": address_candidate.approval.snapshot_json[
                    "allocation_id"
                ]
            },
            idempotency_key=address_candidate.approval.idempotency_key,
            now=now,
            requested_summary="release requested by the cloud-waste detector",
            executed_summary=(
                f"released {address_candidate.approval.snapshot_json['public_ip']}"
            ),
            step=1,
        )

    print("\n--- part 2: idle EC2 instances (ADR-0022) ---\n")

    instance_candidates = await scan_for_idle_instances(
        client,
        proposals,
        approvals,
        requester_id=REQUESTER_ID,
        now=now,
        expires_at=now + timedelta(hours=48),
        critic=critic,
    )
    print(
        f"5. scanned the account -> {len(instance_candidates)} "
        "idle instance(s) proposed"
    )
    for ic in instance_candidates:
        print(
            f"   - {ic.approval.snapshot_json['instance_id']}: "
            f"{ic.approval.snapshot_json['avg_cpu_percent']}% avg CPU, "
            f"{ic.approval.snapshot_json['age_days']} days old"
        )
        _print_critique(ic.approval.snapshot_json)

    if not instance_candidates:
        print("\nNo idle instances found - nothing to approve or execute.")
        return

    instance_candidate = instance_candidates[0]
    await _approve_and_execute(
        approvals,
        outbox,
        audit,
        instance_adapter,
        approval_id=instance_candidate.approval.id,
        proposal_id=instance_candidate.proposal.id,
        action_type="stop_instance",
        payload_json={
            "instance_id": instance_candidate.approval.snapshot_json["instance_id"]
        },
        idempotency_key=instance_candidate.approval.idempotency_key,
        now=now,
        requested_summary="stop requested by the cloud-waste detector",
        executed_summary=(
            f"stopped {instance_candidate.approval.snapshot_json['instance_id']}"
        ),
        step=5,
    )


if __name__ == "__main__":
    asyncio.run(main())
