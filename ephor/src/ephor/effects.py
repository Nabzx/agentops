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
    """The interface every integration implements. See ADR-0006 and ADR-0018."""

    is_idempotent: bool

    async def check_completed(
        self, action: dict[str, Any], idempotency_key: str
    ) -> Effect | None:
        """Has this idempotency key already produced a real Effect?

        Called before ``revalidate()`` **only when a prior attempt for this job
        already exists** (a worker checks this via ``OutboxStore.list_attempts`` -
        never on a genuine first attempt. For an Adapter whose only honest answer
        means safely re-issuing the real call (Stripe, for one - see ADR-0018),
        asking on a first attempt would perform the action before ``revalidate()``
        ever ran, bypassing the one check that exists to stop a stale or invalid
        proposal from executing at all.

        A non-idempotent Adapter must always return ``None``: it structurally cannot
        answer this honestly, which is exactly why ADR-0005 routes it to
        ``NEEDS_MANUAL_RECONCILIATION`` instead of guessing. An idempotent Adapter
        answers as cheaply as it honestly can - sometimes a real, separate lookup,
        sometimes (Stripe, for one) nothing cheaper than safely re-issuing the same
        idempotent call ``execute()`` would make anyway. See ADR-0018 for why this
        exists: without it, ``revalidate()`` can't tell "the world moved on, this is
        stale" apart from "this already succeeded, a crash just cost us recording it"
        - both look identical from a real-world state check alone.
        """
        ...

    async def revalidate(self, action: dict[str, Any]) -> bool:
        """Re-check the action is still valid immediately before executing it.

        Runs on every attempt, not just the first - but only once ``check_completed``
        has already run (on a retry) and said ``None``, so this is never asked to
        judge a case it can't answer correctly. A ``False`` here is treated as a
        ``PermanentEffectError`` by the caller: the world moved on, retrying won't
        help. A trivial Adapter may always return ``True``; a production one must not.
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

    async def check_completed(
        self, action: dict[str, Any], idempotency_key: str
    ) -> Effect | None:
        return None  # execute() is trivially safe to call again - nothing to save

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
