"""Outbox job, Worker, Idempotency key, Exactly-once.

See CONTEXT.md "Durable execution" and ADR-0005 (the exactly-once boundary between the
core and an Adapter) and ADR-0010 (this extraction). ``OutboxJob``/``OutboxAttempt`` are
structural Protocols (see ``ephor.audit`` for why); ``OutboxStore`` is the interface any
backing store implements. ``InMemoryOutboxStore`` is the zero-setup implementation this
package ships with, and is what the ADR-0005 acceptance test runs against.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol


class OutboxStatus(StrEnum):
    PENDING = "pending"
    CLAIMED = "claimed"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    RETRY_SCHEDULED = "retry_scheduled"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"
    CANCELLED = "cancelled"
    # A worker crashed after an Adapter's external call may have succeeded but before
    # that outcome was committed, and the Adapter cannot confirm it (is_idempotent is
    # False). Never auto-retried - see ADR-0005. Distinct from a failure: the Effect may
    # well have happened.
    NEEDS_MANUAL_RECONCILIATION = "needs_manual_reconciliation"


# A job in one of these statuses is never claimed by a worker.
UNCLAIMABLE_STATUSES: frozenset[OutboxStatus] = frozenset(
    {
        OutboxStatus.SUCCEEDED,
        OutboxStatus.DEAD_LETTER,
        OutboxStatus.CANCELLED,
        OutboxStatus.FAILED,
        OutboxStatus.NEEDS_MANUAL_RECONCILIATION,
    }
)

CLAIMABLE_STATUSES: frozenset[OutboxStatus] = frozenset(
    {OutboxStatus.PENDING, OutboxStatus.RETRY_SCHEDULED}
)


def compute_backoff_seconds(
    *,
    attempt: int,
    base_seconds: float,
    max_seconds: float,
    jitter_ratio: float,
    job_id: uuid.UUID,
) -> float:
    """Exponential backoff ``base * 2**(attempt-1)``, capped, with bounded jitter.

    Jitter is seeded from ``job_id`` and ``attempt`` so a given (job, attempt) always
    yields the same delay - reproducible in tests, while still spreading load across a
    fleet of workers.
    """
    exponent = max(0, attempt - 1)
    raw = base_seconds * (2.0**exponent)
    capped = min(raw, max_seconds)
    if jitter_ratio <= 0:
        return capped
    # Deterministic fraction in [0, 1) from the job id and attempt.
    digest = hashlib.sha256(f"{job_id}:{attempt}".encode()).digest()
    fraction = int.from_bytes(digest[:8], "big") / float(1 << 64)
    # Symmetric jitter in [-jitter_ratio, +jitter_ratio] of the capped delay.
    jitter = capped * jitter_ratio * (2.0 * fraction - 1.0)
    return max(0.0, capped + jitter)


def next_attempt_at(
    *,
    now: datetime,
    attempt: int,
    base_seconds: float,
    max_seconds: float,
    jitter_ratio: float,
    job_id: uuid.UUID,
) -> datetime:
    delay = compute_backoff_seconds(
        attempt=attempt,
        base_seconds=base_seconds,
        max_seconds=max_seconds,
        jitter_ratio=jitter_ratio,
        job_id=job_id,
    )
    return now + timedelta(seconds=delay)


class RetryableEffectError(Exception):
    """Raised by an Adapter when the Effect might succeed if retried."""


class PermanentEffectError(Exception):
    """Raised by an Adapter when the Effect will never succeed - do not retry."""


class OutboxAttempt(Protocol):
    """One immutable record of a worker's attempt to process an Outbox job."""

    @property
    def id(self) -> uuid.UUID: ...
    @property
    def outbox_job_id(self) -> uuid.UUID: ...
    @property
    def attempt_number(self) -> int: ...
    @property
    def worker_id(self) -> str: ...
    @property
    def previous_status(self) -> str: ...
    @property
    def started_at(self) -> datetime: ...
    @property
    def lease_expires_at(self) -> datetime | None: ...
    @property
    def finished_at(self) -> datetime | None: ...
    @property
    def result_status(self) -> str | None: ...
    @property
    def error_code(self) -> str | None: ...
    @property
    def error_message(self) -> str | None: ...
    @property
    def retryable(self) -> bool | None: ...


