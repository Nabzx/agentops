# 0013. A real Stripe test-mode client: API mapping, credentials, testing

- **Status:** Accepted
- **Date:** 2026-09-02
- **Driven by:** #48 (`wayfinder:research`)

## Context

`stripe-recovery/client.py`'s `StripeClient` Protocol has one implementation,
`FakeStripeClient`. ADR-0011 already locked *what* the real client does mechanically
("re-confirm the same failed `PaymentIntent`, never create a new one, passing the core's
idempotency key through as Stripe's own `Idempotency-Key` header") and ADR-0003 already locked
the credential model (typed `pydantic-settings` config, env vars as the source of truth,
sandbox-by-default enforced by the key prefix). What's still open is narrower than it looks:

1. **How `list_failed_charges()` maps onto a real Stripe query.** Stripe has no "list failed
   charges" endpoint. The candidates are the legacy Charges list (filter `status=failed`, read
   `failure_code`) or the PaymentIntents list (filter client-side on `status ==
   "requires_payment_method"`, read `last_payment_error.decline_code`). ADR-0011 already commits
   to re-confirming a `PaymentIntent`, so the list side should read from the same object, not a
   different one - a Charge and its PaymentIntent can disagree transiently, and re-deriving the
   PaymentIntent id from a Charge just to confirm it is an extra lookup for no benefit.
2. **Where the secret key actually lives**, concretely, in this package.
3. **How this gets tested without breaking the repo's determinism promise** - the README states
   plainly that nothing here ever contacts a real network by default, and CI must stay that way.

## Decision

**A `StripeTestModeClient` in `stripe_recovery/client.py`, alongside `FakeStripeClient`, wrapping
the official `stripe` Python SDK against the PaymentIntents API. Fake stays the default; real is
an explicit opt-in via one environment variable, never exercised by CI.**

1. **List side: `stripe.PaymentIntent.list(...)`, paginated, filtered client-side** on
   `status == "requires_payment_method"` (Stripe's state for a PaymentIntent whose last
   confirmation attempt failed) and `last_payment_error.decline_code` against ADR-0011's
   allow-list. `FailedCharge.id` on a real client is a PaymentIntent id (`pi_...`), not the
   underlying Charge id (`ch_...`) - a naming mismatch worth a one-line comment on the class, not
   a Protocol change, since the id is already opaque to everything above the client (same
   principle as ADR-0008's Snapshots).
2. **Execute side: `stripe.PaymentIntent.confirm(id, idempotency_key=key)`** - exactly what
   ADR-0011 already specified. The SDK accepts `idempotency_key` as a request option on any
   create/update-style call; no separate dedup mechanism is needed inside this package, Stripe's
   own 24-hour idempotency window is the backstop ADR-0005 relies on.
3. **Credentials: a `StripeRecoverySettings(BaseSettings)`**, `env_prefix="STRIPE_RECOVERY_"`,
   one field `secret_key: SecretStr`. Sandbox is enforced the way ADR-0003 already decided: the
   key's own prefix (`sk_test_`/`rk_test_` vs `sk_live_`/`rk_live_`) decides the mode, and
   constructing a client with a live-looking key raises unless built with an explicit
   `allow_live=True` that nothing in this repo ever passes. `.env.example` gets one new line:
   `STRIPE_RECOVERY_SECRET_KEY=sk_test_...`.
4. **Selection stays a zero-setup default.** `demo.py` and the detector construct
   `FakeStripeClient` unless `STRIPE_RECOVERY_SECRET_KEY` is set in the environment, in which case
   they construct `StripeTestModeClient` instead. Cloning the repo and running the demo never
   requires a Stripe account; pointing it at one is one env var away.
5. **No real network calls in CI, ever.** `stripe-recovery`'s CI job tests
   `StripeTestModeClient`'s own logic (decline-code filtering, the id/idempotency-key plumbing)
   against the `stripe` SDK's resource methods monkeypatched to return canned objects - never a
   live HTTP call, and never a recorded-cassette library, which would need real secrets to record
   against in the first place. A live run against an actual Stripe test-mode account is a manual
   path only, gated behind that same env var, documented in `stripe-recovery/README.md`, never
   invoked automatically.
6. `stripe` (the official SDK) becomes a dependency of `stripe-recovery/pyproject.toml` only -
   not `ephor`, not `backend`. Nothing about the core or the reference app changes.

## Alternatives considered

- **Read from the legacy Charges list instead of PaymentIntents** - rejected: ADR-0011 already
  commits the execute side to re-confirming a PaymentIntent; listing from the same object avoids
  a second lookup and a transient-disagreement window between a Charge and its PaymentIntent.
- **A pluggable secret-store seam now (Vault, a cloud secrets manager)** - rejected for the same
  reason ADR-0003 rejected it originally: no second implementation exists yet to justify the
  seam, and env vars already satisfy "never committed, dead-simple self-hosted."
- **VCR-style recorded HTTP cassettes for tests** - rejected: recording a cassette still needs a
  real Stripe test-mode account and real secrets at least once, and scrubbing those out of a
  cassette file reliably is its own ongoing maintenance burden. Monkeypatching the SDK's resource
  methods tests the same logic without ever needing a key to exist.
- **Run `StripeTestModeClient` against a live Stripe test account in CI**, using a repo secret -
  rejected: it would make CI depend on an external service's availability and rate limits, and
  quietly breaks this repo's "nothing here contacts a real network" promise for anyone reading the
  workflow file, not just anyone running the demo.

## Consequences

- Unblocks a `ready-for-agent` build issue for `StripeTestModeClient` itself - filed as a
  follow-up, since this ADR is the research output, not the build.
- `FakeStripeClient` remains the default and the only client exercised by CI; the "clone it, run
  one command, zero setup" quickstart (#13) is unaffected.
- Anyone who wants to see this run against a real (test-mode) Stripe account can, by setting one
  environment variable, with no code change - closing Phase 2's last unticked box once built.
- `docs/adr/README.md`'s index gets a new row.
