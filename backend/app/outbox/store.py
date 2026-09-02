"""Adapts OutboxRepository/OutboxAttemptRepository to satisfy ephor.outbox.OutboxStore
for real (ADR-0010, #38).

The claim/lease/retry SQL logic is completely unchanged; this only translates ORM rows
into plain objects matching ephor.outbox's structural shapes, and maps ``proposal_id``
(the generic interface) to ``proposed_action_id`` (this app's own column) - the closest
conceptual match, since both mean "the id of the thing that was proposed."

``create()`` is deliberately **not implemented**: ``OutboxJob.workflow_run_id`` and
``approval_request_id`` are NOT NULL foreign keys with no equivalent in the generic
interface (a Stripe detector has no workflow run). Per ADR-0008, closing that gap needs
a real schema change, not a translation wrapper - job creation continues to go through
``ApprovalService._create_outbox_job()``, which builds a full ORM row directly. Every
other method - the ones ``OutboxProcessor``/``OutboxWorker`` actually use - is real.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from ephor.outbox import OutboxAttempt as EphorOutboxAttempt
from ephor.outbox import OutboxJob as EphorOutboxJob
from ephor.outbox import OutboxStore
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.outbox import OutboxJob
from app.models.outbox_attempt import OutboxAttempt
from app.outbox.enums import OutboxStatus
from app.outbox.repository import OutboxAttemptRepository, OutboxRepository


@dataclass(frozen=True)
class _Job:
    """A concrete ``ephor.outbox.OutboxJob`` - what ``PostgresOutboxStore`` returns."""

    id: uuid.UUID
    proposal_id: uuid.UUID
    action_type: str
    payload_json: dict[str, object]
    payload_hash: str
    idempotency_key: str
    status: str
    priority: int
    attempt_count: int
    maximum_attempts: int
    next_attempt_at: datetime
    claimed_at: datetime | None = None
    claimed_by: str | None = None
    lease_expires_at: datetime | None = None
    last_error_code: str | None = None
    last_error_message: str | None = None
    completed_at: datetime | None = None
    dead_lettered_at: datetime | None = None


@dataclass(frozen=True)
class _Attempt:
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


def _translate_job(row: OutboxJob) -> EphorOutboxJob:
    return _Job(
        id=row.id,
        proposal_id=row.proposed_action_id,
        action_type=row.action_type,
        payload_json=row.payload_json,
        payload_hash=row.payload_hash,
        idempotency_key=row.idempotency_key,
        status=row.status,
        priority=row.priority,
        attempt_count=row.attempt_count,
        maximum_attempts=row.maximum_attempts,
        next_attempt_at=row.next_attempt_at,
        claimed_at=row.claimed_at,
        claimed_by=row.claimed_by,
        lease_expires_at=row.lease_expires_at,
        last_error_code=row.last_error_code,
        last_error_message=row.last_error_message,
        completed_at=row.completed_at,
        dead_lettered_at=row.dead_lettered_at,
    )


def _translate_attempt(row: OutboxAttempt) -> EphorOutboxAttempt:
    return _Attempt(
        id=row.id,
        outbox_job_id=row.outbox_job_id,
        attempt_number=row.attempt_number,
        worker_id=row.worker_id,
        previous_status=row.previous_status,
        started_at=row.started_at,
        lease_expires_at=row.lease_expires_at,
        finished_at=row.finished_at,
        result_status=row.result_status,
        error_code=row.error_code,
        error_message=row.error_message,
        retryable=row.retryable,
    )


class OutboxJobNotFoundError(Exception):
    """Raised when an operation targets an outbox job id that doesn't exist."""


class OutboxAttemptNotFoundError(Exception):
    """Raised when an operation targets an outbox attempt id that doesn't exist."""


