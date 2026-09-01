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
