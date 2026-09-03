import pytest
from ephor.effects import PermanentEffectError

from cloud_waste.adapter import CloudWasteAdapter
from cloud_waste.client import ElasticIp, FakeCloudClient


def _client(
    association_id: str | None = None, instance_id: str | None = None
) -> FakeCloudClient:
    return FakeCloudClient(
        [
            ElasticIp(
                id="eipalloc-1",
                public_ip="203.0.113.1",
                association_id=association_id,
                instance_id=instance_id,
            )
        ]
    )


def _action(allocation_id: str = "eipalloc-1") -> dict[str, str]:
    return {"allocation_id": allocation_id}


async def test_check_completed_is_none_before_any_execution() -> None:
    adapter = CloudWasteAdapter(_client())
    assert await adapter.check_completed(_action(), "key-1") is None


async def test_check_completed_returns_the_effect_after_execution() -> None:
    client = _client()
    adapter = CloudWasteAdapter(client)
    first = await adapter.execute(_action(), "key-1")
    completed = await adapter.check_completed(_action(), "key-1")
    assert completed is not None
    assert completed.effect_id == first.effect_id
    assert completed.raw == first.raw


async def test_revalidate_true_for_a_still_unassociated_address() -> None:
    adapter = CloudWasteAdapter(_client())
    assert await adapter.revalidate(_action()) is True


async def test_revalidate_false_for_an_address_already_released() -> None:
    client = _client()
    await client.release_address("eipalloc-1", idempotency_key="other-key")
    adapter = CloudWasteAdapter(client)
    assert await adapter.revalidate(_action()) is False


async def test_revalidate_false_for_an_address_now_associated() -> None:
    adapter = CloudWasteAdapter(
        _client(association_id="eipassoc-1", instance_id="i-123")
    )
    assert await adapter.revalidate(_action()) is False


async def test_revalidate_false_for_an_unknown_address() -> None:
    adapter = CloudWasteAdapter(FakeCloudClient())
    assert await adapter.revalidate(_action("does_not_exist")) is False


async def test_execute_returns_an_effect_on_success() -> None:
    adapter = CloudWasteAdapter(_client())
    effect = await adapter.execute(_action(), "key-1")
    assert effect.effect_id == "eipalloc-1"
    assert effect.raw["released_public_ip"] == "203.0.113.1"


async def test_execute_is_idempotent_across_repeated_calls() -> None:
    """occurred_at legitimately differs per call; what proves idempotency is that the
    real-world outcome (effect_id, raw) never changes.
    """
    client = _client()
    adapter = CloudWasteAdapter(client)
    first = await adapter.execute(_action(), "key-1")
    second = await adapter.execute(_action(), "key-1")
    assert first.effect_id == second.effect_id
    assert first.raw == second.raw


async def test_execute_raises_permanent_error_for_an_unknown_address() -> None:
    adapter = CloudWasteAdapter(FakeCloudClient())
    with pytest.raises(PermanentEffectError):
        await adapter.execute(_action("does_not_exist"), "key-1")


def test_cloud_waste_adapter_declares_itself_idempotent() -> None:
    assert CloudWasteAdapter.is_idempotent is True
