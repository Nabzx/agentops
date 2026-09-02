# Ephor

A safe-action core for AI agents: an agent **proposes** a consequential action, a human
**approves** a frozen snapshot of exactly what will happen, and the action then **executes
exactly once** onto a tamper-evident record.

Named after the Spartan magistrates whose office existed to check and approve the king's
actions before they happened - see [ADR-0004](../docs/adr/0004-name-the-core-ephor.md).

The module layout below mirrors the vocabulary in [CONTEXT.md](../CONTEXT.md); each fills in as
its design locks (see [ROADMAP.md](../ROADMAP.md) Phase 1):

| Module | Status | Vocabulary |
| --- | --- | --- |
| `actions.py` | skeleton | `Action`, `Proposal` |
| `approvals.py` | **implemented** ([ADR-0009](../docs/adr/0009-approval-gate-extraction.md)) | `Approval request`, `Snapshot`, `Decision` |
| `effects.py` | interface locked ([ADR-0006](../docs/adr/0006-adapter-interface.md)), not yet implemented | `Effect`, `Adapter` |
| `outbox.py` | **implemented** ([ADR-0010](../docs/adr/0010-outbox-worker-extraction.md)) | `Outbox job`, `Worker`, `Idempotency key`, `Exactly-once` |
| `audit.py` | **implemented** ([ADR-0007](../docs/adr/0007-audit-store-interface.md)) | `Audit entry`, `Audit chain`, `Correlation id` |
| `permissions.py` | skeleton | `Permission`, `Requester`, `Approver` |

## Developing

```bash
cd ephor
uv sync
uv run pytest
uv run ruff check .
uv run mypy .
```
