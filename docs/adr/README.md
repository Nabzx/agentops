# Architecture Decision Records

One record per locked decision. When Wayfinder settles a `wayfinder:*` question, the outcome
is written here so the *why* survives and agents don't relitigate it.

- Copy [`0000-template.md`](0000-template.md) to `NNNN-short-title.md` (next number).
- Keep it short: the decision, the context, the alternatives, the consequences.
- Link the ADR from the issue that drove it, and mark that issue's build work `ready-for-agent`.

## Index

| # | Decision | Status |
| --- | --- | --- |
| [0001](0001-record-architecture-decisions.md) | Record architecture decisions | Accepted |
| [0002](0002-keep-monetisation-seams-open.md) | Keep monetisation seams open; permissive core licence | Accepted |
| [0003](0003-adapter-scoped-sandbox-first-credentials.md) | Adapter-scoped, sandbox-first credentials | Accepted |
| [0004](0004-name-the-core-ephor.md) | Name the core: Ephor | Accepted |
| [0005](0005-exactly-once-boundary.md) | Exactly-once contract: core vs. Adapter | Accepted |
| [0006](0006-adapter-interface.md) | The Action/Effect Adapter interface | Accepted |
| [0007](0007-audit-store-interface.md) | Extract the audit module: an AuditStore interface | Accepted |
| [0008](0008-generic-snapshot-shape.md) | A generic Snapshot shape for the approval gate and outbox | Accepted |
| [0009](0009-approval-gate-extraction.md) | Extract the approval gate: state machine, snapshot hash, self-approval rule | Accepted |
| [0010](0010-outbox-worker-extraction.md) | Extract the outbox/worker: claim/lease mechanics, retry, the exactly-once proof | Accepted |
| [0011](0011-v1-stripe-action-set.md) | v1 Stripe action set: retry a soft-declined charge, and only that | Accepted |
| [0012](0012-actions-and-effects.md) | Implement the remaining core primitives: Action/Proposal and the Adapter interface | Accepted |
| [0013](0013-real-stripe-test-mode-client.md) | A real Stripe test-mode client: API mapping, credentials, testing | Accepted |
| [0014](0014-product-direction-recovery-wedge-and-platform-thesis.md) | Product direction: a commission-based recovery wedge, with the safety core as the platform thesis | Accepted |
