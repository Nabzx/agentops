"""The Critic seam: an LLM's second opinion on a proposal, per ADR-0021.

A Critic never touches what gets proposed, only whether a human should hesitate over
it - it is always advisory, and can never auto-approve or auto-reject anything
(ADR-0021 point 3; the same "human is always the actual gate" rule every approval
already holds, per ADR-0009). Its output is stored verbatim in the detector's
Snapshot (``Critique.as_snapshot_field()``), so it's part of the same hashed,
tamper-evident record as the proposal itself - no change needed to
``ephor.approvals``/``ephor.actions``/``ephor.effects`` (ADR-0021 point 2).

``FakeCritic`` is the only thing any test, demo, or CI job in this repo talks to.
``ClaudeCritic`` is built for real, using the real ``anthropic`` SDK, wired correctly
end to end - but it is never invoked with a real API key by anything in this repo,
and no test here ever makes a live call to it. Whether and when a real key ever gets
set is the maintainer's call, made separately (ADR-0021's explicit "build it, don't
spend on it" constraint).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import anthropic
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

Recommendation = Literal["proceed", "hesitate"]

# The tool a real Critic is forced to call, so its answer always parses - not a
# format the model might drift away from, a specific function call it must make.
_CRITIQUE_TOOL_NAME = "submit_critique"
_CRITIQUE_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "concerns": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Specific reasons to hesitate, if any. Empty if none.",
        },
        "recommendation": {"type": "string", "enum": ["proceed", "hesitate"]},
        "reasoning": {
            "type": "string",
            "description": "A brief explanation of the recommendation.",
        },
    },
    "required": ["concerns", "recommendation", "reasoning"],
}


@dataclass(frozen=True)
class Critique:
    """One Critic's second opinion on a proposal - always advisory, never a
    decision. ``model`` records which Critic produced it (``"fake"`` for
    ``FakeCritic``), for audit transparency.
    """

    concerns: list[str]
    recommendation: Recommendation
    reasoning: str
    model: str

    def as_snapshot_field(self) -> dict[str, object]:
        """The plain-dict shape this goes into ``snapshot_json`` as - ADR-0008's
        opaque Snapshot doesn't know or care what a Critique is, only that it's
        JSON-safe.
        """
        return {
            "concerns": self.concerns,
            "recommendation": self.recommendation,
            "reasoning": self.reasoning,
            "model": self.model,
        }


class Critic(Protocol):
    """The interface the detector talks to. A real implementation wraps a real LLM
    behind this same shape - vendor-agnostic, same pattern as ``ChainClient`` naming
    no specific chain.
    """

    async def critique(self, evidence: dict[str, object]) -> Critique: ...


class FakeCritic:
    """Deterministic, canned - no real reasoning at all. The only Critic any test,
    demo, or CI job in this repo talks to (ADR-0021).
    """

    def __init__(self, response: Critique | None = None) -> None:
        self._response = response or Critique(
            concerns=[],
            recommendation="proceed",
            reasoning=(
                "fake critic - no real reasoning, always returns this canned response"
            ),
            model="fake",
        )

    async def critique(self, evidence: dict[str, object]) -> Critique:
        return self._response


class ClaudeCriticSettings(BaseSettings):
    """Where a real API key comes from - env vars, same pattern as ADR-0003/0013.
    Never construct this with anything committed to the repo.
    """

    model_config = SettingsConfigDict(env_prefix="EPHOR_CRITIC_", extra="ignore")

    api_key: SecretStr
    # A small, cheap model - a short annotation task doesn't need a large one, and
    # keeping the per-call cost low was locked explicitly in ADR-0021's grilling.
    model: str = "claude-haiku-4-5-20251001"


class ClaudeCritic:
    """Wraps the real Anthropic API, per ADR-0021.

    Built for real - checked against the real SDK's actual types (``ToolParam``,
    ``ToolUseBlock``), not assumed - but never invoked with a real key by anything
    in this repo. Forces a tool call rather than relying on prose formatting, so a
    response always parses into a ``Critique``, never a best-effort text scrape.
    """

    _SYSTEM_PROMPT = (
        "You are a second reviewer for a proposed automated action. You do not "
        "decide anything - a human always makes the final call, regardless of your "
        "recommendation. Given the evidence for one proposal, list any specific "
        "concerns and recommend either 'proceed' or 'hesitate'. Be specific and "
        "brief - a human is about to read this alongside the evidence itself."
    )

    def __init__(self, settings: ClaudeCriticSettings) -> None:
        self._client = anthropic.AsyncAnthropic(
            api_key=settings.api_key.get_secret_value()
        )
        self._model = settings.model

    async def critique(self, evidence: dict[str, object]) -> Critique:
        message = await self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            system=self._SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Evidence for this proposal:\n"
                        f"{json.dumps(evidence, sort_keys=True, default=str)}"
                    ),
                }
            ],
            tools=[
                {
                    "name": _CRITIQUE_TOOL_NAME,
                    "description": "Submit your critique of the proposed action.",
                    "input_schema": _CRITIQUE_INPUT_SCHEMA,
                }
            ],
            tool_choice={"type": "tool", "name": _CRITIQUE_TOOL_NAME},
        )
        tool_use = next(block for block in message.content if block.type == "tool_use")
        # Narrowed explicitly, not cast - this is parsing an external LLM response,
        # not a value this code already knows the shape of.
        data = tool_use.input
        concerns = data.get("concerns")
        recommendation = data.get("recommendation")
        return Critique(
            concerns=[str(c) for c in concerns] if isinstance(concerns, list) else [],
            recommendation="hesitate" if recommendation == "hesitate" else "proceed",
            reasoning=str(data.get("reasoning", "")),
            model=self._model,
        )
