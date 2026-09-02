"""Adapts AuditRepository to satisfy ephor.audit.AuditStore for real (ADR-0007, #32).

AuditRepository's own hash-chain/SQL logic is unchanged; this only translates each
returned AuditEvent (the SQLAlchemy ORM row) into a plain dataclass whose attributes
match ephor.audit.AuditEntry's structural shape. The one field that actually differs
is metadata_json -> metadata - AuditEvent can't be renamed to match directly, because
`metadata` is a reserved attribute on every SQLAlchemy declarative model (see ADR-0007).
"""

from __future__ import annotations

import dataclasses
import uuid
from dataclasses import dataclass
from datetime import datetime

from ephor.audit import AuditEntry, ChainVerification

from app.audit.repository import AuditRepository
from app.models.audit import AuditEvent


@dataclass(frozen=True)
class _Entry:
    """A concrete ``AuditEntry`` - what ``PostgresAuditStore`` actually returns."""

    id: uuid.UUID
    sequence: int
    event_type: str
    actor_role: str
    subject_type: str
    correlation_id: str
    summary: str
    previous_hash: str
    entry_hash: str
    occurred_at: datetime
    actor_user_id: uuid.UUID | None = None
    subject_id: uuid.UUID | None = None
    metadata: dict[str, object] = dataclasses.field(default_factory=dict)


def _translate(row: AuditEvent) -> AuditEntry:
    return _Entry(
        id=row.id,
        sequence=row.sequence,
        event_type=row.event_type,
        actor_role=row.actor_role,
        subject_type=row.subject_type,
        correlation_id=row.correlation_id,
        summary=row.summary,
        previous_hash=row.previous_hash,
        entry_hash=row.entry_hash,
        occurred_at=row.occurred_at,
        actor_user_id=row.actor_user_id,
        subject_id=row.subject_id,
        metadata=row.metadata_json,
    )


class PostgresAuditStore:
    """Wraps ``AuditRepository`` to implement ``ephor.audit.AuditStore`` for real."""

    def __init__(self, repo: AuditRepository) -> None:
        self._repo = repo

    async def append(
        self,
        *,
        event_type: str,
        actor_role: str,
        subject_type: str,
        correlation_id: str,
        summary: str,
        occurred_at: datetime,
        actor_user_id: uuid.UUID | None = None,
        subject_id: uuid.UUID | None = None,
        metadata: dict[str, object] | None = None,
    ) -> AuditEntry:
        row = await self._repo.append(
            event_type=event_type,
            actor_role=actor_role,
            subject_type=subject_type,
            correlation_id=correlation_id,
            summary=summary,
            occurred_at=occurred_at,
            actor_user_id=actor_user_id,
            subject_id=subject_id,
            metadata=metadata,
        )
        return _translate(row)

    async def get(self, entry_id: uuid.UUID) -> AuditEntry | None:
        row = await self._repo.get(entry_id)
        return _translate(row) if row is not None else None

    async def list_events(
        self,
        *,
        event_type: str | None = None,
        correlation_id: str | None = None,
        subject_id: uuid.UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AuditEntry]:
        rows = await self._repo.list_events(
            event_type=event_type,
            correlation_id=correlation_id,
            subject_id=subject_id,
            limit=limit,
            offset=offset,
        )
        return [_translate(r) for r in rows]

    async def list_for_correlation(self, correlation_id: str) -> list[AuditEntry]:
        rows = await self._repo.list_for_correlation(correlation_id)
        return [_translate(r) for r in rows]

    async def verify_chain(self) -> ChainVerification:
        result = await self._repo.verify_chain()
        return ChainVerification(
            ok=result.ok,
            checked=result.checked,
            broken_sequence=result.broken_sequence,
            reason=result.reason,
        )
