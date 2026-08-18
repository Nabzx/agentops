"""Builds and compiles the LangGraph StateGraph mirroring support-ticket-v1's pipeline.

Every node delegates to app.workflows.handlers; edges are decided purely from
app.workflows.definition.STATE_HANDLERS via the WorkflowState already present on the
graph state — no second router is hand-rolled.
"""

from __future__ import annotations

import functools

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.workflows.definition import STATE_HANDLERS
from app.workflows.enums import WorkflowState
from app.workflows.graph.approval import await_approval
from app.workflows.graph.nodes import make_step_node
from app.workflows.graph.state import GraphContext, GraphState

AWAIT_APPROVAL_NODE = "await_approval"


def _route_after_step(state: GraphState) -> str:
    """Where the graph goes after any of the 13 step nodes.

    Mirrors runner.py's is_active/is_paused/is_terminal dispatch: another active state
    keeps advancing, awaiting_approval enters the interrupt node, and every other
    paused/terminal state ends this graph invocation — the graph demonstrates the
    pipeline through the approval decision; execution stays with the production outbox
    worker, unmodified.
    """
    current = WorkflowState(state.current_state)
    handler = STATE_HANDLERS.get(current)
    if handler is not None:
        return handler
    if current == WorkflowState.AWAITING_APPROVAL:
        return AWAIT_APPROVAL_NODE
    return END


def build_graph() -> StateGraph[GraphState, GraphContext, GraphState, GraphState]:
    graph = StateGraph(GraphState, context_schema=GraphContext)
    for handler_name in STATE_HANDLERS.values():
        graph.add_node(handler_name, make_step_node(handler_name))
    graph.add_node(AWAIT_APPROVAL_NODE, await_approval)

    graph.add_edge(START, STATE_HANDLERS[WorkflowState.RECEIVED])
    for handler_name in STATE_HANDLERS.values():
        graph.add_conditional_edges(handler_name, _route_after_step)
    graph.add_edge(AWAIT_APPROVAL_NODE, END)
    return graph


@functools.lru_cache(maxsize=1)
def get_compiled_graph() -> (
    CompiledStateGraph[GraphState, GraphContext, GraphState, GraphState]
):
    """The process-wide compiled graph + its MemorySaver.

    Must be a singleton: MemorySaver's checkpoint data lives inside this specific
    instance, so a resume (Command(resume=...)) against a freshly-compiled graph would
    find no interrupted thread to resume. Callers (the demo CLI, tests) always fetch
    this, never call build_graph().compile(...) directly.
    """
    return build_graph().compile(checkpointer=MemorySaver())
