<div align="center">

# Ephor

[![CI](https://github.com/Nabzx/ephor/actions/workflows/ci.yml/badge.svg)](https://github.com/Nabzx/ephor/actions/workflows/ci.yml)
&nbsp;![Licence: Apache-2.0](https://img.shields.io/badge/licence-Apache--2.0-3B9EFF)
&nbsp;![Python 3.12](https://img.shields.io/badge/python-3.12-3B9EFF)
&nbsp;![Status: early](https://img.shields.io/badge/status-early-orange)

The safety layer for AI agents that take real action.<br>
An agent proposes, a human approves, the action runs exactly once, and every step is proven, not just logged.

</div>

The goal: the trust layer behind the next generation of agents that audit and run real
businesses, starting with revenue recovery on Stripe.

![Propose, approve, execute, audit](assets/demo.gif)

*A charge that failed with a soft decline, proposed, approved, retried exactly once, and
audited - end to end in the terminal, in seconds. No Stripe account, no network, no signup.*

## Quickstart

```bash
git clone https://github.com/Nabzx/ephor.git
cd ephor/stripe-recovery
uv sync
uv run python -m stripe_recovery.demo
```

That's the whole loop, deterministic and offline, in under two minutes on a fresh clone. See
[stripe-recovery/README.md](stripe-recovery/README.md) for what it's actually doing.

Want the full dashboard - sign-in, an approval queue, the audit trail, ticket journeys - against
the reference app this core was extracted from?

```bash
make up && make seed      # stack + synthetic data
make demo                 # approval -> execution, exactly once, in your terminal
```

Then open <http://localhost:3000>. Everything here is deterministic, offline and simulated too:
no paid API, no external network, nothing real is ever contacted.

| Approval detail + decision | Hash-chained audit log |
| --- | --- |
| ![Approval detail](docs/screenshots/04-approval-detail.png) | ![Audit log](docs/screenshots/07-audit.png) |

## Why

Letting an AI agent act on its own is fast until it's wrong: a refund it shouldn't have issued, a
charge it retried twice, a change nobody can explain afterwards. Ephor puts a checkpoint in front
of every consequential action, so nothing happens until a human sees exactly what's about to occur
and says yes.

Named after the Spartan magistrates whose job was to check the king's power before it acted,
2,500 years before this project's `propose → approve → execute` loop existed for the same reason.

## How it works

- **Propose**: an agent puts forward one concrete action. It never executes on its own.
- **Approve**: a human sees a frozen, hashed snapshot of exactly what will happen, and decides.
- **Execute**: once approved, the action runs through a durable outbox, **exactly once**, proven
  by a crash-recovery test and a 50,000-trial randomised chaos sweep
  ([ADR-0015](docs/adr/0015-chaos-test-the-exactly-once-guarantee.md),
  [report](docs/chaos-report.md)), not just claimed.
- **Audit**: every step writes to an append-only, hash-chained log. Tampering breaks the chain
  detectably; nothing can be quietly edited or deleted. Self-approval, tampering and replay are
  each checked by a named, scored [security benchmark](docs/security-benchmark.md)
  ([ADR-0019](docs/adr/0019-security-benchmark.md)) - including the one honest limitation it
  found: an Adapter that lies about its own idempotency can't be caught, by design.

## Status

Early. The core (`ephor/`) - audit, the approval gate, the outbox/worker, and the Action/Adapter
primitives - is extracted, tested, and wired for real into the reference app
([ADR-0007](docs/adr/0007-audit-store-interface.md),
[0009](docs/adr/0009-approval-gate-extraction.md),
[0010](docs/adr/0010-outbox-worker-extraction.md)). `stripe-recovery/` is a working flagship: it
scans, proposes, approves, executes and audits a real charge retry end to end, against a fake
Stripe client by default, or a real Stripe test-mode account one environment variable away
([ADR-0013](docs/adr/0013-real-stripe-test-mode-client.md)). Two more detectors prove the core
generalises: `wallet-guard/` revokes dangerous unlimited token approvals, earning exactly-once
through nonce discipline instead of a payments-provider header
([ADR-0016](docs/adr/0016-wallet-guard-approval-revocation.md)); `cloud-waste/` releases
unassociated Elastic IP addresses, earning exactly-once from AWS's own error semantics instead of
either ([ADR-0020](docs/adr/0020-v1-cloud-waste-action-set.md)) - three genuinely different
Adapter shapes, one core.

## Contributing

Issues are tracked with a locked-spec workflow: see [AGENTS.md](AGENTS.md) for how a decision
gets settled before anyone builds it, and [CONTRIBUTING.md](CONTRIBUTING.md) for the loop itself.

There's no company behind this, just one person building in public. If it's useful, or the idea
resonates, a star is the biggest help there is: it's how someone else finds it.

## Licence

[Apache-2.0](LICENSE)
