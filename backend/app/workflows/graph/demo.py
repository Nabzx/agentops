"""Runnable demo: submit a ticket through the LangGraph pipeline, print the interrupt
payload when it reaches awaiting_approval, take an approve/reject decision, resume, and
(if approved) confirm the outbox job the real outbox worker will later pick up.

Usage (inside the backend environment, against the dev database — run seeds first)::

    python -m app.workflows.graph.demo DEMO-REFUND-APPROVAL-001
    python -m app.workflows.graph.demo DEMO-REFUND-APPROVAL-001 --approve
    python -m app.workflows.graph.demo DEMO-TRACKING-001

A ticket that never reaches awaiting_approval (most demo tickets) just prints its
final state — there is nothing to decide.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command
from sqlalchemy import select

from app.db.session import dispose_engine, get_sessionmaker
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

# Distinct from the production workflow_name so a graph-demo run never collides with a
# real support-ticket-v2 run on uq_workflow_runs_active_ticket.
GRAPH_WORKFLOW_NAME = "support-ticket-v2-langgraph-demo"


async def _submit(seed_tag: str) -> tuple[uuid.UUID, dict[str, Any]]:
    async with get_sessionmaker()() as session:
        ticket = await session.scalar(select(Ticket).where(Ticket.seed_tag == seed_tag))
        if ticket is None:
            print(
                f"no seeded ticket tagged {seed_tag!r} (run seeds first)",
                file=sys.stderr,
            )
            raise SystemExit(1)

        repo = WorkflowRepository(session)
        clock = seed_reference_clock()
        correlation_id = f"lg-demo-{uuid.uuid4().hex[:12]}"
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


async def _resume(run_id: uuid.UUID, *, approve: bool, reason: str) -> dict[str, Any]:
    async with get_sessionmaker()() as session:
        graph = get_compiled_graph()
        context = GraphContext(
            session=session, model_service=ModelService(), clock=seed_reference_clock()
        )
        config: RunnableConfig = {"configurable": {"thread_id": str(run_id)}}
        decision = {"approve": approve, "reason": reason}
        return await graph.ainvoke(Command(resume=decision), config, context=context)


async def _confirm_outbox_job(run_id: uuid.UUID) -> None:
    async with get_sessionmaker()() as session:
        job = await session.scalar(
            select(OutboxJob).where(OutboxJob.workflow_run_id == run_id)
        )
        print(
            f"outbox job created: {job.id} (status={job.status.value})"
            if job
            else "no outbox job"
        )


async def _main(seed_tag: str, decision: str | None) -> None:
    run_id, result = await _submit(seed_tag)
    print(f"run {run_id}: reached {result['current_state']}")

    interrupts = result.get("__interrupt__")
    if not interrupts:
        return

    payload = interrupts[0].value
    print("\nawaiting_approval — proposed action:")
    for key, value in payload.items():
        print(f"  {key}: {value}")

    if decision is None:
        answer = input("\napprove? [y/N] ").strip().lower()
        decision = "approve" if answer == "y" else "reject"

    reason = f"decided via langgraph demo cli ({decision})"
    final = await _resume(run_id, approve=(decision == "approve"), reason=reason)
    print(f"\nrun {run_id}: final state {final['current_state']}")

    if decision == "approve":
        await _confirm_outbox_job(run_id)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="workflow-graph-demo", description="LangGraph support-ticket pipeline demo"
    )
    parser.add_argument("seed_tag", help="e.g. DEMO-REFUND-APPROVAL-001")
    parser.add_argument(
        "--approve", action="store_const", dest="decision", const="approve"
    )
    parser.add_argument(
        "--reject", action="store_const", dest="decision", const="reject"
    )
    args = parser.parse_args(argv)

    async def _run() -> None:
        try:
            await _main(args.seed_tag, args.decision)
        finally:
            await dispose_engine()

    asyncio.run(_run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
