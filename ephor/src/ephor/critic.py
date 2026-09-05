"""The Critic seam: an LLM's second opinion on a proposal, per ADR-0021, generalised
to every detector by ADR-0023.

A Critic never touches what gets proposed, only whether a human should hesitate over
it - it is always advisory, and can never auto-approve or auto-reject anything
(ADR-0021 point 3; the same "human is always the actual gate" rule every approval
already holds, per ADR-0009). Its output is stored verbatim in a detector's Snapshot
(``Critique.as_snapshot_field()``), so it's part of the same hashed, tamper-evident
record as the proposal itself - no change needed to ``ephor.approvals``/
``ephor.actions``/``ephor.effects`` (ADR-0021 point 2).

``FakeCritic`` is the only Critic any test, demo, or CI job in this repo talks to.
The one real implementation, ``ClaudeCritic``, deliberately lives outside this
module (in ``cloud_waste.critic``, the one package ADR-0021 scoped a real, paid Critic
to) so that ``ephor`` itself never gains a paid-vendor SDK as a dependency - this
module needs nothing beyond stdlib/dataclasses/typing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

Recommendation = Literal["proceed", "hesitate"]


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
    """The interface a detector talks to. A real implementation wraps a real LLM
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
