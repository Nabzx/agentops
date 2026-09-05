# cloud-waste

The third detector built on [Ephor](../ephor/), and a proof that the propose → approve →
execute → audit loop generalises to a third, genuinely different domain.

It scans an AWS account's Elastic IP addresses, flags any with no association - no instance
using it, nothing pointing at it - and proposes releasing it. AWS charges for an idle Elastic IP;
releasing one can never destroy data, unlike deleting a volume or a snapshot. See
[ADR-0020](../docs/adr/0020-v1-cloud-waste-action-set.md) for why this is the narrowest, safest
first action, checked against the real EC2 API model - and for why exactly-once here rests on a
third distinct mechanism again: releasing an already-released allocation id fails because the id
genuinely no longer exists, and that failure is the completion signal.

It also scans EC2 instances for sustained low utilisation and proposes stopping them (never
terminating - the data survives, the instance restarts exactly as it was) - see
[ADR-0022](../docs/adr/0022-idle-instance-detection.md).

This package runs with **zero setup, no AWS account, no boto3, by default**: `FakeCloudClient`
(`src/cloud_waste/client.py`) is an in-memory stand-in seeded with fake addresses and instances,
sitting behind the same `CloudClient` interface `AwsCloudClient` - the real, EC2/CloudWatch-backed
implementation - uses.

## Try it

```bash
cd cloud-waste
uv sync
uv run python -m cloud_waste.demo
```

Walks through the whole loop twice on fake data - one unassociated address released, one idle
instance stopped - and prints the audit trail at the end.

## A real AWS account (optional, and never invoked with real credentials by this repo)

`AwsCloudClient` wraps real `boto3` EC2/CloudWatch calls behind the same `CloudClient` interface,
per [ADR-0024](../docs/adr/0024-real-aws-client.md). Setting `CLOUD_WASTE_AWS_REGION` switches the
demo to it - no secret key goes in this project's own config: credentials resolve through
`boto3`'s own default chain (env vars, a named profile, an IAM role, SSO), exactly the way any
other AWS tool on your machine already works.

```bash
export CLOUD_WASTE_AWS_REGION=us-east-1   # your own region and (via boto3) credentials
uv run python -m cloud_waste.demo
```

**Nothing gets released or stopped for real, even then.** `AwsCloudClient` always passes `DryRun`
on its two mutating calls unless constructed with `allow_live=True` - which nothing in this repo
ever does. A real client can list a real account's real resources and still structurally never
mutate anything without that second, explicit opt-in.

**Least-privilege IAM policy** - the only permissions this ever needs, nothing else:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ec2:DescribeAddresses",
        "ec2:ReleaseAddress",
        "ec2:DescribeInstances",
        "ec2:StopInstances",
        "cloudwatch:GetMetricData"
      ],
      "Resource": "*"
    }
  ]
}
```

**Testing**: `AwsCloudClient`'s own logic is tested against
[`moto`](https://github.com/getmoto/moto), which simulates AWS at the transport layer - never a
live account, never real credentials, and never run by anything in this repo's own CI, demo, or
tests with `allow_live=True` set against anything but `moto`'s fully-simulated backend.

## The Critic (optional, and never free)

A `Critic` gives a proposal a second opinion before a human sees it - see
[ADR-0021](../docs/adr/0021-llm-in-the-safety-loop.md). It's always advisory: it can never
approve or reject anything, and it never touches what gets proposed, only whether a human should
hesitate over it.

`FakeCritic` - canned, deterministic, free - is the default, and the only thing this package's
own tests, demo, and CI ever talk to. Setting `EPHOR_CRITIC_API_KEY` switches the demo to
`ClaudeCritic`, a real, working implementation that makes a real, paid call to Claude for every
proposal scanned. It costs a fraction of a cent per call on the default model, but it is not
free, and nothing in this repo ever sets that variable for you.

```bash
export EPHOR_CRITIC_API_KEY=sk-ant-...   # your own key - this will cost you real money
uv run python -m cloud_waste.demo
```

## Developing

```bash
uv run pytest
uv run ruff check .
uv run mypy .
```
