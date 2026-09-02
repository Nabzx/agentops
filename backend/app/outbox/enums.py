"""Outbox job status enum (S6).

Defined in ``ephor.outbox`` (the extracted core, see ADR-0010) and re-exported here so
every existing import site in this app keeps working unchanged - only the definition's
home moved. ``ephor.outbox.OutboxStatus`` also has a ``needs_manual_reconciliation``
member (ADR-0005) that no AgentOps code path produces today - every handler here is
fully in-process/simulated, so the crash-recovery gap that state exists for can't occur
yet. It exists in the shared enum for when a real Adapter (Stripe) does.
"""

from __future__ import annotations

from ephor.outbox import CLAIMABLE_STATUSES, UNCLAIMABLE_STATUSES, OutboxStatus

__all__ = ["CLAIMABLE_STATUSES", "UNCLAIMABLE_STATUSES", "OutboxStatus"]
