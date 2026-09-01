"""Throwaway spike for issue #2: does one Adapter interface cover both a mock adapter and a
thin Stripe stub without the interface itself ever mentioning Stripe? See RESULTS.md.

Not part of the ephor package - this file is discarded once the ADR is written; the real
interface lives in ephor/src/ephor/effects.py once #10-#12 extract it for real.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol


class RetryableEffectError(Exception):
    """Raised by an Adapter when the Effect might succeed if retried."""


class PermanentEffectError(Exception):
    """Raised by an Adapter when the Effect will never succeed - do not retry."""


@dataclass(frozen=True)
class Effect:
    effect_id: str
    occurred_at: datetime
    raw: dict[str, Any]


class Adapter(Protocol):
    """The interface every integration implements. The core only ever sees this - never a
    concrete Adapter's own types.
    """

    is_idempotent: bool

    async def revalidate(self, action: dict[str, Any]) -> bool:
        """Re-check the action is still valid immediately before executing it."""
        ...

    async def execute(self, action: dict[str, Any], idempotency_key: str) -> Effect:
        """Perform the Effect. Raise RetryableEffectError or PermanentEffectError on failure."""
        ...


class MockAdapter:
    """The in-memory adapter the core ships with, per ROADMAP Phase 1."""

    is_idempotent = True

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def revalidate(self, action: dict[str, Any]) -> bool:
        return True

    async def execute(self, action: dict[str, Any], idempotency_key: str) -> Effect:
        self.calls.append(idempotency_key)
        return Effect(
            effect_id=f"mock_{idempotency_key}",
            occurred_at=datetime.now(UTC),
            raw={"ok": True},
        )


class StripeStubAdapter:
    """A thin stand-in for a real Stripe adapter - simulates retrying a failed charge.
    No real network call; this is a stub, matching this project's offline-only rule.
    """

    is_idempotent = True

    def __init__(self) -> None:
        self._seen_keys: dict[str, Effect] = {}

    async def revalidate(self, action: dict[str, Any]) -> bool:
        # Real adapter: re-fetch the charge from Stripe, confirm it's still `failed`.
        return bool(action.get("charge_status") == "failed")

    async def execute(self, action: dict[str, Any], idempotency_key: str) -> Effect:
        # Simulates Stripe's own Idempotency-Key header: same key -> same stored result,
        # never a second real charge attempt. This is the "adapter closes the gap" half
        # of ADR-0005.
        if idempotency_key in self._seen_keys:
            return self._seen_keys[idempotency_key]
        if action["amount_cents"] <= 0:
            raise PermanentEffectError("cannot retry a non-positive charge amount")
        effect = Effect(
            effect_id=f"ch_{idempotency_key}",
            occurred_at=datetime.now(UTC),
            raw={
                "id": f"ch_{idempotency_key}",
                "status": "succeeded",
                "amount": action["amount_cents"],
            },
        )
        self._seen_keys[idempotency_key] = effect
        return effect


async def run_through_core(adapter: Adapter, action: dict[str, Any], key: str) -> Effect:
    """Stands in for what the real Outbox worker does - the core, calling only the interface."""
    if not await adapter.revalidate(action):
        raise PermanentEffectError("action is no longer valid")
    return await adapter.execute(action, key)


async def main() -> None:
    mock = MockAdapter()
    stripe = StripeStubAdapter()

    mock_effect = await run_through_core(mock, {"kind": "test"}, "key-1")
    print("mock effect:", mock_effect)

    stripe_action = {"charge_status": "failed", "amount_cents": 4700}
    stripe_effect_1 = await run_through_core(stripe, stripe_action, "key-2")
    stripe_effect_2 = await run_through_core(stripe, stripe_action, "key-2")
    assert stripe_effect_1 == stripe_effect_2, "same idempotency key produced two different effects"
    print("stripe effect (same key twice, deduped):", stripe_effect_1)

    try:
        await run_through_core(
            stripe, {"charge_status": "failed", "amount_cents": -1}, "key-3"
        )
        raise AssertionError("expected PermanentEffectError")
    except PermanentEffectError as exc:
        print("permanent error correctly raised:", exc)

    try:
        await run_through_core(
            stripe, {"charge_status": "already_succeeded", "amount_cents": 100}, "key-4"
        )
        raise AssertionError("expected revalidate() to reject a stale action")
    except PermanentEffectError as exc:
        print("stale-action rejection correctly raised:", exc)

    print("\nAll checks passed - one interface covered both adapters, no Stripe leakage.")


if __name__ == "__main__":
    asyncio.run(main())
