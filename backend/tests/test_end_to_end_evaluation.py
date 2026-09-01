"""Smoke test for the S8 end-to-end evaluation (all hard gates zero)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from app.evaluation.end_to_end import HARD_GATES, run_evaluation
from app.models.ticket import Ticket
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tests.conftest import TEST_DATABASE_URL

pytestmark = pytest.mark.usefixtures("_prepare_test_database")


@pytest.fixture
async def factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    from app.seeds.runner import seed

    from tests.test_approval_service import _truncate_all

    engine = create_async_engine(TEST_DATABASE_URL)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    seeded_here = False
    async with maker() as session:
        if (
            await session.scalar(
                select(Ticket).where(Ticket.seed_tag == "DEMO-REFUND-APPROVAL-001")
            )
            is None
        ):
            await seed(session)
            await session.commit()
            seeded_here = True
    try:
        yield maker
    finally:
        if seeded_here:
            async with maker() as session:
                await _truncate_all(session)
                await session.commit()
        await engine.dispose()


async def test_end_to_end_all_hard_gates_pass(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    evaluation = await run_evaluation(write_report=False, session_factory=factory)
    assert evaluation.case_count >= 40
    assert evaluation.checks_run == evaluation.checks_passed, evaluation.failures
    for gate in HARD_GATES:
        assert evaluation.gates[gate] == 0, (gate, evaluation.failures)
    assert evaluation.all_gates_pass
