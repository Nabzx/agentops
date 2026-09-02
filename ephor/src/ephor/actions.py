"""Action, Proposal - see CONTEXT.md "The action loop" and ADR-0012.

A Proposal is an immutable record of what a detector put forward - it carries no status
of its own. Once an ``ApprovalRequest`` references it by ``proposal_id``
(ephor.approvals, ADR-0008), the Approval's status is the single source of truth for
where things stand; duplicating that onto the Proposal would just be two places that
could disagree.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


class Proposal(Protocol):
    """The read shape of one Proposal - an Action put forward, not yet decided."""

    @property
    def id(self) -> uuid.UUID: ...
    @property
    def action_type(self) -> str: ...
    @property
    def parameters(self) -> dict[str, object]: ...
    @property
    def risk_level(self) -> str: ...
    @property
    def evidence(self) -> dict[str, object]: ...
    @property
    def created_at(self) -> datetime: ...


class ProposalStore(Protocol):
    """The persistence interface any backing store implements. See ADR-0012."""

    async def create(
        self,
        *,
        action_type: str,
        parameters: dict[str, object],
        risk_level: str,
        evidence: dict[str, object],
        created_at: datetime,
    ) -> Proposal: ...

    async def get(self, proposal_id: uuid.UUID) -> Proposal | None: ...

    async def list_by_action_type(self, action_type: str) -> list[Proposal]: ...


@dataclass(frozen=True)
class InMemoryProposal:
    """A concrete ``Proposal`` - the shape ``InMemoryProposalStore`` returns."""

    id: uuid.UUID
    action_type: str
    parameters: dict[str, object]
    risk_level: str
    evidence: dict[str, object]
    created_at: datetime


class InMemoryProposalStore:
    """A process-local, in-memory ``ProposalStore``. Not durable across restarts."""

    def __init__(self) -> None:
        self._proposals: dict[uuid.UUID, InMemoryProposal] = {}

    async def create(
        self,
        *,
        action_type: str,
        parameters: dict[str, object],
        risk_level: str,
        evidence: dict[str, object],
        created_at: datetime,
    ) -> Proposal:
        proposal = InMemoryProposal(
            id=uuid.uuid4(),
            action_type=action_type,
            parameters=parameters,
            risk_level=risk_level,
            evidence=evidence,
            created_at=created_at,
        )
        self._proposals[proposal.id] = proposal
        return proposal

    async def get(self, proposal_id: uuid.UUID) -> Proposal | None:
        return self._proposals.get(proposal_id)

    async def list_by_action_type(self, action_type: str) -> list[Proposal]:
        rows = [p for p in self._proposals.values() if p.action_type == action_type]
        return sorted(rows, key=lambda p: p.created_at)


__all__ = [
    "InMemoryProposal",
    "InMemoryProposalStore",
    "Proposal",
    "ProposalStore",
]
