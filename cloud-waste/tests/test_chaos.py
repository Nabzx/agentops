"""Chaos-tests the real pipeline, not just the outbox in isolation - for both
Adapters this package ships.

Mirrors ``wallet-guard/tests/test_chaos.py`` and ``stripe-recovery/tests/test_chaos.py``
exactly: ``ephor/tests/chaos_harness.py`` (ADR-0015) proves the outbox's own state
machine holds exactly-once against a synthetic mock adapter; this drives the same
randomised crash injection through the *real* Adapters (``CloudWasteAdapter``,
``IdleInstanceAdapter``) wrapping the *real* ``FakeCloudClient``, via
``ephor.outbox.InMemoryOutboxStore``'s real claim/attempt lifecycle.

A worker checks ``store.list_attempts(job_id)`` before starting a new attempt - if a
prior attempt already exists, ``adapter.check_completed`` is asked first (ADR-0018),
and only falls through to ``revalidate()``/``execute()`` if it says ``None``. On a
genuine first attempt, ``check_completed`` is never called at all. The crash-injection
driver itself is adapter-agnostic - it only ever calls the three ``Adapter`` methods
every Adapter in this project implements - so one harness runs both resource types,
parametrised rather than duplicated.

Deterministic and reproducible, same discipline as the core's own harness: each trial
is seeded from its own index.
"""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Literal

from ephor.effects import Adapter
from ephor.outbox import UNCLAIMABLE_STATUSES, InMemoryOutboxStore, OutboxStatus

from cloud_waste.adapter import CloudWasteAdapter, IdleInstanceAdapter
from cloud_waste.client import ElasticIp, FakeCloudClient, Instance

NOW = datetime(2026, 1, 1, tzinfo=UTC)
LEASE_SECONDS = 30
MAX_CYCLES = 15

ResourceKind = Literal["address", "instance"]


class CrashPoint(StrEnum):
    NONE = "none"
    BEFORE_CLAIM = "before_claim"
    AFTER_CLAIM_BEFORE_EXECUTE = "after_claim_before_execute"
    AFTER_EXECUTE_BEFORE_COMMIT = "after_execute_before_commit"
    AFTER_COMMIT_BEFORE_FINISH = "after_commit_before_finish"


@dataclass
class Violation:
    seed: int
    resource_id: str
    detail: str

    def __str__(self) -> str:
        return f"[seed {self.seed}] {self.resource_id}: {self.detail}"


@dataclass
class TrialResult:
    seed: int
    jobs: int = 0
    violations: list[Violation] = field(default_factory=list)


async def _advance_one_cycle(
    store: InMemoryOutboxStore,
    adapter: Adapter,
    job_id: uuid.UUID,
    rng: random.Random,
    *,
    now: datetime,
    force_none: bool,
) -> tuple[bool, datetime]:
    """Returns (is now terminal, clock time after this cycle). Adapter-agnostic - only
    ever calls the three methods every ``Adapter`` in this project implements.
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
    action = dict(job.payload_json)

    # ADR-0018: a prior attempt existing is the *only* signal that justifies asking
    # check_completed at all - never on a genuine first attempt.
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
        # The real effect already landed; check_completed will find it on the next
        # cycle - the outbox job itself doesn't know yet, which is the whole point of
        # asking the adapter rather than trusting job status.
        return False, now + timedelta(seconds=LEASE_SECONDS + 1)

    await store.mark_succeeded(job_id, now=now)

    if crash_at == CrashPoint.AFTER_COMMIT_BEFORE_FINISH:
        return True, now

    await store.finish_attempt(attempt.id, result_status="succeeded", now=now)
    return True, now


def _build_adapter(kind: ResourceKind, client: FakeCloudClient) -> Adapter:
    if kind == "address":
        return CloudWasteAdapter(client)
    return IdleInstanceAdapter(client)


def _seed_resource(
    kind: ResourceKind, client: FakeCloudClient, resource_id: str
) -> None:
    if kind == "address":
        client.seed(
            ElasticIp(
                id=resource_id,
                public_ip="203.0.113.1",
                association_id=None,
                instance_id=None,
            )
        )
    else:
        client.seed_instance(
            Instance(
                id=resource_id,
                state="running",
                launch_time=NOW - timedelta(days=90),
                tags={},
                avg_cpu_percent=1.0,
                avg_network_bytes=1_000.0,
            )
        )


async def _effect_really_landed(
    kind: ResourceKind, client: FakeCloudClient, resource_id: str
) -> bool:
    """Not just trusting the outbox's status - ask the actual cloud state. An address
    ceases to exist on release; an instance stays present but changes state."""
    if kind == "address":
        remaining = await client.list_addresses()
        return not any(a.id == resource_id for a in remaining)
    instances = await client.list_instances()
    current = next((i for i in instances if i.id == resource_id), None)
    return current is not None and current.state == "stopped"


async def run_trial(seed: int, kind: ResourceKind) -> TrialResult:
    rng = random.Random(seed)  # noqa: S311 - deterministic test fuzzing, not crypto
    store = InMemoryOutboxStore()
    client = FakeCloudClient()
    adapter = _build_adapter(kind, client)
    action_type = "release_address" if kind == "address" else "stop_instance"
    payload_key = "allocation_id" if kind == "address" else "instance_id"
    result = TrialResult(seed=seed)

    resource_ids: list[str] = []
    for i in range(rng.randint(2, 5)):
        resource_id = f"{kind}-{seed}-{i}"
        _seed_resource(kind, client, resource_id)
        resource_ids.append(resource_id)

    now = NOW
    for resource_id in resource_ids:
        job = await store.create(
            proposal_id=uuid.uuid4(),
            action_type=action_type,
            payload_json={payload_key: resource_id},
            idempotency_key=f"{action_type}-{resource_id}",
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
                Violation(seed, resource_id, "never reached a terminal state")
            )
            continue

        final = await store.get(job.id)
        assert final is not None
        final_status = OutboxStatus(final.status)

        if not await _effect_really_landed(kind, client, resource_id):
            result.violations.append(
                Violation(seed, resource_id, "effect did not land despite SUCCEEDED")
            )
        if final_status != OutboxStatus.SUCCEEDED:
            result.violations.append(
                Violation(seed, resource_id, f"ended {final_status}, not SUCCEEDED")
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
                    Violation(seed, resource_id, "a terminal job was reclaimed later")
                )

    return result


async def _run_all(kind: ResourceKind, trials: int) -> None:
    results = [await run_trial(seed, kind) for seed in range(trials)]

    violations = [v for r in results for v in r.violations]
    assert not violations, "\n".join(str(v) for v in violations)

    total_jobs = sum(r.jobs for r in results)
    assert total_jobs >= trials * 2


async def test_address_adapter_holds_exactly_once_under_crash_injection() -> None:
    await _run_all("address", trials=200)


async def test_instance_adapter_holds_exactly_once_under_crash_injection() -> None:
    await _run_all("instance", trials=200)
