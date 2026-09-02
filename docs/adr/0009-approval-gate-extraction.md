# 0009. Extract the approval gate: state machine, snapshot hash, self-approval rule

- **Status:** Accepted
- **Date:** 2026-09-02
- **Driven by:** #11

## Context

ADR-0008 locked the generic shape for `ApprovalRequest`. Reading `backend/app/approvals/service.py`
in full before extracting anything surfaced something ADR-0008 didn't fully anticipate:
`ApprovalService` isn't just "a model with AgentOps-specific columns" the way #10's audit module
was - its *logic* is fused with AgentOps' own orchestration. `approve()`/`reject()`/`cancel()`/
`retry()` inline workflow-run loading, checkpoint building, ticket/order resolution, refund-limit
computation, proposed-action transitions and outbox-payload construction. None of that belongs in
a generic core - a Stripe detector has no workflow run, no checkpoint, no ticket.

What genuinely *is* generic, and already present almost verbatim:

- `ApprovalStatus` and its transition table (`backend/app/approvals/enums.py`) - already
  generic string values, zero AgentOps coupling.
- `ApprovalDecisionType` - generic.
- The snapshot hash mechanism (`backend/app/approvals/snapshot.py`) - canonicalise, SHA-256,
  compare. The *mechanism* is generic even though `ApprovalSnapshot` (the pydantic model it
  hashes) is entirely support-ops-shaped.
- **The self-approval rule** - duplicated three times in `ApprovalService`
  (`approve`/`reject`/`retry`). Issue #11 names this explicitly, and CONTEXT.md already states it
  as an invariant ("Requester: ... Never an approver of its own request").

## Decision

**Extract exactly those four things, with tests. Leave AgentOps' orchestration untouched.**

1. `ephor/src/ephor/approvals.py` now has real content: `ApprovalStatus`/`ApprovalDecisionType`
   (ported verbatim as `StrEnum`s), the transition table, `compute_snapshot_hash`/`verify_snapshot`
   generalised to an opaque `dict` (per ADR-0008 - the core hashes whatever a detector puts in the
   snapshot, never interprets it), `assert_not_self_decision`, structural `ApprovalRequest`/
   `Decision` Protocols matching ADR-0008's generic shape, an `ApprovalStore` Protocol, and a real,
   tested `InMemoryApprovalStore`.
2. **AgentOps re-exports instead of duplicating.** `backend/app/approvals/enums.py` is now a thin
   re-export of `ephor.approvals`'s enums/transitions. Every existing import site
   (`app/outbox/processor.py`, `app/models/approval.py`, `app/api/routes/approvals.py`,
   `app/approvals/{repository,cli,service}.py`, three test files) keeps importing
   `from app.approvals.enums import ApprovalStatus` unchanged - only the definition's home moved.
   Confirmed safe because `pg_enum()` (`app/models/enums.py`) accepts any `type[StrEnum]`
   regardless of origin.
3. **The self-approval rule is single-sourced.** The three duplicated inline checks in
   `ApprovalService` now call a `_require_not_self_decision` helper that wraps
   `ephor.approvals.assert_not_self_decision`, translating its `SelfDecisionError` back to the
   existing `ApprovalError`/`ApprovalErrorCode.APPROVAL_SELF_DECISION_FORBIDDEN` with each call
   site's own message. Same behaviour, same error path, one implementation.
4. **`ApprovalSnapshot`, `ApprovalService`'s orchestration, and the production
   `approval_requests`/`approval_decisions` tables are not touched otherwise** - same instinct as
   ADR-0007. Wiring `ApprovalService` to build/verify snapshots through `ephor.approvals`'s generic
   functions instead of `snapshot.py`'s typed-model versions is real follow-up work (#36), not
   rushed here.

**Infrastructure fallout, worth recording:** `backend` now has a local path dependency on `ephor`
(`[tool.uv.sources]` in `backend/pyproject.toml`). This broke the Docker build, whose context was
scoped to `./backend` and couldn't see `../ephor`. Fixed by widening `backend`'s and `worker`'s
build context to the repo root (`docker-compose.yml`), adding a matching `COPY ephor /ephor` step
and adjusted paths in `backend/Dockerfile`, a runtime `./ephor:/ephor` volume mount (for the same
live-editing experience the existing `./backend:/app` mount gives), and a root `.dockerignore`
(the old `backend/.dockerignore` no longer applies once the context isn't `./backend`).

## Alternatives considered

- **Move `ApprovalService`'s full orchestration into `ephor`** - rejected: workflow runs,
  checkpoints and tickets are AgentOps-specific concepts with no place in a generic core. This
  would also be a much larger, riskier change to production approval-decision code for no benefit
  the core actually needs.
- **Duplicate the enums in both places instead of re-exporting** - rejected: defeats the point of
  a single source of truth, and risks silent drift between the two copies over time.
- **Leave the self-approval checks duplicated in `ApprovalService`** - rejected: issue #11 names
  this rule explicitly as something to extract, and CONTEXT.md already treats it as an invariant,
  not an app-specific business rule.

## Consequences

- `ephor/tests/test_approvals.py` covers the state machine (valid/invalid transitions), snapshot
  tamper detection, self-approval rejection, and `InMemoryApprovalStore`'s CRUD/query behaviour.
- `backend`'s behaviour is unchanged: all 423 backend tests pass, `make verify-all` passes
  end to end (one hard-gate scenario, `s6_regression`, failed once and passed on an unmodified
  rerun - a pre-existing flake in the eval suite, same shape as `refund_audit_and_pii` found
  during #10, not chased here either).
- **Follow-up, done (#36):** `app/approvals/snapshot.py`'s `compute_snapshot_hash`/
  `verify_snapshot` now delegate the canonicalise-and-hash mechanism to `ephor.approvals`,
  keeping only the domain-specific "which fields are hash-relevant" decision locally. The hash
  algorithm is byte-for-byte identical (confirmed by all 423 tests, including tamper-detection
  ones, still passing unchanged) - existing stored hashes remain valid.
- Sets the template for #12 (outbox/worker): expect the same split - a generic exactly-once state
  machine and attempt ledger extract cleanly, while AgentOps-specific payload construction stays
  in the app layer.
