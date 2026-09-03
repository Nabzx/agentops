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

This package runs with **zero setup, no AWS account, no boto3**: `FakeCloudClient`
(`src/cloud_waste/client.py`) is an in-memory stand-in seeded with fake addresses, sitting behind
the same `CloudClient` interface a real EC2-backed implementation would use.

## Try it

```bash
cd cloud-waste
uv sync
uv run python -m cloud_waste.demo
```

Walks through the whole loop on two fake addresses - one unassociated, one attached to an
instance - and prints the audit trail at the end.

## Developing

```bash
uv run pytest
uv run ruff check .
uv run mypy .
```
