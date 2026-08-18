"""The interrupt() node: pause for a human decision, then apply it via the real
ApprovalService. Approval creation, snapshot hashing, idempotency and the exactly-once
outbox job are 100% reused here — nothing in this file reimplements that logic.
"""

from __future__ import annotations

from langgraph.runtime import Runtime
from langgraph.types import interrupt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.approvals.service import (
    ApprovalService,
    ApproveRequest,
    CreateApprovalRequest,
    RejectRequest,
)
from app.auth.models import AuthenticatedUser
from app.models.user import User
from app.workflows.graph.state import GraphContext, GraphState
from app.workflows.repository import WorkflowRepository

# Seeded demo identities (app/seeds/generator.py::_build_users) — this graph-demo
# package is the only caller that hardcodes them; production code never does. approve()
# forbids a requester approving their own request, so these must be two different users.
REQUESTER_EMAIL = "agent.amara@meridian.example"
SUPERVISOR_EMAIL = "super.priya@meridian.example"


async def _actor(session: AsyncSession, email: str) -> AuthenticatedUser:
    user = await session.scalar(select(User).where(User.email == email))
    if user is None:
        raise LookupError(f"seeded demo user not found: {email!r} (run seeds first)")
    return AuthenticatedUser.build(
        user_id=user.id, role=user.role, email=user.email, is_active=user.is_active
    )


async def await_approval(
    state: GraphState, *, runtime: Runtime[GraphContext]
) -> dict[str, object]:
    gctx = runtime.context
    assert gctx is not None  # noqa: S101 - always supplied via ainvoke(context=...)
    repo = WorkflowRepository(gctx.session)
    proposal = await repo.get_current_proposal(state.workflow_run_id)
    if proposal is None:
        raise RuntimeError("reached awaiting_approval with no proposed action")

    # Read-only above this line only: LangGraph re-runs this node from the top on
    # resume, so every side effect must happen strictly after interrupt() returns.
    decision = interrupt(
        {
            "workflow_run_id": str(state.workflow_run_id),
            "ticket_reference": state.ticket_reference,
            "proposed_action_id": str(proposal.id),
            "action_type": proposal.action_type,
            "risk_level": proposal.risk_level,
            "required_role": proposal.required_role,
            "draft_subject": proposal.draft_response_subject,
            "draft_body": proposal.draft_response_body,
        }
    )

    service = ApprovalService(gctx.session, clock=gctx.clock)
    requester = await _actor(gctx.session, REQUESTER_EMAIL)
    supervisor = await _actor(gctx.session, SUPERVISOR_EMAIL)

    created = await service.create_request(
        CreateApprovalRequest(proposed_action_id=proposal.id), actor=requester
    )

    if decision.get("approve"):
        result = await service.approve(
            created.approval_id,
            ApproveRequest(reason=decision.get("reason")),
            actor=supervisor,
        )
    else:
        result = await service.reject(
            created.approval_id,
            RejectRequest(reason=decision.get("reason") or "rejected via graph demo"),
            actor=supervisor,
        )
    await gctx.session.commit()
    return {"current_state": result.workflow_state}
