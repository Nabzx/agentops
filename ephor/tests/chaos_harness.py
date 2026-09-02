"""A randomised chaos harness for the exactly-once guarantee (ADR-0005).

``test_outbox.py``'s acceptance test proves the guarantee at three hand-picked crash
points, once each. This harness generalises that into a fuzzer: many jobs, each
driven through a real worker loop (``claim_batch`` -> ``start_attempt`` -> the
Adapter's call -> the local commit -> ``finish_attempt``) with a randomly chosen
crash point injected on every cycle, repeated across many independently-seeded
trials. The same invariants are checked every time, not just at the three points
someone thought to write down by hand:

1. an idempotent Adapter never produces more than one real Effect for a given job,
   no matter how many times it was crashed and retried;
2. a job that finishes SUCCEEDED has exactly one real Effect behind it - not zero,
   not more than one;
3. a non-idempotent Adapter that lands in ``NEEDS_MANUAL_RECONCILIATION`` has exactly
   one real Effect behind it, and the store genuinely never lets that job be reclaimed
   afterwards - checked with a real ``claim_batch`` call a year in simulated time
   later, not just by trusting the status enum;
4. every terminal job, of any kind, is never returned by a later ``claim_batch`` call.

This is not a formal proof - it's a much larger, randomised sample of the same state
space the hand-picked test only visits at three points. Deterministic and
reproducible: each trial is seeded from its own index, so "trial 4231 failed" always
reproduces by re-running that one seed.
"""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from ephor.outbox import UNCLAIMABLE_STATUSES, InMemoryOutboxStore, OutboxStatus

NOW = datetime(2026, 1, 1, tzinfo=UTC)
WORKER_IDS = ("worker-a", "worker-b", "worker-c")
LEASE_SECONDS = 30
MAX_CYCLES = 15  # forced-success safety valve - see _advance_one_cycle


class CrashPoint(StrEnum):
    NONE = "none"  # the attempt completes normally
    BEFORE_CLAIM = "before_claim"  # crashed before claiming - nothing happened yet
    # claimed, crashed before calling out
    AFTER_CLAIM_BEFORE_CALL = "after_claim_before_call"
    AFTER_CALL_BEFORE_COMMIT = "after_call_before_commit"  # the dangerous window
    # committed; attempt ledger left open
    AFTER_COMMIT_BEFORE_FINISH = "after_commit_before_finish"


class ChaosAdapter:
    """A mock external system with a real side effect (an in-memory ledger) - same
    shape as ``test_outbox.py``'s ``_MockAdapter``, but callable across however many
    crash-and-retry cycles a trial's random sequence produces for this job.
    """

    def __init__(self, *, is_idempotent: bool) -> None:
        self.is_idempotent = is_idempotent
        self.real_effects: list[str] = []
        self._seen_keys: set[str] = set()

    def call(self, idempotency_key: str) -> None:
        if self.is_idempotent and idempotency_key in self._seen_keys:
            return  # the target itself deduped - no second real effect
        self._seen_keys.add(idempotency_key)
        self.real_effects.append(idempotency_key)


@dataclass
class Violation:
    trial_seed: int
    job_id: uuid.UUID
    detail: str

    def __str__(self) -> str:
        return f"[seed {self.trial_seed}] job {self.job_id}: {self.detail}"


@dataclass
class TrialSummary:
    seed: int
    jobs: int = 0
    crash_injections: int = 0
    crash_point_counts: dict[str, int] = field(default_factory=dict)
    violations: list[Violation] = field(default_factory=list)


async def _advance_one_cycle(
    store: InMemoryOutboxStore,
    job_id: uuid.UUID,
    adapter: ChaosAdapter,
    rng: random.Random,
    *,
    now: datetime,
    force_none: bool,
) -> tuple[CrashPoint, bool, datetime]:
    """Drives exactly one claim/attempt cycle for ``job_id``, injecting a randomly
    chosen crash point (or forcing a clean completion if ``force_none``, so a trial
    can't spin forever on unlucky sampling). Returns the crash point injected,
    whether the job is now terminal, and the clock time after this cycle.
    """
    crash_at = CrashPoint.NONE if force_none else rng.choice(list(CrashPoint))
    worker_id = rng.choice(WORKER_IDS)

    if crash_at == CrashPoint.BEFORE_CLAIM:
        return crash_at, False, now + timedelta(seconds=1)

    claimed = await store.claim_batch(
        worker_id=worker_id, now=now, lease_seconds=LEASE_SECONDS, batch_size=1
    )
    if not claimed:
        return crash_at, False, now + timedelta(seconds=LEASE_SECONDS + 1)

    job = claimed[0]
    attempt = await store.start_attempt(
        job_id=job_id,
        worker_id=worker_id,
        previous_status=OutboxStatus.CLAIMED,
        lease_expires_at=job.lease_expires_at,
        now=now,
    )

    if crash_at == CrashPoint.AFTER_CLAIM_BEFORE_CALL:
        return crash_at, False, now + timedelta(seconds=LEASE_SECONDS + 1)

    adapter.call(job.idempotency_key)

    if crash_at == CrashPoint.AFTER_CALL_BEFORE_COMMIT:
        if not adapter.is_idempotent:
            await store.mark_needs_manual_reconciliation(
                job_id, now=now, note="chaos: crashed after call, before commit"
            )
            return crash_at, True, now
        return crash_at, False, now + timedelta(seconds=LEASE_SECONDS + 1)

    await store.mark_succeeded(job_id, now=now)

    if crash_at == CrashPoint.AFTER_COMMIT_BEFORE_FINISH:
        return crash_at, True, now  # SUCCEEDED is terminal - nothing left to retry

    await store.finish_attempt(attempt.id, result_status="succeeded", now=now)
    return crash_at, True, now


