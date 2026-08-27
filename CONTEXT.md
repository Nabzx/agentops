# AgentOps

The shared language of the project. Every agent and human uses these terms exactly, so that
many parallel contributors describe the same system the same way. Components are named by the
**role** they fill, never by the library that currently fills it. Where a term has a tempting
synonym that means something subtly different, it is listed under _Avoid_.

AgentOps is the **safe-action layer for AI agents**: an agent *proposes* a consequential
action, a human *approves* a frozen snapshot of exactly what will happen, and the action then
*executes exactly once* onto a tamper-evident record. The reusable part of this is **the core**;
the first thing built on it is **the flagship detector**.

## The action loop

**Action**
: A single consequential thing an agent wants to happen in the real world — a refund, a
  charge retry, a subscription change. It is always a *request*, never self-executed.
  _Avoid_: task, command, operation, tool call

**Proposal**
: An Action put forward for a decision, carrying its parameters, its risk, and the evidence
  behind it. A proposal has not happened and may be rejected.
  _Avoid_: suggestion, recommendation, draft action

**Approval request**
: The record that a Proposal is awaiting a human decision. It holds the Snapshot and the
  decision history and moves through pending → approved / rejected / expired.
  _Avoid_: ticket, task, review item

**Snapshot**
: The exact, frozen description of what an approver is shown — Action, amount, deterministic
  limit, rule outcome and citations — canonicalised and SHA-256 hashed, re-verified before
  every decision. A supervisor can only approve exactly what the Snapshot describes.
  _Avoid_: preview, summary, diff

**Decision**
: A human's approve / reject / cancel on an Approval request, recorded as an append-only row.
  The requester may never decide their own request.
  _Avoid_: approval (the act vs. the record), sign-off, vote

**Effect**
: The real-world result an Action produces once executed — a recorded refund, a sent dunning
  email. In this project every Effect is **simulated** or runs against a **sandbox**.
  _Avoid_: side effect, outcome, result

**Adapter**
: The component that knows how to carry out a class of Effects against one external system
  (e.g. a Stripe adapter). Adapters implement the `Action`/`Effect` interface; the core knows
  nothing about any specific system.
  _Avoid_: integration, connector, plugin, driver

## Durable execution

**Outbox job**
: The durable unit of work created — in the same database transaction as an approving
  Decision — to carry out an approved Action. An approval and its job can never diverge.
  _Avoid_: task, message, queue item

**Worker**
: The process that claims Outbox jobs (with `FOR UPDATE SKIP LOCKED`), leases them, and runs
  them through an Adapter, recording an immutable attempt history.
  _Avoid_: consumer, runner, processor

**Idempotency key**
: The stable key that ties an Action to at-most-one Effect, so retries and reprocessing
  produce no second Effect.
  _Avoid_: dedup key, request id

**Exactly-once**
: The guarantee that one approved Action yields **exactly one** Effect, proven by a gate, not
  asserted. It is exactly-once *effect*, not exactly-once delivery.
  _Avoid_: at-least-once, idempotent (as a synonym), guaranteed delivery

## The record

**Audit entry**
: One append-only, hash-chained row recording a consequential or security event, written in
  the same transaction as the event it records.
  _Avoid_: log line, event, history row

**Audit chain**
: The linked sequence of Audit entries where each entry's hash covers the previous one, so any
  edit or deletion is detectable. "Chain intact" means it verifies.
  _Avoid_: audit log (loosely), ledger, trail

**Correlation id**
: The single identity threaded across an Action's whole journey — proposal, decision, job,
  execution, audit — so one request can be traced end to end.
  _Avoid_: trace id, request id (these are narrower), session id

## Roles & governance

**Requester**
: The identity (often an agent acting for an operator) that raises a Proposal. Never an approver of its own request.
  _Avoid_: user, agent (too broad), author

**Approver**
: The human with permission to decide an Approval request. Holds the `approval_decide` permission.
  _Avoid_: reviewer, admin, supervisor (that is one instance of an approver)

**Permission**
: A named capability checked on every consequential route (e.g. `approval_decide`,
  `outbox_inspect`). The UI hides what a role lacks; the backend still refuses it.
  _Avoid_: role (a role is a bundle of permissions), scope, grant

## The flagship

**Detector**
: A component that inspects one external system and emits Proposals for recoverable value. The
  flagship is the Stripe revenue-recovery detector; more detectors are the roadmap.
  _Avoid_: analyzer, scanner, agent, auditor

**Recoverable value**
: A specific, quantified opportunity a Detector finds (e.g. a soft-declined charge worth
  retrying), expressed so the headline can read "found $X".
  _Avoid_: insight, saving, opportunity (unquantified)

## The build

**The core**
: The reusable safe-action framework extracted in Track A — the action loop, durable
  execution, and audit, behind the Adapter interface. Its published name is an open decision.
  _Avoid_: the library, the SDK, the platform, AgentOps (that is the whole project)

**Wayfinder**
: The decision workflow that turns open questions into locked specs before anything is built:
  a `map` issue names the decisions, then each is settled by `research` (autonomous),
  `grilling` (pressure-tested with a human) or a throwaway `prototype`. A settled spec becomes
  `ready-for-agent`.
  _Avoid_: planning, design phase, spike (a prototype is one kind)
