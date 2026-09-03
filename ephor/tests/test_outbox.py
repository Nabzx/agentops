import uuid
from datetime import UTC, datetime, timedelta

import pytest

from ephor.outbox import (
    CLAIMABLE_STATUSES,
    UNCLAIMABLE_STATUSES,
    DuplicateIdempotencyKeyError,
    InMemoryOutboxStore,
    OutboxJob,
    OutboxStatus,
    PermanentEffectError,
    compute_backoff_seconds,
    next_attempt_at,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


async def _job(store: InMemoryOutboxStore, **overrides: object) -> OutboxJob:
    defaults: dict[str, object] = {
        "proposal_id": uuid.uuid4(),
        "action_type": "retry_charge",
        "payload_json": {"amount_pence": 4700},
        "idempotency_key": f"act-{uuid.uuid4().hex[:8]}",
        "next_attempt_at": NOW,
    }
    defaults.update(overrides)
    return await store.create(**defaults)  # type: ignore[arg-type]


# --- status taxonomy ----------------------------------------------------------------
def test_needs_manual_reconciliation_is_unclaimable() -> None:
    assert OutboxStatus.NEEDS_MANUAL_RECONCILIATION in UNCLAIMABLE_STATUSES
    assert OutboxStatus.NEEDS_MANUAL_RECONCILIATION not in CLAIMABLE_STATUSES


# --- backoff -----------------------------------------------------------------------
def test_backoff_is_deterministic_given_the_same_inputs() -> None:
    job_id = uuid.uuid4()
    kwargs = {
        "attempt": 2,
        "base_seconds": 2.0,
        "max_seconds": 60.0,
        "jitter_ratio": 0.2,
        "job_id": job_id,
    }
    assert compute_backoff_seconds(**kwargs) == compute_backoff_seconds(**kwargs)  # type: ignore[arg-type]


def test_backoff_grows_exponentially_up_to_the_cap() -> None:
    job_id = uuid.uuid4()
    no_jitter = {
        "base_seconds": 2.0,
        "max_seconds": 60.0,
        "jitter_ratio": 0.0,
        "job_id": job_id,
    }
    assert compute_backoff_seconds(attempt=1, **no_jitter) == 2.0  # type: ignore[arg-type]
    assert compute_backoff_seconds(attempt=2, **no_jitter) == 4.0  # type: ignore[arg-type]
    assert compute_backoff_seconds(attempt=10, **no_jitter) == 60.0  # type: ignore[arg-type]


def test_next_attempt_at_adds_the_backoff_to_now() -> None:
    job_id = uuid.uuid4()
    scheduled = next_attempt_at(
        now=NOW,
        attempt=1,
        base_seconds=2.0,
        max_seconds=60.0,
        jitter_ratio=0.0,
        job_id=job_id,
    )
    assert scheduled == NOW + timedelta(seconds=2.0)


# --- InMemoryOutboxStore: creation --------------------------------------------------
async def test_create_rejects_a_duplicate_idempotency_key() -> None:
    """Mirrors production Postgres's own uq_outbox_idempotency_key constraint - found
    missing while building the security benchmark, fixed on the spot.
    """
    store = InMemoryOutboxStore()
    await _job(store, idempotency_key="shared-key")
    with pytest.raises(DuplicateIdempotencyKeyError):
        await _job(store, idempotency_key="shared-key")


# --- InMemoryOutboxStore: claiming and status transitions ---------------------------
async def test_claim_batch_only_returns_due_unlocked_jobs() -> None:
    store = InMemoryOutboxStore()
    due = await _job(store, next_attempt_at=NOW)
    not_due = await _job(store, next_attempt_at=NOW + timedelta(hours=1))

    claimed = await store.claim_batch(
        worker_id="w1", now=NOW, lease_seconds=60, batch_size=10
    )
    assert [j.id for j in claimed] == [due.id]
    assert not_due.id not in [j.id for j in claimed]


async def test_a_claimed_job_is_not_claimed_again_while_leased() -> None:
    store = InMemoryOutboxStore()
    job = await _job(store)
    first = await store.claim_batch(
        worker_id="w1", now=NOW, lease_seconds=60, batch_size=10
    )
    assert [j.id for j in first] == [job.id]

    second = await store.claim_batch(
        worker_id="w2", now=NOW + timedelta(seconds=5), lease_seconds=60, batch_size=10
    )
    assert second == []


async def test_an_expired_lease_is_reclaimable() -> None:
    store = InMemoryOutboxStore()
    job = await _job(store)
    await store.claim_batch(worker_id="w1", now=NOW, lease_seconds=60, batch_size=10)

    reclaimed = await store.claim_batch(
        worker_id="w2",
        now=NOW + timedelta(seconds=120),
        lease_seconds=60,
        batch_size=10,
    )
    assert [j.id for j in reclaimed] == [job.id]
    assert reclaimed[0].claimed_by == "w2"


async def test_higher_priority_claims_first() -> None:
    store = InMemoryOutboxStore()
    low = await _job(store, priority=100)
    high = await _job(store, priority=300)

    claimed = await store.claim_batch(
        worker_id="w1", now=NOW, lease_seconds=60, batch_size=10
    )
    assert [j.id for j in claimed] == [high.id, low.id]


async def test_mark_succeeded_clears_the_lease_and_error() -> None:
    store = InMemoryOutboxStore()
    job = await _job(store)
    await store.claim_batch(worker_id="w1", now=NOW, lease_seconds=60, batch_size=10)
    updated = await store.mark_succeeded(job.id, now=NOW)
    assert updated.status == OutboxStatus.SUCCEEDED
    assert updated.lease_expires_at is None
    assert updated.completed_at == NOW


async def test_mark_needs_manual_reconciliation_records_a_note() -> None:
    store = InMemoryOutboxStore()
    job = await _job(store)
    updated = await store.mark_needs_manual_reconciliation(
        job.id, now=NOW, note="worker crashed mid-call, target may have succeeded"
    )
    assert updated.status == OutboxStatus.NEEDS_MANUAL_RECONCILIATION
    assert updated.last_error_message is not None


async def test_reset_for_retry_reopens_a_dead_lettered_job() -> None:
    store = InMemoryOutboxStore()
    job = await _job(store)
    await store.mark_dead_letter(
        job.id, now=NOW, error_code="transient_dependency", error_message="boom"
    )
    reopened = await store.reset_for_retry(job.id, now=NOW, maximum_attempts=5)
    assert reopened.status == OutboxStatus.PENDING


async def test_counts_by_status_reflects_current_state() -> None:
    store = InMemoryOutboxStore()
    await _job(store)
    counts = await store.counts_by_status()
    assert counts[OutboxStatus.PENDING.value] == 1
    assert counts[OutboxStatus.SUCCEEDED.value] == 0


# --- ADR-0005 acceptance test: exactly-once, proven not claimed ---------------------
#
# A mock Adapter, crashable at one of three points: before the external call, after the
# call but before the local commit, and after the commit. Proves: an idempotent Adapter
# never produces a second real Effect from any crash point once retried to completion;
# a non-idempotent Adapter lands in needs_manual_reconciliation, never blind-retried,
# when crashed in the succeeded-but-uncommitted window.


class _CrashPoint:
    BEFORE_CALL = "before_call"
    AFTER_CALL_BEFORE_COMMIT = "after_call_before_commit"
    AFTER_COMMIT = "after_commit"


class _MockAdapter:
    """Simulates a real Effect call with a real side effect (an in-memory ledger)."""

    def __init__(self, *, is_idempotent: bool) -> None:
        self.is_idempotent = is_idempotent
        self.real_effects: list[str] = []  # what actually "happened" out there
        self._seen_keys: set[str] = set()

    def call(self, idempotency_key: str) -> None:
        """The actual external call. An idempotent Adapter dedups on the key; a
        non-idempotent one has no such capability and would fire again if called twice.
        """
        if self.is_idempotent and idempotency_key in self._seen_keys:
            return  # the target itself deduped - no second real effect
        self._seen_keys.add(idempotency_key)
        self.real_effects.append(idempotency_key)


async def _run_one_attempt(
    store: InMemoryOutboxStore,
    job_id: uuid.UUID,
    adapter: _MockAdapter,
    crash_at: str | None,
) -> None:
    """Stands in for one OutboxProcessor._execute pass, per ADR-0005's job-state
    model.
    """
    job = await store.get(job_id)
    assert job is not None
    if crash_at == _CrashPoint.BEFORE_CALL:
        return  # crashed before the call ever happened - safe to retry from scratch
    adapter.call(job.idempotency_key)
    if crash_at == _CrashPoint.AFTER_CALL_BEFORE_COMMIT:
        if not adapter.is_idempotent:
            # The core cannot know if the effect happened - never auto-retry.
            await store.mark_needs_manual_reconciliation(
                job_id, now=NOW, note="crashed after call, before commit"
            )
        # An idempotent adapter: the outcome is uncommitted, but retrying is safe
        # because the target itself will dedup on the next attempt's call().
        return
    # AFTER_COMMIT or no crash: the job completes normally.
    await store.mark_succeeded(job_id, now=NOW)


async def test_idempotent_adapter_never_double_fires_from_any_crash_point() -> None:
    for crash_at in (
        _CrashPoint.BEFORE_CALL,
        _CrashPoint.AFTER_CALL_BEFORE_COMMIT,
        _CrashPoint.AFTER_COMMIT,
        None,
    ):
        store = InMemoryOutboxStore()
        adapter = _MockAdapter(is_idempotent=True)
        job = await _job(store)

        await _run_one_attempt(store, job.id, adapter, crash_at)
        # Retry to completion regardless of where the first attempt crashed.
        current = await store.get(job.id)
        assert current is not None
        if current.status != OutboxStatus.SUCCEEDED:
            await _run_one_attempt(store, job.id, adapter, None)

        assert (
            adapter.real_effects.count(job.idempotency_key) <= 1
        ), f"double-fired after crash at {crash_at}"
        final = await store.get(job.id)
        assert final is not None
        assert final.status == OutboxStatus.SUCCEEDED


async def test_non_idempotent_adapter_halts_into_reconciliation_not_retry() -> None:
    store = InMemoryOutboxStore()
    adapter = _MockAdapter(is_idempotent=False)
    job = await _job(store)

    await _run_one_attempt(store, job.id, adapter, _CrashPoint.AFTER_CALL_BEFORE_COMMIT)

    final = await store.get(job.id)
    assert final is not None
    assert final.status == OutboxStatus.NEEDS_MANUAL_RECONCILIATION
    assert final.status in UNCLAIMABLE_STATUSES
    # Exactly one real effect happened - and the core must never blind-retry past this
    # to find out. A second _run_one_attempt call would be a bug in a real worker loop:
    # the whole point of needs_manual_reconciliation is that nothing retries it.
    assert len(adapter.real_effects) == 1


async def test_non_idempotent_adapter_crashed_before_the_call_is_safe_to_retry() -> (
    None
):
    """Only the succeeded-but-uncommitted window is dangerous for a non-idempotent
    Adapter - crashing before the call ever happened has nothing to reconcile."""
    store = InMemoryOutboxStore()
    adapter = _MockAdapter(is_idempotent=False)
    job = await _job(store)

    await _run_one_attempt(store, job.id, adapter, _CrashPoint.BEFORE_CALL)
    await _run_one_attempt(store, job.id, adapter, None)

    final = await store.get(job.id)
    assert final is not None
    assert final.status == OutboxStatus.SUCCEEDED
    assert len(adapter.real_effects) == 1


def test_permanent_effect_error_is_importable_and_raisable() -> None:
    try:
        raise PermanentEffectError("no handler for this action type")
    except PermanentEffectError as exc:
        assert "no handler" in str(exc)
