# 0018. Close the gap: `Adapter.check_completed()`, asked before `revalidate()` on every attempt

- **Status:** Accepted
- **Date:** 2026-09-03
- **Driven by:** ADR-0017's open question, grilled with the maintainer in two rounds

## Context

ADR-0017 found that `revalidate()` cannot tell "the world moved on, this is stale"
apart from "this already succeeded, a crash just cost us recording it" - both look
identical from a real-world state check. It left the fix direction open rather than
patch it unilaterally, since closing it means changing `ephor.effects.Adapter` -
already locked by ADR-0006.

Grilled in two rounds:

**Round 1 - where does "did this already happen?" get answered?** Two real
candidates: ephor keeps its own record (extend `OutboxJob`/`OutboxStore` with an
"effect landed" marker separate from "job succeeded"), or ephor asks the Adapter,
since an adapter that declares `is_idempotent = True` is - by definition - already
tracking "have I seen this idempotency key" as the mechanism that makes it idempotent
in the first place. **Decided: ask the Adapter.** A second, ephor-owned copy of "did
this happen" can only ever be a guess at what the Adapter's target system actually
did; the Adapter (or its client) is the only honest source of truth. This also
naturally and correctly excludes non-idempotent Adapters, which structurally cannot
answer this question - exactly why ADR-0005 already routes them to
`NEEDS_MANUAL_RECONCILIATION` instead of guessing.

**Round 2 - required or optional; new method or extend `revalidate()`?** Every
Adapter already declares `is_idempotent: bool` unconditionally, including `False` -
**decided: `check_completed` is required on every Adapter too**, uniform, no
`isinstance`/`hasattr` checks anywhere a caller uses one. And **decided: a new,
separate method**, not a richer `revalidate()` - `revalidate()`'s current contract
(a plain `bool`, no idempotency key) stays exactly as every existing caller already
uses it; nothing about today's `revalidate()` call sites changes.

## Decision

**Add `check_completed(action, idempotency_key) -> Effect | None` to the `Adapter`
Protocol, required on every implementation. A worker calls it before `revalidate()`
only when a prior attempt for this job already exists - never on the genuine first
attempt.**

1. **Signature matches `execute()`'s**, not just the idempotency key alone: some
   Adapters (Stripe, honestly) have no separate lookup-by-idempotency-key endpoint at
   all - the only way to learn the deduped outcome is to safely re-issue the same
   mutating call, which needs the same `action` fields `execute()` needs (the charge
   id). Giving `check_completed` only the idempotency key would make that
   implementation impossible for exactly the Adapter this project ships for real.
2. **Only called on a retry, found while implementing this, not while grilling it -
   worth stating plainly.** The original plan was "call it unconditionally, every
   attempt, no bookkeeping." Building `StripeAdapter.check_completed` surfaced why
   that's unsafe specifically for Stripe: since its only honest implementation is to
   safely re-issue the same `confirm` call, calling it on a *genuinely first* attempt
   would perform the real action **before `revalidate()` ever ran** - silently
   bypassing the one safety check that exists precisely to stop a stale or invalid
   proposal from executing. Fixed by gating on an already-free signal: the worker
   checks `await store.list_attempts(job_id)` (every `OutboxStore` already provides
   this) - if any prior attempt exists, ask `check_completed` first; on a genuine
   first attempt (no prior attempts, regardless of `attempt_count`, which doesn't
   reliably increment on a lease-expiry reclaim), skip straight to `revalidate()`
   then `execute()`, exactly as before ADR-0017. No new state, no new store method -
   just the right existing signal.
3. **The worker-loop contract, documented here and modelled in
   `wallet-guard/tests/test_chaos.py`:** on a retry (prior attempts exist), call
   `check_completed` first. If it returns an `Effect`, skip `revalidate()`/`execute()`
   entirely and commit success with that `Effect`. If it returns `None` - or this is
   the first attempt - proceed exactly as today: `revalidate()` then, if still valid,
   `execute()`.
4. **Each Adapter answers as cheaply as it honestly can** - this isn't uniform across
   Adapters, and that's fine:
   - `MockAdapter`: always `None`. Its `execute()` is trivially safe to call
     repeatedly regardless; there's nothing to save by tracking prior calls.
   - `WalletGuardAdapter`: a genuinely cheap, separate check - `FakeChainClient`
     already keeps a `idempotency_key -> TokenApproval` record for its own dedup;
     exposing it costs nothing extra. A real EVM client would have an even cheaper
     real equivalent (query the transaction by account+nonce - far cheaper than
     resubmitting).
   - `StripeAdapter`: honestly, **not** cheaper than `execute()` - Stripe has no
     separate "look up by idempotency key" endpoint. `check_completed` re-issues the
     same `confirm` call Stripe's own dedup already makes safe, and reports success
     only if the result says so. Documented plainly as such, not oversold as a free
     lookup it isn't.

## Alternatives considered

- **Ephor tracks "effect landed" itself** (extend `OutboxJob`/`OutboxStore`) -
  rejected in round 1: a second, ephor-owned record of what the real world did can
  only mirror the Adapter's own knowledge, imperfectly, and could drift from it. The
  Adapter (or its client) is the actual source of truth.
- **Skip `revalidate()` on retries for an idempotent Adapter and just call
  `execute()` again, trusting its own dedup - no new method at all** - considered
  while researching this ADR, genuinely simpler for adapters like Stripe where
  `check_completed` ends up equivalent to `execute()` anyway. Rejected because it
  forecloses the case an Adapter *can* answer more cheaply (wallet-guard's fake, and
  any real chain client) from ever doing so, and because it would need "is this a
  retry" bookkeeping a worker doesn't otherwise need - `check_completed`, called
  unconditionally on every attempt, needs none.
- **Extend `revalidate()` with the idempotency key and a three-way result** -
  rejected in round 2: breaks its current simple contract at every existing call
  site, for a question `revalidate()` was never meant to answer.

## Consequences

- `ephor.effects.Adapter` gains a required method - a real, if narrow, breaking
  change to a locked interface (ADR-0006). `MockAdapter`, `StripeAdapter` and
  `WalletGuardAdapter` all need it implemented before this ships; none of the
  existing three are optional here.
- `stripe_recovery.client.StripeClient` and `wallet_guard.client.ChainClient` each
  need one new client-level method for their Adapter to call: a way to look up a
  prior result by idempotency key (cheap for `FakeChainClient`/a real chain client;
  effectively a re-confirm for Stripe).
- `wallet-guard/tests/test_chaos.py`'s local `succeeded_effects` workaround (modelling
  the fix by hand, per ADR-0017) is replaced by a real call to
  `WalletGuardAdapter.check_completed` - the chaos test now proves the actual shipped
  fix, not a stand-in for it.
- `stripe-recovery` gets the same fix even though nothing surfaced it there yet -
  the gap ADR-0017 found is a property of the Adapter contract itself, not specific
  to wallet-guard's domain.