class OutboxJob(Protocol):
    """The read shape of one durable Outbox job, per ADR-0008's generic shape."""

    @property
    def id(self) -> uuid.UUID: ...
    @property
    def proposal_id(self) -> uuid.UUID: ...
    @property
    def action_type(self) -> str: ...
    @property
    def payload_json(self) -> dict[str, object]: ...
    @property
    def payload_hash(self) -> str: ...
    @property
    def idempotency_key(self) -> str: ...
    @property
    def status(self) -> str: ...
    @property
    def priority(self) -> int: ...
    @property
    def attempt_count(self) -> int: ...
    @property
    def maximum_attempts(self) -> int: ...
    @property
    def next_attempt_at(self) -> datetime: ...
    @property
    def claimed_at(self) -> datetime | None: ...
    @property
    def claimed_by(self) -> str | None: ...
    @property
    def lease_expires_at(self) -> datetime | None: ...
    @property
    def last_error_code(self) -> str | None: ...
    @property
    def last_error_message(self) -> str | None: ...
    @property
    def completed_at(self) -> datetime | None: ...
    @property
    def dead_lettered_at(self) -> datetime | None: ...


class OutboxStore(Protocol):
    """The persistence interface any backing store implements. See ADR-0010."""

    async def create(
        self,
        *,
        proposal_id: uuid.UUID,
        action_type: str,
        payload_json: dict[str, object],
        idempotency_key: str,
        next_attempt_at: datetime,
        priority: int = 100,
        maximum_attempts: int = 5,
    ) -> OutboxJob: ...

    async def get(self, job_id: uuid.UUID) -> OutboxJob | None: ...

    async def get_by_idempotency_key(self, key: str) -> OutboxJob | None: ...

    async def claim_batch(
        self, *, worker_id: str, now: datetime, lease_seconds: int, batch_size: int
    ) -> list[OutboxJob]:
        """Claim up to ``batch_size`` due, unlocked jobs and lease them to a worker."""
        ...

    async def mark_processing(self, job_id: uuid.UUID) -> OutboxJob: ...
    async def mark_succeeded(
        self, job_id: uuid.UUID, *, now: datetime
    ) -> OutboxJob: ...

    async def schedule_retry(
        self,
        job_id: uuid.UUID,
        *,
        next_attempt_at: datetime,
        error_code: str,
        error_message: str,
    ) -> OutboxJob: ...

    async def mark_failed(
        self, job_id: uuid.UUID, *, now: datetime, error_code: str, error_message: str
    ) -> OutboxJob: ...

    async def mark_dead_letter(
        self, job_id: uuid.UUID, *, now: datetime, error_code: str, error_message: str
    ) -> OutboxJob: ...

    async def mark_needs_manual_reconciliation(
        self, job_id: uuid.UUID, *, now: datetime, note: str
    ) -> OutboxJob:
        """Route a job here instead of retrying - see ``OutboxStatus`` and ADR-0005."""
        ...

    async def cancel(
        self, job_id: uuid.UUID, *, now: datetime, reason: str
    ) -> OutboxJob: ...

    async def reset_for_retry(
        self, job_id: uuid.UUID, *, now: datetime, maximum_attempts: int
    ) -> OutboxJob: ...

    async def counts_by_status(self) -> dict[str, int]: ...

    async def start_attempt(
        self,
        *,
        job_id: uuid.UUID,
        worker_id: str,
        previous_status: str,
        lease_expires_at: datetime | None,
        now: datetime,
    ) -> OutboxAttempt: ...

    async def finish_attempt(
        self,
        attempt_id: uuid.UUID,
        *,
        result_status: str,
        now: datetime,
        error_code: str | None = None,
        error_message: str | None = None,
        retryable: bool | None = None,
    ) -> OutboxAttempt: ...

    async def list_attempts(self, job_id: uuid.UUID) -> list[OutboxAttempt]: ...


@dataclass
class InMemoryOutboxJob:
    """A plain, concrete ``OutboxJob`` - the shape ``InMemoryOutboxStore`` returns."""

    id: uuid.UUID
    proposal_id: uuid.UUID
    action_type: str
    payload_json: dict[str, object]
    payload_hash: str
    idempotency_key: str
    status: str
    next_attempt_at: datetime
    priority: int = 100
    attempt_count: int = 0
    maximum_attempts: int = 5
    claimed_at: datetime | None = None
    claimed_by: str | None = None
    lease_expires_at: datetime | None = None
    last_error_code: str | None = None
    last_error_message: str | None = None
    completed_at: datetime | None = None
    dead_lettered_at: datetime | None = None


