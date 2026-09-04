"""The seam between this flagship and a cloud account.

``CloudClient`` is a small Protocol; ``FakeCloudClient`` is an in-memory stand-in seeded
with fake addresses and instances, so this whole package runs with zero setup and no AWS
account, no boto3 - that stays the default everywhere in this repo, same as
``stripe-recovery``'s ``FakeStripeClient`` and ``wallet-guard``'s ``FakeChainClient``. A
real EC2-backed implementation of the same Protocol (using ``DryRun`` and a
least-privilege IAM policy, per ADR-0020) is a distinct, later concern - not built here.

Two resource types, two different idempotency mechanisms, per ADR-0020/0022:

- An already-released allocation id fails to release a second time because the id
  genuinely no longer exists - that failure *is* the completion signal, not a header or
  a nonce ledger. ``FakeCloudClient`` models the caller-side half of that with a plain
  dedup-by-key record; a real client's equivalent check would ask ``DescribeAddresses``
  whether the allocation id still exists at all - genuinely cheap, unlike Stripe's
  re-confirm-required case (ADR-0018).
- Stopping an instance needs no dedup ledger at all: AWS's own ``StopInstances`` is safe
  to call on an already-stopped instance regardless of key - the resource's own state
  machine provides idempotency for free. ``get_stopped`` checks current state, not a
  per-key record.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

# Mirrors AWS's own published Trusted Advisor "low utilization" convention (ADR-0022) -
# not a number this project invented. The exact constants are fine to hardcode for the
# fake/seeded data this package ships with; re-verify them against AWS's current
# published guidance before a real client is ever built against them.
IDLE_CPU_PERCENT_THRESHOLD: float = 10.0
IDLE_NETWORK_BYTES_THRESHOLD: float = 5_000_000


@dataclass(frozen=True)
class ElasticIp:
    """One Elastic IP address, as AWS's own API would describe it. An address with no
    ``association_id``/``instance_id`` has nothing using it.
    """

    id: str  # the allocation id
    public_ip: str
    association_id: str | None
    instance_id: str | None


@dataclass(frozen=True)
class Instance:
    """One EC2 instance, as AWS's own API would describe it. ``avg_cpu_percent`` and
    ``avg_network_bytes`` stand in for what a real client would compute from
    ``CloudWatch.GetMetricStatistics`` over an observation window (ADR-0022) - this
    fake carries the aggregate directly rather than simulating a time series.
    """

    id: str  # the instance id
    state: str  # "running" or "stopped"
    launch_time: datetime
    tags: dict[str, str]
    avg_cpu_percent: float
    avg_network_bytes: float


class CloudClient(Protocol):
    """The interface the detector and Adapter talk to. A real implementation would wrap
    an EC2/CloudWatch client behind this same shape.
    """

    async def list_addresses(self) -> list[ElasticIp]: ...

    async def release_address(
        self, allocation_id: str, *, idempotency_key: str
    ) -> ElasticIp:
        """Release the address behind ``allocation_id`` (ADR-0020 - the address is
        never re-associated or reused, only released). A resubmission with the same
        ``idempotency_key`` resolves to the same recorded outcome, never a second
        real release.
        """
        ...

    async def get_released(
        self, allocation_id: str, *, idempotency_key: str
    ) -> ElasticIp | None:
        """Has this idempotency key already produced a release? See ADR-0018 -
        called by the Adapter's ``check_completed`` only on a retry, never a
        genuine first attempt.
        """
        ...

    async def list_instances(self) -> list[Instance]: ...

    async def stop_instance(
        self, instance_id: str, *, idempotency_key: str
    ) -> Instance:
        """Stop the instance behind ``instance_id`` (ADR-0022 - stop, never terminate:
        the instance restarts exactly as it was via ``StartInstances``). Safe to call
        again regardless of ``idempotency_key`` - an already-stopped instance just
        stays stopped.
        """
        ...

    async def get_stopped(
        self, instance_id: str, *, idempotency_key: str
    ) -> Instance | None:
        """Is this instance already stopped? A state fact, not a per-key record
        (ADR-0022) - ``idempotency_key`` is accepted for interface parity with the
        other ``get_*`` methods, not used. Called by ``check_completed`` only on a
        retry, never a genuine first attempt (ADR-0018).
        """
        ...


class AddressNotFoundError(Exception):
    """Raised when an operation targets an allocation id that doesn't exist."""


class InstanceNotFoundError(Exception):
    """Raised when an operation targets an instance id that doesn't exist."""


class FakeCloudClient:
    """An in-memory stand-in for an AWS account. No boto3, no network access, ever."""

    def __init__(self, addresses: list[ElasticIp] | None = None) -> None:
        self._addresses: dict[str, ElasticIp] = {a.id: a for a in (addresses or [])}
        self._result_by_key: dict[str, ElasticIp] = {}
        self._instances: dict[str, Instance] = {}

    def seed(self, address: ElasticIp) -> None:
        self._addresses[address.id] = address

    def seed_instance(self, instance: Instance) -> None:
        self._instances[instance.id] = instance

    async def list_addresses(self) -> list[ElasticIp]:
        return list(self._addresses.values())

    async def release_address(
        self, allocation_id: str, *, idempotency_key: str
    ) -> ElasticIp:
        if idempotency_key in self._result_by_key:
            return self._result_by_key[idempotency_key]  # already gone - same outcome

        address = self._addresses.get(allocation_id)
        if address is None:
            raise AddressNotFoundError(f"no such allocation {allocation_id}")

        # The address genuinely ceases to exist - the whole point of this mechanism.
        del self._addresses[allocation_id]
        self._result_by_key[idempotency_key] = address
        return address

    async def get_released(
        self, allocation_id: str, *, idempotency_key: str
    ) -> ElasticIp | None:
        return self._result_by_key.get(idempotency_key)

    async def list_instances(self) -> list[Instance]:
        return list(self._instances.values())

    async def stop_instance(
        self, instance_id: str, *, idempotency_key: str
    ) -> Instance:
        instance = self._instances.get(instance_id)
        if instance is None:
            raise InstanceNotFoundError(f"no such instance {instance_id}")
        if instance.state == "stopped":
            return instance  # already stopped - a safe no-op, not a second effect

        stopped = _stopped_copy(instance)
        self._instances[instance_id] = stopped
        return stopped

    async def get_stopped(
        self, instance_id: str, *, idempotency_key: str
    ) -> Instance | None:
        instance = self._instances.get(instance_id)
        return (
            instance if instance is not None and instance.state == "stopped" else None
        )


def _stopped_copy(instance: Instance) -> Instance:
    return Instance(
        id=instance.id,
        state="stopped",
        launch_time=instance.launch_time,
        tags=instance.tags,
        avg_cpu_percent=instance.avg_cpu_percent,
        avg_network_bytes=instance.avg_network_bytes,
    )
