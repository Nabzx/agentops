"""Audit entry, Audit chain - see CONTEXT.md "The record".

An append-only, hash-chained record of consequential and security-relevant events.
``AuditStore`` is the interface (ADR-0007); any backing store - Postgres, SQLite, an
in-memory dict - implements it structurally, without inheriting from anything here.
``AuditEntry`` is likewise a structural shape, not a concrete class: an ORM row and a
plain dataclass can both satisfy it, as long as they carry the same fields.
``InMemoryAuditStore`` is the zero-setup implementation this package ships with.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

GENESIS_HASH = "0" * 64

# Fields (in order) covered by the entry hash. Volatile/derived fields (id, entry_hash
# itself) are excluded.
_HASHED_FIELDS = (
    "sequence",
    "event_type",
    "actor_user_id",
    "actor_role",
    "subject_type",
    "subject_id",
    "correlation_id",
    "summary",
    "metadata",
    "previous_hash",
    "occurred_at",
)


def canonical_payload(fields: dict[str, Any]) -> str:
    ordered = {key: fields.get(key) for key in _HASHED_FIELDS}
    return json.dumps(ordered, sort_keys=True, ensure_ascii=True, default=str)


def compute_entry_hash(fields: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_payload(fields).encode("utf-8")).hexdigest()


class AuditEntry(Protocol):
    """The read shape of one immutable, hash-chained audit-log entry.

    Structural, not a base class: a plain (frozen) dataclass (see ``InMemoryEntry``) and
    a mutable SQLAlchemy ORM row can both satisfy this without either knowing about the
    other. Declared as read-only properties, not plain attributes, so a *frozen*
    dataclass - which only offers read access - still structurally matches; a settable
    ORM attribute satisfies a read-only requirement too.
    """

    @property
    def id(self) -> uuid.UUID: ...
    @property
    def sequence(self) -> int: ...
    @property
    def event_type(self) -> str: ...
    @property
    def actor_role(self) -> str: ...
    @property
    def subject_type(self) -> str: ...
    @property
    def correlation_id(self) -> str: ...
    @property
    def summary(self) -> str: ...
    @property
    def previous_hash(self) -> str: ...
    @property
    def entry_hash(self) -> str: ...
    @property
    def occurred_at(self) -> datetime: ...
    @property
    def actor_user_id(self) -> uuid.UUID | None: ...
    @property
    def subject_id(self) -> uuid.UUID | None: ...
    @property
    def metadata(self) -> dict[str, object]: ...


def entry_hash_fields(entry: AuditEntry) -> dict[str, Any]:
    """The fields (and order) covered by ``entry``'s hash, from any conforming entry."""
    return {
        "sequence": entry.sequence,
        "event_type": entry.event_type,
        "actor_user_id": str(entry.actor_user_id) if entry.actor_user_id else None,
        "actor_role": entry.actor_role,
        "subject_type": entry.subject_type,
        "subject_id": str(entry.subject_id) if entry.subject_id else None,
        "correlation_id": entry.correlation_id,
        "summary": entry.summary,
        "metadata": entry.metadata,
        "previous_hash": entry.previous_hash,
        "occurred_at": entry.occurred_at.isoformat(),
    }


def recompute_entry_hash(entry: AuditEntry) -> str:
    return compute_entry_hash(entry_hash_fields(entry))


@dataclass(frozen=True)
class ChainVerification:
    ok: bool
    checked: int
    broken_sequence: int | None = None
    reason: str | None = None


class AuditStore(Protocol):
    """The append-only persistence interface every backing store implements.

    See ADR-0007.
    """

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
        """Append one entry, chained to the tail, in the caller's transaction."""
        ...

    async def get(self, entry_id: uuid.UUID) -> AuditEntry | None: ...

    async def list_events(
        self,
        *,
        event_type: str | None = None,
        correlation_id: str | None = None,
        subject_id: uuid.UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AuditEntry]: ...

    async def list_for_correlation(self, correlation_id: str) -> list[AuditEntry]: ...

    async def verify_chain(self) -> ChainVerification:
        """Walk the whole chain in order, recomputing each hash."""
        ...


@dataclass(frozen=True)
class InMemoryEntry:
    """A plain, concrete ``AuditEntry`` - the shape ``InMemoryAuditStore`` returns."""

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
    metadata: dict[str, object] = field(default_factory=dict)


class InMemoryAuditStore:
    """A process-local, in-memory ``AuditStore`` - the zero-setup implementation this
    package ships with. Not durable across restarts; use a real backing store (e.g. a
    Postgres-backed implementation) for anything that needs to survive one.
    """

    def __init__(self) -> None:
        self._entries: list[InMemoryEntry] = []

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
        tail = self._entries[-1] if self._entries else None
        sequence = (tail.sequence + 1) if tail is not None else 1
        previous_hash = tail.entry_hash if tail is not None else GENESIS_HASH

        unhashed = InMemoryEntry(
            id=uuid.uuid4(),
            sequence=sequence,
            event_type=event_type,
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            subject_type=subject_type,
            subject_id=subject_id,
            correlation_id=correlation_id,
            summary=summary,
            metadata=metadata or {},
            previous_hash=previous_hash,
            entry_hash="",
            occurred_at=occurred_at,
        )
        entry = dataclasses.replace(unhashed, entry_hash=recompute_entry_hash(unhashed))
        self._entries.append(entry)
        return entry

    async def get(self, entry_id: uuid.UUID) -> AuditEntry | None:
        return next((e for e in self._entries if e.id == entry_id), None)

    async def list_events(
        self,
        *,
        event_type: str | None = None,
        correlation_id: str | None = None,
        subject_id: uuid.UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AuditEntry]:
        rows: list[InMemoryEntry] = self._entries
        if event_type is not None:
            rows = [e for e in rows if e.event_type == event_type]
        if correlation_id is not None:
            rows = [e for e in rows if e.correlation_id == correlation_id]
        if subject_id is not None:
            rows = [e for e in rows if e.subject_id == subject_id]
        ordered = sorted(rows, key=lambda e: e.sequence, reverse=True)
        return list(ordered[offset : offset + limit])

    async def list_for_correlation(self, correlation_id: str) -> list[AuditEntry]:
        rows = [e for e in self._entries if e.correlation_id == correlation_id]
        return sorted(rows, key=lambda e: e.sequence)

    async def verify_chain(self) -> ChainVerification:
        previous = GENESIS_HASH
        expected_seq = 1
        for entry in sorted(self._entries, key=lambda e: e.sequence):
            if entry.sequence != expected_seq:
                return ChainVerification(
                    False, expected_seq - 1, entry.sequence, "sequence gap"
                )
            if entry.previous_hash != previous:
                return ChainVerification(
                    False, expected_seq - 1, entry.sequence, "previous-hash mismatch"
                )
            if recompute_entry_hash(entry) != entry.entry_hash:
                return ChainVerification(
                    False, expected_seq - 1, entry.sequence, "entry-hash mismatch"
                )
            previous = entry.entry_hash
            expected_seq += 1
        return ChainVerification(True, len(self._entries))
