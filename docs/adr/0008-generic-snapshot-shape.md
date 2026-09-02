# 0008. A generic Snapshot shape for the approval gate and outbox

- **Status:** Accepted
- **Date:** 2026-09-02
- **Driven by:** #11, #12 (both `ready-for-agent`, blocked in practice on this design question)

## Context

ADR-0007 (extracting the audit module) found that `ApprovalRequest` and `OutboxJob`, unlike
`AuditEvent`, are not self-contained: they carry hard foreign keys to AgentOps-specific tables
(`tickets`, `orders`, `workflow_runs`) and support-ops-specific business columns
(`draft_response_body`, `policy_citation_ids`, `rule_result_json`). None of that belongs in a
generic safe-action core - a Stripe detector has no ticket, no draft response, no policy
citations. This ADR settles what the generic shape actually looks like, so #11/#12 can extract
against something real instead of guessing.

Grilled with the maintainer in one round.

## Decision

**Four changes, all additive to the core's own shape - none of them touch AgentOps' existing
production table.**

1. **`subject_type: str` / `subject_id: UUID | None` replace `ticket_id`/`order_id`.** Same
   pattern `AuditEntry` already uses (ADR-0007) - the core describes "what this Approval is
   about" the same way it describes "what this Audit entry is about." No FK to any
   AgentOps-specific table.
2. **`snapshot_json: dict` / `snapshot_hash: str` replace six named columns**
   (`policy_citation_ids`, `policy_version_ids`, `rule_result_json`, `draft_response_subject`,
   `draft_response_body`, `evidence_snapshot_json`/`_hash`). This is CONTEXT.md's `Snapshot`
   definition made literal: *"the exact, frozen description of what an approver is shown...
   canonicalised and SHA-256 hashed, re-verified before every decision."* The core stores it,
   hashes it, shows it, and re-verifies it - it never interprets what's inside. Each detector
   decides its own shape: support-ops puts policy citations and a draft reply in there; a future
   Stripe detector would put the charge amount and its recovery rationale.
3. **A `proposal_id: UUID` replaces `workflow_run_id` and `proposed_action_id`** on both
   `ApprovalRequest` and `OutboxJob`. The core only needs to know which `Proposal` (its own
   concept) this Approval/Job is for - it has no concept of a "workflow run," because that's
   AgentOps' own orchestration detail, not a core-level idea. AgentOps keeps its own mapping from
   `proposal_id` back to `workflow_run_id` on its own side.
4. **AgentOps' production `approval_requests`/`outbox_jobs` tables are not modified.** Following
   the same instinct as ADR-0007 (prove the interface without touching the production hash-chain
   path): AgentOps keeps its existing rich table (or a 1:1-joined side table) with `ticket_id`,
   `order_id`, `draft_response_body`, etc., exactly as today, for its own dashboard. The **core's**
   table (in `ephor`) is the new, clean, minimal shape above - used by any detector, including a
   future Stripe one. AgentOps' approval flow becomes the first thing that populates both: its own
   rich record for its dashboard, and a generic core record for the safety mechanism.

## Alternatives considered

- **Let the core know about tickets/orders directly** - rejected: defeats the entire point of
  extracting a reusable core; a Stripe detector has neither.
- **Keep the six named "what the approver sees" columns, just make them nullable/optional** -
  rejected: still support-ops-shaped by default, and a new detector would need to either abuse
  those field names for unrelated data or the core would grow new named columns per detector
  forever. One opaque, hashed blob scales to any detector without schema changes.
- **Migrate the production table in place** (drop `ticket_id`/`draft_response_body`/etc., have the
  dashboard read from the generic shape instead) - rejected: real risk to a working, hash-chain-
  adjacent production path for no benefit right now; #10 already established that proving an
  interface doesn't require rewriting what already works.

## Consequences

- Unblocks #11 (approval gate extraction) and #12 (outbox/worker extraction) to build against a
  concrete, agreed shape instead of an open question.
- `ephor.approvals` (once built) defines `ApprovalRequest`/`Decision` with:
  `subject_type`, `subject_id`, `snapshot_json`, `snapshot_hash`, `proposal_id`, plus the fields
  already generic today (`status`, `action_type`, `risk_level`, amounts, `idempotency_key`,
  `expires_at`, `decided_at`). `ephor.outbox`'s `OutboxJob` drops `workflow_run_id`/
  `proposed_action_id` for `proposal_id`; `payload_json`/`payload_hash` were already generic and
  are unchanged.
- AgentOps' extraction work (#11/#12, whenever picked up) needs to build the translation between
  its rich production record and the core's generic one - the same shape of work #32 already
  scopes for audit, now needed twice more.
- **Not decided here:** the generic shape of `Proposal` itself (currently AgentOps'
  `proposed_actions` table, referenced by the new `proposal_id`). Whoever picks up #11 should
  check whether `Proposal` needs its own version of this same treatment before extracting it, or
  whether referencing it by id is enough for now.
