# 0005. Exactly-once contract: what the core guarantees vs. what an Adapter must provide

- **Status:** Accepted
- **Date:** 2026-09-01
- **Driven by:** #3 (`wayfinder:grilling`)

## Context

CONTEXT.md already fixes the philosophy: *"the guarantee that one approved Action yields exactly
one Effect, proven by a gate, not asserted. It is exactly-once effect, not exactly-once
delivery."* What was still open is the actual line between the core (which owns the Outbox job,
Idempotency key and attempt history) and the Adapter (which performs the Effect): what must an
Adapter provide for that guarantee to hold, and what happens when it structurally can't?

Grilled with the maintainer across two rounds.

## Decision

**Layered enforcement, not a single mechanism.**

1. **The core always generates a stable Idempotency key** per Action (derived from the Approval
   Decision, per CONTEXT.md) and maintains a **transactional attempt ledger** - every attempt is
   recorded as in-flight / succeeded / failed-retryable / failed-permanent /
   needs-manual-reconciliation, written in the same transaction as the state change it records.
   This alone recovers correctly from a crash *before* the external call, or *after* the local
   commit - the ledger tells the worker exactly what to do on restart.
2. **The ledger cannot close the gap where the external call succeeds but the process dies before
   the local commit.** Only the target system, treating the Idempotency key as its own dedup
   token, can close that gap (the model case: Stripe's `Idempotency-Key` header). So every Adapter
   must declare a capability flag, **`is_idempotent: bool`**:
   - `is_idempotent=True` - the Adapter passes the core's key through to a target that natively
     deduplicates on it (or implements equivalent dedup itself). The core may safely retry through
     this crash window; the target guarantees the second call is a no-op.
   - `is_idempotent=False` - the target has no dedup capability at all. The core **never**
     auto-retries across the succeeded-externally-but-not-yet-committed crash window for these
     Adapters. On worker restart, an attempt found in-flight with no confirmed outcome routes to
     **`needs-manual-reconciliation`** instead - a job state, not a retry, and not a failure.
     Designing how a human resolves that state is explicitly **out of scope** for this ADR (see
     Consequences).
3. **Two separate axes, not one.** Adapters speak only the retry-classification axis: they raise
   one of two exception types, a transient-error type (core will retry, honouring the loop below)
   or a permanent-error type (core marks failed-permanent, no further retries). Adapters never see
   or decide the job-state axis (in-flight / succeeded / failed-* / needs-manual-reconciliation) -
   that is the core's alone, decided from its own crash-recovery logic plus the `is_idempotent`
   flag, never from anything an Adapter reports.
4. **The core owns the retry loop entirely** - attempt count, backoff, claiming via
   `FOR UPDATE SKIP LOCKED` (per CONTEXT.md's `Worker` definition). Identical logic for every
   Adapter; Adapters only classify *whether retrying could help*, never *whether* to retry.

**Acceptance test (required before #12 - outbox extraction - is considered done):** a mock Adapter
configurable to crash the worker process at one of three points - before the external call, after
the call but before the local commit, after the commit - asserting:

- an `is_idempotent=True` Adapter never produces a second real Effect, from any crash point, once
  retried to completion;
- an `is_idempotent=False` Adapter lands in `needs-manual-reconciliation` when crashed in the
  succeeded-but-uncommitted window, rather than being retried.

This is what makes exactly-once *proven*, per AGENTS.md's own language, not merely claimed.

## Alternatives considered

- **Adapter-only responsibility** (no core-side ledger) - rejected: the core needs the ledger
  regardless, to know what to retry after any crash; making Adapters redo that bookkeeping
  duplicates work and invites per-Adapter bugs.
- **Core-only responsibility** (no Adapter idempotency requirement) - rejected: cannot close the
  succeeded-but-uncommitted gap; a Adapter-side dedup token is unavoidable for any system without
  it.
- **Forbid non-idempotent Adapters entirely** - rejected: would rule out real, useful integrations
  with no native dedup capability (plenty of APIs and most legacy webhooks). The
  `needs-manual-reconciliation` state preserves the exactly-once *guarantee* (never silently
  double-fire) while still allowing such Adapters to exist.
- **Allow non-idempotent Adapters with silent at-least-once retry** - rejected: breaks the
  exactly-once effect guarantee CONTEXT.md already promises; a documented "may occasionally
  double-fire" caveat is not the bar this project set for itself.

## Consequences

- Unblocks #12 (extract the durable outbox and worker into the core) and informs #2 (the Adapter
  interface must expose `is_idempotent`, accept the core's Idempotency key, and raise one of the
  two classified exception types).
- The core's job-state machine gains a fifth state, `needs-manual-reconciliation`, alongside
  in-flight / succeeded / failed-retryable / failed-permanent.
- **Explicitly deferred, needs its own ticket later:** the actual resolution workflow for
  `needs-manual-reconciliation` (how a human confirms whether the real-world Effect happened, and
  what they can do about it). Track A extraction (#9-#12) only needs the state to exist and to
  correctly halt automatic retries - not a resolution UI.
- The mock Adapter shipped with the core (per ROADMAP's Phase 1) should default `is_idempotent`
  to a settable flag in tests, so the acceptance test above can exercise both paths.
