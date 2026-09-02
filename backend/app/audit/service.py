"""Audit service: record consequential events in the caller's transaction (S7).

Callers pass their own ``AsyncSession`` so the audit row commits *with* the event it
describes: there is never a consequential action without its audit record, and a
rollback drops both. The correlation id defaults to the observability context.

Depends on ``ephor.audit.AuditStore`` (not the concrete ``AuditRepository``) since
#32 - the actual Postgres/hash-chain logic is unchanged, only the declared type moved
to the shared interface.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from ephor.audit import AuditEntry, AuditStore
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.enums import AuditEventType
from app.audit.repository import AuditRepository
from app.audit.store import PostgresAuditStore
from app.core.context import current


class AuditService:
    def __init__(self, session: AsyncSession) -> None:
        self._store: AuditStore = PostgresAuditStore(AuditRepository(session))

    async def record(
        self,
        event_type: AuditEventType,
        *,
        occurred_at: datetime,
        subject_type: str,
        subject_id: uuid.UUID | None = None,
        actor_user_id: uuid.UUID | None = None,
        actor_role: str = "system",
        summary: str = "",
        metadata: dict[str, object] | None = None,
        correlation_id: str | None = None,
    ) -> AuditEntry:
        return await self._store.append(
            event_type=event_type.value,
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            subject_type=subject_type,
            subject_id=subject_id,
            correlation_id=correlation_id or current().correlation_id,
            summary=summary,
            metadata=metadata or {},
            occurred_at=occurred_at,
        )
