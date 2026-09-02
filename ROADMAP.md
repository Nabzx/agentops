# Roadmap

AgentOps the platform is built (S0–S10 — see the [README](README.md)). This roadmap covered
extracting the reusable **safe-action core** and shipping a **narrow flagship detector** on top
of it as an open-source project (Phases 0–3, all done) - and now covers proving that flagship is
worth real money to a real customer, per [ADR-0014](docs/adr/0014-product-direction-recovery-wedge-and-platform-thesis.md).

Work runs agent-driven on **two parallel tracks** that rarely touch the same files. Wayfinder
decides *what and how*; implementation agents build only locked specs; a human reviews and
merges every PR; every phase ends in a **tagged, runnable build**.

## Ground rules

- **Wayfinder decides, agents build.** Open questions live as `wayfinder:*` issues (map →
  research/grilling/prototype). Nothing gets built until its spec is `ready-for-agent`.
- **No self-merges.** Every PR is reviewed by a human before merge. This is what
  "agents held accountable" means in practice.
- **Every phase ends in a tag** (`v0.1`, `v0.2`, …) that actually runs, even if narrow.
  Don't let a phase balloon past its goal.
- **Swap when blocked.** If a track stalls, move to the other — don't wait.
- **Determinism holds.** The core is deterministic and offline-testable; the flagship talks
  to **Stripe test mode only**. Nothing touches real money.

## Tracks

- **Track A — Core framework.** Extract the approval gate, durable transactional outbox,
  exactly-once executor, hash-chained audit and RBAC out of the AgentOps app into a
  standalone, documented package — living in this same repo, not a separate one — behind an
  `Action`/`Effect` **adapter interface**, shipping with an in-memory mock adapter so it runs
  with zero setup. Optimised first for **clone it, run one command, watch it work**; a
  published `pip install` package is a later nice-to-have once someone actually wants to
  depend on it, not the launch bar.
- **Track B — Flagship detector.** The **Stripe revenue-recovery** detector: scan charges and
  subscriptions → propose recovery actions → (Track A approval gate) → execute against Stripe
  test mode → audit. The *first of many* detectors.

The support-ops app that AgentOps is today becomes the second example on the core.

---

## Phase 0 — Bootstrap & position (scaffold)

