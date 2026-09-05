"""The two Adapters (ephor.effects) this package ships - one per action type, per
ADR-0006, not one Adapter branching on action shape.

``CloudWasteAdapter`` releases an unassociated Elastic IP (ADR-0020) - exactly-once
rests on "does the allocation id still exist". ``IdleInstanceAdapter`` stops an idle
instance (ADR-0022) - exactly-once needs no dedup ledger at all, since AWS's own
``StopInstances`` is safe to call on an already-stopped instance regardless of key.

Both Adapters classify two more client-layer exceptions that only ``AwsCloudClient``
(ADR-0024) ever actually raises: ``LiveActionsDisabledError`` (a real ``DryRun``
confirmed the call would succeed, but this repo's own policy never lets it - permanent,
since the client's configuration never changes mid-flight) and ``TransientCloudError``
(an unclassified AWS-side failure - throttling, a network blip - worth retrying).
``FakeCloudClient`` never raises either, so this is dormant in every test/demo/CI path
today - see client.py's own docstring for why that's deliberate (ADR-0024 item 3).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ephor.effects import Effect, PermanentEffectError, RetryableEffectError

from cloud_waste.client import (
    IDLE_CPU_PERCENT_THRESHOLD,
    IDLE_NETWORK_BYTES_THRESHOLD,
    AddressNotFoundError,
    CloudClient,
    InstanceNotFoundError,
    LiveActionsDisabledError,
    TransientCloudError,
)


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
        except LiveActionsDisabledError as exc:
            raise PermanentEffectError(str(exc)) from exc
        except TransientCloudError as exc:
            raise RetryableEffectError(str(exc)) from exc
        return Effect(
            effect_id=result.id,
            occurred_at=datetime.now(UTC),
            raw={"released_public_ip": result.public_ip},
        )


class IdleInstanceAdapter:
    """Stops one idle EC2 instance.

    ``is_idempotent`` because AWS's own instance state machine makes a repeat
    ``StopInstances`` call a safe no-op, not a second real effect - see ``client.py``'s
    module docstring and ADR-0022.
    """

    is_idempotent = True

    def __init__(self, client: CloudClient) -> None:
        self._client = client

    async def check_completed(
        self, action: dict[str, Any], idempotency_key: str
    ) -> Effect | None:
        """Only ever called by a worker on a retry, never the first attempt for a
        job - see ADR-0018. Unlike ``CloudWasteAdapter``'s version, this asks a state
        fact, not a per-key record (ADR-0022).
        """
        instance_id = action["instance_id"]
        result = await self._client.get_stopped(
            instance_id, idempotency_key=idempotency_key
        )
        if result is None:
            return None
        return Effect(
            effect_id=result.id,
            occurred_at=datetime.now(UTC),
            raw={"stopped_instance_id": result.id},
        )

    async def revalidate(self, action: dict[str, Any]) -> bool:
        """Re-check the instance is still running and still idle by the same
        criteria the detector used - it may have started doing real work, or already
        been stopped by hand, since this was approved.
        """
        instance_id = action["instance_id"]
        instances = await self._client.list_instances()
        current = next((i for i in instances if i.id == instance_id), None)
        if current is None or current.state != "running":
            return False  # already stopped, or never existed - nothing to do
        return (
            current.avg_cpu_percent <= IDLE_CPU_PERCENT_THRESHOLD
            and current.avg_network_bytes <= IDLE_NETWORK_BYTES_THRESHOLD
        )

    async def execute(self, action: dict[str, Any], idempotency_key: str) -> Effect:
        """Raises PermanentEffectError on anything that will never succeed - per the
        Adapter contract (ADR-0006), execute() never lets an unclassified exception
        escape.
        """
        instance_id = action["instance_id"]
        try:
            result = await self._client.stop_instance(
                instance_id, idempotency_key=idempotency_key
            )
        except InstanceNotFoundError as exc:
            raise PermanentEffectError(str(exc)) from exc
        except LiveActionsDisabledError as exc:
            raise PermanentEffectError(str(exc)) from exc
        except TransientCloudError as exc:
            raise RetryableEffectError(str(exc)) from exc
        return Effect(
            effect_id=result.id,
            occurred_at=datetime.now(UTC),
            raw={"stopped_instance_id": result.id},
        )
