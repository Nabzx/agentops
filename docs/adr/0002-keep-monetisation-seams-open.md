# 0002. Keep monetisation seams open; permissive core licence

- **Status:** Proposed
- **Date:** 2026-08-27
- **Driven by:** #6 (`wayfinder:research`) — see [research](../research/monetisation-seam.md)

## Context

The core is being open-sourced. Before the extraction locks the module boundaries, we need to
know where a future hosted/paid edge could attach **without forking the OSS**, so today's
architecture doesn't design it out. Seven comparable OSS-companies were surveyed against their
own licences, pricing and engineering posts (Temporal, Dagster, Airbyte, n8n, Sentry, PostHog,
Supabase). The consistent paid boundary is **operational**: the code runs free on the user's
machine; what sells is a hosted runner, managed connectors, a control-plane/dashboard, usage
metering, or enterprise governance (SSO / RBAC / audit retention / support).

## Decision

**Keep three seams open as architectural boundaries; build none of them now.**

1. **The Adapter interface is the one extension point.** The core depends only on the
   `Action`/`Effect` interface, never on a concrete Adapter; Adapters register via a pluggable
   registry; credentials are **Adapter-scoped**. This keeps both a managed-Adapter catalogue and
   a hosted runner reachable.
2. **A clean core ↔ control-plane boundary.** Approval / Decision / Audit state is exposed as a
   stable **read model / event stream** with pluggable notification and reviewer-routing points;
   the **Audit store sits behind an append-only persistence interface** (writer + chain
   verifier); `Permission` stays the single enforcement point so enterprise RBAC/SSO extends it.
3. **A countable billable unit.** Every executed **Action** and unit of **Recoverable value**
   stays a discrete, identified, queryable event (the `Correlation id` already threads this), so
   usage metering can attach later without a schema migration.

**Licence:** because every viable seam is operational, a **permissive licence (Apache-2.0) for
the core** keeps a hosted edge viable *and* maximises launch adoption (the Temporal/Supabase
pattern). Do **not** adopt a source-available licence pre-emptively; defer any restrictive
licence to a *future* hosted component only. _Note: the repo currently ships **MIT** (added in
S10); adopting this ADR means moving the core to Apache-2.0 — that licence change is left to the
maintainer to confirm on merge._

## Alternatives considered

- **Source-available now (ELv2 / SUL / FSL / BSL)** — protects against a hosted free-rider that
  doesn't exist yet; costs adoption and contribution, and isn't OSI-open. Premature.
- **Build a hosted edge now** — out of scope; the point is only to keep the seams reachable.

## Consequences

Extraction work (#9–#12, #2) must preserve: core-depends-only-on-Adapter-interface; a pluggable
Adapter registry; Adapter-scoped credentials; the Audit store behind an interface; Approval/Audit
exposed as a read-model/event stream; `Permission` as the single enforcement point; and executed
Action / Recoverable value as countable events. A maintainer decision on **MIT → Apache-2.0** is
outstanding.
