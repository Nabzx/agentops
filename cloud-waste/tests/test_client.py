from datetime import UTC, datetime

import pytest

from cloud_waste.client import (
    AddressNotFoundError,
    ElasticIp,
    FakeCloudClient,
    Instance,
    InstanceNotFoundError,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _address(**overrides: object) -> ElasticIp:
    defaults: dict[str, object] = {
        "id": "eipalloc-1",
        "public_ip": "203.0.113.1",
        "association_id": None,
        "instance_id": None,
    }
    defaults.update(overrides)
    return ElasticIp(**defaults)  # type: ignore[arg-type]


def _instance(**overrides: object) -> Instance:
    defaults: dict[str, object] = {
        "id": "i-1",
        "state": "running",
        "launch_time": NOW,
        "tags": {},
        "avg_cpu_percent": 1.0,
        "avg_network_bytes": 1_000.0,
    }
    defaults.update(overrides)
    return Instance(**defaults)  # type: ignore[arg-type]


async def test_list_addresses_returns_everything_seeded() -> None:
    client = FakeCloudClient([_address(id="a"), _address(id="b")])
    addresses = await client.list_addresses()
    assert {a.id for a in addresses} == {"a", "b"}


async def test_release_address_removes_it_from_the_account() -> None:
    client = FakeCloudClient([_address()])
    released = await client.release_address("eipalloc-1", idempotency_key="k1")
    assert released.id == "eipalloc-1"
    assert await client.list_addresses() == []


async def test_release_address_dedups_on_idempotency_key() -> None:
    client = FakeCloudClient([_address()])
    first = await client.release_address("eipalloc-1", idempotency_key="k1")
    second = await client.release_address("eipalloc-1", idempotency_key="k1")
    assert first == second


async def test_release_address_raises_for_an_unknown_id() -> None:
    client = FakeCloudClient()
    with pytest.raises(AddressNotFoundError):
        await client.release_address("nonexistent", idempotency_key="k1")


async def test_get_released_is_none_before_any_release() -> None:
    client = FakeCloudClient([_address()])
    assert await client.get_released("eipalloc-1", idempotency_key="k1") is None


async def test_get_released_returns_the_result_after_release() -> None:
    client = FakeCloudClient([_address()])
    released = await client.release_address("eipalloc-1", idempotency_key="k1")
    result = await client.get_released("eipalloc-1", idempotency_key="k1")
    assert result == released


async def test_two_distinct_keys_release_two_distinct_addresses_independently() -> None:
    client = FakeCloudClient([_address(id="a"), _address(id="b")])
    released_a = await client.release_address("a", idempotency_key="key-a")
    released_b = await client.release_address("b", idempotency_key="key-b")
    assert released_a.id == "a"
    assert released_b.id == "b"


# --- instances -----------------------------------------------------------------------


async def test_list_instances_returns_everything_seeded() -> None:
    client = FakeCloudClient()
    client.seed_instance(_instance(id="a"))
    client.seed_instance(_instance(id="b"))
    instances = await client.list_instances()
    assert {i.id for i in instances} == {"a", "b"}


async def test_stop_instance_transitions_it_to_stopped() -> None:
    client = FakeCloudClient()
    client.seed_instance(_instance())
    stopped = await client.stop_instance("i-1", idempotency_key="k1")
    assert stopped.state == "stopped"
    [current] = await client.list_instances()
    assert current.state == "stopped"


async def test_stop_instance_on_an_already_stopped_instance_is_a_safe_no_op() -> None:
    """No dedup ledger needed at all - the resource's own state is the guarantee
    (ADR-0022) - a different idempotency key each time changes nothing.
    """
    client = FakeCloudClient()
    client.seed_instance(_instance())
    first = await client.stop_instance("i-1", idempotency_key="key-a")
    second = await client.stop_instance("i-1", idempotency_key="key-b")
    assert first.state == second.state == "stopped"


async def test_stop_instance_raises_for_an_unknown_id() -> None:
    client = FakeCloudClient()
    with pytest.raises(InstanceNotFoundError):
        await client.stop_instance("nonexistent", idempotency_key="k1")


async def test_get_stopped_is_none_for_a_running_instance() -> None:
    client = FakeCloudClient()
    client.seed_instance(_instance())
    assert await client.get_stopped("i-1", idempotency_key="k1") is None


async def test_get_stopped_returns_the_instance_once_stopped() -> None:
    """A state fact, not a per-key record - even a key that never triggered the stop
    sees the same answer (ADR-0022).
    """
    client = FakeCloudClient()
    client.seed_instance(_instance())
    await client.stop_instance("i-1", idempotency_key="the-real-key")
    result = await client.get_stopped("i-1", idempotency_key="a-totally-different-key")
    assert result is not None
    assert result.state == "stopped"
