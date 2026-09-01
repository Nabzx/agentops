# 0006. The Action/Effect Adapter interface

- **Status:** Accepted
- **Date:** 2026-09-01
- **Driven by:** #2 (`wayfinder:prototype`) — see [the spike](../../prototypes/adapter-interface-2/)

## Context

Every integration implements one interface so the core knows nothing about Stripe or any other
specific system (see `Adapter` in CONTEXT.md). The shape had to satisfy the exactly-once contract
already locked in [ADR-0005](0005-exactly-once-boundary.md) - an `is_idempotent` capability flag,
a core-generated idempotency key passed into execution, and exactly two Adapter-raised exception
types for retry classification.

Grilled with the maintainer, then validated with a throwaway spike (mock adapter + a thin Stripe
stub) - see [RESULTS.md](../../prototypes/adapter-interface-2/RESULTS.md). The spike confirmed
the shape below covers both without either adapter leaking into the other.

## Decision

**The Adapter interface, as a Python `Protocol`:**

```python
class Adapter(Protocol):
    is_idempotent: bool

    async def revalidate(self, action: Action) -> bool: ...
    async def execute(self, action: Action, idempotency_key: str) -> Effect: ...
```

- **Async throughout** — every real Adapter target is an I/O-bound network call.
- **`revalidate` runs immediately before `execute`**, on every attempt (not just the first) - it
  re-checks the action is still valid given whatever changed in the world since it was approved
  (see ADR-0005's Q2 grilling). Returning `False` is treated as a `PermanentEffectError`: the
  world moved on, retrying won't help. A trivial Adapter (the mock) can just always return `True`.
- **`execute` takes the core's own idempotency key**, not one the Adapter invents - the Adapter's
  job is to pass it through to (or otherwise honour it against) the target system, per
  `is_idempotent`.
- **`Effect` is a fixed, generic return shape**: `effect_id: str`, `occurred_at: datetime`,
  `raw: dict` - the target's own opaque payload, stored for audit but never interpreted by the
  core. No Adapter-specific fields exist anywhere else in the interface.
- **Exactly the two exception types from ADR-0005** — `RetryableEffectError` and
  `PermanentEffectError` — raised by `execute` (or by the core, wrapping a `False` from
  `revalidate`). No third type.
- **Registration is a plain dict**, not a plugin/entry-point system - `registry.register("stripe",
  StripeAdapter)`. Revisit only once a second real (non-mock) Adapter exists to justify more
  machinery.

## Alternatives considered

- **`execute` only, no `revalidate`** — rejected: leaves a real gap where an approved action
  executes into a world that's already changed (the exact kind of silent-wrong-action this
  project exists to prevent).
- **A richer `Effect` type with per-Adapter fields** — rejected: the entire point of the interface
  is that the core never knows what's inside a Stripe response; a fixed `raw: dict` escape hatch
  keeps that boundary honest without the core needing per-Adapter type definitions.
- **A plugin-discovery registry (entry points, decorators-with-magic)** — rejected for now, YAGNI:
  one real target (Stripe) plus the mock doesn't justify it; a plain dict is simpler and just as
  correct at this scale.
- **A third exception type for "uncertain"** — rejected: ADR-0005 already settled that job-state
  uncertainty (`needs-manual-reconciliation`) is a core-decided state from crash recovery, never
  something an Adapter reports.

## Consequences

- Unblocks #10 (approval gate extraction), #11 (audit extraction), #12 (outbox/worker
  extraction — together with ADR-0005) and #14 (Stripe detector skeleton).
- `ephor/src/ephor/effects.py` (currently empty, see #9) gets this `Adapter` Protocol, the
  `Effect` dataclass/model, and the two exception types as its first real content, as part of the
  Phase 1 extraction issues above - not in this ADR, which only proposes the interface per issue
  #2's own scope.
- The Stripe flagship's real adapter (#14) must implement `revalidate` meaningfully (an actual
  re-fetch of charge state), not just return `True` - the mock is allowed to skip real checking,
  a production Adapter is not.
