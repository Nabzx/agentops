"""Proves PostgresAuditStore's outbox sibling for real: PostgresOutboxStore against a
real seeded job, not just a structural mypy check (S6, #38).
"""

from __future__ import annotations

import uuid

from app.outbox.enums import OutboxStatus
from app.outbox.store import (
    OutboxAttemptNotFoundError,
    OutboxJobNotFoundError,
    PostgresOutboxStore,
    _assert_satisfies_outbox_store,
)
from app.rules.clock import seed_reference_clock
from ephor.outbox import OutboxStore
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.test_outbox_execution import (  # reuse the execution harness
    _approved_job,
    maker,  # noqa: F401
)

NOW = seed_reference_clock().now()


async def test_postgres_outbox_store_satisfies_the_protocol(
    maker: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    async with maker() as session:
        store: OutboxStore = PostgresOutboxStore(session)
        assert _assert_satisfies_outbox_store(store) is store


async def test_get_translates_proposed_action_id_to_proposal_id(
    maker: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    job_id, _, _ = await _approved_job(maker)
    async with maker() as session:
        store = PostgresOutboxStore(session)
        job = await store.get(job_id)
        assert job is not None
        assert job.status == OutboxStatus.PENDING
        assert isinstance(job.proposal_id, uuid.UUID)


async def test_get_returns_none_for_an_unknown_job(
    maker: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    async with maker() as session:
        store = PostgresOutboxStore(session)
        assert await store.get(uuid.uuid4()) is None


async def test_claim_batch_returns_translated_jobs(
    maker: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    job_id, _, _ = await _approved_job(maker)
    async with maker() as session:
        store = PostgresOutboxStore(session)
        claimed = await store.claim_batch(
            worker_id="test-worker", now=NOW, lease_seconds=60, batch_size=10
        )
        await session.commit()
    assert job_id in [j.id for j in claimed]


async def test_mark_succeeded_updates_status_and_completed_at(
    maker: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    job_id, _, _ = await _approved_job(maker)
    async with maker() as session:
        store = PostgresOutboxStore(session)
        updated = await store.mark_succeeded(job_id, now=NOW)
        await session.commit()
    assert updated.status == OutboxStatus.SUCCEEDED
    assert updated.completed_at == NOW


async def test_mark_succeeded_raises_for_an_unknown_job(
    maker: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    async with maker() as session:
        store = PostgresOutboxStore(session)
        try:
            await store.mark_succeeded(uuid.uuid4(), now=NOW)
            raise AssertionError("expected OutboxJobNotFoundError")
        except OutboxJobNotFoundError:
            pass


async def test_mark_needs_manual_reconciliation_records_a_note(
    maker: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    job_id, _, _ = await _approved_job(maker)
    async with maker() as session:
        store = PostgresOutboxStore(session)
        updated = await store.mark_needs_manual_reconciliation(
            job_id, now=NOW, note="crashed after the call, before commit"
        )
        await session.commit()
    assert updated.status == OutboxStatus.NEEDS_MANUAL_RECONCILIATION
    assert updated.last_error_message == "crashed after the call, before commit"


async def test_start_attempt_and_finish_attempt_round_trip(
    maker: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    job_id, _, _ = await _approved_job(maker)
    async with maker() as session:
        store = PostgresOutboxStore(session)
        attempt = await store.start_attempt(
            job_id=job_id,
            worker_id="test-worker",
            previous_status=OutboxStatus.PENDING,
            lease_expires_at=None,
            now=NOW,
        )
        assert attempt.attempt_number == 1
        finished = await store.finish_attempt(
            attempt.id, result_status="succeeded", now=NOW
        )
        await session.commit()
    assert finished.result_status == "succeeded"
    assert finished.id == attempt.id


async def test_finish_attempt_raises_for_an_unknown_attempt(
    maker: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    async with maker() as session:
        store = PostgresOutboxStore(session)
        try:
            await store.finish_attempt(uuid.uuid4(), result_status="succeeded", now=NOW)
            raise AssertionError("expected OutboxAttemptNotFoundError")
        except OutboxAttemptNotFoundError:
            pass


async def test_list_attempts_returns_them_in_order(
    maker: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    job_id, _, _ = await _approved_job(maker)
    async with maker() as session:
        store = PostgresOutboxStore(session)
        first = await store.start_attempt(
            job_id=job_id,
            worker_id="w1",
            previous_status=OutboxStatus.PENDING,
            lease_expires_at=None,
            now=NOW,
        )
        await store.finish_attempt(first.id, result_status="retry_scheduled", now=NOW)
        second = await store.start_attempt(
            job_id=job_id,
            worker_id="w1",
            previous_status=OutboxStatus.RETRY_SCHEDULED,
            lease_expires_at=None,
            now=NOW,
        )
        await session.commit()

    async with maker() as session:
        attempts = await PostgresOutboxStore(session).list_attempts(job_id)
    assert [a.attempt_number for a in attempts] == [1, 2]
    assert attempts[1].id == second.id


async def test_create_is_not_implemented(
    maker: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    async with maker() as session:
        store = PostgresOutboxStore(session)
        try:
            await store.create(
                proposal_id=uuid.uuid4(),
                action_type="retry_charge",
                payload_json={},
                idempotency_key="act-test",
                next_attempt_at=NOW,
            )
            raise AssertionError("expected NotImplementedError")
        except NotImplementedError as exc:
            assert "NOT NULL foreign keys" in str(exc)
