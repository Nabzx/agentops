# 0015. Chaos-test the exactly-once guarantee, don't just assert it at three points

- **Status:** Accepted
- **Date:** 2026-09-03
- **Driven by:** maintainer decision, no Wayfinder ticket (a rigor improvement on an
  existing, already-locked guarantee - ADR-0005 - not a new architectural question)

## Context

ADR-0005's acceptance test (`ephor/tests/test_outbox.py`) proves exactly-once holds at
three hand-picked crash points, once each: before the Adapter's call, after the call but
before the local commit, and after the commit. That's a real, valuable test - it's the
whole reason the guarantee is provable rather than asserted. But it only visits three
points in a much larger space: a job can be crashed and retried more than once, crashed
at a different point each time, share a store with other jobs, and land in
`NEEDS_MANUAL_RECONCILIATION` by an unluckier route than the one test picked by hand. A
hand-picked test proves the three cases someone thought to write down; it doesn't prove
there's no fourth case nobody thought of.

## Decision

**Add a randomised chaos harness (`ephor/tests/chaos_harness.py`) that drives many jobs
through the real worker loop - `claim_batch` -> `start_attempt` -> the Adapter's call ->
the local commit -> `finish_attempt` - injecting a randomly chosen crash point on every
cycle, across many independently-seeded trials. Run a few hundred trials as a normal
test on every push; publish a much larger sweep's numbers in `docs/chaos-report.md`.**

1. **Five crash points, not three** - the original three, split slightly finer against
   the real worker loop (crashed before claiming at all; claimed but crashed before
   calling out; the dangerous post-call-pre-commit window; committed but the attempt
   ledger left open) - plus a genuine no-crash completion.
2. **A job can be crashed more than once before it terminates.** Each trial drives a job
   through repeated cycles, re-picking a random crash point every time, up to a capped
   number of cycles with the last one forced to complete cleanly - so a trial can't spin
   forever on unlucky sampling, but the crash *sequence* leading up to success is still
   randomised, not fixed.
3. **Several jobs share one store per trial**, so cross-job interference has a chance to
   surface, not just single-job crash timing.
4. **Terminal jobs are checked against the real store, not just the status enum** - after
   a job reaches a terminal state, the harness calls `claim_batch` again a year later in
   simulated time and asserts the job is never returned.
5. **Deterministic and reproducible.** Each trial is seeded from its own index
   (`random.Random(seed)`), so "trial 4231 failed" always reproduces by re-running that
   one seed alone - a chaos test that can't be reproduced is barely better than a flaky
   one.
6. **Sanity-checked against a real failure**, not just written and trusted: disabling the
   `ChaosAdapter`'s own idempotent dedup by hand made the harness fail on the very first
   seed, every time, both at the CI-sized 300-trial run and a 20,000-trial sweep -
   confirming the harness actually detects the violation it claims to detect, not just
   that it passes when nothing's wrong.
7. **CI runs 300 trials on every push** (`test_outbox_chaos.py`, `EPHOR_CHAOS_TRIALS`
   overridable) - a few hundred milliseconds, and already a far larger sample than the
   three-point test. `generate_chaos_report.py` runs a much bigger sweep (50,000 trials
   by default) and writes `docs/chaos-report.md` - not run in CI, since it isn't needed
   there to catch a regression, only to state a bigger number honestly.

## Alternatives considered

- **A formal spec (TLA+/Alloy) of the outbox state machine** - rejected for now: real
  value, but a much larger investment than this project's stage justifies, and a chaos
  harness catches the same class of "sequence nobody thought to write down" bug with a
  fraction of the effort. Worth reconsidering if the state machine grows more complex.
- **Replace the three-point acceptance test with the chaos harness** - rejected: the
  hand-picked test is easier to read as a specification of exactly what ADR-0005
  requires; the chaos harness is a complementary, much larger sample, not a replacement
  for a readable, minimal example.
- **Run the full 50,000-trial sweep in CI** - rejected: ~9 seconds for no regression-
  catching benefit over 300 trials at a few hundred milliseconds; the big sweep's value
  is a bigger, published number, not a stronger CI gate.

## Consequences

- `docs/chaos-report.md` is generated, not hand-written - regenerate it by re-running
  `uv run python -m tests.generate_chaos_report` from `ephor/`, never edit it directly.
- Nothing outside `ephor/tests/` changed - `backend/` and `stripe-recovery/` are
  untouched, and the existing ADR-0005 acceptance test is unmodified.
- The published proof for the exactly-once claim is now: one readable, three-point
  acceptance test, plus a 50,000-trial, zero-violation chaos sweep across five crash
  points and randomised multi-crash sequences - not just the former on its own.
