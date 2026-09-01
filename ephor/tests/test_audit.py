import dataclasses
import uuid
from datetime import UTC, datetime

from ephor.audit import GENESIS_HASH, ChainVerification, InMemoryAuditStore

NOW = datetime(2026, 1, 1, tzinfo=UTC)


async def _seeded_store(n: int = 3) -> InMemoryAuditStore:
    store = InMemoryAuditStore()
    for i in range(n):
        await store.append(
            event_type=f"event_{i}",
            actor_role="agent",
            subject_type="test_subject",
            correlation_id="corr-1",
            summary=f"entry {i}",
            occurred_at=NOW,
        )
    return store


async def test_first_entry_chains_from_genesis() -> None:
    store = InMemoryAuditStore()
    entry = await store.append(
        event_type="first",
        actor_role="agent",
        subject_type="test_subject",
        correlation_id="corr-1",
        summary="the first entry",
        occurred_at=NOW,
    )
    assert entry.sequence == 1
    assert entry.previous_hash == GENESIS_HASH
    assert entry.entry_hash != GENESIS_HASH


async def test_each_entry_chains_to_its_predecessor() -> None:
    store = await _seeded_store(3)
    entries = await store.list_for_correlation("corr-1")
    assert [e.sequence for e in entries] == [1, 2, 3]
    assert entries[1].previous_hash == entries[0].entry_hash
    assert entries[2].previous_hash == entries[1].entry_hash


async def test_hash_is_deterministic_given_the_same_fields() -> None:
    async def _append(store: InMemoryAuditStore) -> str:
        entry = await store.append(
            event_type="same_event",
            actor_role="agent",
            subject_type="test_subject",
            correlation_id="corr-1",
            summary="identical entry",
            occurred_at=NOW,
        )
        return entry.entry_hash

    assert await _append(InMemoryAuditStore()) == await _append(InMemoryAuditStore())


async def test_verify_chain_passes_on_an_untouched_chain() -> None:
    store = await _seeded_store(5)
    result = await store.verify_chain()
    assert result == ChainVerification(True, 5)


async def test_verify_chain_detects_a_tampered_summary() -> None:
    store = await _seeded_store(3)
    tampered = dataclasses.replace(store._entries[1], summary="a different summary")
    store._entries[1] = tampered

    result = await store.verify_chain()
    assert not result.ok
    assert result.reason == "entry-hash mismatch"
    assert result.broken_sequence == tampered.sequence


async def test_verify_chain_detects_a_deleted_entry() -> None:
    store = await _seeded_store(3)
    del store._entries[1]

    result = await store.verify_chain()
    assert not result.ok
    assert result.reason == "sequence gap"


async def test_list_events_filters_by_event_type_and_subject() -> None:
    store = InMemoryAuditStore()
    await store.append(
        event_type="a",
        actor_role="agent",
        subject_type="ticket",
        subject_id=None,
        correlation_id="corr-a",
        summary="a",
        occurred_at=NOW,
    )
    await store.append(
        event_type="b",
        actor_role="agent",
        subject_type="ticket",
        correlation_id="corr-b",
        summary="b",
        occurred_at=NOW,
    )
    only_a = await store.list_events(event_type="a")
    assert [e.event_type for e in only_a] == ["a"]


async def test_list_events_is_most_recent_first_and_respects_limit() -> None:
    store = await _seeded_store(5)
    page = await store.list_events(correlation_id="corr-1", limit=2)
    assert [e.sequence for e in page] == [5, 4]


async def test_get_returns_none_for_an_unknown_id() -> None:
    store = InMemoryAuditStore()
    assert await store.get(uuid.uuid4()) is None
