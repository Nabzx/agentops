"""The seam between this flagship and a cloud account.

``CloudClient`` is a small Protocol; ``FakeCloudClient`` is an in-memory stand-in seeded
with fake addresses and instances, so this whole package runs with zero setup and no AWS
account, no boto3 - that stays the default everywhere in this repo, same as
``stripe-recovery``'s ``FakeStripeClient`` and ``wallet-guard``'s ``FakeChainClient``.
``AwsCloudClient`` is the real, EC2/CloudWatch-backed implementation of the same
Protocol, per ADR-0024 - built for real, never invoked with real credentials by
anything in this repo (ADR-0024 grilled item 3).

Two resource types, two different idempotency mechanisms, per ADR-0020/0022:

- An already-released allocation id fails to release a second time because the id
  genuinely no longer exists - that failure *is* the completion signal, not a header or
  a nonce ledger. ``FakeCloudClient`` models the caller-side half of that with a plain
  dedup-by-key record; ``AwsCloudClient`` asks ``describe_addresses`` whether the
  allocation id still exists at all - genuinely cheap, unlike Stripe's
  re-confirm-required case (ADR-0018).
- Stopping an instance needs no dedup ledger at all: AWS's own ``StopInstances`` is safe
  to call on an already-stopped instance regardless of key - the resource's own state
  machine provides idempotency for free. ``get_stopped`` checks current state, not a
  per-key record.
"""

from __future__ import annotations

import asyncio
import dataclasses
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Protocol

import boto3
from botocore.exceptions import ClientError
from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    from mypy_boto3_cloudwatch.client import CloudWatchClient
    from mypy_boto3_cloudwatch.type_defs import MetricDataQueryTypeDef
    from mypy_boto3_ec2.client import EC2Client

