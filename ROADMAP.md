# Roadmap

AgentOps the platform is built (S0–S10 — see the [README](README.md)). This roadmap covers
the **next chapter**: extracting the reusable **safe-action core** and shipping a **narrow
flagship detector** on top of it, as an open-source project.

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

- [ ] Carve the safe-action layer into its own package (within this repo) with a public API
- [ ] Define the `Action`/`Effect` adapter interface (see the adapter-API decision)
- [ ] Ship an in-memory mock adapter + a 20-line propose→approve→execute→audit example
- [ ] Port the existing test suite; keep exactly-once and audit gates green

**Done when:** a stranger clones the repo, runs one command, and a short script proves the
propose→approve→execute→audit loop with the mock adapter — no external service, no signup.
Tag `v0.1`.

## Phase 2 — v0.2: Runnable in 2 minutes (Track A)

- [ ] One-command quickstart (`docker compose up` / equivalent) on a sample dataset
- [ ] One **real** integration adapter on sandbox credentials (Stripe test mode)
- [ ] README first screen: logo, one-liner, a **GIF of the loop**, 3-line quickstart

**Done when:** a stranger clones it and sees a real approved action execute in under 2 minutes,
straight from the README, with nothing to install first. Tag `v0.2`.

## Phase 3 — v0.3: Stripe flagship (Track B)

- [ ] Detector scans failed charges / churned subscriptions for recoverable revenue
- [ ] Emits concrete proposals (retry charge, send dunning, fix subscription state)
- [ ] Executes approved proposals through the core against Stripe test mode, fully audited
- [ ] Headline demo: "found $X/mo → you approved $Y → here's the audit trail"

**Done when:** the flagship demo runs end to end on test data. Tag `v0.3`.

## Phase 4 — v1.0: Launch

- [ ] Docs site, demo video, CONTRIBUTING + issue templates
- [ ] Show HN + relevant subreddits + a thread; update the CV bullet with traction

**Done when:** it's live and posted. Tag `v1.0`.

## Phase 5 — Beyond: the broad vision

The "automated FDE" is a **roadmap of detectors** on one safe-action core: cloud-cost waste,
unused seats, refund leakage, support-ops. Each new detector is a plugin/PR — this is where
"audit your whole business" ships, one trustworthy detector at a time.

---

## Open decisions (Wayfinder map)

Locked before the phases that depend on them:

- **Framework name** — not yet locked; lives in this repo as a package, not a separate one.
  See issue #1. `wayfinder:grilling`
- **`Action`/`Effect` adapter API** — the interface every integration implements. `wayfinder:prototype`
- **Exactly-once contract boundary** — what the core guarantees vs. what an adapter must. `wayfinder:grilling`
- **v1 Stripe action set** — which recovery actions ship first. `wayfinder:grilling`

Settled: **adapter credential model** ([ADR-0003](docs/adr/0003-adapter-scoped-sandbox-first-credentials.md))
and **monetisation seam / core licence** ([ADR-0002](docs/adr/0002-keep-monetisation-seams-open.md),
core is Apache-2.0).
