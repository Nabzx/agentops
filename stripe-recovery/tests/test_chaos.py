"""Chaos-tests the real pipeline, not just the outbox in isolation.

Mirrors ``wallet-guard/tests/test_chaos.py`` exactly, for the adapter ADR-0018 was
actually hardest for: ``ephor/tests/chaos_harness.py`` (ADR-0015) proves the outbox's
own state machine holds exactly-once against a synthetic mock adapter; this drives
the same randomised crash injection through the *real* ``StripeAdapter`` wrapping the
*real* ``FakeStripeClient``, via ``ephor.outbox.InMemoryOutboxStore``'s real
claim/attempt lifecycle.

This is what ADR-0017/0018 are actually about for this Adapter specifically: a worker
checks ``store.list_attempts(job_id)`` before starting a new attempt - if a prior
attempt already exists, ``adapter.check_completed`` is asked first (which, for
Stripe, is honestly no cheaper than ``execute()`` itself - see ADR-0018), and only
falls through to ``revalidate()``/``execute()`` if it says ``None``. On a genuine
first attempt, ``check_completed`` is never called at all - the one thing that has
to hold for Stripe specifically, since calling it there is a real action, not a free
read.

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

from stripe_recovery.adapter import StripeAdapter
from stripe_recovery.client import FailedCharge, FakeStripeClient

NOW = datetime(2026, 1, 1, tzinfo=UTC)
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
    charge_id: str
    detail: str

    def __str__(self) -> str:
        return f"[seed {self.seed}] {self.charge_id}: {self.detail}"


@dataclass
class TrialResult:
    seed: int
    jobs: int = 0
    violations: list[Violation] = field(default_factory=list)


async def _advance_one_cycle(
    store: InMemoryOutboxStore,
    adapter: StripeAdapter,
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
    # check_completed at all - never on a genuine first attempt. For Stripe this
    # matters more than for wallet-guard: check_completed is a real re-confirm call,
    # not a free read, so calling it before a first execute() would be a live action.
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
        # The real confirm already landed; check_completed will find it on the next
        # cycle via get_confirmed - the outbox job itself doesn't know yet, which is
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
    client = FakeStripeClient()
    adapter = StripeAdapter(client)
    result = TrialResult(seed=seed)

    charge_ids: list[str] = []
    for i in range(rng.randint(2, 5)):
        charge_id = f"ch-{seed}-{i}"
        client.seed(
            FailedCharge(
                id=charge_id,
                amount_pence=rng.randint(100, 100_000),
                customer_id=f"cus_{seed}_{i}",
                decline_code="insufficient_funds",
            )
        )
        charge_ids.append(charge_id)

    now = NOW
    for charge_id in charge_ids:
        job = await store.create(
            proposal_id=uuid.uuid4(),
            action_type="retry_charge",
            payload_json={"charge_id": charge_id},
            idempotency_key=f"retry-{charge_id}",
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
                Violation(seed, charge_id, "never reached a terminal state")
            )
            continue

        final = await store.get(job.id)
        assert final is not None
        final_status = OutboxStatus(final.status)

        # Not just trusting the outbox's status - ask the actual Stripe state.
        remaining = await client.list_failed_charges()
        still_failed = next((c for c in remaining if c.id == charge_id), None)
        if still_failed is not None:
            result.violations.append(
                Violation(seed, charge_id, "still failed after SUCCEEDED")
            )
        if final_status != OutboxStatus.SUCCEEDED:
            result.violations.append(
                Violation(seed, charge_id, f"ended {final_status}, not SUCCEEDED")
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
                    Violation(seed, charge_id, "a terminal job was reclaimed later")
                )

    return result


async def test_real_adapter_holds_exactly_once_under_crash_injection() -> None:
    trials = 200
    results = [await run_trial(seed) for seed in range(trials)]

    violations = [v for r in results for v in r.violations]
    assert not violations, "\n".join(str(v) for v in violations)

    total_jobs = sum(r.jobs for r in results)
    assert total_jobs >= trials * 2
