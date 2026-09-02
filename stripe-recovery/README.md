# stripe-recovery

The Stripe revenue-recovery flagship: the first detector built on [Ephor](../ephor/), and a
proof that the propose → approve → execute → audit loop works on something real.

It scans a Stripe account for failed charges, classifies each one's decline code against an
explicit allow-list ([ADR-0011](../docs/adr/0011-v1-stripe-action-set.md)), and proposes a retry
for every one that's safe to retry - never for a hard decline like a stolen card.

This package runs with **zero setup and no Stripe account**: `FakeStripeClient`
(`src/stripe_recovery/client.py`) is an in-memory stand-in seeded with fake charges, sitting
behind the same `StripeClient` interface a real Stripe-SDK-backed implementation would use. See
[ADR-0011](../docs/adr/0011-v1-stripe-action-set.md) and
[ADR-0012](../docs/adr/0012-actions-and-effects.md) for the reasoning.

## Try it

```bash
cd stripe-recovery
uv sync
uv run python -m stripe_recovery.demo
```

Walks through the whole loop on two fake charges - one retryable, one not - and prints the audit
trail at the end.

## Developing

```bash
uv run pytest
uv run ruff check .
uv run mypy .
```
