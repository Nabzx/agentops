"""Chaos-tests the real pipeline, not just the outbox in isolation.

``ephor/tests/chaos_harness.py`` (ADR-0015) proves the outbox's own state machine
holds exactly-once against a synthetic mock adapter. This drives the same kind of
randomised crash injection through the *real* integration: the actual
``WalletGuardAdapter`` wrapping the actual ``FakeChainClient``, via
``ephor.outbox.InMemoryOutboxStore``'s real claim/attempt lifecycle - proving the
whole wiring holds, not just the abstract contract each side promises to honour.

This is exactly what found the gap ADR-0017 writes up: a naive revalidate-then-execute
retry loop misreads "already succeeded" as "no longer needed" after a crash in the
post-call-pre-commit window, because ``revalidate()`` alone can't tell those apart.
The fix modelled here (``succeeded_effects``, checked before revalidate on every
cycle) is the pattern - not yet a shared ephor primitive, see the ADR.

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
    succeeded_effects: dict[str, object],
    rng: random.Random,
    *,
    now: datetime,
    force_none: bool,
) -> tuple[bool, datetime]:
    """Returns (is now terminal, clock time after this cycle).

    ``succeeded_effects`` models the "idempotent success first" check ADR-0017 found
    missing from a naive revalidate-then-execute loop: a real worker must know a
    retried job's idempotency key already succeeded *before* calling revalidate again,
    or revalidate correctly reporting "no longer needed" gets misread as "never
    happened" - see the ADR for why this can't be answered from the outbox job's own
    status alone in the crash window this test targets.
    """
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

    attempt = await store.start_attempt(
        job_id=job_id,
        worker_id=worker_id,
        previous_status=OutboxStatus.CLAIMED,
        lease_expires_at=job.lease_expires_at,
        now=now,
    )

    if job.idempotency_key in succeeded_effects:
        # A prior attempt's execute() already landed for real - a crash cost us the
        # outbox commit, not the effect. Finish the bookkeeping; don't ask revalidate
        # a question it can't answer correctly here (ADR-0017).
        await store.mark_succeeded(job_id, now=now)
        await store.finish_attempt(attempt.id, result_status="succeeded", now=now)
        return True, now

    if crash_at == CrashPoint.AFTER_CLAIM_BEFORE_EXECUTE:
        return False, now + timedelta(seconds=LEASE_SECONDS + 1)

    action = dict(job.payload_json)
    if not await adapter.revalidate(action):
        raise AssertionError(f"unexpectedly stale action for job {job_id}")
    effect = await adapter.execute(action, job.idempotency_key)
    succeeded_effects[job.idempotency_key] = effect.raw

    if crash_at == CrashPoint.AFTER_EXECUTE_BEFORE_COMMIT:
        # The real revoke already landed; succeeded_effects now knows it, even though
        # the outbox job itself doesn't yet - that's the whole point of this record.
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
    succeeded_effects: dict[str, object] = {}
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
                succeeded_effects,
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
