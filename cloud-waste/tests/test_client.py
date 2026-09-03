import pytest

from cloud_waste.client import AddressNotFoundError, ElasticIp, FakeCloudClient


def _address(**overrides: object) -> ElasticIp:
    defaults: dict[str, object] = {
        "id": "eipalloc-1",
        "public_ip": "203.0.113.1",
        "association_id": None,
        "instance_id": None,
    }
    defaults.update(overrides)
    return ElasticIp(**defaults)  # type: ignore[arg-type]


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
