"""LangGraph StateGraph implementation of the support-ticket pipeline (portfolio demo).

Reuses the exact handlers, transition table and approval/outbox subsystems from
app.workflows.* and app.approvals.* — this package only adds orchestration wiring.
Parallel to WorkflowRunner; does not replace it. See docs/workflow-graph-demo.md.
"""
