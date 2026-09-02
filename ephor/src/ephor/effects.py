"""Effect, Adapter - see CONTEXT.md "The action loop" and ADR-0006.

Every integration implements this one interface so the core knows nothing about Stripe
or any specific system. Validated against a throwaway spike before being locked -
see ``prototypes/adapter-interface-2/`` and ADR-0006 for the reasoning.

The two exceptions an Adapter raises to classify a failure live in ``ephor.outbox``
(``RetryableEffectError``/``PermanentEffectError``), not here - that's where the retry
loop that reacts to them lives (ADR-0005), and this module re-exports them so callers
only need to import from one place for the whole Adapter contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from ephor.outbox import PermanentEffectError, RetryableEffectError


@dataclass(frozen=True)
class Effect:
    """The generic result of one Adapter execution. ``raw`` is the target's own opaque
    payload - stored for audit, never interpreted by the core.
    """

    effect_id: str
    occurred_at: datetime
    raw: dict[str, Any] = field(default_factory=dict)


class Adapter(Protocol):
    """The interface every integration implements. See ADR-0006."""

    is_idempotent: bool

    async def revalidate(self, action: dict[str, Any]) -> bool:
        """Re-check the action is still valid immediately before executing it.

        Runs on every attempt, not just the first. A ``False`` here is treated as a
        ``PermanentEffectError`` by the caller: the world moved on, retrying won't help.
        A trivial Adapter may always return ``True``; a production one must not.
        """
        ...

    async def execute(self, action: dict[str, Any], idempotency_key: str) -> Effect:
        """Perform the Effect. Raise RetryableEffectError or PermanentEffectError."""
        ...


class AdapterRegistry:
    """A plain dict mapping a name to an Adapter class - not a plugin/discovery system.

    Revisit only once a second real (non-mock) Adapter exists to justify more, per
    ADR-0006.
    """

    def __init__(self) -> None:
        self._adapters: dict[str, type[Adapter]] = {}

    def register(self, name: str, adapter_cls: type[Adapter]) -> None:
        self._adapters[name] = adapter_cls

    def get(self, name: str) -> type[Adapter] | None:
        return self._adapters.get(name)


class MockAdapter:
    """The in-memory Adapter the core ships with, per ROADMAP Phase 1. Always succeeds;
    never touches anything outside this process.
    """

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


__all__ = [
    "Adapter",
    "AdapterRegistry",
    "Effect",
    "MockAdapter",
    "PermanentEffectError",
    "RetryableEffectError",
]
