"""Seed one *pending* refund approval so the dashboard decision flow is demonstrable.

The end-to-end demo (``make demo`` / ``make approval-demo``) drives an approval all the way
to a simulated refund, which leaves the queue empty. Run this to put a fresh pending approval
back on the board for the ``DEMO-REFUND-APPROVAL-001`` ticket:

    make demo-seed-approval

It resets the workflow/approval/outbox/execution tables, starts the demo refund workflow,
and raises the approval as a Support Agent — stopping short of any decision. Every effect is
simulated and offline. Development/demo use only.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select, text

from app.approvals.service import ApprovalService, CreateApprovalRequest
from app.auth.models import AuthenticatedUser
from app.db.session import get_sessionmaker
from app.models.enums import UserRole
from app.models.ticket import Ticket
from app.models.user import User
from app.rules.clock import seed_reference_clock
from app.workflows.repository import WorkflowRepository
from app.workflows.service import StartWorkflowRequest, SupportWorkflowService


async def main() -> None:
    factory = get_sessionmaker()
    clock = seed_reference_clock()

    async with factory() as session:
        await session.execute(
            text(
                "TRUNCATE TABLE refund_ledger_entries, executed_actions, "
                "outbox_attempts, outbox_jobs, approval_requests, workflow_runs "
                "RESTART IDENTITY CASCADE"
            )
        )
        await session.commit()

    async with factory() as session:
        ticket = await session.scalar(
            select(Ticket).where(Ticket.seed_tag == "DEMO-REFUND-APPROVAL-001")
        )
        if ticket is None:
            raise SystemExit("seed the database first: make seed")
        ticket_id = ticket.id

    run = await SupportWorkflowService(session_factory=factory).start(
        StartWorkflowRequest(ticket_id=ticket_id)
    )

    async with factory() as session:
        agent_row = (
            await session.scalars(
                select(User)
                .where(User.role == UserRole.support_agent)
                .order_by(User.email)
            )
        ).first()
        if agent_row is None:
            raise SystemExit("no support agent found: make seed")
        agent = AuthenticatedUser.build(
            user_id=agent_row.id,
            role=UserRole.support_agent,
            email=agent_row.email,
            is_active=True,
        )
        proposal = await WorkflowRepository(session).get_current_proposal(run.run_id)
        if proposal is None:
            raise SystemExit("workflow produced no proposed action")
        created = await ApprovalService(session, clock=clock).create_request(
            CreateApprovalRequest(proposed_action_id=proposal.id), agent
        )
        await session.commit()

    print(
        f"pending approval seeded: {created.approval_id} "
        f"status={created.status.value} (sign in as a Supervisor to decide it)"
    )


if __name__ == "__main__":
    asyncio.run(main())
