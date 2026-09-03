"""Chaos-tests the real pipeline, not just the outbox in isolation.

``ephor/tests/chaos_harness.py`` (ADR-0015) proves the outbox's own state machine
holds exactly-once against a synthetic mock adapter. This drives the same kind of
randomised crash injection through the *real* integration: the actual
``WalletGuardAdapter`` wrapping the actual ``FakeChainClient``, via
``ephor.outbox.InMemoryOutboxStore``'s real claim/attempt lifecycle - proving the
whole wiring holds, not just the abstract contract each side promises to honour.

This is exactly what found the gap ADR-0017 writes up, and now proves the real fix
(ADR-0018): a worker checks ``store.list_attempts(job_id)`` before starting a new
attempt - if a prior attempt already exists, ``adapter.check_completed`` is asked
first, and only falls through to ``revalidate()``/``execute()`` if it says ``None``.
On a genuine first attempt, ``check_completed`` is never called at all.

Deterministic and reproducible, same discipline as the core's own harness: each
trial is seeded from its own index.
"""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from ephor.outbox import UNCLAIMABLE_STATUSES, InMemoryOutboxStore, OutboxStatus

from wallet_guard.adapter import WalletGuardAdapter
from wallet_guard.client import INFINITE_ALLOWANCE, FakeChainClient, TokenApproval

NOW = datetime(2026, 1, 1, tzinfo=UTC)
OWNER = "0xChaosOwner"
LEASE_SECONDS = 30
MAX_CYCLES = 15


class CrashPoint(StrEnum):
    NONE = "none"
    BEFORE_CLAIM = "before_claim"
    AFTER_CLAIM_BEFORE_EXECUTE = "after_claim_before_execute"
    AFTER_EXECUTE_BEFORE_COMMIT = "after_execute_before_commit"
    AFTER_COMMIT_BEFORE_FINISH = "after_commit_before_finish"


@dataclass
class Violation:
    seed: int
    approval_id: str
    detail: str

    def __str__(self) -> str:
        return f"[seed {self.seed}] {self.approval_id}: {self.detail}"


@dataclass
class TrialResult:
    seed: int
    jobs: int = 0
    violations: list[Violation] = field(default_factory=list)


async def _advance_one_cycle(
    store: InMemoryOutboxStore,
    adapter: WalletGuardAdapter,
    job_id: uuid.UUID,
    rng: random.Random,
    *,
    now: datetime,
    force_none: bool,
) -> tuple[bool, datetime]:
    """Returns (is now terminal, clock time after this cycle)."""
    crash_at = CrashPoint.NONE if force_none else rng.choice(list(CrashPoint))
    worker_id = rng.choice(("worker-a", "worker-b"))

    if crash_at == CrashPoint.BEFORE_CLAIM:
        return False, now + timedelta(seconds=1)

    claimed = await store.claim_batch(
        worker_id=worker_id, now=now, lease_seconds=LEASE_SECONDS, batch_size=1
    )
    if not claimed:
        return False, now + timedelta(seconds=LEASE_SECONDS + 1)
    job = claimed[0]
    action = dict(job.payload_json)

    # ADR-0018: a prior attempt existing is the *only* signal that justifies asking
    # check_completed at all - never on a genuine first attempt, see the ADR for why.
    prior_attempts = await store.list_attempts(job_id)

    attempt = await store.start_attempt(
        job_id=job_id,
        worker_id=worker_id,
        previous_status=OutboxStatus.CLAIMED,
        lease_expires_at=job.lease_expires_at,
        now=now,
    )

    if prior_attempts:
        completed = await adapter.check_completed(action, job.idempotency_key)
        if completed is not None:
            await store.mark_succeeded(job_id, now=now)
            await store.finish_attempt(attempt.id, result_status="succeeded", now=now)
            return True, now

    if crash_at == CrashPoint.AFTER_CLAIM_BEFORE_EXECUTE:
        return False, now + timedelta(seconds=LEASE_SECONDS + 1)

    if not await adapter.revalidate(action):
        raise AssertionError(f"unexpectedly stale action for job {job_id}")
    await adapter.execute(action, job.idempotency_key)

    if crash_at == CrashPoint.AFTER_EXECUTE_BEFORE_COMMIT:
        # The real revoke already landed; check_completed will find it on the next
        # cycle via get_revoked - the outbox job itself doesn't know yet, which is
        # the whole point of asking the adapter rather than trusting job status.
        return False, now + timedelta(seconds=LEASE_SECONDS + 1)

    await store.mark_succeeded(job_id, now=now)

    if crash_at == CrashPoint.AFTER_COMMIT_BEFORE_FINISH:
        return True, now

    await store.finish_attempt(attempt.id, result_status="succeeded", now=now)
    return True, now


async def run_trial(seed: int) -> TrialResult:
    rng = random.Random(seed)  # noqa: S311 - deterministic test fuzzing, not crypto
    store = InMemoryOutboxStore()
    client = FakeChainClient()
    adapter = WalletGuardAdapter(client)
    result = TrialResult(seed=seed)

    approval_ids: list[str] = []
    for i in range(rng.randint(2, 5)):
        approval_id = f"appr-{seed}-{i}"
        client.seed(
            TokenApproval(
                id=approval_id,
                owner_address=OWNER,
                token_address=f"0xToken{i}",
                token_symbol=f"TOK{i}",
                spender_address=f"0xSpender{i}",
                allowance=INFINITE_ALLOWANCE,
            )
        )
        approval_ids.append(approval_id)

    now = NOW
    for approval_id in approval_ids:
        job = await store.create(
            proposal_id=uuid.uuid4(),
            action_type="revoke_approval",
            payload_json={"approval_id": approval_id, "owner_address": OWNER},
            idempotency_key=f"revoke-{approval_id}",
            next_attempt_at=NOW,
        )
        result.jobs += 1

        for cycle in range(MAX_CYCLES):
            done, now = await _advance_one_cycle(
                store,
                adapter,
                job.id,
                rng,
                now=now,
                force_none=cycle == MAX_CYCLES - 1,
            )
            if done:
                break
        else:  # pragma: no cover - the forced-NONE cycle should prevent this
            result.violations.append(
                Violation(seed, approval_id, "never reached a terminal state")
            )
            continue

        final = await store.get(job.id)
        assert final is not None
        final_status = OutboxStatus(final.status)

        # Not just trusting the outbox's status - ask the actual chain state.
        remaining = await client.list_approvals(OWNER)
        still_active = next((a for a in remaining if a.id == approval_id), None)
        if still_active is not None:
            result.violations.append(
                Violation(seed, approval_id, "still an active approval after SUCCEEDED")
            )
        if final_status != OutboxStatus.SUCCEEDED:
            result.violations.append(
                Violation(seed, approval_id, f"ended {final_status}, not SUCCEEDED")
            )
        if final_status in UNCLAIMABLE_STATUSES:
            far_future = NOW + timedelta(days=365)
            reclaimed = await store.claim_batch(
                worker_id="chaos-auditor",
                now=far_future,
                lease_seconds=30,
                batch_size=100,
            )
            if any(j.id == job.id for j in reclaimed):
                result.violations.append(
                    Violation(seed, approval_id, "a terminal job was reclaimed later")
                )

    return result


async def test_real_adapter_holds_exactly_once_under_crash_injection() -> None:
    trials = 200
    results = [await run_trial(seed) for seed in range(trials)]

    violations = [v for r in results for v in r.violations]
    assert not violations, "\n".join(str(v) for v in violations)

    total_jobs = sum(r.jobs for r in results)
    assert total_jobs >= trials * 2
