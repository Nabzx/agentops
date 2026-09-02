# wallet-guard

The second detector built on [Ephor](../ephor/), and a proof that the propose → approve →
execute → audit loop holds for a genuinely different kind of Adapter - not just a second
Stripe-shaped one.

It scans a wallet for token approvals, flags any that grant an **unlimited** allowance (the
maximum representable amount, not just a large one) and proposes revoking each one - never
touching a bounded, finite approval. See
[ADR-0016](../docs/adr/0016-wallet-guard-approval-revocation.md) for the action set and, more
interestingly, for why exactly-once here rests on **nonce discipline** rather than a header the
way `stripe-recovery` leans on Stripe's `Idempotency-Key`.

This package runs with **zero setup, no wallet, no RPC endpoint**: `FakeChainClient`
(`src/wallet_guard/client.py`) is an in-memory stand-in seeded with fake approvals, sitting
behind the same `ChainClient` interface a real EVM-RPC-backed implementation would use.

## Try it

```bash
cd wallet-guard
uv sync
uv run python -m wallet_guard.demo
```

Walks through the whole loop on two fake approvals - one unlimited, one bounded - and prints the
audit trail at the end.

## Developing

```bash
uv run pytest
uv run ruff check .
uv run mypy .
```
