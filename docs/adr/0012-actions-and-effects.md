# 0012. Implement the remaining core primitives: Action/Proposal and the Adapter interface

- **Status:** Accepted
- **Date:** 2026-09-02
- **Driven by:** #14 (surfaced as a prerequisite while scoping the flagship skeleton)

## Context

Scoping #14 (the Stripe flagship skeleton) surfaced two `ephor` modules still sitting empty
(from #9): `effects.py` and `actions.py`. Both are needed before any detector can run:

- **`effects.py`** - the Adapter interface. Already fully designed and validated: ADR-0006 locked
  the shape, and `prototypes/adapter-interface-2/spike.py` proved it covers both a mock adapter and
  a Stripe-shaped stub without either leaking into the other. Nobody had copied that validated
  shape into the real package yet.
- **`actions.py`** - Action/Proposal. CONTEXT.md defines both terms, but nobody had designed the
  concrete generic shape - the same gap ADR-0008 closed for `ApprovalRequest`/`OutboxJob`.

Neither needed a fresh grilling round: `effects.py` is a direct port of an already-validated
design, and `actions.py`'s shape falls out directly from how `proposal_id` is already used
throughout `ephor.approvals` and `ephor.outbox`.

## Decision

**Implement both for real, as a matched pair, since the flagship needs both before it can run.**

1. **`ephor.effects`**: the `Adapter` Protocol (`is_idempotent: bool`, `revalidate(action) ->
   bool`, `execute(action, idempotency_key) -> Effect`) and the `Effect` dataclass (`effect_id`,
   `occurred_at`, `raw: dict` - the target's opaque payload), ported verbatim from the validated
   spike. `RetryableEffectError`/`PermanentEffectError` are **not** redefined here - they already
   live in `ephor.outbox` (added during #12, since that's where the retry loop that reacts to them
   lives, per ADR-0005) and are re-exported from `effects` so a caller only needs one import for
   the whole Adapter contract. A plain-dict `AdapterRegistry` (`register`/`get`), no plugin
   system - YAGNI until a second real Adapter exists (ADR-0006 point 4). Ships with `MockAdapter`,
   the in-memory Adapter Phase 1 asks for.
2. **`ephor.actions`**: `Proposal` as a structural Protocol (same read-only-property pattern as
   every other module this session) with `id`, `action_type`, `parameters: dict`, `risk_level`,
   `evidence: dict`, `created_at`. **Deliberately carries no status field.** Once an
   `ApprovalRequest` references a Proposal by `proposal_id` (ADR-0008), the Approval's own status
   is the single source of truth for where things stand - giving the Proposal its own status too
   would just create two places that could disagree. A `ProposalStore` Protocol +
   `InMemoryProposalStore`, same shape as every other module.

## Alternatives considered

- **Give `Proposal` its own status field** (draft/awaiting_approval/approved/...) - rejected: the
  moment an `ApprovalRequest` exists for a Proposal, its status already tracks exactly this, and
  keeping both in sync is a bug waiting to happen. One source of truth.
- **Define `RetryableEffectError`/`PermanentEffectError` again in `effects.py`** - rejected:
  they already exist in `ephor.outbox`; redefining them would create two distinct exception
  classes with the same name and meaning, and a catch on one would silently miss the other.
- **Build a real plugin/entry-point Adapter discovery mechanism now** - rejected, same reasoning
  as ADR-0006: one real Adapter (the Stripe one, about to be built) doesn't justify it.

## Consequences

- `ephor/tests/test_effects.py` and `test_actions.py` cover both modules - 10 new tests, all
  passing alongside the existing 43.
- Unblocks the actual build half of #14 - the Stripe flagship skeleton can now depend on a real
  `Adapter` interface and a real `Proposal` concept instead of empty stubs.
- `backend` is completely untouched by this ADR - neither module has anything for AgentOps to
  re-export or align with, unlike audit/approvals/outbox.
