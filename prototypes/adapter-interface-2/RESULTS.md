# Results

**One interface covers both adapters cleanly.** `MockAdapter` and `StripeStubAdapter` implement
identical method signatures (`is_idempotent`, `revalidate`, `execute`); `run_through_core` - the
stand-in for the real Outbox worker - never branches on which adapter it's holding, and never
imports or references anything Stripe-specific. Stripe's own shape (a charge id, an amount, a
status string) stays entirely inside `StripeStubAdapter.execute`'s `raw` payload.

**Four things this spike specifically checked:**

1. **The `Effect` return shape is genuinely generic.** `effect_id` / `occurred_at` / `raw` held
   both a trivial mock result and a Stripe-charge-shaped one without any change to the type.
2. **`revalidate` catches a stale action before `execute` runs.** A charge action, its
   `charge_status` no longer `"failed"`, gets rejected before any (simulated) call to Stripe -
   proving the interface has the right seam for the "did anything change since approval" check
   from Q2.
3. **The idempotency key actually dedups**, simulating what a real Stripe `Idempotency-Key`
   header does: calling `execute` twice with the same key against `StripeStubAdapter` returns the
   identical `Effect` the second time, not a second charge attempt.
4. **The exception taxonomy is enough.** A single `PermanentEffectError` cleanly covered both "the
   action itself is invalid" (negative amount) and "revalidate says stop" - no need for the
   `RetryableEffectError` path in this spike since nothing here simulates a transient failure, but
   the type exists and nothing forced a third category to be invented.

**Nothing here contradicts ADR-0005.** The spike doesn't touch job states or crash recovery
(that's the core's job, not the adapter's) - it only exercises the boundary ADR-0005 drew.

**Recommendation:** lock this interface as-is (see ADR-0006). No changes needed from the grilled
design.
