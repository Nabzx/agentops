"""ClaudeCritic is tested structurally only, against a monkeypatched SDK - never a
live call, per ADR-0021's explicit "build it, don't spend on it" constraint.
``Critique``/``Critic``/``FakeCritic`` moved to ``ephor.critic`` (ADR-0023) and are
covered there instead - ``ephor/tests/test_critic.py``.
"""

from __future__ import annotations

from typing import Any

from cloud_waste.critic import ClaudeCritic, ClaudeCriticSettings


class _FakeToolUseBlock:
    """Stands in for anthropic's real ToolUseBlock - just enough shape for
    ClaudeCritic to parse, without importing the SDK's own response types.
    """

    type = "tool_use"

    def __init__(self, input_data: dict[str, Any]) -> None:
        self.input = input_data


class _FakeMessage:
    def __init__(self, content: list[Any]) -> None:
        self.content = content


async def test_claude_critic_parses_a_well_formed_tool_use_response(
    monkeypatch: Any,
) -> None:
    critic = ClaudeCritic(
        ClaudeCriticSettings.model_validate({"api_key": "sk-ant-test-dummy"})
    )
    response = _FakeMessage(
        [
            _FakeToolUseBlock(
                {
                    "concerns": ["seen active recently"],
                    "recommendation": "hesitate",
                    "reasoning": "traffic in the last 48 hours",
                }
            )
        ]
    )

    async def fake_create(**_: Any) -> _FakeMessage:
        return response

    monkeypatch.setattr(critic._client.messages, "create", fake_create)

    result = await critic.critique({"public_ip": "203.0.113.1"})

    assert result.recommendation == "hesitate"
    assert result.concerns == ["seen active recently"]
    assert result.reasoning == "traffic in the last 48 hours"
    assert result.model == ClaudeCriticSettings.model_fields["model"].default


async def test_claude_critic_defaults_to_proceed_on_a_malformed_response(
    monkeypatch: Any,
) -> None:
    """A defensive parse, not a crash - an LLM response is never fully trusted."""
    critic = ClaudeCritic(
        ClaudeCriticSettings.model_validate({"api_key": "sk-ant-test-dummy"})
    )
    response = _FakeMessage([_FakeToolUseBlock({})])

    async def fake_create(**_: Any) -> _FakeMessage:
        return response

    monkeypatch.setattr(critic._client.messages, "create", fake_create)

    result = await critic.critique({"public_ip": "203.0.113.1"})

    assert result.recommendation == "proceed"
    assert result.concerns == []
