# 0010. Extract the outbox/worker: claim/lease mechanics, retry, the exactly-once proof

- **Status:** Accepted
- **Date:** 2026-09-02
- **Driven by:** #12

## Context

Same investigation as #10/#11: read the real code before assuming the shape. `backend/app/outbox/`
splits more cleanly than approvals did:

- **`OutboxRepository`/`OutboxAttemptRepository`** (`app/outbox/repository.py`) - claiming
  (`FOR UPDATE SKIP LOCKED`, lease-based reclamation), status transitions, and the attempt ledger.
  This is **already almost entirely generic** - no ticket/order/workflow coupling at this layer.
  Only `OutboxJob`'s own model fields (`workflow_run_id`/`proposed_action_id`, per ADR-0008) and
  one list-filter parameter carry AgentOps coupling.
- **`OutboxProcessor`** (`app/outbox/processor.py`) - `_apply_success`/`_handle_failure` are
  deeply AgentOps-specific (ticket resolution, order locking, refund-ledger entries, workflow-state
  transitions). Same shape as `ApprovalService` in #11 - stays in the app layer.
- **`compute_backoff_seconds`** (`app/outbox/retry.py`) - already 100% generic.
- **`OutboxStatus`** - generic values, but missing the `needs_manual_reconciliation` state
  ADR-0005 requires for a non-idempotent Adapter. AgentOps never reaches it today (every handler
  is fully in-process/simulated, so the "external call succeeded but we lost track" gap literally
  can't occur yet) - but the generic core has to be able to represent it for a real Adapter
  (Stripe) later.

ADR-0005 also required an acceptance test that nothing had built yet: a mock Adapter, crashable at
a chosen point, proving an idempotent Adapter never double-fires and a non-idempotent one halts
into `needs_manual_reconciliation` instead of blind-retrying. That test is the actual proof
exactly-once holds - #12 is where it gets built.

## Decision

**Extract the generic claim/retry/attempt mechanics and the exactly-once proof. Leave
`OutboxProcessor`'s AgentOps-specific effect application untouched.**

1. `ephor/src/ephor/outbox.py` now has real content: `OutboxStatus` (ported verbatim, plus
   `needs_manual_reconciliation`), `CLAIMABLE_STATUSES`/`UNCLAIMABLE_STATUSES` (extended - the new
   status is unclaimable), `compute_backoff_seconds`/`next_attempt_at` (ported verbatim from
   `app/outbox/retry.py`), `RetryableEffectError`/`PermanentEffectError` (named in ADR-0005/0006
   but never given a real home outside the #2 prototype spike until now), structural
   `OutboxJob`/`OutboxAttempt` Protocols per ADR-0008's generic shape, an `OutboxStore` Protocol
   mirroring the real repository's method set, and a real, tested `InMemoryOutboxStore` with
   lease-based `claim_batch` (competing-claim behaviour is actually testable without Postgres).
2. **The ADR-0005 acceptance test is built**, in `ephor/tests/test_outbox.py`: a mock Adapter with
   an injectable crash point (before the call / after the call but before commit / after commit)
   against `InMemoryOutboxStore`, proving an idempotent Adapter never produces a second real effect
   from any crash point once retried to completion, and a non-idempotent one lands in
   `needs_manual_reconciliation` - never auto-retried - when crashed in the
   succeeded-but-uncommitted window, while a crash *before* the call is safely retryable even for a
   non-idempotent Adapter (there's nothing to reconcile if the call never happened).
3. **AgentOps re-exports instead of duplicating** - `app/outbox/enums.py` and `app/outbox/retry.py`
   are now thin re-exports of `ephor.outbox`, same pattern as #11's `app/approvals/enums.py`.
   `needs_manual_reconciliation` joins the shared enum's value set even though no AgentOps code
   path produces it today - confirmed safe by running `alembic upgrade head` against the live
   Postgres and the full 423-test suite: nothing writes that value, and Alembic only applies
   existing migrations, it doesn't diff against live model state.
4. **`OutboxProcessor`, the Postgres-backed repositories, and the production
   `outbox_jobs`/`outbox_attempts` tables are not touched otherwise.** Wiring `OutboxRepository` to
   actually implement `ephor.outbox.OutboxStore` is real follow-up work (#38), same shape as #32
   and #36.

## Alternatives considered

- **Move `OutboxProcessor`'s effect-application logic into the core** - rejected: ticket/order/
  workflow concepts have no place in a generic core, and it would be a large, risky change to
  production execution logic for no benefit the core actually needs.
- **Skip the `needs_manual_reconciliation` status until a real Adapter needs it** - rejected: the
  whole point of building the acceptance test now is proving the *contract* holds before anything
  depends on it; adding the state after a real Adapter exists would mean redesigning the job-state
  machine under production pressure instead of in the safety of a spike.
- **Build the acceptance test against the real Postgres-backed repository instead of an in-memory
  store** - rejected: `InMemoryOutboxStore` is what Phase 1 explicitly asks for ("ship an in-memory
  mock adapter") and is what a project cloning this repo actually runs, with zero setup.

## Consequences

- `ephor/tests/test_outbox.py` covers claim/lease behaviour (including competing-claim and
  expired-lease reclamation), retry backoff determinism, status transitions, and the full
  ADR-0005 acceptance test - 16 new tests, all passing.
- `backend`'s behaviour is unchanged: all 423 backend tests pass, `ruff`/`mypy` clean, the Alembic
  migration still applies cleanly, `make verify-all` passes end to end.
- **Follow-up (#38, not part of this PR):** wire `OutboxRepository` to actually implement
  `ephor.outbox.OutboxStore` - same shape as #32 and #36.
- Track A's three extraction issues (#10, #11, #12) are now all done. The next fork is #4 (v1
  Stripe action set, Track B) - a grilling conversation, not an extraction.
