"""The seam between this flagship and a cloud account.

``CloudClient`` is a small Protocol; ``FakeCloudClient`` is an in-memory stand-in seeded
with fake addresses, so this whole package runs with zero setup and no AWS account, no
boto3 - that stays the default everywhere in this repo, same as ``stripe-recovery``'s
``FakeStripeClient`` and ``wallet-guard``'s ``FakeChainClient``. A real EC2-backed
implementation of the same Protocol (using ``DryRun`` and a least-privilege IAM policy,
per ADR-0020) is a distinct, later concern - not built here.

Idempotency here is a third distinct mechanism again, per ADR-0020: an already-released
allocation id fails to release a second time because the id genuinely no longer exists -
that failure *is* the completion signal, not a header or a nonce ledger.
``FakeCloudClient`` models the caller-side half of that with a plain dedup-by-key
record, same shape as the other two fakes; a real client's equivalent check would
instead ask ``DescribeAddresses`` whether the allocation id still exists at all -
genuinely cheap there, unlike Stripe's re-confirm-required case (ADR-0018).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ElasticIp:
    """One Elastic IP address, as AWS's own API would describe it. An address with no
    ``association_id``/``instance_id`` has nothing using it.
    """

    id: str  # the allocation id
    public_ip: str
    association_id: str | None
    instance_id: str | None


class CloudClient(Protocol):
    """The interface the detector and Adapter talk to. A real implementation would wrap
    an EC2 client (``DescribeAddresses``, ``ReleaseAddress``) behind this same shape.
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


class AddressNotFoundError(Exception):
    """Raised when an operation targets an allocation id that doesn't exist."""


class FakeCloudClient:
    """An in-memory stand-in for an AWS account. No boto3, no network access, ever."""

    def __init__(self, addresses: list[ElasticIp] | None = None) -> None:
        self._addresses: dict[str, ElasticIp] = {a.id: a for a in (addresses or [])}
        self._result_by_key: dict[str, ElasticIp] = {}

    def seed(self, address: ElasticIp) -> None:
        self._addresses[address.id] = address

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