class PostgresOutboxStore:
    """Wraps the two outbox repositories to implement ``ephor.outbox.OutboxStore``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._jobs = OutboxRepository(session)
        self._attempts = OutboxAttemptRepository(session)

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
    ) -> EphorOutboxJob:
        raise NotImplementedError(
            "OutboxJob.workflow_run_id/approval_request_id are NOT NULL foreign keys "
            "with no equivalent in the generic interface - see this module's "
            "docstring. Create jobs via ApprovalService._create_outbox_job() instead."
        )

    async def get(self, job_id: uuid.UUID) -> EphorOutboxJob | None:
        row = await self._jobs.get(job_id)
        return _translate_job(row) if row is not None else None

    async def get_by_idempotency_key(self, key: str) -> EphorOutboxJob | None:
        row = await self._jobs.get_by_idempotency_key(key)
        return _translate_job(row) if row is not None else None

    async def claim_batch(
        self, *, worker_id: str, now: datetime, lease_seconds: int, batch_size: int
    ) -> list[EphorOutboxJob]:
        rows = await self._jobs.claim_batch(
            worker_id=worker_id,
            now=now,
            lease_seconds=lease_seconds,
            batch_size=batch_size,
        )
        return [_translate_job(r) for r in rows]

    async def _locked_or_raise(self, job_id: uuid.UUID) -> OutboxJob:
        row = await self._jobs.get_for_update(job_id)
        if row is None:
            raise OutboxJobNotFoundError(f"no outbox job {job_id}")
        return row

    async def mark_processing(self, job_id: uuid.UUID) -> EphorOutboxJob:
        row = await self._locked_or_raise(job_id)
        await self._jobs.mark_processing(row)
        return _translate_job(row)

    async def mark_succeeded(
        self, job_id: uuid.UUID, *, now: datetime
    ) -> EphorOutboxJob:
        row = await self._locked_or_raise(job_id)
        await self._jobs.mark_succeeded(row, now=now)
        return _translate_job(row)

    async def schedule_retry(
        self,
        job_id: uuid.UUID,
        *,
        next_attempt_at: datetime,
        error_code: str,
        error_message: str,
    ) -> EphorOutboxJob:
        row = await self._locked_or_raise(job_id)
        await self._jobs.schedule_retry(
            row,
            next_attempt_at=next_attempt_at,
            error_code=error_code,
            error_message=error_message,
        )
        return _translate_job(row)

    async def mark_failed(
        self, job_id: uuid.UUID, *, now: datetime, error_code: str, error_message: str
    ) -> EphorOutboxJob:
        row = await self._locked_or_raise(job_id)
        await self._jobs.mark_failed(
            row, now=now, error_code=error_code, error_message=error_message
        )
        return _translate_job(row)

    async def mark_dead_letter(
        self, job_id: uuid.UUID, *, now: datetime, error_code: str, error_message: str
    ) -> EphorOutboxJob:
        row = await self._locked_or_raise(job_id)
        await self._jobs.mark_dead_letter(
            row, now=now, error_code=error_code, error_message=error_message
        )
        return _translate_job(row)

    async def mark_needs_manual_reconciliation(
        self, job_id: uuid.UUID, *, now: datetime, note: str
    ) -> EphorOutboxJob:
        """AgentOps never reaches this state today (every handler is fully in-process/
        simulated - see ADR-0010), so there's no existing repository method to delegate
        to. Mutates the row directly, following the exact same pattern as the other
        mark_* methods on OutboxRepository.
        """
        row = await self._locked_or_raise(job_id)
        row.status = OutboxStatus.NEEDS_MANUAL_RECONCILIATION
        row.claimed_at = None
        row.claimed_by = None
        row.lease_expires_at = None
        row.last_error_code = "needs_manual_reconciliation"
        row.last_error_message = note
        await self._session.flush()
        return _translate_job(row)

    async def cancel(
        self, job_id: uuid.UUID, *, now: datetime, reason: str
    ) -> EphorOutboxJob:
        row = await self._locked_or_raise(job_id)
        await self._jobs.cancel(row, now=now, reason=reason)
        return _translate_job(row)

    async def reset_for_retry(
        self, job_id: uuid.UUID, *, now: datetime, maximum_attempts: int
    ) -> EphorOutboxJob:
        row = await self._locked_or_raise(job_id)
        await self._jobs.reset_for_retry(
            row, now=now, maximum_attempts=maximum_attempts
        )
        return _translate_job(row)

    async def counts_by_status(self) -> dict[str, int]:
        return await self._jobs.counts_by_status()

    async def start_attempt(
        self,
        *,
        job_id: uuid.UUID,
        worker_id: str,
        previous_status: str,
        lease_expires_at: datetime | None,
        now: datetime,
    ) -> EphorOutboxAttempt:
        number = await self._attempts.next_attempt_number(job_id)
        row = await self._attempts.start(
            job_id=job_id,
            attempt_number=number,
            worker_id=worker_id,
            previous_status=previous_status,
            lease_expires_at=lease_expires_at,
            now=now,
        )
        return _translate_attempt(row)

    async def finish_attempt(
        self,
        attempt_id: uuid.UUID,
        *,
        result_status: str,
        now: datetime,
        error_code: str | None = None,
        error_message: str | None = None,
        retryable: bool | None = None,
    ) -> EphorOutboxAttempt:
        row = await self._attempts.get(attempt_id)
        if row is None:
            raise OutboxAttemptNotFoundError(f"no outbox attempt {attempt_id}")
        await self._attempts.finish(
            row,
            result_status=result_status,
            now=now,
            error_code=error_code,
            error_message=error_message,
            retryable=retryable,
        )
        return _translate_attempt(row)

    async def list_attempts(self, job_id: uuid.UUID) -> list[EphorOutboxAttempt]:
        rows = await self._attempts.list_for_job(job_id)
        return [_translate_attempt(r) for r in rows]


# Type-only proof that PostgresOutboxStore satisfies ephor.outbox.OutboxStore -
# exercised for real (not just statically) in tests/test_outbox_store.py.
def _assert_satisfies_outbox_store(store: OutboxStore) -> OutboxStore:
    return store