# Inspired by AWS's own published Trusted Advisor "low utilization" convention
# (ADR-0022) - not a number this project invented, but not a faithful reproduction of
# it either. AWS's real check counts a per-day CPU/network boolean across the last 14
# days and flags on >=4 days; this checks one average, computed over the whole
# IDLE_LOOKBACK_DAYS window, against the threshold once - a deliberate v1
# simplification, not an oversight (ADR-0024, grilled item 1). A faithful
# >=4-of-14-days implementation stays a named, deferred v1.1 candidate.
IDLE_CPU_PERCENT_THRESHOLD: float = 10.0
IDLE_NETWORK_BYTES_THRESHOLD: float = 5_000_000
IDLE_LOOKBACK_DAYS: int = 14


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
    """One EC2 instance, as AWS's own API would describe it. ``avg_cpu_percent`` is
    ``CPUUtilization``'s ``Average`` over ``IDLE_LOOKBACK_DAYS``; ``avg_network_bytes``
    is ``NetworkIn``'s ``Average`` plus ``NetworkOut``'s ``Average`` over the same
    window - both computed for real by ``AwsCloudClient`` via one batched
    ``GetMetricData`` call (ADR-0024). ``FakeCloudClient`` just carries whatever
    values it was seeded with.
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


class LiveActionsDisabledError(Exception):
    """Raised by ``AwsCloudClient`` when ``release_address``/``stop_instance`` is asked
    to mutate real state while ``allow_live=False``. AWS's own ``DryRun`` already
    confirmed the call would have succeeded for real - this isn't a lie about that,
    it's this repo's own policy declining to let it actually happen (ADR-0024 grilled
    item 3: nothing here is ever configured with ``allow_live=True``). Treated as
    permanent, not retryable, by ``adapter.py`` - the client's own configuration never
    changes mid-flight, so retrying the same job against the same client can never
    succeed differently.
    """


class TransientCloudError(Exception):
    """Raised by ``AwsCloudClient`` for an AWS-side failure that isn't a known
    permanent case (not-found, dry-run-disabled) - throttling, a transient network
    blip, IAM propagation delay. Worth retrying, unlike the two errors above.
    """


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


# A real AWS account no longer has the original public IP once an address is truly
# released - unlike FakeCloudClient's in-memory ledger, AWS itself throws the record
# away. That's fine: the approval's own Snapshot already recorded the public IP
# durably at proposal time (ADR-0008), well before this could ever be a retry. This
# placeholder is honest about what it is, not a fabricated-looking real value.
_PUBLIC_IP_NOT_RECOVERABLE = "(unknown - already released; see the approval's Snapshot)"


class CloudWasteAwsSettings(BaseSettings):
    """Only non-secret config - per ADR-0024, credentials resolve through boto3's own
    default chain (env vars, a named profile, an IAM role, SSO), never a
    project-specific settings field. Wrapping AWS's own credential resolution in
    another settings layer the way ADR-0003/0013 do for Stripe would regress real
    users away from profiles/IAM roles they already have configured - a deliberate
    difference from every other Settings class in this project, not an oversight.
    """

    model_config = SettingsConfigDict(env_prefix="CLOUD_WASTE_AWS_", extra="ignore")

    region: str
    profile_name: str | None = None


def _address_from_aws(raw: dict[str, object]) -> ElasticIp:
    return ElasticIp(
        id=str(raw["AllocationId"]),
        public_ip=str(raw.get("PublicIp", "")),
        association_id=(
            str(raw["AssociationId"]) if raw.get("AssociationId") else None
        ),
        instance_id=str(raw["InstanceId"]) if raw.get("InstanceId") else None,
    )


def _instance_from_aws(raw: dict[str, object]) -> Instance:
    state = raw["State"]
    assert isinstance(state, dict)  # noqa: S101 - narrowing a real, well-known AWS shape
    tags_raw = raw.get("Tags")
    tags = (
        {str(t["Key"]): str(t["Value"]) for t in tags_raw}
        if isinstance(tags_raw, list)
        else {}
    )
    launch_time = raw["LaunchTime"]
    assert isinstance(launch_time, datetime)  # noqa: S101
    return Instance(
        id=str(raw["InstanceId"]),
        state=str(state["Name"]),
        launch_time=launch_time,
        tags=tags,
        # Filled in from CloudWatch by list_instances(), for a running instance only.
        avg_cpu_percent=0.0,
        avg_network_bytes=0.0,
    )


def _is_dry_run_would_succeed(exc: ClientError) -> bool:
    return exc.response.get("Error", {}).get("Code") == "DryRunOperation"


class AwsCloudClient:
    """Wraps real EC2/CloudWatch calls, per ADR-0024.

    Reads (``list_addresses``/``list_instances``) are always real once this is
    constructed at all - they have no side effects, nothing to gate. The two mutating
    calls (``release_address``/``stop_instance``) are gated a second, independent
    time: ``DryRun`` is always on unless ``allow_live=True``, which nothing in this
    repo ever passes (ADR-0024 grilled item 3) - a real client can list a real
    account's real resources and still structurally never release or stop anything.

    ``boto3`` has no native async API, so the handful of synchronous SDK calls this
    makes run via ``asyncio.to_thread`` rather than pulling in a second, less-mature
    async wrapper library just for this.
    """

    def __init__(
        self, settings: CloudWasteAwsSettings, *, allow_live: bool = False
    ) -> None:
        session = boto3.Session(
            profile_name=settings.profile_name, region_name=settings.region
        )
        self._ec2: EC2Client = session.client("ec2")
        self._cloudwatch: CloudWatchClient = session.client("cloudwatch")
        self._allow_live = allow_live

    async def list_addresses(self) -> list[ElasticIp]:
        response = await asyncio.to_thread(self._ec2.describe_addresses)
        return [_address_from_aws(dict(a)) for a in response["Addresses"]]

    async def release_address(
        self, allocation_id: str, *, idempotency_key: str
    ) -> ElasticIp:
        addresses = await self.list_addresses()
        current = next((a for a in addresses if a.id == allocation_id), None)
        if current is None:
            raise AddressNotFoundError(f"no such allocation {allocation_id}")
        try:
            await asyncio.to_thread(
                self._ec2.release_address,
                AllocationId=allocation_id,
                DryRun=not self._allow_live,
            )
        except ClientError as exc:
            self._raise_for_address_error(exc, allocation_id)
        return current

    async def get_released(
        self, allocation_id: str, *, idempotency_key: str
    ) -> ElasticIp | None:
        addresses = await self.list_addresses()
        if any(a.id == allocation_id for a in addresses):
            return None  # still exists - not released (yet)
        return ElasticIp(
            id=allocation_id,
            public_ip=_PUBLIC_IP_NOT_RECOVERABLE,
            association_id=None,
            instance_id=None,
        )

    async def list_instances(self) -> list[Instance]:
        response = await asyncio.to_thread(self._ec2.describe_instances)
        instances = [
            _instance_from_aws(dict(instance))
            for reservation in response["Reservations"]
            for instance in reservation["Instances"]
        ]
        running_ids = [i.id for i in instances if i.state == "running"]
        if not running_ids:
            return instances
        metrics = await self._fetch_idle_metrics(running_ids)
        return [
            dataclasses.replace(
                i,
                avg_cpu_percent=metrics[i.id][0],
                avg_network_bytes=metrics[i.id][1],
            )
            if i.id in metrics
            else i
            for i in instances
        ]

    async def stop_instance(
        self, instance_id: str, *, idempotency_key: str
    ) -> Instance:
        instances = await self.list_instances()
        current = next((i for i in instances if i.id == instance_id), None)
        if current is None:
            raise InstanceNotFoundError(f"no such instance {instance_id}")
        try:
            await asyncio.to_thread(
                self._ec2.stop_instances,
                InstanceIds=[instance_id],
                DryRun=not self._allow_live,
            )
        except ClientError as exc:
            self._raise_for_instance_error(exc, instance_id)
        return current

    async def get_stopped(
        self, instance_id: str, *, idempotency_key: str
    ) -> Instance | None:
        instances = await self.list_instances()
        current = next((i for i in instances if i.id == instance_id), None)
        return current if current is not None and current.state == "stopped" else None

    async def _fetch_idle_metrics(
        self, instance_ids: list[str]
    ) -> dict[str, tuple[float, float]]:
        """One batched ``GetMetricData`` call for every running instance - CPU and
        both network directions, each as a single ``Average`` over the whole
        ``IDLE_LOOKBACK_DAYS`` window (one datapoint per metric, per ADR-0024's
        locked v1 simplification - not AWS's own per-day-count algorithm).

        ``EndTime`` gets a small buffer past "now" rather than landing on it exactly -
        confirmed empirically (against moto, standing in for CloudWatch's own
        documented behaviour) that a query ending exactly at "now" can miss the most
        recent, still-aggregating period's datapoint entirely.
        """
        now = datetime.now(UTC) + timedelta(minutes=5)
        start = now - timedelta(days=IDLE_LOOKBACK_DAYS)
        period = IDLE_LOOKBACK_DAYS * 86_400
        metric_specs = [
            ("cpu", "CPUUtilization"),
            ("in", "NetworkIn"),
            ("out", "NetworkOut"),
        ]
        queries: list[MetricDataQueryTypeDef] = [
            {
                "Id": f"m{idx}_{key}",
                "MetricStat": {
                    "Metric": {
                        "Namespace": "AWS/EC2",
                        "MetricName": metric_name,
                        "Dimensions": [{"Name": "InstanceId", "Value": instance_id}],
                    },
                    "Period": period,
                    "Stat": "Average",
                },
                "ReturnData": True,
            }
            for idx, instance_id in enumerate(instance_ids)
            for key, metric_name in metric_specs
        ]
        response = await asyncio.to_thread(
            self._cloudwatch.get_metric_data,
            MetricDataQueries=queries,
            StartTime=start,
            EndTime=now,
        )
        values_by_id = {
            result["Id"]: (result["Values"][0] if result["Values"] else 0.0)
            for result in response["MetricDataResults"]
        }
        return {
            instance_id: (
                values_by_id.get(f"m{idx}_cpu", 0.0),
                values_by_id.get(f"m{idx}_in", 0.0)
                + values_by_id.get(f"m{idx}_out", 0.0),
            )
            for idx, instance_id in enumerate(instance_ids)
        }

    def _raise_for_address_error(self, exc: ClientError, allocation_id: str) -> None:
        code = exc.response.get("Error", {}).get("Code")
        if code == "InvalidAllocationID.NotFound":
            raise AddressNotFoundError(f"no such allocation {allocation_id}") from exc
        if _is_dry_run_would_succeed(exc):
            raise LiveActionsDisabledError(
                f"DryRun confirmed releasing {allocation_id} would succeed, but "
                "allow_live=False - nothing was actually released"
            ) from exc
        raise TransientCloudError(str(exc)) from exc

    def _raise_for_instance_error(self, exc: ClientError, instance_id: str) -> None:
        code = exc.response.get("Error", {}).get("Code")
        if code == "InvalidInstanceID.NotFound":
            raise InstanceNotFoundError(f"no such instance {instance_id}") from exc
        if _is_dry_run_would_succeed(exc):
            raise LiveActionsDisabledError(
                f"DryRun confirmed stopping {instance_id} would succeed, but "
                "allow_live=False - nothing was actually stopped"
            ) from exc
        raise TransientCloudError(str(exc)) from exc
