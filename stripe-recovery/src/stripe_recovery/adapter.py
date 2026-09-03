"""StripeAdapter: the Adapter (ephor.effects) that retries a soft-declined charge.

See ADR-0011 for the action set and the retry mechanics.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ephor.effects import Effect, PermanentEffectError

from stripe_recovery.client import (
    RETRYABLE_DECLINE_CODES,
    ChargeNotFoundError,
    StripeClient,
)


class StripeAdapter:
    """Retries a soft-declined Stripe charge.

    ``is_idempotent`` because Stripe's own ``Idempotency-Key`` deduplication makes a
    repeated confirm call a no-op, not a second real charge attempt - see ADR-0005/0011.
    """

    is_idempotent = True

    def __init__(self, client: StripeClient) -> None:
        self._client = client

    async def check_completed(
        self, action: dict[str, Any], idempotency_key: str
    ) -> Effect | None:
        """Not a free lookup for Stripe - see ``client.py``'s ``get_confirmed`` and
        ADR-0018. A worker must only call this on a retry, never a genuine first
        attempt for a job.
        """
        charge_id = action["charge_id"]
        try:
            result = await self._client.get_confirmed(
                charge_id, idempotency_key=idempotency_key
            )
        except ChargeNotFoundError:
            return None
        if result is None:
            return None
        return Effect(
            effect_id=result.id,
            occurred_at=datetime.now(UTC),
            raw={"status": result.status, "amount_pence": result.amount_pence},
        )

    async def revalidate(self, action: dict[str, Any]) -> bool:
        """Re-check the charge is still failed, with a retryable decline code, right
        before executing - the world may have moved on since this was approved.
        """
        charge_id = action["charge_id"]
        charges = await self._client.list_failed_charges()
        charge = next((c for c in charges if c.id == charge_id), None)
        if charge is None:
            return False  # already resolved, or never existed - nothing to retry
        return charge.decline_code in RETRYABLE_DECLINE_CODES

    async def execute(self, action: dict[str, Any], idempotency_key: str) -> Effect:
        """Raises PermanentEffectError on anything that will never succeed - per the
        Adapter contract (ADR-0006), execute() never lets an unclassified exception
        escape; the core only knows how to react to the two Adapter exception types.
        """
        charge_id = action["charge_id"]
        try:
            result = await self._client.confirm_payment_intent(
                charge_id, idempotency_key=idempotency_key
            )
        except ChargeNotFoundError as exc:
            raise PermanentEffectError(str(exc)) from exc
        if result.status != "succeeded":
            raise PermanentEffectError(f"charge {charge_id} did not succeed on retry")
        return Effect(
            effect_id=result.id,
            occurred_at=datetime.now(UTC),
            raw={"status": result.status, "amount_pence": result.amount_pence},
        )
