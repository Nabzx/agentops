# 0011. v1 Stripe action set: retry a soft-declined charge, and only that

- **Status:** Accepted
- **Date:** 2026-09-02
- **Driven by:** #4 (`wayfinder:grilling`)

## Context

The flagship detector finds recoverable revenue in a Stripe account, but needs a bounded v1 action
set - judged on value, safety in test mode, and demo clarity, per issue #4. Candidates: retry a
soft-declined charge; send/trigger dunning; fix a stuck subscription state.

Grilled with the maintainer in one round.

## Decision

**v1 ships exactly one action: retry a soft-declined charge, re-confirming the same
`PaymentIntent`, restricted to an explicit allow-list of retryable decline codes.**

1. **Scope: one action, not three.** Retrying a charge is the only candidate that is a single,
   discrete, fully-automatable action with an unambiguous outcome (the charge succeeded or it
   didn't). Dunning's payoff depends on the customer acting afterwards - it isn't itself a
   recovery, it's a bet on one. "Fix a stuck subscription" is vague enough to hide several
   different possible actions behind one name. A narrow v1 matches the "found $X - you approved -
   here's the proof" headline the flagship needs to deliver on day one, and matches this project's
   established pattern of shipping the narrowest useful slice first (one detector before many, one
   repo before a split, clone-and-run before a package).
2. **Retryability is an explicit allow-list of Stripe decline codes, never a deny-list.** Soft
   declines - `insufficient_funds`, `try_again_later`, `processing_error`, and similarly transient
   codes - are retryable. Hard declines - `stolen_card`, `lost_card`, `pickup_card`, `fraudulent`,
   and similar - are never retried; retrying them risks looking like fraud to the card network, not
   just wasting a charge attempt. An allow-list fails safe: an unrecognised or future Stripe
   decline code is never proposed for retry by default, and extending the list later is a
   two-line change. A deny-list would do the opposite - silently trusting every new code Stripe
   ever introduces.
3. **Mechanically: re-confirm the same failed `PaymentIntent`, never create a new one.** A fresh
   `PaymentIntent` is a distinct object in Stripe's own system, harder to trace back to "this was a
   retry of that failed charge" in the audit trail, and re-introduces the idempotency problem
   ADR-0005 already solved for exactly this case. Re-confirming the same `PaymentIntent` means the
   core's idempotency key (ADR-0005) passes straight through as Stripe's own `Idempotency-Key`
   header on the `confirm` call - a crash-and-retry on our side is provably safe, using the exact
   contract the Adapter interface (ADR-0006) already locked.
4. **Dunning and the stuck-subscription action are deferred, not dropped.** They're the natural
   v1.1/v1.2 follow-ons, matching the "more detectors/actions later" shape already in ROADMAP's
   Phase 5 - noted here so the research behind them isn't lost, but nothing forces that scope onto
   v1.

## Alternatives considered

- **Ship all three candidate actions in v1** - rejected: three different action shapes (a
  discrete retry, an outreach nudge with a deferred payoff, and an ambiguous state-fix) is a much
  larger surface to get right before the flagship has proven itself once. Narrower is safer and
  faster to a working demo.
- **A deny-list of non-retryable decline codes** - rejected: fails open on any decline code the
  list doesn't yet know about, including ones Stripe adds after v1 ships. The allow-list is the
  fail-safe direction.
- **Create a new `PaymentIntent` per retry attempt** - rejected: loses the direct link back to the
  original failed charge in Stripe's own data model, and duplicates idempotency-key handling that
  re-confirming the existing `PaymentIntent` gets for free.

## Consequences

- Unblocks #14 (the Stripe flagship detector skeleton) - the only remaining blocker on Track B.
- The Stripe Adapter (built as part of #14) must classify a failed charge's `decline_code` against
  the allow-list before ever proposing a retry, and its `execute()` must call
  `PaymentIntent.confirm` with the core's idempotency key passed through as Stripe's
  `Idempotency-Key` header.
- The detector's Snapshot (per ADR-0008) for this action should carry at minimum: the charge
  amount, the customer/subscription reference, and the specific decline code that made this
  eligible - so an approver sees *why* the system considers this safe to retry, not just that it
  does.
- Dunning and stuck-subscription fixes are backlog items for v1.1/v1.2, not tracked as blocking
  work here.
