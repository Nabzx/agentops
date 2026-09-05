from datetime import UTC, datetime

import pytest
from ephor.effects import PermanentEffectError, RetryableEffectError

from cloud_waste.adapter import CloudWasteAdapter, IdleInstanceAdapter
from cloud_waste.client import (
    ElasticIp,
    FakeCloudClient,
    Instance,
    LiveActionsDisabledError,
    TransientCloudError,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


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


def _instance_client(
    state: str = "running",
    avg_cpu_percent: float = 1.0,
    avg_network_bytes: float = 1_000.0,
) -> FakeCloudClient:
    client = FakeCloudClient()
    client.seed_instance(
        Instance(
            id="i-1",
            state=state,
            launch_time=NOW,
            tags={},
            avg_cpu_percent=avg_cpu_percent,
            avg_network_bytes=avg_network_bytes,
        )
    )
    return client


def _instance_action(instance_id: str = "i-1") -> dict[str, str]:
    return {"instance_id": instance_id}


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


# --- IdleInstanceAdapter ---------------------------------------------------------


async def test_idle_check_completed_is_none_before_any_execution() -> None:
    adapter = IdleInstanceAdapter(_instance_client())
    assert await adapter.check_completed(_instance_action(), "key-1") is None


async def test_idle_check_completed_returns_the_effect_after_execution() -> None:
    client = _instance_client()
    adapter = IdleInstanceAdapter(client)
    first = await adapter.execute(_instance_action(), "key-1")
    completed = await adapter.check_completed(_instance_action(), "different-key")
    assert completed is not None
    assert completed.effect_id == first.effect_id


async def test_idle_revalidate_true_for_a_still_idle_instance() -> None:
    adapter = IdleInstanceAdapter(_instance_client())
    assert await adapter.revalidate(_instance_action()) is True


async def test_idle_revalidate_false_for_a_busy_instance() -> None:
    adapter = IdleInstanceAdapter(_instance_client(avg_cpu_percent=90.0))
    assert await adapter.revalidate(_instance_action()) is False


async def test_idle_revalidate_false_for_an_already_stopped_instance() -> None:
    adapter = IdleInstanceAdapter(_instance_client(state="stopped"))
    assert await adapter.revalidate(_instance_action()) is False


async def test_idle_revalidate_false_for_an_unknown_instance() -> None:
    adapter = IdleInstanceAdapter(FakeCloudClient())
    assert await adapter.revalidate(_instance_action("does_not_exist")) is False


async def test_idle_execute_returns_an_effect_on_success() -> None:
    adapter = IdleInstanceAdapter(_instance_client())
    effect = await adapter.execute(_instance_action(), "key-1")
    assert effect.effect_id == "i-1"
    assert effect.raw["stopped_instance_id"] == "i-1"


async def test_idle_execute_is_idempotent_across_repeated_calls() -> None:
    client = _instance_client()
    adapter = IdleInstanceAdapter(client)
    first = await adapter.execute(_instance_action(), "key-1")
    second = await adapter.execute(_instance_action(), "key-2")
    assert first.effect_id == second.effect_id == "i-1"


async def test_idle_execute_raises_permanent_error_for_an_unknown_instance() -> None:
    adapter = IdleInstanceAdapter(FakeCloudClient())
    with pytest.raises(PermanentEffectError):
        await adapter.execute(_instance_action("does_not_exist"), "key-1")


def test_idle_instance_adapter_declares_itself_idempotent() -> None:
    assert IdleInstanceAdapter.is_idempotent is True


# --- classifying AwsCloudClient's real-only exceptions (ADR-0024) ---------------------
#
# FakeCloudClient never raises either of these - only AwsCloudClient does, and nothing
# in this repo ever runs that with real credentials (ADR-0024 grilled item 3). Tested
# here with a minimal stub so the classification logic itself is proven regardless.


class _LiveDisabledClient(FakeCloudClient):
    async def release_address(
        self, allocation_id: str, *, idempotency_key: str
    ) -> ElasticIp:
        raise LiveActionsDisabledError("would have succeeded, allow_live=False")

    async def stop_instance(
        self, instance_id: str, *, idempotency_key: str
    ) -> Instance:
        raise LiveActionsDisabledError("would have succeeded, allow_live=False")


class _TransientErrorClient(FakeCloudClient):
    async def release_address(
        self, allocation_id: str, *, idempotency_key: str
    ) -> ElasticIp:
        raise TransientCloudError("throttled")

    async def stop_instance(
        self, instance_id: str, *, idempotency_key: str
    ) -> Instance:
        raise TransientCloudError("throttled")


async def test_execute_raises_permanent_error_when_live_actions_are_disabled() -> None:
    adapter = CloudWasteAdapter(_LiveDisabledClient())
    with pytest.raises(PermanentEffectError):
        await adapter.execute(_action(), "key-1")


async def test_execute_raises_retryable_error_for_a_transient_cloud_failure() -> None:
    adapter = CloudWasteAdapter(_TransientErrorClient())
    with pytest.raises(RetryableEffectError):
        await adapter.execute(_action(), "key-1")


async def test_idle_execute_raises_permanent_error_when_live_actions_are_disabled() -> (
    None
):
    adapter = IdleInstanceAdapter(_LiveDisabledClient())
    with pytest.raises(PermanentEffectError):
        await adapter.execute(_instance_action(), "key-1")


async def test_idle_execute_raises_retryable_error_for_a_transient_cloud_failure() -> (
    None
):
    adapter = IdleInstanceAdapter(_TransientErrorClient())
    with pytest.raises(RetryableEffectError):
        await adapter.execute(_instance_action(), "key-1")
