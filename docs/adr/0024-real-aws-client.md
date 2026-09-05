# 0024. A real AWS client: API mapping, credentials, testing - and a real gap in ADR-0022's threshold

- **Status:** Proposed
- **Date:** 2026-09-05
- **Driven by:** #78 (`wayfinder:research`)

## Context

`cloud-waste/client.py`'s `CloudClient` Protocol has one implementation, `FakeCloudClient`, for
both resource types it covers (Elastic IPs, EC2 instances). ADR-0013 already did this exercise
once for Stripe; ADR-0022 explicitly flagged that its idle-instance thresholds were "mirroring
AWS's own published Trusted Advisor convention... exact constants flagged for re-checking against
AWS's current docs before a real client ships." This is that re-check, plus the API mapping,
credential model, and testing strategy a real `AwsCloudClient` needs.

Checked against real sources throughout, not assumed: the `botocore` service models (via the
scratch venv already used for ADR-0020/0022's research) for every API shape below, and AWS's own
published Trusted Advisor documentation for the threshold re-check.

## Research findings

**1. Address side is unchanged from ADR-0020 - `DescribeAddresses`/`ReleaseAddress`, both confirmed
to support `DryRun`.** Nothing new here; this ADR's findings are additive to ADR-0020's, not a
revision of them.

**2. Instance/idle side: `DescribeInstances` (list), `StopInstances` (execute, `DryRun` confirmed
present), and CloudWatch `GetMetricData` - not `GetMetricStatistics` - for the CPU/network
evidence.** `GetMetricData` is the modern, batched API: one call carries up to 500
`MetricDataQuery` entries, so both metrics for every instance in the account can be fetched in a
single request rather than one `GetMetricStatistics` call per metric per instance. Confirmed shape
via `botocore`: `MetricDataQuery{Id, MetricStat: {Metric: {Namespace, MetricName, Dimensions:
[{Name, Value}]}, Period, Stat}}` → `MetricDataResult{Id, Timestamps, Values}`. `GetMetricData` has
no `DryRun` parameter at all (confirmed absent) - it's read-only, so there's nothing to gate.

**3. A real gap found, not just a number to update: AWS's own published algorithm is not the
single-average-against-a-threshold check ADR-0022 built.** Re-verified directly against AWS's
Trusted Advisor documentation (its own [GitHub tooling
repo](https://github.com/aws/Trusted-Advisor-Tools/blob/master/LowUtilizationEC2Instances/README.md)
states the check plainly): *"Checks the Amazon EC2 instances that were running at any time during
the last 14 days and alerts you if the daily CPU utilization was 10% or less and network I/O was 5
MB or less on 4 or more days."* That's a **per-day boolean, counted across a 14-day lookback, and
compared to a day-count threshold (≥4 days)** - not one scalar average checked once, which is what
`IdleInstanceAdapter`/`scan_for_idle_instances` (#73) actually does today against a single
`Instance.avg_cpu_percent`/`avg_network_bytes` pair. The 10% CPU and 5 MB network numbers
themselves were right; the shape of the check around them wasn't. This is a real design question
for the real client, not a constant to tweak - see grilling item 1.

**4. The network threshold is very likely a daily total, not an average rate - a second,
related naming/semantics gap.** "5 MB... on a day" reads as CloudWatch's `Sum` statistic for
`NetworkIn`+`NetworkOut` combined, over a `Period` of one day (86400 seconds) - a day's total bytes
moved, not an averaged rate the way `avg_network_bytes` is currently named and computed. If the
real client is built around AWS's actual per-day-count algorithm (finding 3), `avg_network_bytes`
would need renaming to something like `daily_network_bytes` to describe what it actually is -
another concrete consequence of finding 3, not a separate decision.

**5. Credentials should NOT copy ADR-0003/0013's Stripe-shaped `pydantic-settings` pattern
verbatim - AWS already has its own universal credential chain, and re-wrapping it would be a
regression, not a safety improvement.** Every real AWS user already has credentials resolved one
of several standard ways - `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`/`AWS_SESSION_TOKEN` env
vars, a named profile in `~/.aws/credentials`, an EC2/ECS/Lambda instance role, SSO - and `boto3`
already resolves all of them correctly via its own default provider chain. A project-specific
`pydantic-settings` class re-reading raw keys from custom env vars would work for the narrowest
case (static keys) while actively locking out everyone using a profile or an IAM role - a real
regression against how AWS tooling normally behaves, not an improvement on it.
**Recommendation: let `boto3.client(...)` resolve credentials itself; the only project-owned
setting is non-secret config** - `region_name` (required; see finding 7), optionally
`profile_name`. This is a narrower, different-shaped `Settings` class than Stripe's, not a
missing one.

**6. Sandbox-first, extended from ADR-0020's `DryRun` finding: AWS hands this project a stronger
double-gate than Stripe's test/live key split ever could, and it should be used.** The four
read-only calls (`DescribeAddresses`, `DescribeInstances`, `GetMetricData`) have no side effects
and nothing to gate - once a real client is constructed at all (one env var, exactly like
`StripeTestModeClient`), reads are always real, the same way `StripeTestModeClient.list_failed_charges()`
already always makes a real read. The two mutating calls (`ReleaseAddress`, `StopInstances`) get a
second, independent gate on top: `allow_live=False` (the only value ever passed anywhere in this
repo, same restriction as every other real client) sets `DryRun=True` unconditionally, so even a
fully-credentialed real client can list a real account's real resources and still structurally
cannot release an address or stop an instance unless `allow_live=True` is passed explicitly -
nobody in this repo will ever pass it. Stripe's `PaymentIntent.confirm` has no equivalent second
gate once a real key is used; AWS's `DryRun` gives this project a strictly stronger guarantee here
for free.

**7. Region is a real open gap ADR-0020 never had to address - `FakeCloudClient` has no concept of
one.** EC2 and CloudWatch are both region-scoped services; a real client needs a `region_name`.
**Recommendation for v1: a single, explicit, required region - no scanning "all enabled regions in
the account."** Matches every other client this project has built (one Stripe account, one chain,
now one AWS region) and keeps the same "no silent caps" discipline the chaos/security-benchmark
work has held elsewhere - documented as a named v1 limitation, not silently absent.

**8. Least-privilege IAM policy, concretely scoped, not just "restricted somehow":** exactly
`ec2:DescribeAddresses`, `ec2:ReleaseAddress`, `ec2:DescribeInstances`, `ec2:StopInstances`,
`cloudwatch:GetMetricData` - no access to any other action, resource type, or service. Ships as a
documented policy JSON in `cloud-waste/README.md`, the AWS-native equivalent of ADR-0013's
`rk_test_...` restricted Stripe key.

**9. Testing without a live account: a real, considered alternative to ADR-0013's pattern, not a
silent departure from it.** ADR-0013 tested `StripeTestModeClient` by monkeypatching the `stripe`
SDK's resource methods to return canned objects. For AWS, **`moto`** - a dedicated, actively
maintained library that intercepts calls at `botocore`'s transport layer and simulates real AWS
service behaviour (including realistic error codes like `InvalidAllocationID.NotFound`) entirely
in-memory - would exercise `boto3`'s actual request-building and response-parsing code against a
realistic backend, catching a class of bug (a wrong parameter name, a misread response field) that
a hand-typed canned dict can't. The trade-off is real: `moto` is a new, if narrowly test-only,
dependency; hand-monkeypatching keeps zero new dependencies but tests less of `boto3`'s own
plumbing. Left open for the grilling round (item 2) rather than decided here, since it's a real
choice with a real cost either way, not a mechanical follow-on from ADR-0013.

## Open questions for a grilling round (not decided here)

1. **Faithful "≥4-of-14-days" algorithm vs. keep the current single-average check as a documented
   v1 simplification** (finding 3/4) - and if faithful, `Instance`/`IdleInstanceCandidate`/
   `detector.py` (all already shipped, tested, fake-only) need real shape changes: per-day
   CPU/network booleans or a day-count, not one scalar pair. This is the one finding here that
   touches already-merged code, not just new code for the real client.
2. **`moto` vs. hand-monkeypatching `boto3`** for testing the real client without a live account
   (finding 9) - a real new-dependency-vs-plumbing-coverage trade-off.
3. Whether the maintainer wants to spend anything at all running this for real, even against a
   personal AWS account - same question ADR-0021 asked about the Critic, asked here for the first
   time about AWS: every real API call this makes, including reads, is a genuinely billable (if
   typically fractions-of-a-cent) AWS API call against whoever's account the credentials point to,
   unlike Stripe's fully free test-mode API. `FakeCloudClient` stays the only thing any test, demo,
   or CI job in this repo talks to either way.

## Consequences

- Not `ready-for-agent` yet - the three open questions above need a grilling round first, the same
  shape ADR-0021 went through before its own build issue was filed.
- If accepted as researched: `boto3` becomes a dependency of `cloud-waste` only, `moto` becomes a
  `cloud-waste` dev-only dependency if item 2 is decided that way; no change to `ephor`,
  `stripe-recovery`, or `wallet-guard`.
- `README.md`'s "no paid API" line, already carrying one precise exception for the Critic
  (ADR-0021/0023), would need a second, distinctly-worded one here if this is ever built and used
  for real: not "costs money per call" the way an LLM does, but "makes real, billable AWS API
  calls against a real account" - a different kind of real than either the Critic or Stripe's fully
  free test-mode API.
- `docs/adr/README.md`'s index gets a new row, status `Proposed` until grilled.
