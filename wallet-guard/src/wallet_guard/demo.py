"""The propose -> approve -> execute -> audit loop, end to end, on fake data.

Run with: ``uv run python -m wallet_guard.demo``

No RPC endpoint, no real wallet, nothing real. Same shape as
``stripe_recovery.demo`` - the point of this package is proving that shape holds for
a second, genuinely different kind of Adapter, not inventing a new one.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from ephor.actions import InMemoryProposalStore
from ephor.approvals import ApprovalStatus, InMemoryApprovalStore
from ephor.audit import InMemoryAuditStore
from ephor.outbox import InMemoryOutboxStore

from wallet_guard.adapter import WalletGuardAdapter
from wallet_guard.client import INFINITE_ALLOWANCE, FakeChainClient, TokenApproval
from wallet_guard.detector import scan_for_risky_approvals

REQUESTER_ID = uuid.uuid4()
SUPERVISOR_ID = uuid.uuid4()
OWNER_ADDRESS = "0xOwnerWallet"


async def main() -> None:
    now = datetime.now(UTC)
    client = FakeChainClient(
        [
            TokenApproval(
                id="appr_unlimited_usdc",
                owner_address=OWNER_ADDRESS,
                token_address="0xUSDC",
                token_symbol="USDC",
                spender_address="0xAbandonedRouter",  # unlimited - risky
                allowance=INFINITE_ALLOWANCE,
            ),
            TokenApproval(
                id="appr_finite_dai",
                owner_address=OWNER_ADDRESS,
                token_address="0xDAI",
                token_symbol="DAI",
                spender_address="0xActiveDexRouter",  # a bounded amount - left alone
                allowance=500_000000000000000000,
            ),
        ]
    )
    adapter = WalletGuardAdapter(client)
    proposals = InMemoryProposalStore()
    approvals = InMemoryApprovalStore()
    outbox = InMemoryOutboxStore()
    audit = InMemoryAuditStore()

    # 1. Propose: scan the wallet for dangerous approvals.
    candidates = await scan_for_risky_approvals(
        client,
        proposals,
        approvals,
        owner_address=OWNER_ADDRESS,
        requester_id=REQUESTER_ID,
        now=now,
        expires_at=now + timedelta(hours=48),
    )
    print(f"1. scanned {OWNER_ADDRESS} -> {len(candidates)} risky approval(s) proposed")
    for c in candidates:
        print(
            f"   - {c.approval.snapshot_json['spender_address']} can move unlimited "
            f"{c.approval.snapshot_json['token_symbol']}"
        )

    if not candidates:
        print("\nNo risky approvals found - nothing to approve or execute.")
        return

    candidate = candidates[0]
    approval = candidate.approval
    await audit.append(
        event_type="approval_requested",
        actor_role="agent",
        subject_type="approval",
        correlation_id=approval.idempotency_key,
        summary="revocation requested by the wallet-guard detector",
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
        action_type="revoke_approval",
        payload_json={
            "approval_id": approval.snapshot_json["approval_id"],
            "owner_address": approval.snapshot_json["owner_address"],
        },
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
        raise RuntimeError("approval is no longer active")
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
            f"revoked {approval.snapshot_json['spender_address']}'s approval on "
            f"{approval.snapshot_json['token_symbol']}"
        ),
        occurred_at=now,
        metadata={"effect_id": effect.effect_id, **effect.raw},
    )
    verification = await audit.verify_chain()
    print(f"4. audited -> entry #{entry.sequence}, chain intact: {verification.ok}")


if __name__ == "__main__":
    asyncio.run(main())
