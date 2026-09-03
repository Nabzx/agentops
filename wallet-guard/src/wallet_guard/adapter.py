"""WalletGuardAdapter: the Adapter (ephor.effects) that revokes a dangerous token
approval.

See ADR-0016 for the action set and why exactly-once here rests on nonce discipline
rather than a header, the way ``stripe_recovery.adapter`` rests on Stripe's own
``Idempotency-Key``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ephor.effects import Effect, PermanentEffectError

from wallet_guard.client import ApprovalNotFoundError, ChainClient


class WalletGuardAdapter:
    """Revokes one dangerous (unlimited-allowance) token approval.

    ``is_idempotent`` because a retry with the same idempotency key resolves to the
    same recorded nonce, and the network finalises at most one transaction per
    (account, nonce) - see ``client.py``'s module docstring and ADR-0016.
    """

    is_idempotent = True

    def __init__(self, client: ChainClient) -> None:
        self._client = client

    async def check_completed(
        self, action: dict[str, Any], idempotency_key: str
    ) -> Effect | None:
        """A genuinely cheap check here - see ADR-0018 and ``client.py``'s
        ``get_revoked``. Only ever called by a worker on a retry, never the first
        attempt for a job.
        """
        result = await self._client.get_revoked(idempotency_key)
        if result is None:
            return None
        return Effect(
            effect_id=result.id,
            occurred_at=datetime.now(UTC),
            raw={"allowance": result.allowance, "token_symbol": result.token_symbol},
        )

    async def revalidate(self, action: dict[str, Any]) -> bool:
        """Re-check the approval is still active right before executing - the owner
        may have revoked it themselves, or changed it, since this was approved.
        """
        approval_id = action["approval_id"]
        owner_address = action["owner_address"]
        approvals = await self._client.list_approvals(owner_address)
        current = next((a for a in approvals if a.id == approval_id), None)
        return current is not None and current.allowance > 0

    async def execute(self, action: dict[str, Any], idempotency_key: str) -> Effect:
        """Raises PermanentEffectError on anything that will never succeed - per the
        Adapter contract (ADR-0006), execute() never lets an unclassified exception
        escape.
        """
        approval_id = action["approval_id"]
        try:
            result = await self._client.revoke_approval(
                approval_id, idempotency_key=idempotency_key
            )
        except ApprovalNotFoundError as exc:
            raise PermanentEffectError(str(exc)) from exc
        if result.allowance != 0:
            raise PermanentEffectError(f"approval {approval_id} was not revoked")
        return Effect(
            effect_id=result.id,
            occurred_at=datetime.now(UTC),
            raw={"allowance": result.allowance, "token_symbol": result.token_symbol},
        )
