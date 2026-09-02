"""The propose -> approve -> execute -> audit loop, end to end, on fake data.

Run with: ``uv run python -m stripe_recovery.demo``

No network access, no Stripe account, nothing real. This is what Phase 1 of the
ROADMAP calls "a short script [that] proves the loop with the mock adapter."
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta

from ephor.actions import InMemoryProposalStore
from ephor.approvals import ApprovalStatus, InMemoryApprovalStore
from ephor.audit import InMemoryAuditStore
from ephor.outbox import InMemoryOutboxStore

from stripe_recovery.adapter import StripeAdapter
from stripe_recovery.client import (
    FailedCharge,
    FakeStripeClient,
    StripeClient,
    StripeRecoverySettings,
    StripeTestModeClient,
)
from stripe_recovery.detector import scan_for_recoverable_charges

REQUESTER_ID = uuid.uuid4()
SUPERVISOR_ID = uuid.uuid4()


def _build_client() -> StripeClient:
    """Real Stripe test mode when STRIPE_RECOVERY_SECRET_KEY is set (see ADR-0013);
    the zero-setup fake, seeded with a demo-shaped pair of charges, otherwise.
    """
    if os.environ.get("STRIPE_RECOVERY_SECRET_KEY"):
        print("Using a real Stripe test-mode account (secret key set via env).\n")
        # model_validate({}) rather than StripeRecoverySettings() - the field has no
        # default (it always comes from the environment, per ADR-0003), so mypy can't
        # see that a zero-arg call is safe; model_validate({}) still runs the env
        # source, just without a call signature mypy checks per-field.
        return StripeTestModeClient(StripeRecoverySettings.model_validate({}))
    return FakeStripeClient(
        [
            FailedCharge(
                id="ch_soft_decline",
                amount_pence=4700,
                customer_id="cus_alice",
                decline_code="insufficient_funds",  # retryable
            ),
            FailedCharge(
                id="ch_hard_decline",
                amount_pence=12000,
                customer_id="cus_bob",
                decline_code="stolen_card",  # never retryable
            ),
        ]
    )


async def main() -> None:
    now = datetime.now(UTC)
    client = _build_client()
    adapter = StripeAdapter(client)
    proposals = InMemoryProposalStore()
    approvals = InMemoryApprovalStore()
    outbox = InMemoryOutboxStore()
    audit = InMemoryAuditStore()

    # 1. Propose: scan for recoverable revenue.
    candidates = await scan_for_recoverable_charges(
        client,
        proposals,
        approvals,
        requester_id=REQUESTER_ID,
        now=now,
        expires_at=now + timedelta(hours=48),
    )
    print(f"1. scanned Stripe -> {len(candidates)} recoverable charge(s) proposed")
    for c in candidates:
        amount_pence = c.approval.requested_amount_pence or 0
        print(
            f"   - {c.approval.snapshot_json['charge_id']}: "
            f"£{amount_pence / 100:.2f} "
            f"({c.approval.snapshot_json['decline_code']})"
        )

    if not candidates:
        print(
            "\nNo recoverable charges found - nothing to approve or execute. "
            "This is expected on a fresh Stripe test-mode account with no failed "
            "PaymentIntents yet; create one and re-run to see the rest of the loop."
        )
        return

    candidate = candidates[0]
    approval = candidate.approval
    await audit.append(
        event_type="approval_requested",
        actor_role="agent",
        subject_type="approval",
        correlation_id=approval.idempotency_key,
        summary="approval requested by the Stripe recovery detector",
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
        action_type="retry_charge",
        payload_json={"charge_id": approval.snapshot_json["charge_id"]},
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
        raise RuntimeError("charge is no longer eligible for retry")
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
        summary=(
            f"retried {approval.snapshot_json['charge_id']}, "
            f"now {effect.raw['status']}"
        ),
        occurred_at=now,
        metadata={"effect_id": effect.effect_id, **effect.raw},
    )
    verification = await audit.verify_chain()
    print(f"4. audited -> entry #{entry.sequence}, chain intact: {verification.ok}")


if __name__ == "__main__":
    asyncio.run(main())
