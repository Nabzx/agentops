# 0019. A named, scored security benchmark - not more tests in disguise

- **Status:** Accepted
- **Date:** 2026-09-03
- **Driven by:** maintainer decision, no Wayfinder ticket (a rigor addition, same
  shape as ADR-0015 - not a new architectural question)

## Context

ADR-0015 chaos-tests one guarantee (exactly-once) at scale. What's still missing is
a single, nameable answer to "what have you actually checked this holds against" -
self-approval, tampering, replay, a component lying about its own guarantees. Those
properties were each proven somewhere in the test suite already, but scattered, and
with no honest accounting of what *isn't* defended.

## Decision

**`ephor/tests/security_benchmark.py`: a named suite of adversarial cases, each
either "defended" (the core structurally blocks or detects the attack) or an honest
"known limitation" (a real, demonstrated gap - not hidden). `test_security_benchmark.py`
asserts every case still matches its written kind on every CI run; a known limitation
unexpectedly starting to pass is treated as a regression in the write-up, exactly like
a defended case failing.**

1. **Seven cases, six defended, one genuine limitation:** self-approval blocked;
   tampered audit entry detected; tampered snapshot detected; an executed approval
   can never be re-approved; a non-idempotent Adapter is never auto-retried past the
   dangerous crash window (ADR-0005, condensed to one scored line here); a duplicate
   idempotency key across two unrelated jobs is rejected. The one real limitation: an
   Adapter that lies about `is_idempotent = True` while not actually deduplicating
   defeats exactly-once, and nothing in the core can detect a lie about an Adapter's
   own declared capability - a trust boundary, not a bug, demonstrated with a
   `_LyingAdapter` rather than asserted in prose.
2. **Building this found a real, fixable gap - fixed on the spot, not just written
   up.** `InMemoryOutboxStore.create()` let two unrelated jobs share one
   `idempotency_key` with no error, unlike production Postgres's own
   `uq_outbox_idempotency_key` constraint. Closing it needed no design decision, just
   parity with a guarantee already made elsewhere - `DuplicateIdempotencyKeyError` is
   now raised, and that case moved from "known limitation" to "defended" as a result.
   Confirmed nothing in `ephor`, `stripe-recovery`, or `wallet-guard` relied on the
   old, permissive behaviour before shipping the fix.
3. **A generated, not hand-written, report** - `docs/security-benchmark.md`, via
   `generate_security_benchmark_report.py`, same pattern as `docs/chaos-report.md`.

## Alternatives considered

- **Leave these as ordinary, scattered unit tests** - rejected: the point is a single,
  nameable artifact that answers "what has this actually been checked against," not
  one more test file indistinguishable from the others.
- **Quietly fix the idempotency-key gap without a benchmark case for it** - rejected:
  the value of naming it as a benchmark case is that a future regression (someone
  removing the check) fails loudly and specifically, not just as one assertion among
  many in a large test file.
- **Hide or omit the lying-adapter limitation** - rejected outright: an honest
  limitation, clearly demonstrated, is worth more than a benchmark that only ever
  reports green.

## Consequences

- `docs/security-benchmark.md` is generated - regenerate with
  `uv run python -m tests.generate_security_benchmark_report` from `ephor/`, never
  hand-edited.
- `ephor.outbox` gains `DuplicateIdempotencyKeyError`, and `OutboxStore.create()`'s
  Protocol docstring documents it - a real, if small, behavioural change to the
  in-memory reference store, additive only (nothing previously relied on the gap).
- The lying-adapter limitation stands as the honest boundary of what this core
  claims: Adapter honesty about its own idempotency is trusted, not verified, and
  cannot be, without a mechanism this project hasn't built and isn't proposing here.
