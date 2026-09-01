# Ephor

A safe-action core for AI agents: an agent **proposes** a consequential action, a human
**approves** a frozen snapshot of exactly what will happen, and the action then **executes
exactly once** onto a tamper-evident record.

Named after the Spartan magistrates whose office existed to check and approve the king's
actions before they happened - see [ADR-0004](../docs/adr/0004-name-the-core-ephor.md).

This package is currently a skeleton (see issue #9). The module layout below mirrors the
vocabulary in [CONTEXT.md](../CONTEXT.md); each module fills in once its design is locked:

| Module | Fills in once | Vocabulary |
| --- | --- | --- |
| `actions.py` | now | `Action`, `Proposal` |
| `approvals.py` | now | `Approval request`, `Snapshot`, `Decision` |
| `effects.py` | #2 (adapter interface) locked | `Effect`, `Adapter` |
| `outbox.py` | #3 (exactly-once boundary) locked | `Outbox job`, `Worker`, `Idempotency key`, `Exactly-once` |
| `audit.py` | now | `Audit entry`, `Audit chain`, `Correlation id` |
| `permissions.py` | now | `Permission`, `Requester`, `Approver` |

## Developing

```bash
cd ephor
uv sync
uv run pytest
uv run ruff check .
uv run mypy .
```