@dataclass
class InMemoryAttempt:
    id: uuid.UUID
    outbox_job_id: uuid.UUID
    attempt_number: int
    worker_id: str
    previous_status: str
    started_at: datetime
    lease_expires_at: datetime | None = None
    finished_at: datetime | None = None
    result_status: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    retryable: bool | None = None


class OutboxJobNotFoundError(Exception):
    """Raised when an operation targets an Outbox job id that doesn't exist."""


class InMemoryOutboxStore:
    """A process-local, in-memory ``OutboxStore``. Not durable across restarts."""

    def __init__(self) -> None:
        self._jobs: dict[uuid.UUID, InMemoryOutboxJob] = {}
        self._attempts: dict[uuid.UUID, InMemoryAttempt] = {}

    def _get_or_raise(self, job_id: uuid.UUID) -> InMemoryOutboxJob:
        job = self._jobs.get(job_id)
        if job is None:
            raise OutboxJobNotFoundError(f"no outbox job {job_id}")
        return job

    async def create(
        self,
        *,
        proposal_id: uuid.UUID,
        action_type: str,
        payload_json: dict[str, object],
        idempotency_key: str,
        next_attempt_at: datetime,
        priority: int = 100,
        maximum_attempts: int = 5,
    ) -> OutboxJob:
        job = InMemoryOutboxJob(
            id=uuid.uuid4(),
            proposal_id=proposal_id,
            action_type=action_type,
            payload_json=payload_json,
            payload_hash=hashlib.sha256(
                repr(sorted(payload_json.items())).encode()
            ).hexdigest(),
            idempotency_key=idempotency_key,
            status=OutboxStatus.PENDING,
            next_attempt_at=next_attempt_at,
            priority=priority,
            maximum_attempts=maximum_attempts,
        )
        self._jobs[job.id] = job
        return job

    async def get(self, job_id: uuid.UUID) -> OutboxJob | None:
        return self._jobs.get(job_id)

    async def get_by_idempotency_key(self, key: str) -> OutboxJob | None:
        return next((j for j in self._jobs.values() if j.idempotency_key == key), None)

    async def claim_batch(
        self, *, worker_id: str, now: datetime, lease_seconds: int, batch_size: int
    ) -> list[OutboxJob]:
        claimable_or_reclaimable = CLAIMABLE_STATUSES | {
            OutboxStatus.CLAIMED,
            OutboxStatus.PROCESSING,
        }
        due = [
            j
            for j in self._jobs.values()
            if OutboxStatus(j.status) in claimable_or_reclaimable
            and j.next_attempt_at <= now
            and (j.lease_expires_at is None or j.lease_expires_at <= now)
        ]
        due.sort(key=lambda j: (-j.priority, j.next_attempt_at))
        claimed = due[:batch_size]
        lease_until = now + timedelta(seconds=lease_seconds)
        for job in claimed:
            job.status = OutboxStatus.CLAIMED
            job.claimed_at = now
            job.claimed_by = worker_id
            job.lease_expires_at = lease_until
        return list(claimed)

    async def mark_processing(self, job_id: uuid.UUID) -> OutboxJob:
        job = self._get_or_raise(job_id)
        job.status = OutboxStatus.PROCESSING
        return job

    async def mark_succeeded(self, job_id: uuid.UUID, *, now: datetime) -> OutboxJob:
        job = self._get_or_raise(job_id)
        job.status = OutboxStatus.SUCCEEDED
        job.completed_at = now
        job.lease_expires_at = None
        job.last_error_code = None
        job.last_error_message = None
        return job

    async def schedule_retry(
        self,
        job_id: uuid.UUID,
        *,
        next_attempt_at: datetime,
        error_code: str,
        error_message: str,
    ) -> OutboxJob:
        job = self._get_or_raise(job_id)
        job.status = OutboxStatus.RETRY_SCHEDULED
        job.attempt_count += 1
        job.next_attempt_at = next_attempt_at
        job.claimed_at = None
        job.claimed_by = None
        job.lease_expires_at = None
        job.last_error_code = error_code
        job.last_error_message = error_message
        return job

    async def mark_failed(
        self, job_id: uuid.UUID, *, now: datetime, error_code: str, error_message: str
    ) -> OutboxJob:
        job = self._get_or_raise(job_id)
        job.status = OutboxStatus.FAILED
        job.attempt_count += 1
        job.completed_at = now
        job.claimed_at = None
        job.claimed_by = None
        job.lease_expires_at = None
        job.last_error_code = error_code
        job.last_error_message = error_message
        return job

    async def mark_dead_letter(
        self, job_id: uuid.UUID, *, now: datetime, error_code: str, error_message: str
    ) -> OutboxJob:
        job = self._get_or_raise(job_id)
        job.status = OutboxStatus.DEAD_LETTER
        job.attempt_count += 1
        job.dead_lettered_at = now
        job.claimed_at = None
        job.claimed_by = None
        job.lease_expires_at = None
        job.last_error_code = error_code
        job.last_error_message = error_message
        return job

    async def mark_needs_manual_reconciliation(
        self, job_id: uuid.UUID, *, now: datetime, note: str
    ) -> OutboxJob:
        job = self._get_or_raise(job_id)
        job.status = OutboxStatus.NEEDS_MANUAL_RECONCILIATION
        job.claimed_at = None
        job.claimed_by = None
        job.lease_expires_at = None
        job.last_error_code = "needs_manual_reconciliation"
        job.last_error_message = note
        return job

    async def cancel(
        self, job_id: uuid.UUID, *, now: datetime, reason: str
    ) -> OutboxJob:
        job = self._get_or_raise(job_id)
        job.status = OutboxStatus.CANCELLED
        job.completed_at = now
        job.claimed_at = None
        job.claimed_by = None
        job.lease_expires_at = None
        job.last_error_code = "cancelled"
        job.last_error_message = reason
        return job

    async def reset_for_retry(
        self, job_id: uuid.UUID, *, now: datetime, maximum_attempts: int
    ) -> OutboxJob:
        job = self._get_or_raise(job_id)
        job.status = OutboxStatus.PENDING
        job.next_attempt_at = now
        job.maximum_attempts = job.attempt_count + maximum_attempts
        job.completed_at = None
        job.dead_lettered_at = None
        job.claimed_at = None
        job.claimed_by = None
        job.lease_expires_at = None
        return job

    async def counts_by_status(self) -> dict[str, int]:
        counts = {status.value: 0 for status in OutboxStatus}
        for job in self._jobs.values():
            counts[job.status] = counts.get(job.status, 0) + 1
        return counts

    async def start_attempt(
        self,
        *,
        job_id: uuid.UUID,
        worker_id: str,
        previous_status: str,
        lease_expires_at: datetime | None,
        now: datetime,
    ) -> OutboxAttempt:
        existing = [a for a in self._attempts.values() if a.outbox_job_id == job_id]
        attempt = InMemoryAttempt(
            id=uuid.uuid4(),
            outbox_job_id=job_id,
            attempt_number=len(existing) + 1,
            worker_id=worker_id,
            previous_status=previous_status,
            lease_expires_at=lease_expires_at,
            started_at=now,
        )
        self._attempts[attempt.id] = attempt
        return attempt

    async def finish_attempt(
        self,
        attempt_id: uuid.UUID,
        *,
        result_status: str,
        now: datetime,
        error_code: str | None = None,
        error_message: str | None = None,
        retryable: bool | None = None,
    ) -> OutboxAttempt:
        attempt = self._attempts[attempt_id]
        attempt.result_status = result_status
        attempt.error_code = error_code
        attempt.error_message = error_message
        attempt.retryable = retryable
        attempt.finished_at = now
        return attempt

    async def list_attempts(self, job_id: uuid.UUID) -> list[OutboxAttempt]:
        rows = [a for a in self._attempts.values() if a.outbox_job_id == job_id]
        return sorted(rows, key=lambda a: a.attempt_number)


__all__ = [
    "CLAIMABLE_STATUSES",
    "UNCLAIMABLE_STATUSES",
    "InMemoryAttempt",
    "InMemoryOutboxJob",
    "InMemoryOutboxStore",
    "OutboxAttempt",
    "OutboxJob",
    "OutboxJobNotFoundError",
    "OutboxStatus",
    "OutboxStore",
    "PermanentEffectError",
    "RetryableEffectError",
    "compute_backoff_seconds",
    "next_attempt_at",
]
