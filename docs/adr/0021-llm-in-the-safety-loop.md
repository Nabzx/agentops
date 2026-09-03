# 0021. An LLM in the safety loop: critique, advisory-only, opt-in - and what's still open

- **Status:** Proposed - a recommendation, not a locked decision. Crosses a stated repo-wide
  invariant (below), so it stays "Proposed" until the maintainer decides to grill and lock it,
  not "Accepted" the way ADR-0020's research was.
- **Date:** 2026-09-03
- **Driven by:** #61 (`wayfinder:research`)

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

## What's still open - for a grilling round, not decided here

- **Which detector gets this first**, and specifically: is it worth building *before* or
  *alongside* #64 (the cloud-waste flagship) - the judgement-call problem this whole idea exists
  to solve (idle-instance detection) lives there, not in `stripe-recovery`/`wallet-guard`'s
  already-narrow, already-unambiguous action sets.
- **Which model, and who provides the key.** Not a technical question - a decision about the
  project's own convention (a specific vendor's API? does `Critic` name a vendor or stay
  vendor-agnostic like `ChainClient` does for "some EVM chain"?).
- **Whether the maintainer actually wants to spend real money to demonstrate this at all**, given
  the project's own stated position (no paid API, anywhere) has held since Phase 0 - crossing it
  is a real, deliberate call, not a default this research should make on its own.

## Consequences

- No change proposed to any locked `ephor` interface - the finding that a critique fits inside
  the existing opaque Snapshot is itself a real result, not a placeholder for one.
- Nothing here is `ready-for-agent` yet, unlike ADR-0020 - this ADR stays Proposed until the
  three open questions above are actually grilled with the maintainer.
