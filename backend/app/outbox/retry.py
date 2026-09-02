"""Bounded exponential backoff with deterministic jitter for outbox retries (S6).

Defined in ``ephor.outbox`` (the extracted core, see ADR-0010) and re-exported here so
every existing import site in this app keeps working unchanged - only the definition's
home moved.
"""

from __future__ import annotations

from ephor.outbox import compute_backoff_seconds, next_attempt_at

__all__ = ["compute_backoff_seconds", "next_attempt_at"]
