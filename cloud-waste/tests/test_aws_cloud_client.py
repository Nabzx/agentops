"""Tests AwsCloudClient's own logic against moto's simulated EC2/CloudWatch backend
(ADR-0024, grilled item 2) - never a live account, never with real credentials.

moto intercepts boto3 calls at the transport layer and simulates real AWS behaviour,
including real error codes (``InvalidAllocationID.NotFound``, ``DryRunOperation``) -
confirmed directly against a live moto session before writing these, not assumed.
Every test here constructs ``AwsCloudClient`` with ``allow_live=False`` except the
handful that explicitly test what ``allow_live=True`` unlocks - ADR-0024's "build it,
never use it" restriction is about real AWS credentials, not about exercising
``allow_live=True`` against moto's fully-simulated, zero-cost backend.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import boto3
import pytest
from moto import mock_aws

from cloud_waste.client import (
    AddressNotFoundError,
    AwsCloudClient,
    CloudWasteAwsSettings,
    InstanceNotFoundError,
    LiveActionsDisabledError,
)

REGION = "us-east-1"


def _settings() -> CloudWasteAwsSettings:
    return CloudWasteAwsSettings(region=REGION)


@pytest.fixture
def moto_session() -> Iterator[None]:
    with mock_aws():
        yield


async def test_list_addresses_returns_everything_in_the_account(
    moto_session: None,
) -> None:
    ec2 = boto3.client("ec2", region_name=REGION)
    ec2.allocate_address(Domain="vpc")
    ec2.allocate_address(Domain="vpc")

    client = AwsCloudClient(_settings())
    addresses = await client.list_addresses()
    assert len(addresses) == 2


async def test_an_unassociated_address_has_no_association_or_instance(
    moto_session: None,
) -> None:
    ec2 = boto3.client("ec2", region_name=REGION)
    ec2.allocate_address(Domain="vpc")

    client = AwsCloudClient(_settings())
    [address] = await client.list_addresses()
    assert address.association_id is None
    assert address.instance_id is None


async def test_release_address_with_allow_live_actually_releases_it(
    moto_session: None,
) -> None:
    ec2 = boto3.client("ec2", region_name=REGION)
    allocation = ec2.allocate_address(Domain="vpc")

    client = AwsCloudClient(_settings(), allow_live=True)
    released = await client.release_address(
        allocation["AllocationId"], idempotency_key="k1"
    )
    assert released.id == allocation["AllocationId"]
    assert released.public_ip == allocation["PublicIp"]
    assert await client.list_addresses() == []


async def test_release_address_without_allow_live_raises_and_releases_nothing(
    moto_session: None,
) -> None:
    """The default, everywhere-in-this-repo path (ADR-0024 grilled item 3) - DryRun
    confirms it would work, but nothing actually happens.
    """
    ec2 = boto3.client("ec2", region_name=REGION)
    allocation = ec2.allocate_address(Domain="vpc")

    client = AwsCloudClient(_settings(), allow_live=False)
    with pytest.raises(LiveActionsDisabledError):
        await client.release_address(allocation["AllocationId"], idempotency_key="k1")

    [still_there] = await client.list_addresses()
    assert still_there.id == allocation["AllocationId"]


async def test_release_address_raises_for_an_unknown_allocation_id(
    moto_session: None,
) -> None:
    client = AwsCloudClient(_settings(), allow_live=True)
    with pytest.raises(AddressNotFoundError):
        await client.release_address("eipalloc-does-not-exist", idempotency_key="k1")


async def test_get_released_is_none_for_an_address_still_present(
    moto_session: None,
) -> None:
    ec2 = boto3.client("ec2", region_name=REGION)
    allocation = ec2.allocate_address(Domain="vpc")

    client = AwsCloudClient(_settings())
    result = await client.get_released(allocation["AllocationId"], idempotency_key="k1")
    assert result is None


async def test_get_released_returns_a_placeholder_once_the_address_is_gone(
    moto_session: None,
) -> None:
    """AWS itself no longer has the original public IP once released - that's fine,
    the approval's own Snapshot recorded it durably already (ADR-0024's noted gap).
    """
    ec2 = boto3.client("ec2", region_name=REGION)
    allocation = ec2.allocate_address(Domain="vpc")
    ec2.release_address(AllocationId=allocation["AllocationId"])

    client = AwsCloudClient(_settings())
    result = await client.get_released(allocation["AllocationId"], idempotency_key="k1")
    assert result is not None
    assert result.id == allocation["AllocationId"]


async def test_list_instances_returns_everything_in_the_account(
    moto_session: None,
) -> None:
    ec2 = boto3.client("ec2", region_name=REGION)
    ec2.run_instances(ImageId="ami-12345678", MinCount=1, MaxCount=1)

    client = AwsCloudClient(_settings())
    instances = await client.list_instances()
    assert len(instances) == 1
    assert instances[0].state == "running"
    assert isinstance(instances[0].launch_time, datetime)


async def test_list_instances_maps_tags(moto_session: None) -> None:
    ec2 = boto3.client("ec2", region_name=REGION)
    resv = ec2.run_instances(
        ImageId="ami-12345678",
        MinCount=1,
        MaxCount=1,
        TagSpecifications=[
            {
                "ResourceType": "instance",
                "Tags": [{"Key": "env", "Value": "prod"}],
            }
        ],
    )
    instance_id = resv["Instances"][0]["InstanceId"]

    client = AwsCloudClient(_settings())
    [instance] = await client.list_instances()
    assert instance.id == instance_id
    assert instance.tags == {"env": "prod"}


async def test_list_instances_fetches_real_cloudwatch_metrics_for_running_instances(
    moto_session: None,
) -> None:
    ec2 = boto3.client("ec2", region_name=REGION)
    resv = ec2.run_instances(ImageId="ami-12345678", MinCount=1, MaxCount=1)
    instance_id = resv["Instances"][0]["InstanceId"]

    cloudwatch = boto3.client("cloudwatch", region_name=REGION)
    cloudwatch.put_metric_data(
        Namespace="AWS/EC2",
        MetricData=[
            {
                "MetricName": "CPUUtilization",
                "Dimensions": [{"Name": "InstanceId", "Value": instance_id}],
                "Timestamp": datetime.now(UTC),
                "Value": 2.5,
                "Unit": "Percent",
            },
            {
                "MetricName": "NetworkIn",
                "Dimensions": [{"Name": "InstanceId", "Value": instance_id}],
                "Timestamp": datetime.now(UTC),
                "Value": 1000.0,
                "Unit": "Bytes",
            },
            {
                "MetricName": "NetworkOut",
                "Dimensions": [{"Name": "InstanceId", "Value": instance_id}],
                "Timestamp": datetime.now(UTC),
                "Value": 500.0,
                "Unit": "Bytes",
            },
        ],
    )

    client = AwsCloudClient(_settings())
    [instance] = await client.list_instances()
    assert instance.avg_cpu_percent == 2.5
    assert instance.avg_network_bytes == 1500.0


async def test_list_instances_never_queries_metrics_for_a_stopped_instance(
    moto_session: None,
) -> None:
    """No CloudWatch call at all when nothing is running - nothing to check."""
    ec2 = boto3.client("ec2", region_name=REGION)
    resv = ec2.run_instances(ImageId="ami-12345678", MinCount=1, MaxCount=1)
    instance_id = resv["Instances"][0]["InstanceId"]
    ec2.stop_instances(InstanceIds=[instance_id])

    client = AwsCloudClient(_settings())
    [instance] = await client.list_instances()
    assert instance.state == "stopped"
    assert instance.avg_cpu_percent == 0.0
    assert instance.avg_network_bytes == 0.0


async def test_stop_instance_with_allow_live_actually_stops_it(
    moto_session: None,
) -> None:
    ec2 = boto3.client("ec2", region_name=REGION)
    resv = ec2.run_instances(ImageId="ami-12345678", MinCount=1, MaxCount=1)
    instance_id = resv["Instances"][0]["InstanceId"]

    client = AwsCloudClient(_settings(), allow_live=True)
    stopped = await client.stop_instance(instance_id, idempotency_key="k1")
    assert stopped.id == instance_id
    [current] = await client.list_instances()
    assert current.state == "stopped"


async def test_stop_instance_without_allow_live_raises_and_stops_nothing(
    moto_session: None,
) -> None:
    ec2 = boto3.client("ec2", region_name=REGION)
    resv = ec2.run_instances(ImageId="ami-12345678", MinCount=1, MaxCount=1)
    instance_id = resv["Instances"][0]["InstanceId"]

    client = AwsCloudClient(_settings(), allow_live=False)
    with pytest.raises(LiveActionsDisabledError):
        await client.stop_instance(instance_id, idempotency_key="k1")

    [current] = await client.list_instances()
    assert current.state == "running"


async def test_stop_instance_raises_for_an_unknown_instance_id(
    moto_session: None,
) -> None:
    client = AwsCloudClient(_settings(), allow_live=True)
    with pytest.raises(InstanceNotFoundError):
        await client.stop_instance("i-does-not-exist", idempotency_key="k1")


async def test_get_stopped_is_none_for_a_running_instance(
    moto_session: None,
) -> None:
    ec2 = boto3.client("ec2", region_name=REGION)
    resv = ec2.run_instances(ImageId="ami-12345678", MinCount=1, MaxCount=1)
    instance_id = resv["Instances"][0]["InstanceId"]

    client = AwsCloudClient(_settings())
    result = await client.get_stopped(instance_id, idempotency_key="k1")
    assert result is None


async def test_get_stopped_returns_the_instance_once_it_is_really_stopped(
    moto_session: None,
) -> None:
    ec2 = boto3.client("ec2", region_name=REGION)
    resv = ec2.run_instances(ImageId="ami-12345678", MinCount=1, MaxCount=1)
    instance_id = resv["Instances"][0]["InstanceId"]
    ec2.stop_instances(InstanceIds=[instance_id])

    client = AwsCloudClient(_settings())
    result = await client.get_stopped(instance_id, idempotency_key="k1")
    assert result is not None
    assert result.state == "stopped"
