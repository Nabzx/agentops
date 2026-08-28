# 0003. Adapter-scoped, sandbox-first credentials

- **Status:** Proposed
- **Date:** 2026-08-27
- **Driven by:** #5 (`wayfinder:research`) — see [research](../research/adapter-credentials.md)

## Context

Every Adapter needs credentials for its external system (Stripe test mode first). We need one
credential model: sandbox by default, scoped, never committed, dead-simple for a self-hosted
user, and clean as Adapters multiply. Comparable tools were checked against primary sources
(Stripe SDK/keys, Airbyte, n8n, Dagster `EnvVar`/`ConfigurableResource`, LangChain, 12-factor,
`pydantic-settings`, `python-dotenv`). The consistent pattern: env vars are the substrate, a
typed per-component config object is the ergonomic layer, an external secret store is an
optional seam — not the default.

## Decision

Each Adapter holds its credentials in a **typed `pydantic-settings` config object**, one
subclass per Adapter, namespaced by `env_prefix` (e.g. `AGENTOPS_STRIPE_`), with secrets typed
as `SecretStr`.

- **Env vars are the source of truth**; a git-ignored `.env` (shipped as a committed
  `.env.example` with `sk_test_…` / `rk_test_…` placeholders) makes local dev one file.
- **Sandbox is the default and enforced.** Mode is read from the Stripe key prefix
  (`_test_` vs `_live_`), not a separate flag; a live key is refused unless the Adapter is built
  with an explicit `allow_live=True`. Live is never reachable by omission.
- **The core's Idempotency key is passed through** to the provider call, not the SDK's
  per-process one, so exactly-once survives worker restarts.
- **No secret store in v0.1–v0.3, but resolution goes through one seam**, so Vault / a cloud
  manager / encrypted-at-rest can slot in later without touching Adapters.

## Alternatives considered

- **Raw env vars only** — no typing, validation, per-Adapter namespace, or test/live guard.
- **Pluggable secret provider now** — a seam before a second implementation exists to justify it.
- **OS keychain (keyring)** — desktop-shaped; awkward in the Docker/CI/headless OSS target.

## Consequences

- **Unblocks #2:** the Adapter interface can require a `Settings` type and a
  `build(*, allow_live=False)` factory; the core depends on that contract, never on Stripe.
- **Unblocks #9:** the scaffold ships `pydantic-settings` + `python-dotenv`, a committed
  `.env.example`, `.env` in `.gitignore`, and an `AdapterSettings` base + `resolve_mode`.
- Operationalises the roadmap's "Stripe test mode only" promise; least-privilege restricted keys
  (`rk_…`) cost nothing extra. Residual risk: a `.env` committed by accident — mitigated by
  shipping only `.env.example` and git-ignoring `.env` from the first commit.
