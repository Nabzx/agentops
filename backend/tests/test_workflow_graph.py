"""Parity tests for the LangGraph pipeline (backend/app/workflows/graph/).

Runs the same seeded demo tickets test_workflow_integration.py uses through the
LangGraph StateGraph instead of WorkflowRunner/SupportWorkflowService, and asserts it
reaches the same terminal/paused state. Three paths are covered: a plain auto-resolve,
an early block (no approval reached), and the approval path — interrupt, resume, and
confirmation that the real ApprovalService created exactly one OutboxJob, proving the
exactly-once outbox guarantee is genuinely inherited rather than reimplemented.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from app.llm.service import ModelService
from app.models.outbox import OutboxJob
from app.models.ticket import Ticket
from app.rules.clock import seed_reference_clock
from app.workflows.enums import TriggerType, WorkflowState
from app.workflows.graph.build import get_compiled_graph
from app.workflows.graph.state import GraphContext
from app.workflows.registry import WORKFLOW_V2_VERSION
from app.workflows.repository import WorkflowRepository
from app.workflows.state import SupportWorkflowState
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tests.conftest import TEST_DATABASE_URL

pytestmark = pytest.mark.usefixtures("_prepare_test_database")

# Distinct from the production workflow_name so a graph-demo run never collides with
# a real support-ticket-v2 run on uq_workflow_runs_active_ticket.
GRAPH_WORKFLOW_NAME = "support-ticket-v2-langgraph-demo"


@pytest.fixture
async def maker() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    from app.seeds.runner import seed

    engine = create_async_engine(TEST_DATABASE_URL)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with session_maker() as session:
        await session.execute(
            text("DELETE FROM workflow_runs WHERE workflow_name = :name"),
            {"name": GRAPH_WORKFLOW_NAME},
        )
        demo = await session.scalar(
            select(Ticket).where(Ticket.seed_tag == "DEMO-TRACKING-001")
        )
        if demo is None:
            await seed(session)
        await session.commit()
    try:
        yield session_maker
    finally:
        async with session_maker() as session:
            await session.execute(
                text("DELETE FROM workflow_runs WHERE workflow_name = :name"),
                {"name": GRAPH_WORKFLOW_NAME},
            )
            await session.commit()
        await engine.dispose()


async def _submit(
    session_maker: async_sessionmaker[AsyncSession], seed_tag: str
) -> tuple[uuid.UUID, dict[str, Any]]:
    """Create a run for the seeded ticket and drive the graph to its first pause."""
    clock = seed_reference_clock()
    async with session_maker() as session:
        ticket = await session.scalar(select(Ticket).where(Ticket.seed_tag == seed_tag))
        assert ticket is not None
        repo = WorkflowRepository(session)
        correlation_id = f"graph-test-{uuid.uuid4().hex[:12]}"
        run = await repo.create_run(
            workflow_name=GRAPH_WORKFLOW_NAME,
            workflow_version=WORKFLOW_V2_VERSION,
            state_schema_version="workflow-state-v1",
            ticket_id=ticket.id,
            correlation_id=correlation_id,
            trigger_type=TriggerType.TICKET_RECEIVED,
            initial_state=WorkflowState.RECEIVED,
            initial_step="receive",
            now=clock.now(),
        )
        await session.commit()

        initial = SupportWorkflowState(
            workflow_run_id=run.id,
            workflow_name=GRAPH_WORKFLOW_NAME,
            workflow_version=WORKFLOW_V2_VERSION,
            ticket_id=ticket.id,
            ticket_reference=ticket.ticket_reference,
            correlation_id=correlation_id,
        )
        graph = get_compiled_graph()
        context = GraphContext(
            session=session, model_service=ModelService(), clock=clock
        )
        config: RunnableConfig = {"configurable": {"thread_id": str(run.id)}}
        result = await graph.ainvoke(initial, config, context=context)
        return run.id, result


async def _resume(
    session_maker: async_sessionmaker[AsyncSession], run_id: uuid.UUID, *, approve: bool
) -> dict[str, Any]:
    async with session_maker() as session:
        graph = get_compiled_graph()
        context = GraphContext(
            session=session, model_service=ModelService(), clock=seed_reference_clock()
        )
        config: RunnableConfig = {"configurable": {"thread_id": str(run_id)}}
        decision = {"approve": approve, "reason": "decided in a parity test"}
        return await graph.ainvoke(Command(resume=decision), config, context=context)


async def test_tracking_ticket_auto_resolves_without_approval(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    _run_id, result = await _submit(maker, "DEMO-TRACKING-001")
    assert result["current_state"] == WorkflowState.AWAITING_AGENT
    assert "__interrupt__" not in result


async def test_cross_customer_blocks_before_any_approval(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    _run_id, result = await _submit(maker, "DEMO-CROSS-CUSTOMER-001")
    assert result["current_state"] == WorkflowState.BLOCKED
    assert "__interrupt__" not in result
    # Never reveals or proceeds against the other customer's order.
    assert result.get("resolved_order_id") is None


async def test_refund_approval_interrupts_then_creates_exactly_one_outbox_job(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    run_id, submitted = await _submit(maker, "DEMO-REFUND-APPROVAL-001")
    assert submitted["current_state"] == WorkflowState.AWAITING_APPROVAL
    interrupts = submitted.get("__interrupt__")
    assert interrupts, "expected the graph to pause at await_approval"
    payload = interrupts[0].value
    assert payload["action_type"] == "request_supervisor_refund_approval"
    assert payload["proposed_action_id"]

    resumed = await _resume(maker, run_id, approve=True)
    assert resumed["current_state"] == WorkflowState.APPROVED_PENDING_EXECUTION

    async with maker() as session:
        jobs = (
            await session.scalars(
                select(OutboxJob).where(OutboxJob.workflow_run_id == run_id)
            )
        ).all()
        assert len(jobs) == 1
