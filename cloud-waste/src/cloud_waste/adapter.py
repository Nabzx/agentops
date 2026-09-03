"""CloudWasteAdapter: the Adapter (ephor.effects) that releases an unassociated
Elastic IP.

See ADR-0020 for the action set and why exactly-once here rests on "does the
allocation id still exist" rather than a header (ADR-0006/0011) or nonce discipline
(ADR-0016).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ephor.effects import Effect, PermanentEffectError

from cloud_waste.client import AddressNotFoundError, CloudClient


class CloudWasteAdapter:
    """Releases one unassociated Elastic IP address.

    ``is_idempotent`` because a retry with the same idempotency key resolves to the
    same recorded outcome - see ``client.py``'s module docstring and ADR-0020.
    """

    is_idempotent = True

    def __init__(self, client: CloudClient) -> None:
        self._client = client

    async def check_completed(
        self, action: dict[str, Any], idempotency_key: str
    ) -> Effect | None:
        """Only ever called by a worker on a retry, never the first attempt for a
        job - see ADR-0018.
        """
        allocation_id = action["allocation_id"]
        result = await self._client.get_released(
            allocation_id, idempotency_key=idempotency_key
        )
        if result is None:
            return None
        return Effect(
            effect_id=result.id,
            occurred_at=datetime.now(UTC),
            raw={"released_public_ip": result.public_ip},
        )

    async def revalidate(self, action: dict[str, Any]) -> bool:
        """Re-check the address is still unassociated right before executing - it may
        have been attached to something, or already released by hand, since this was
        approved.
        """
        allocation_id = action["allocation_id"]
        addresses = await self._client.list_addresses()
        current = next((a for a in addresses if a.id == allocation_id), None)
        if current is None:
            return False  # already released, or never existed - nothing to do
        return current.association_id is None and current.instance_id is None

    async def execute(self, action: dict[str, Any], idempotency_key: str) -> Effect:
        """Raises PermanentEffectError on anything that will never succeed - per the
        Adapter contract (ADR-0006), execute() never lets an unclassified exception
        escape.
        """
        allocation_id = action["allocation_id"]
        try:
            result = await self._client.release_address(
                allocation_id, idempotency_key=idempotency_key
            )
        except AddressNotFoundError as exc:
            raise PermanentEffectError(str(exc)) from exc
        return Effect(
            effect_id=result.id,
            occurred_at=datetime.now(UTC),
            raw={"released_public_ip": result.public_ip},
        )
