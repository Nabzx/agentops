# 0007. Extract the audit module: an AuditStore interface, not a shared table

- **Status:** Accepted
- **Date:** 2026-09-02
- **Driven by:** #10

## Context

Of the three Phase 1 extraction targets (#10 audit, #11 approval gate, #12 outbox/worker), only
audit is actually generic. `AuditEvent` (`backend/app/models/audit.py`) has no foreign keys to
anything AgentOps-specific - just `subject_type: str` / `subject_id: uuid.UUID | None`, opaque
`metadata_json`, and the hash-chain fields. `ApprovalRequest` and `OutboxJob`, by contrast, have
hard foreign keys to `workflow_runs`, `tickets`, `orders`, plus AgentOps-specific business columns
(`draft_response_body`, `policy_citation_ids`). Those need a real schema redesign (an opaque,
hashed `Snapshot` blob replacing named columns) before they can extract cleanly - a separate,
bigger piece of work, not attempted here.

ADR-0002 already committed to the shape this ADR makes concrete: *"the Audit store sits behind an
append-only persistence interface (writer + chain verifier)."*

## Decision

**`ephor.audit` owns the interface, the hashing, and a real zero-setup implementation. AgentOps'
Postgres implementation is proven compatible with it, with one honestly-scoped gap left open.**

- `ephor/src/ephor/audit.py` defines `AuditEntry` (a **structural `Protocol`**, not a concrete
  class - a frozen dataclass and a mutable ORM row can both satisfy it), `AuditStore` (the
  append/get/list/verify interface), and `InMemoryAuditStore` - a complete, tested, in-process
  implementation. The hashing (`compute_entry_hash`, `canonical_payload`, `GENESIS_HASH`) is
  ported near-verbatim from `backend/app/audit/hashing.py`, unchanged - it was already
  framework-agnostic.
- `AuditEntry`'s fields are declared as **read-only properties**, not plain attributes: mypy
  otherwise requires a Protocol's plain attributes to be *settable*, which a frozen dataclass
  can't satisfy. Properties fix this without weakening the contract - nothing needs to mutate an
  audit entry after it's written.
- `backend/app/audit/repository.py`'s `AuditRepository` was aligned to the interface's method
  shapes with two small, zero-behaviour-change edits: `actor_user_id` / `subject_id` / `metadata`
  in `append()` gained defaults (`None`/`{}`), and `get()`'s parameter was renamed `event_id` ->
  `entry_id` (never called by keyword, confirmed via grep before renaming). Verified via a direct
  `inspect.signature` comparison and a scratch mypy check - every method now matches exactly
  except one thing.
- **The one thing that doesn't match, and why it's not fixed here:** `AuditRepository`'s methods
  return `AuditEvent` (the SQLAlchemy ORM row), not something satisfying `AuditEntry`, because
  `AuditEvent.metadata_json` isn't named `metadata`. I looked at renaming or aliasing it - and
  found `metadata` is a **reserved attribute name on every SQLAlchemy declarative model**
  (`Base.metadata` is the schema's `MetaData` object). Adding an instance-level `metadata`
  property to `AuditEvent` risks shadowing that for SQLAlchemy's own internals. Closing this gap
  for real needs a small translation wrapper (an adapter class that maps `AuditEvent` rows to an
  `AuditEntry`-conforming dataclass) - a new, additive file, not a change to the hash-chain logic
  itself. Left for a follow-up issue rather than rushed here.

## Alternatives considered

- **Move `AuditEvent` (the ORM model) into `ephor` wholesale** - rejected: forces every `ephor`
  user onto SQLAlchemy/Postgres, contradicting the "runs with zero setup" Phase 1 goal and
  ADR-0002's "Audit store behind an interface" commitment.
- **Rename `AuditEvent.metadata_json` to `metadata` to match the interface exactly** - rejected:
  collides with SQLAlchemy's reserved `Base.metadata` attribute. Discovered while attempting the
  property-alias approach; not a change worth the risk to working, hash-chain-critical code for a
  cosmetic naming match.
- **Force full conformance now via the translation wrapper** - deferred, not rejected: it's the
  right eventual answer, just additive, low-risk work better done as its own reviewable change
  once this interface has landed, rather than bundled into the ADR that defines it.

## Consequences

- `ephor.audit` is real, tested, working code today - not a skeleton. `ephor/tests/test_audit.py`
  covers chain integrity, tamper detection (mutated entry, deleted entry), hash determinism, and
  `InMemoryAuditStore`'s query behaviour.
- `backend`'s hash-chain logic is untouched behaviourally; all 423 backend tests still pass.
- **Follow-up, done (#32):** `backend/app/audit/store.py`'s `PostgresAuditStore` wraps
  `AuditRepository`, translating `AuditEvent` rows to an `AuditEntry`-conforming dataclass.
  `AuditService` now depends on `ephor.audit.AuditStore` as its actual, mypy-verified type -
  `self._store: AuditStore = PostgresAuditStore(...)` type-checks for real, closing the gap this
  ADR left open. No behaviour change; all 423 backend tests still pass.
- Sets the template question for #11/#12: what's genuinely generic (interface + hashing, here)
  versus what needs a real schema redesign first (their Snapshot problem) has to be answered
  per-module, not assumed.
