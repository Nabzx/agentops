"""FakeCritic is the only Critic any test in this repo talks to - the real
implementation (``cloud_waste.critic.ClaudeCritic``) deliberately lives outside
``ephor`` (ADR-0023) and is tested there, structurally only, never with a live call.
"""

from __future__ import annotations

from ephor.critic import Critique, FakeCritic


async def test_fake_critic_always_returns_its_canned_response() -> None:
    critic = FakeCritic()
    first = await critic.critique({"public_ip": "203.0.113.1"})
    second = await critic.critique({"public_ip": "203.0.113.99"})
    assert first == second
    assert first.recommendation == "proceed"
    assert first.model == "fake"


async def test_fake_critic_can_be_given_a_specific_response() -> None:
    canned = Critique(
        concerns=["this address was seen active 2 days ago"],
        recommendation="hesitate",
        reasoning="recently active addresses may still be needed",
        model="fake",
    )
    critic = FakeCritic(canned)
    result = await critic.critique({"public_ip": "203.0.113.1"})
    assert result == canned


def test_critique_as_snapshot_field_is_json_safe_plain_dict() -> None:
    critique = Critique(
        concerns=["a", "b"],
        recommendation="hesitate",
        reasoning="because",
        model="fake",
    )
    field = critique.as_snapshot_field()
    assert field == {
        "concerns": ["a", "b"],
        "recommendation": "hesitate",
        "reasoning": "because",
        "model": "fake",
    }
