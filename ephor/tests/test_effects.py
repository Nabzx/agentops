from ephor.effects import AdapterRegistry, MockAdapter, PermanentEffectError


async def test_mock_adapter_always_revalidates_true() -> None:
    adapter = MockAdapter()
    assert await adapter.revalidate({"kind": "test"}) is True


async def test_mock_adapter_execute_returns_an_effect_and_records_the_call() -> None:
    adapter = MockAdapter()
    effect = await adapter.execute({"kind": "test"}, "key-1")
    assert effect.effect_id == "mock_key-1"
    assert effect.raw == {"ok": True}
    assert adapter.calls == ["key-1"]


async def test_mock_adapter_is_idempotent() -> None:
    assert MockAdapter.is_idempotent is True


def test_registry_registers_and_looks_up_an_adapter_by_name() -> None:
    registry = AdapterRegistry()
    registry.register("mock", MockAdapter)
    assert registry.get("mock") is MockAdapter


def test_registry_returns_none_for_an_unknown_name() -> None:
    registry = AdapterRegistry()
    assert registry.get("nonexistent") is None


def test_permanent_effect_error_is_importable_and_raisable() -> None:
    try:
        raise PermanentEffectError("no handler for this action type")
    except PermanentEffectError as exc:
        assert "no handler" in str(exc)
