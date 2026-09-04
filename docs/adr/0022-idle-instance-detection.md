# 0022. Idle-EC2-instance detection (v1.1): a real judgement call, and what the Critic is actually for

- **Status:** Accepted - direction and mechanism locked; the exact numeric threshold is flagged
  for re-verification against AWS's current published guidance before a real client ships (see
  Consequences). Nothing about that gap blocks the build, which is fake-client-only regardless.
- **Date:** 2026-09-04
- **Driven by:** #71 (`wayfinder:research`)

## Context

ADR-0020 deferred this exact case: judging "idle" needs a judgement call a rule engine can't
safely make alone. ADR-0021 built the `Critic` specifically for it. Checked against the real
CloudWatch and EC2 API models (botocore, not assumption - `GetMetricStatistics`,
`DescribeInstances`, `StopInstances` all inspected directly) before deciding anything.

## Research findings

**1. The metric: `CPUUtilization`, confirmed to need no extra setup.** `GetMetricStatistics`
against `Namespace="AWS/EC2"`, `MetricName="CPUUtilization"` needs nothing beyond what every EC2
instance already reports by default - unlike memory utilization, which needs the CloudWatch
agent installed on the instance, a real operational dependency this project has no way to assume.
`NetworkIn`/`NetworkOut` are available the same way, and combining CPU with network avoids
flagging a low-CPU instance that's still doing real I/O-bound work.

**2. The threshold mirrors an existing, published convention rather than inventing one.** AWS's
own Trusted Advisor "Low Utilization Amazon EC2 Instances" check is publicly documented as
roughly: low average CPU and low network I/O sustained across most of a multi-day window (AWS's
own materials describe something in the shape of ≤10% average CPU and ≤5MB network I/O on 4 or
more of the last 14 days). **The exact constants need re-checking against AWS's current published
figures before a real client ships** - this ADR locks the *shape* of the rule (an established,
documented multi-day multi-metric convention, not a number this project made up), not the precise
digits, which are worth getting from the source at build time rather than trusted from memory
here.

**3. The action: stop, not terminate - confirmed directly in AWS's own docs, not inferred.**
`StopInstances`'s documentation states plainly: "you can restart your instance at any time using
the StartInstances API," and once stopped, "you are not billed for instance usage." This is the
same reasoning ADR-0020 already used for Elastic IPs, applied to the action ADR-0020 itself
predicted would need it: the softest, most reversible EC2 action available, and the one that
actually addresses the largest cost driver (compute, billed hourly) rather than a smaller
storage/address fee.

**4. Idempotency here is a fourth distinct shape - not a repeat of `ReleaseAddress`'s.**
`ReleaseAddress` fails on a repeat call because the target genuinely no longer exists.
`StopInstances` does not fail on a repeat call - AWS's own instance state machine treats stopping
an already-stopped instance as a no-op, not an error. `check_completed` for this Adapter can't
use "did the call fail" as its signal (there's nothing to catch); it has to ask
`DescribeInstances` whether the instance's `State.Name` is already `"stopped"`, and treat that as
completion regardless of which attempt actually caused it.

**5. What the Critic is actually for here, concretely - checked against the real `Instance`
shape, not assumed.** `DescribeInstances` returns `LaunchTime`, `State`, `Tags`, `InstanceId` and
`InstanceType` directly. Unlike an unassociated Elastic IP (nothing ambiguous to critique), "low
utilization for N days" is a heuristic that can be wrong in specific, nameable ways: an instance
launched two days ago that simply hasn't started serving traffic yet, or one tagged as a
disaster-recovery standby that is *supposed* to sit idle. The evidence handed to the Critic should
include `launch_time` (age), `tags`, and the raw metric values - not just "flagged as idle" -
so a genuine second opinion is possible, not a restatement of the rule's own boolean.

## Alternatives considered

- **A single-metric (CPU-only) threshold, invented for this project** - rejected: mirroring an
  existing, publicly documented convention is more defensible than a number nobody can point to a
  source for, and combining CPU with network catches a case CPU alone misses (an idle-CPU
  instance still doing real network I/O, e.g. a lightweight proxy).
- **Terminate instead of stop** - rejected for the same reason ADR-0020 rejected deleting EBS
  volumes: real, irreversible loss (the instance itself, its ephemeral state) for a smaller
  benefit than stopping already provides (compute billing stops immediately either way).
- **Let the Critic's recommendation gate whether a proposal is even created** - rejected: ADR-0021
  already locked "always advisory, never a veto in either direction." The rule decides whether to
  propose; the Critic only ever adds a second opinion for the human, exactly as already locked -
  not re-litigated here.

## Consequences

- Unblocks a `ready-for-agent` build issue for `cloud-waste` v1.1 - fake-client-only, same as
  every other detector's first build in this project. The threshold constants named above are
  fine to hardcode in the fake/seeded demo data; they only need re-verification against AWS's
  current documentation when a real client is eventually built (ADR-0013/0020's same deferred
  pattern - not this unit of work).
- `CloudWasteAdapter`'s `check_completed` grows a second, genuinely different implementation
  shape (state-check, not failure-as-signal) alongside `release_address`'s existing one - both
  live in the same package, on two different actions.
- The evidence dict handed to the Critic grows real fields (`launch_time`, `tags`, metric values)
  - the first time a detector's evidence is built specifically *for* the Critic to reason over,
  not just for a human to read.
