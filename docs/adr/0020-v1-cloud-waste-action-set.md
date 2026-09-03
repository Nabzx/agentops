# 0020. v1 cloud-waste action set: release an unassociated Elastic IP, and only that

- **Status:** Accepted
- **Date:** 2026-09-03
- **Driven by:** #60 (`wayfinder:research`)

## Context

A third detector needs the same discipline ADR-0011 (Stripe) and ADR-0016 (wallet-guard) already
applied: one narrow action, chosen for safety and clarity over maximum dollar value, with a real
credential model and a real idempotency mechanism - not three candidates picked because they
sound impressive.

Four AWS waste patterns were considered, checked against the real EC2 API model (botocore's
`service-2.json`, not assumption - `DescribeAddresses`, `ReleaseAddress`, `StopInstances` and
`TerminateInstances` were all inspected directly):

1. **Unattached EBS volumes** - real, often large, $ savings. Rejected as v1: the action is
   deleting a volume, which is genuinely irreversible and risks real data loss if the "unattached
   means abandoned" assumption is ever wrong (e.g. deliberately detached mid-migration). No other
   detector in this project has an action with a real data-loss failure mode - this would be the
   first, and shouldn't be v1.
2. **Idle EC2 instances (low sustained CPU)** - real waste, but detection needs CloudWatch metrics
   (a time-series threshold, not a boolean state check) - a real added dependency and a judgement
   call ("how idle, for how long") neither Stripe's decline-code allow-list nor wallet-guard's
   exact-sentinel check needed. Rejected for v1 on complexity, not safety - a real v1.1 candidate
   once the pattern is proven again.
3. **Old/stale EBS snapshots** - similar shape to unattached volumes; same data-loss concern
   (a snapshot may be someone's only backup of something already deleted elsewhere). Deferred with
   volumes.
4. **Unassociated Elastic IP addresses** - **chosen.** AWS charges an explicit hourly fee for an
   Elastic IP not attached to a running instance - a real, well-known, easy-to-explain waste
   pattern. Confirmed directly in `DescribeAddresses`'s response shape: an `Address` carries both
   `AssociationId` and `InstanceId` - unassociated means both are absent, a plain boolean check,
   no metrics, no judgement call.

## Decision

**v1 ships exactly one action: release an Elastic IP address with no association, and only
that.**

1. **Detection is a boolean, not a threshold.** `DescribeAddresses` returns every EIP in the
   account; one with no `AssociationId` and no `InstanceId` is unassociated - unambiguous, no
   time window, no "how much is too much" judgement call.
2. **The action can never cause data loss - checked against AWS's own documentation, not
   inferred.** `ReleaseAddress`'s own docs state plainly: "Releasing an Elastic IP address
   automatically disassociates it from any instance," and warn to "update your DNS records and any
   servers or devices that communicate with" the address afterward. That's the entire real risk -
   something external had this specific address hardcoded. No data is destroyed; the address goes
   back to AWS's pool. This is the softest failure mode of any action-set decision so far in this
   project, softer than a Stripe retry (which at least touches money) and comparable to wallet-guard's
   revocation (recoverable by re-approving, or here, by allocating a new address).
3. **Sandbox-first means something different here than ADR-0003's Stripe-shaped model, and that's
   locked explicitly, not glossed over.** AWS has no parallel test/live account namespace the way
   Stripe's key prefix encodes it. The real, AWS-native equivalent - confirmed present on
   `ReleaseAddress`, `DescribeAddresses` and every other EC2 mutating call inspected - is the API's
   own `DryRun` parameter: passing it validates the call would succeed (permissions, target
   existence) without ever performing it, returning a distinct, recognisable response either way.
   Combined with a least-privilege IAM policy scoped to exactly `ec2:DescribeAddresses` and
   `ec2:ReleaseAddress` (no read/write to instances, volumes, or anything else), this is this
   provider's real sandbox-first story - not a weaker stand-in for ADR-0003's, a different
   mechanism doing the same job.
4. **Idempotency is earned differently again - a third distinct mechanism in this project, not a
   copy of the first two.** `ReleaseAddress` has no request-level dedup key the way Stripe's header
   or an EVM nonce provide. What it has instead: releasing an already-released allocation id fails
   with AWS's documented `InvalidAllocationID.NotFound`-shaped error, because the id genuinely no
   longer exists once released. That failure *is* the completion signal - a
   `check_completed`-equivalent (ADR-0018) for this Adapter is exactly "does this allocation id
   still exist"; if `DescribeAddresses` no longer returns it, the release already happened,
   full stop, no separate ledger needed.

## Alternatives considered

- **Unattached EBS volumes as v1** - rejected: real irreversible data-loss risk on the very first
  cloud action this project ships, where a stopped/reversible action or a monetary-but-recoverable
  one has been the bar for every prior action set.
- **Idle EC2 instances (stop, not terminate) as v1** - rejected for v1 specifically because of the
  CloudWatch-metrics dependency and the judgement call it introduces, not because "stop" itself is
  unsafe (it's genuinely the most reversible EC2 action available - the data survives, the instance
  restarts exactly as it was). A strong v1.1 candidate once this detector's shape is proven once.
- **A deny-list of "always safe to release" tags instead of an unconditional check** - rejected:
  the same reasoning as ADR-0011's decline-code allow-list. An allow-list (unassociated, full stop)
  fails safe; a deny-list (release unless tagged `keep`) fails open on anything nobody thought to
  tag.

## Consequences

- Unblocks a `ready-for-agent` build issue for the third detector - a fake-cloud-client-only
  skeleton first, the same shape #14 was for Stripe before #51 made it real.
- Unattached EBS volumes, stale snapshots and idle-instance stopping remain named, real v1.1/v1.2
  candidates - not dropped, deferred on the same terms ADR-0011 deferred dunning.
- The credential model here (DryRun + least-privilege IAM, no test/live account split) is this
  project's second distinct sandbox-first mechanism, alongside ADR-0003's Stripe-key-prefix model -
  worth keeping in mind that "sandbox-first" is a principle each Adapter earns its own way, not one
  mechanism reused verbatim.
