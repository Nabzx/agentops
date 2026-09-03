# 0017. `revalidate()` can't tell "stale" from "already succeeded" - found by chaos-testing the real adapter

- **Status:** Accepted (the finding). The fix direction is a recommendation, not a
  locked decision - see Consequences.
- **Date:** 2026-09-03
- **Driven by:** `wallet-guard/tests/test_chaos.py` - an integration-level chaos test
  built to check the real `WalletGuardAdapter` + `FakeChainClient` against
  `ephor.outbox.InMemoryOutboxStore`'s real claim/attempt lifecycle, not just the
  abstract contract ADR-0015's harness already proves against a synthetic mock.

## Context

ADR-0015's chaos harness proves the outbox's own state machine holds exactly-once
against a synthetic `ChaosAdapter` that only tracks "did I get called." Testing the
*real* `WalletGuardAdapter` under the same randomised crash injection found something
that synthetic mock couldn't: a worker built the way both flagships' `demo.py` scripts
suggest - `revalidate()` then `execute()`, on every attempt, per ADR-0006's own stated
contract ("runs on every attempt, not just the first") - misreports a job as failed in
exactly the crash window ADR-0005 already named as dangerous.

**The sequence:** a worker claims a job, calls `execute()`, which really revokes the
approval (or retries the charge) - then crashes before the outbox records
`SUCCEEDED`. Another worker later reclaims the same job and calls `revalidate()`
again, as instructed. `revalidate()` checks real-world state ("is this approval still
active" / "is this charge still failed") - and since the action already succeeded,
the real-world state now says no. Per ADR-0006, a `False` from `revalidate()` is
treated as `PermanentEffectError`: the job gets marked **FAILED**, even though the
effect it wanted to happen already did.

**Checked against production, not assumed:** `backend/app/outbox/processor.py`'s
real `_execute()` already has the fix, with an explicit comment: *"Idempotent success
first: a prior committed effect for this business action wins, before any
revalidation."* It checks a durable `ExecutedActionRepository`, keyed by idempotency
key, **before** ever calling revalidate. `ephor`'s extracted core has no equivalent -
`ephor.outbox`/`ephor.effects` can't answer "did this idempotency key already
succeed" independent of the job's own status, and the job's own status is exactly
what's ambiguous in this window (still `claimed`, not yet `succeeded` - the crash cost
the *commit*, not the *effect*).

## What this doesn't mean

This is **not** a violation of the exactly-once guarantee ADR-0005/0015 already
proved. The adapter's own dedup (a header or, for `wallet-guard`, nonce discipline)
still means the real world is never acted on twice. This is a **different**
correctness concern: a job that actually succeeded can be *misclassified* as failed -
wrong bookkeeping and a wrong audit trail entry, not a double effect. It's also
currently **latent, not shipped**: neither `stripe-recovery/demo.py` nor
`wallet-guard/demo.py` has a retry loop at all - both are one-shot happy-path
scripts. Nobody has hit this in running code. It would bite the first real,
crash-safe worker built for either flagship the way the demo's shape naively
suggests.

## The fix, modelled but not yet built into ephor

`wallet-guard/tests/test_chaos.py` proves the shape of a correct fix: a worker keeps
its own record of which idempotency keys already produced a real effect
(`succeeded_effects` in the test), checked **before** calling `revalidate()` on every
attempt - not just the first. If the key's already there, finish the outbox
bookkeeping directly; skip revalidate entirely. This mirrors
`ExecutedActionRepository` exactly, just modelled in-memory for the test.

This is not yet proposed as a change to `ephor.effects.Adapter` or `ephor.outbox`
themselves. Two real directions exist and neither is chosen here:

1. **Leave it to each worker implementation** - document the pattern (this ADR, plus
   a note in both flagships' READMEs when either grows a real worker), the way
   AgentOps' own backend already independently arrived at it.
2. **Give `ephor` a shared primitive for it** - e.g. an `OutboxStore` method to record
   and check a completed effect by idempotency key, or a small
   `ExecutedEffectsStore` alongside `AuditStore`/`ApprovalStore`/`OutboxStore`. This
   would remove a footgun every future Adapter author would otherwise have to
   rediscover, at the cost of extending an already-locked interface (ADR-0006) -
   a real decision, not a quick patch.

## Consequences

- `wallet-guard/tests/test_chaos.py` now models and proves the correct pattern (200
  trials in CI, checked at 5,000 locally) - the finding is real and the test
  demonstrates the fix works, without changing any locked ephor interface.
- Whether `ephor` should provide this generically (direction 2 above) is open,
  flagged here for a real decision rather than resolved unilaterally - a natural
  candidate for the next Wayfinder-style research or grilling ticket.
- `stripe-recovery`'s own future worker (if and when one is built beyond its current
  one-shot demo) needs the same pattern - this finding isn't wallet-guard-specific,
  it's a property of the Adapter contract itself once retries are real.
