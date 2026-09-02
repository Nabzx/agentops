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

## Running it against a real Stripe test-mode account

Optional, and never required. Copy `.env.example` to `.env`, fill in a real Stripe **test-mode**
secret key (`sk_test_...`), and the same command scans your actual account instead:

```bash
cp .env.example .env   # then edit it
uv run python -m stripe_recovery.demo
```

`StripeTestModeClient` (`src/stripe_recovery/client.py`) wraps the official Stripe SDK against
the PaymentIntents API - see [ADR-0013](../docs/adr/0013-real-stripe-test-mode-client.md) for the
API mapping, credential model and why nothing here ever runs a real network call in CI. A
live-looking key (`sk_live_.../rk_live_...`) is refused outright, not silently accepted.

## Developing

```bash
uv run pytest
uv run ruff check .
uv run mypy .
```