async def _run_job_to_terminal(
    store: InMemoryOutboxStore,
    job_id: uuid.UUID,
    adapter: ChaosAdapter,
    rng: random.Random,
) -> list[CrashPoint]:
    now = NOW
    injected: list[CrashPoint] = []
    for cycle in range(MAX_CYCLES):
        crash_at, done, now = await _advance_one_cycle(
            store, job_id, adapter, rng, now=now, force_none=cycle == MAX_CYCLES - 1
        )
        injected.append(crash_at)
        if done:
            return injected
    # pragma: no cover - the forced-NONE cycle above should make this unreachable
    raise AssertionError(
        f"job {job_id} never reached a terminal state within {MAX_CYCLES} cycles"
    )


def _check_job_invariants(
    seed: int, job_id: uuid.UUID, adapter: ChaosAdapter, final_status: OutboxStatus
) -> list[Violation]:
    violations: list[Violation] = []
    effect_count = len(adapter.real_effects)

    if adapter.is_idempotent and effect_count > 1:
        violations.append(
            Violation(seed, job_id, f"idempotent adapter fired {effect_count} times")
        )
    if final_status == OutboxStatus.SUCCEEDED and effect_count != 1:
        violations.append(
            Violation(seed, job_id, f"SUCCEEDED with {effect_count} real effects")
        )
    if final_status == OutboxStatus.NEEDS_MANUAL_RECONCILIATION:
        if adapter.is_idempotent:
            violations.append(
                Violation(seed, job_id, "an idempotent adapter reached reconciliation")
            )
        if effect_count != 1:
            violations.append(
                Violation(
                    seed, job_id, f"reconciliation with {effect_count} real effects"
                )
            )
    return violations


async def run_trial(seed: int) -> TrialSummary:
    """One trial: several independently-randomised jobs sharing one store, so
    cross-job interference (not just single-job crash timing) has a chance to show
    up too.
    """
    rng = random.Random(seed)  # noqa: S311 - deterministic test fuzzing, not crypto
    store = InMemoryOutboxStore()
    summary = TrialSummary(seed=seed)

    for _ in range(rng.randint(2, 6)):
        is_idempotent = rng.random() < 0.7  # most real Adapters are; some aren't
        adapter = ChaosAdapter(is_idempotent=is_idempotent)
        job = await store.create(
            proposal_id=uuid.uuid4(),
            action_type="retry_charge",
            payload_json={"amount_pence": rng.randint(100, 100_000)},
            idempotency_key=f"chaos-{uuid.uuid4().hex[:10]}",
            next_attempt_at=NOW,
        )
        summary.jobs += 1

        injected = await _run_job_to_terminal(store, job.id, adapter, rng)
        summary.crash_injections += len(injected)
        for point in injected:
            summary.crash_point_counts[point.value] = (
                summary.crash_point_counts.get(point.value, 0) + 1
            )

        final = await store.get(job.id)
        assert final is not None
        final_status = OutboxStatus(final.status)
        summary.violations.extend(
            _check_job_invariants(seed, job.id, adapter, final_status)
        )

        if final_status in UNCLAIMABLE_STATUSES:
            # Not just trusting the enum - actually ask the store, a long time later,
            # with a batch big enough to catch it if it were somehow still claimable.
            far_future = NOW + timedelta(days=365)
            still_claimable = await store.claim_batch(
                worker_id="chaos-auditor",
                now=far_future,
                lease_seconds=30,
                batch_size=100,
            )
            if any(j.id == job.id for j in still_claimable):
                summary.violations.append(
                    Violation(seed, job.id, "a terminal job was reclaimed a year later")
                )

    return summary


async def run_trials(count: int, *, start_seed: int = 0) -> list[TrialSummary]:
    return [await run_trial(seed) for seed in range(start_seed, start_seed + count)]
