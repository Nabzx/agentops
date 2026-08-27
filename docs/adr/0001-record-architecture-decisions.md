# 0001. Record architecture decisions

- **Status:** Accepted
- **Date:** 2026-08-27
- **Driven by:** the OSS pivot — many parallel agents must not relitigate settled choices

## Context

The next chapter of AgentOps runs agent-driven on parallel tracks. When Wayfinder settles an
open question, that outcome needs a durable home so implementation agents inherit the *why*
and don't re-argue it in code review.

## Decision

We will record every settled decision as a short ADR in `docs/adr/`, numbered sequentially,
linked from the `wayfinder:*` issue that drove it. A decision is not "locked" until its ADR is
Accepted and its build work is labelled `ready-for-agent`.

## Alternatives considered

- **Decisions live in issue threads only** — they scroll away and are hard to cite.
- **A single big design doc** — becomes stale and merge-contended across parallel tracks.

## Consequences

Agents have one place to learn why the system is the way it is. ADRs are cheap to write and
cheap to supersede. Reviewers can reject a PR that contradicts an Accepted ADR by number.
