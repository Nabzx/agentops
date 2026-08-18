"""Thin LangGraph node wrappers around the existing step handlers.

Each node does zero business logic: it builds a WorkflowExecutionContext, calls the
existing app.workflows.handlers function unchanged, and persists the step + checkpoint
through the same WorkflowRepository the production WorkflowRunner uses. Only the
per-step bookkeeping (start_step/complete_step/checkpoint/commit) is duplicated from
runner.py's _run_one_step — that loop can't be reused directly since LangGraph drives
one node per call rather than a while-loop, but every actual decision still comes from
handlers.py and definition.py, called unchanged. Claim/lease is skipped entirely: a
graph run is single-process by construction, so there is no competing worker to lock
out (see docs/workflow-graph-demo.md for what a multi-worker cutover would need).
"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Protocol

from langgraph.runtime import Runtime

from app.llm.redaction import redact_json
from app.workflows import handlers as step_handlers
from app.workflows.checkpointing import build_snapshot
from app.workflows.context import StepExecutionResult, WorkflowExecutionContext
from app.workflows.definition import (
    STATE_HANDLERS,
    STATE_SCHEMA_VERSION,
    TransitionSpec,
    is_valid_transition,
    next_handler,
    transition_spec,
)
from app.workflows.enums import WorkflowFailureCode, WorkflowState, is_terminal
from app.workflows.graph.state import GraphContext, GraphState
from app.workflows.repository import WorkflowRepository
from app.workflows.state import snapshot_hash

# Reverse of STATE_HANDLERS: handler name -> the source state it runs in.
_HANDLER_SOURCE_STATE: dict[str, WorkflowState] = {
    handler: state for state, handler in STATE_HANDLERS.items()
}

# Mirrors runner.py's _TERMINAL_FAILURES mapping (kept in sync by hand — runner.py
# stays untouched, and it's small enough not to warrant a shared import of a private
# module-level constant).
_TERMINAL_FAILURES: dict[str, WorkflowFailureCode] = {
    "validation_failed": WorkflowFailureCode.VALIDATION_FAILED,
    "dependency_unavailable": WorkflowFailureCode.DEPENDENCY_UNAVAILABLE,
    "model_failed": WorkflowFailureCode.MODEL_FAILED,
    "ownership_blocked": WorkflowFailureCode.OWNERSHIP_BLOCKED,
}


class NodeFn(Protocol):
    """Matches LangGraph's runtime-aware node shape: runtime is keyword-only."""

    def __call__(
        self, state: GraphState, *, runtime: Runtime[GraphContext]
    ) -> Awaitable[dict[str, object]]: ...


async def _execute_with_retry(
    spec: TransitionSpec,
    handler: step_handlers.StepHandler,
    ctx: WorkflowExecutionContext,
    state: GraphState,
) -> StepExecutionResult:
    """Mirrors WorkflowRunner._execute_with_retry exactly (same small loop)."""
    attempts = spec.retry_max_attempts + 1
    result = await handler(ctx, state)
    while result.retryable and attempts > 1 and is_terminal(result.destination_state):
        attempts -= 1
        result = await handler(ctx, state)
    return result


def make_step_node(handler_name: str) -> NodeFn:
    """Build a LangGraph node that runs one existing handler, unchanged."""
    handler = step_handlers.get_handler(handler_name)
    source_state = _HANDLER_SOURCE_STATE[handler_name]
    spec = transition_spec(source_state)
    assert spec is not None  # active states always have a spec  # noqa: S101

    async def node(
        state: GraphState, *, runtime: Runtime[GraphContext]
    ) -> dict[str, object]:
        gctx = runtime.context
        assert gctx is not None  # noqa: S101 - always supplied via ainvoke(context=...)
        repo = WorkflowRepository(gctx.session)
        index = state.step_index

        input_hash = snapshot_hash(redact_json(state.snapshot()))
        attempt = await repo.current_attempt(state.workflow_run_id, handler_name)
        step = await repo.start_step(
            run_id=state.workflow_run_id,
            step_index=index,
            step_name=handler_name,
            source_state=source_state,
            attempt=attempt,
            input_hash=input_hash,
            input_summary_json={"state": source_state.value},
            now=gctx.clock.now(),
        )
        await gctx.session.commit()  # persist "started" before external work

        ctx = WorkflowExecutionContext(
            session=gctx.session,
            correlation_id=state.correlation_id,
            worker_id=gctx.worker_id,
            clock=gctx.clock,
            model_service=gctx.model_service,
            workflow_run_id=state.workflow_run_id,
            current_step_id=step.id,
        )
        result = await _execute_with_retry(spec, handler, ctx, state)
        run = await repo.get(state.workflow_run_id)
        assert run is not None  # noqa: S101 - created before the graph is invoked

        if not is_valid_transition(source_state, result.destination_state):
            await repo.fail_step(
                step,
                destination_state=None,
                error_code="internal_error",
                error_message=(
                    f"illegal transition {source_state.value}"
                    f"->{result.destination_state.value}"
                ),
                retryable=False,
                latency_ms=0,
                now=gctx.clock.now(),
            )
            await repo.mark_terminal(
                run,
                state=WorkflowState.FAILED_DEPENDENCY,
                now=gctx.clock.now(),
                failure_code=WorkflowFailureCode.INTERNAL_ERROR,
                failure_message="illegal transition produced by handler",
            )
            await gctx.session.commit()
            return {"current_state": WorkflowState.FAILED_DEPENDENCY}

        destination = result.destination_state
        new_index = index + 1
        current_step = next_handler(destination) or destination.value
        fragment: dict[str, object] = {
            **result.state_fragment,
            "current_state": destination,
            "step_index": new_index,
            "current_step": current_step,
            "warnings": [*state.warnings, *result.warnings],
        }
        updated = state.model_copy(update=fragment)

        await repo.complete_step(
            step,
            destination_state=destination,
            output_hash=snapshot_hash(redact_json(updated.snapshot())),
            output_summary_json={"destination": destination.value},
            latency_ms=0,
            now=gctx.clock.now(),
            model_call_ids=result.model_call_ids,
            tool_call_ids=result.tool_call_ids,
            citation_ids=result.citation_ids,
        )
        snapshot, digest = build_snapshot(updated)
        checkpoint = await repo.append_checkpoint(
            run_id=state.workflow_run_id,
            step_index=new_index,
            state=destination,
            state_schema_version=STATE_SCHEMA_VERSION,
            snapshot_json=snapshot,
            snapshot_hash=digest,
            now=gctx.clock.now(),
        )
        if is_terminal(destination):
            await repo.mark_terminal(
                run,
                state=destination,
                now=gctx.clock.now(),
                failure_code=_TERMINAL_FAILURES.get(result.failure_code or ""),
                failure_message=result.error_message,
            )
        else:
            await repo.update_state(
                run, state=destination, step_index=new_index, current_step=current_step
            )
        await repo.set_last_checkpoint(run, checkpoint.id)
        await gctx.session.commit()  # completed + checkpoint + state, atomically
        return fragment

    return node
