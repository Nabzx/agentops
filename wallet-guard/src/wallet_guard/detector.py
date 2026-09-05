"""The detector: scans a wallet's token approvals, flags the ones granting an
unlimited allowance, and emits a Proposal + ApprovalRequest for each.

Note on ``subject_id``: an approval's id here is an opaque, detector-defined string
(see ``client.py``), not a UUID, so it doesn't fit ``ApprovalRequest.subject_id:
uuid.UUID | None`` - exactly the same shape as ``stripe_recovery.detector``'s note on
Stripe charge ids. The approval id lives in the Snapshot instead, per ADR-0008.
``requested_amount_pence`` is left unset - there's no currency amount involved in
revoking an approval, and that field is optional precisely so a non-monetary action
like this one doesn't have to invent one.

An optional ``Critic`` (ADR-0021, extended to every detector by ADR-0023) adds a
second opinion to the Snapshot before it's hashed - ``FakeCritic`` by default, so
nothing here changes unless a caller opts in. The unlimited-allowance check is still
the entire condition for whether to propose at all; the Critic never gets a vote on
that, only on what a human sees alongside it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from ephor.actions import Proposal, ProposalStore
from ephor.approvals import ApprovalRequest, ApprovalStore
from ephor.critic import Critic

from wallet_guard.client import INFINITE_ALLOWANCE, ChainClient


@dataclass(frozen=True)
class RevocationCandidate:
    proposal: Proposal
    approval: ApprovalRequest


async def scan_for_risky_approvals(
    client: ChainClient,
    proposals: ProposalStore,
    approvals: ApprovalStore,
    *,
    owner_address: str,
    requester_id: uuid.UUID,
    now: datetime,
    expires_at: datetime,
    critic: Critic | None = None,
) -> list[RevocationCandidate]:
    """Scan once, propose revoking every approval that grants an unlimited
    allowance. A merely large-but-finite allowance is left alone in v1 (ADR-0016) -
    the allow-list is exact, not a judgement call.
    """
    found: list[RevocationCandidate] = []
    for approval in await client.list_approvals(owner_address):
        if approval.allowance != INFINITE_ALLOWANCE:
            continue

        proposal = await proposals.create(
            action_type="revoke_approval",
            parameters={
                "approval_id": approval.id,
                "owner_address": approval.owner_address,
            },
            risk_level="low",
            evidence={
                "token_symbol": approval.token_symbol,
                "spender_address": approval.spender_address,
                "allowance": str(approval.allowance),
            },
            created_at=now,
        )
        snapshot: dict[str, object] = {
            "action_type": "revoke_approval",
            "approval_id": approval.id,
            "owner_address": approval.owner_address,
            "token_address": approval.token_address,
            "token_symbol": approval.token_symbol,
            "spender_address": approval.spender_address,
            "allowance": str(approval.allowance),
            "reason": (
                f"{approval.spender_address} holds an unlimited approval on "
                f"{approval.token_symbol} - the maximum representable amount, not "
                "just a large one"
            ),
        }
        if critic is not None:
            critique = await critic.critique(
                {
                    "approval_id": approval.id,
                    "token_symbol": approval.token_symbol,
                    "spender_address": approval.spender_address,
                    "allowance": str(approval.allowance),
                }
            )
            snapshot["llm_critique"] = critique.as_snapshot_field()
        approval_request = await approvals.create(
            proposal_id=proposal.id,
            subject_type="token_approval",
            requester_id=requester_id,
            action_type="revoke_approval",
            risk_level="low",
            idempotency_key=f"revoke-{approval.id}",
            snapshot_json=snapshot,
            created_at=now,
            expires_at=expires_at,
        )
        found.append(RevocationCandidate(proposal=proposal, approval=approval_request))
    return found
