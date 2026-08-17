"""Graph state schema and the run-scoped dependency-injection context.

SupportWorkflowState already holds everything the LangGraph state needs — every field
a handler reads or writes — and LangGraph's Pydantic-state support handles it directly.
No subclassing needed; reused as-is rather than duplicated.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.service import ModelService
from app.rules.clock import Clock, SystemClock
from app.workflows.state import SupportWorkflowState

# The LangGraph state schema is the same Pydantic model the production runner
# checkpoints.
GraphState = SupportWorkflowState


@dataclass
class GraphContext:
    """Run-scoped dependencies, injected via LangGraph's context_schema/Runtime.

    Mirrors WorkflowExecutionContext's non-step-specific fields; each graph node
    builds a real WorkflowExecutionContext from this plus its own step details.
    """

    session: AsyncSession
    model_service: ModelService
    clock: Clock = field(default_factory=SystemClock)
    worker_id: str = "langgraph-demo"
