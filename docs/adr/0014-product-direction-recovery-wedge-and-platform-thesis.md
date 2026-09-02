# 0014. Product direction: a commission-based recovery wedge, with the safety core as the platform thesis

- **Status:** Accepted
- **Date:** 2026-09-02
- **Driven by:** maintainer decision, no Wayfinder ticket (a business-direction call, not an
  architecture question - see ADR-0002 for why an ADR still records it)

## Context

Phase 4 of ROADMAP.md ("Launch") was written before any business direction was chosen - it just
said "post it." ADR-0002 already anticipated this moment: it kept three seams open specifically
so a paid edge could attach later without a fork, and named "**Recoverable value** stays a
discrete, identified, queryable event" as one of them. That seam has sat unused since - nothing
in `stripe-recovery/` currently tracks recovered value as a first-class, billable thing.

Four real directions were considered, each genuinely fundable in its own right:

1. **Commission-based failed-payment recovery** - the flagship as-is, sold on a cut of what it
   recovers.
2. **The safety/trust layer sold as infrastructure to other agent builders** - `ephor` itself as
   the product, usage-priced.
3. **Crypto/DeFi treasury operations** - the same shape, applied to on-chain actions, where
   irreversibility makes the safety story land harder.
4. **AI governance/compliance tooling** - the audit chain and approval gate sold to a
   compliance/risk buyer at regulated enterprises.

## Decision

**Pursue #1 as the wedge, #2 as the platform thesis it's building toward. #3 and #4 are documented
and deliberately not pursued now.**

1. **The wedge is revenue-shaped, not launch-shaped.** Phase 4 stops meaning "post to Show HN" and
   starts meaning "get the recovery loop generating real, provable commission for one design
   partner." Traction on a real account is the actual goal, not GitHub stars - stars are a
   consequence of a real product being real, not the target.
2. **The platform thesis is the story wrapped around the wedge, not the near-term GTM.** `ephor`
   staying genuinely reusable is what makes "we're starting in recovery, but the engine is the
   product" true rather than aspirational - which is exactly why Track A was built as a real
   extraction (#10-#12) rather than left as one Stripe-shaped codebase with the word "core" in a
   folder name. Selling `ephor` itself to other agent builders is the direction to grow into once
   the wedge proves the engine holds up on real money, not a parallel effort to start now.
3. **#3 (crypto) and #4 (governance) are shelved, not rejected.** Crypto needs a wallet Adapter
   built from nothing (no existing SDK the way Stripe's is), a bigger compliance surface, and a
   smaller near-term market than SaaS failed-payment recovery. Governance/compliance sells to a
   risk buyer at a slow enterprise cycle that doesn't suit a solo, pre-revenue build. Both stay
   real options once #1 has proven the underlying engine on real money - #3 in particular reuses
   almost everything (the approval gate, the exactly-once outbox) behind a new Adapter, the same
   pattern `stripe-recovery` already validated once.

## What the wedge actually requires that doesn't exist yet

Charging commission on recovered revenue - not just running a deterministic demo - needs real
product work Track B never had to build:

- **A recovered-value ledger.** ADR-0002 named this seam; nothing implements it. Every executed
  retry needs to produce a discrete, queryable "recovered £X" record the commission is computed
  from - not just an audit-log entry meant for a human to read.
- **Multi-tenant accounts.** `stripe-recovery` today assumes one Stripe account and one secret
  key. A real customer needs their own isolated credentials, proposals, and audit trail.
- **Stripe Connect, not a single secret key.** Acting on a customer's Stripe account means
  building on Connect (or an equivalent), not `StripeRecoverySettings`'s one-key model - a real
  change to the credential story ADR-0003 locked, not just a config tweak.
- **Billing the commission itself.** Ironically the same propose-approve-execute-audit shape this
  whole project is built around - which is either a nice validation of the core, or scope
  creep, depending on sequencing.

None of this is built yet, and none of it should be built speculatively before a real design
partner exists to build it for.

## Alternatives considered

- **Open-source launch first, business model later (the original Phase 4)** - rejected as the
  *only* plan: a GitHub launch with no revenue thesis behind it risks becoming activity instead
  of progress. Kept as a real, parallel outcome of the wedge working, not the goal itself.
- **Build the platform (#2) before proving the wedge (#1)** - rejected: selling infrastructure to
  other agent builders needs a credible story that it survived contact with real money and a real
  customer first. Building the platform pitch before that proof exists is building the thing
  people are supposed to trust before it's actually been tested.
- **Start on #3 or #4 immediately, as the more "impressive" story** - rejected for now: both are
  real, but neither has a faster or clearer path to a first paying relationship than #1, and this
  is a solo, pre-revenue build where sequencing matters more than ambition.

## Consequences

- ROADMAP.md's Phase 4 is rewritten around this wedge, with the missing product work (recovered-
  value ledger, multi-tenancy, Stripe Connect, commission billing) named as real, unbuilt
  milestones - not yet scoped as Wayfinder tickets, since no design partner exists yet to build
  them for.
- #2, #3, #4 are recorded here so the reasoning survives, exactly as ADR-0002 intended when it
  kept their seams open - nothing about pursuing #1 first forecloses any of them.
- The next real decision point is finding a design partner - a company with real failed-payment
  recovery to do - not more engineering on the demo shape that already works.
