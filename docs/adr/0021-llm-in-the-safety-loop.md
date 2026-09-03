# 0021. An LLM in the safety loop: critique, advisory-only, opt-in - built, not yet spent

- **Status:** Accepted
- **Date:** 2026-09-03
- **Driven by:** #61 (`wayfinder:research`), grilled with the maintainer in one round

## Context

Every detector's proposal logic so far is a rule engine: an exact decline-code allow-list, an
exact allowance sentinel, a boolean unassociated check. Nothing reasons; everything is checked.
That's been the right choice for three narrow, deliberately unambiguous v1 action sets - but it's
also why ADR-0020 explicitly deferred idle-EC2-instance detection: judging "idle" needs a
judgement call a rule engine can't safely make alone. A real LLM is the obvious way to make that
judgement call - the question is how to do it without weakening anything already proven.

**This also crosses a real, stated line.** README.md says plainly: "no paid API, no external
network, nothing real is ever contacted." `.github/workflows/ci.yml` states the same thing as a
top-of-file comment. Every "real" client this project has built - `StripeTestModeClient`, and
`cloud-waste`'s planned real AWS client - costs nothing to try, because they read/write a sandbox
account for free. An LLM call has a real, recurring, non-zero cost the first time anyone
exercises it. That's a different kind of line to cross than "here's an optional real API client,"
and worth naming as such rather than smoothing over.

## Research findings

**1. Propose vs. critique is not a coin flip - the architecture already tells you which is
safer to build first.** Proposing means the LLM originates a proposal's exact parameters
(charge id, amount, action type) from raw, possibly adversarial data - a real validation and
prompt-injection surface, and the harder half of "broad reasoning in, narrow action out"
(the maintainer's own framing of the open problem here). Critiquing means the LLM only ever
annotates a proposal a deterministic, already-tested detector produced - it never touches what
gets proposed, only whether a human should hesitate over it. **Recommendation: critique only for
v1.** Proposing is the more ambitious, more valuable version of this idea, and stays a real,
named v2 candidate once critique's plumbing is proven - not dropped, deferred the same way
ADR-0020 deferred idle-instance detection.

**2. Where the critique lives - checked against the real code, not assumed. No core interface
changes needed.** `ApprovalStore.create()` computes `snapshot_hash = compute_snapshot_hash(snapshot_json)`
from whatever dict the caller passes in (`ephor/src/ephor/approvals.py:310`) - confirmed by
reading it, not inferring it. A detector can add one more key, e.g. `snapshot["llm_critique"]`,
before calling `create()`, and it becomes part of the immutable, hashed record automatically.
This is exactly what ADR-0008 already intended ("each detector decides its own Snapshot shape")
- a critique is just one more opaque field, proven to fit without touching `ephor.approvals`,
`ephor.actions`, or `ephor.effects` at all. The human approver sees the detector's evidence and
the LLM's contemporaneous critique together, hashed together - neither can be quietly altered
afterward, and there's a real audit record of what was flagged at decision time, not just what
was decided.

**3. The critique must be advisory-only, never a veto, in either direction.** No approval
request this project has ever built can decide itself (`assert_not_self_decision`,
ADR-0009) - the human is always the actual gate. An LLM critique that could auto-reject or
auto-approve would be the first thing in this project capable of deciding without a human, and
that's a bigger, different decision than "add a critique." **Recommendation: the critique is
always informational.** This also directly bounds the worst case of a prompt-injection attempt
against it (see below): even a fully attacker-controlled critique text can only mislead a human
who still has to explicitly approve - it can never itself cause an action to execute or be
blocked. The proposal's own parameters (amount, decline code, allocation id) are still fetched
and validated by the detector from the real API, never derived from the same freeform text the
critique reads.

**4. The paid-API line: opt-in, same shape as every other real client, but the first one that
costs money to try.** `STRIPE_RECOVERY_SECRET_KEY` set → real Stripe; unset → `FakeStripeClient`,
zero cost. The same pattern applies here: an env var (e.g. `EPHOR_CRITIC_API_KEY`) present →
a real `Critic` calls a real LLM; absent → a `FakeCritic` returns a canned, deterministic
critique, and the demo/CI path is completely unaffected either way - this is the fourth
client-shaped seam in this project (Stripe, chain, cloud, now critic), same convention every
time. Unlike the other three, though, *setting* the env var here means the next run genuinely
costs money, not just "now it's real instead of fake" - worth a clear warning in whatever
package ships this, not left implicit.

**5. Testing something non-deterministic - the `FakeCritic` answers most of it.** Every test in
this repo, including the chaos harnesses, is deterministic by design (seeded randomness). A real
LLM call is not. `FakeCritic`-backed tests stay fully deterministic and are what CI runs, same as
`FakeStripeClient`/`FakeChainClient` today. A real `Critic` would only ever be tested by
structural assertions (does it return a well-formed `Critique` within a timeout, does a
known-clear-cut bad case get flagged) - never exact-text assertions, and never run in CI, same
restriction ADR-0013/0020 already put on real Stripe/AWS clients.

## Grilled and locked

1. **Sequencing: cloud-waste v1 ships first, with no LLM at all - the Critic layer is added to it
   afterward, once it exists.** #64 gets built exactly as ADR-0020 scoped it, rule-based, the same
   way `stripe-recovery` and `wallet-guard` both shipped fake-only before anything "real" was
   added. The Critic layer then attaches to `cloud-waste` specifically, because idle-instance
   detection - deferred in ADR-0020 for exactly this reason - is the actual judgement-call problem
   this feature exists to solve, not `stripe-recovery`/`wallet-guard`'s already-unambiguous action
   sets.
2. **Vendor and model: Anthropic, a small/cheap model by default.** The maintainer is already
   building this entire project with Claude - no reason to reach for a different vendor. `Critic`
   stays a vendor-agnostic Protocol (same pattern as `ChainClient` naming no specific chain); the
   real implementation is named `ClaudeCritic`. A short annotation task doesn't need a large model
   - the default model choice should keep the (already trivial) per-call cost as low as it can be.
3. **Build it, don't spend on it - a real, explicit constraint, not a hedge.** `ClaudeCritic` gets
   built for real, using the real `anthropic` SDK, wired correctly end to end - but it is never
   invoked with a real API key during this work, and no test in this repo ever makes a live call
   to it, exactly the same restriction already on `StripeTestModeClient` and the planned real AWS
   client (ADR-0013/0020: real clients are built and structurally tested, never exercised in CI or
   by the agent building them). `FakeCritic` stays the only thing any test, demo, or CI job ever
   talks to. Whether and when a real key ever gets set is entirely the maintainer's call, made
   later, separately from this decision.

## Consequences

- No change needed to any locked `ephor` interface - the finding that a critique fits inside the
  existing opaque Snapshot holds exactly as researched.
- Unblocks a `ready-for-agent` build issue for the Critic layer, scoped to land on `cloud-waste`
  once #64 exists - not built in the same unit of work as #64 itself.
- README.md's "no paid API... nothing real is ever contacted" line will need a precise update once
  this ships: true by default and true of everything anyone doesn't deliberately opt into, not true
  of the one thing this ADR adds - worth getting the wording exactly right when the time comes,
  not glossed over.