- [x] Lock positioning: name shortlist, one-liner, narrow-flagship decision (see `wayfinder:map`)
- [x] Push S0–S10 to the remote; CI on every PR (branch protection skipped — solo repo, see #7)
- [x] Operating docs in place: this roadmap, [CONTEXT.md](CONTEXT.md), [AGENTS.md](AGENTS.md), `docs/adr/`
- [x] Label taxonomy created; open decisions seeded as Wayfinder issues

**Done when:** the repo runs the loop — Wayfinder issues open, `ready-for-agent` specs queued, CI green on PRs.

## Phase 1 — v0.1: Extract the core (Track A)

- [x] Carve the safe-action layer into its own package (within this repo) with a public API -
      audit ([ADR-0007](docs/adr/0007-audit-store-interface.md)), the approval gate
      ([ADR-0009](docs/adr/0009-approval-gate-extraction.md)) and the outbox/worker
      ([ADR-0010](docs/adr/0010-outbox-worker-extraction.md)) are all extracted and tested -
      Track A's three extraction issues (#10, #11, #12) are done
- [x] Define the `Action`/`Effect` adapter interface (see the adapter-API decision) - locked
      ([ADR-0006](docs/adr/0006-adapter-interface.md)) and implemented
      ([ADR-0012](docs/adr/0012-actions-and-effects.md))
- [x] Ship an in-memory mock adapter + a 20-line propose→approve→execute→audit example -
      `stripe-recovery/src/stripe_recovery/demo.py` (#14) wires audit/approvals/outbox/effects/
      actions together end to end, against a fake Stripe client, zero setup
- [x] Port the existing test suite; keep exactly-once and audit gates green - audit's, approvals'
      and outbox's suites are ported (`ephor/tests/`, including the ADR-0005 acceptance test);
      backend's 423 tests confirmed still green throughout

**Done when:** a stranger clones the repo, runs one command, and a short script proves the
propose→approve→execute→audit loop with the mock adapter — no external service, no signup.
Tag `v0.1`. **Met** - `cd stripe-recovery && uv run python -m stripe_recovery.demo`.

## Phase 2 — v0.2: Runnable in 2 minutes (Track A)

- [x] One-command quickstart on a sample dataset - `cd stripe-recovery && uv sync && uv run
      python -m stripe_recovery.demo` (#13); the Docker-based `make up && make demo` full-dashboard
      path stays as a secondary option
- [x] One **real** integration adapter on sandbox credentials (Stripe test mode) -
      `StripeTestModeClient` (#51, [ADR-0013](docs/adr/0013-real-stripe-test-mode-client.md)),
      an opt-in behind one env var; `FakeStripeClient` stays the zero-setup default
- [x] README first screen: one-liner, a **GIF of the loop**, 3-line quickstart (#13)

**Done when:** a stranger clones it and sees a real approved action execute in under 2 minutes,
straight from the README, with nothing to install first. Tag `v0.2`. **Met.**

## Phase 3 — v0.3: Stripe flagship (Track B)

- [x] Detector scans failed charges for recoverable revenue - `stripe-recovery/` (#14), against a
      fake in-memory Stripe client (`FakeStripeClient`); churned subscriptions are out of v1's
      scope ([ADR-0011](docs/adr/0011-v1-stripe-action-set.md))
- [x] Emits concrete proposals - retry charge only, per ADR-0011 (dunning and subscription-state
      fixes are deferred to v1.1/v1.2, not built)
- [x] Executes approved proposals through the core, fully audited - against the fake client by
      default; against a real Stripe test-mode account too, one env var away (#51)
- [x] Headline demo: "found $X/mo → you approved $Y → here's the audit trail" -
      `stripe_recovery.demo` prints exactly this shape, on fake data or real test-mode data

**Done when:** the flagship demo runs end to end on test data. Tag `v0.3`. **Met.**

## Phase 4 — v1.0: Prove the wedge on real money

Reframed by [ADR-0014](docs/adr/0014-product-direction-recovery-wedge-and-platform-thesis.md):
the goal is a real design partner recovering real revenue on commission, not a launch post. None
of the below is built yet, and none of it should be until a design partner exists to build it for.

- [ ] A recovered-value ledger - every executed retry produces a discrete, queryable "recovered
      £X" record (the seam ADR-0002 named and left unbuilt), not just an audit-log entry
- [ ] Multi-tenant accounts - isolated credentials, proposals and audit trail per customer,
      instead of `stripe-recovery`'s current one-account assumption
- [ ] Stripe Connect - acting on a customer's own Stripe account, replacing
      `StripeRecoverySettings`'s single-key model (a real change to ADR-0003's credential story)
- [ ] Commission billing on recovered value - the same propose-approve-execute-audit shape,
      turned on itself
- [ ] Docs site, demo video, CONTRIBUTING + issue templates, Show HN - still worth doing, but as
      a consequence of the wedge working, not the goal itself

**Done when:** one real account has had real revenue recovered and commission genuinely billed on
it. Tag `v1.0`.

## Phase 5 — Beyond: the platform thesis, and what's shelved

**The platform thesis** ([ADR-0014](docs/adr/0014-product-direction-recovery-wedge-and-platform-thesis.md)):
once the wedge holds up on real money, `ephor` itself - the safety/trust layer, not the Stripe
detector - is the thing other agent builders would want, sold as infrastructure they embed
(usage-priced: per action executed, per audited event). This is the direction Track A's real
extraction was always aimed at proving out; it's a "grow into," not a parallel effort to start
alongside Phase 4.

**Shelved as a *business* direction, not rejected** (ADR-0014): pursuing crypto/DeFi treasury
operations as the near-term commercial bet, and AI-governance/compliance tooling sold to a risk
buyer at regulated enterprises (a real fit for the audit chain and approval gate, but too slow a
sales cycle for a solo, pre-revenue build). Both stay real options once the wedge has proven the
engine on real money.

**A second detector is built, as engineering proof rather than a business bet**
([ADR-0016](docs/adr/0016-wallet-guard-approval-revocation.md)): `wallet-guard/` scans a wallet
for unlimited token approvals and proposes revoking them - the same propose-approve-execute-audit
shape as `stripe-recovery`, but with exactly-once earned through nonce discipline instead of a
payments-provider header, proving the core generalises past one Adapter shape. Cloud-cost waste,
unused seats and support-ops remain the natural long-tail once the platform thesis is being
pursued for real - each one a plugin/PR, the same shape now validated twice.

---

## Open decisions (Wayfinder map)

None left blocking either track.

Settled: **framework name** — **Ephor** ([ADR-0004](docs/adr/0004-name-the-core-ephor.md)),
**exactly-once boundary** ([ADR-0005](docs/adr/0005-exactly-once-boundary.md)),
**adapter interface** ([ADR-0006](docs/adr/0006-adapter-interface.md)),
**adapter credential model** ([ADR-0003](docs/adr/0003-adapter-scoped-sandbox-first-credentials.md)),
**monetisation seam / core licence** ([ADR-0002](docs/adr/0002-keep-monetisation-seams-open.md),
core is Apache-2.0), **v1 Stripe action set** — retry a soft-declined charge, and only that
([ADR-0011](docs/adr/0011-v1-stripe-action-set.md)), **the real Stripe test-mode client's shape**
([ADR-0013](docs/adr/0013-real-stripe-test-mode-client.md)), and **product direction** — commission-
based recovery as the wedge, the safety core as the platform thesis to grow into
([ADR-0014](docs/adr/0014-product-direction-recovery-wedge-and-platform-thesis.md)). **Track A
(core extraction) is done** — #10, #11, #12 are all closed and wired into AgentOps for real (#32,
#36, #38). **Track B is done too** — #14 (the flagship) and #51 (the real Stripe client) are both
closed; `FakeStripeClient` stays the default, `StripeTestModeClient` is one env var away. What's
left is Phase 4 as ADR-0014 reframed it — finding a design partner, not more engineering on a
demo shape that already works.
