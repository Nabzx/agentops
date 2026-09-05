# 0025. Toward "the open-source Salus": auto-decide, retry-feedback, a policy DSL, a proxy

- **Status:** Proposed
- **Date:** 2026-09-05
- **Driven by:** #83 (`wayfinder:research`)

## Context

The maintainer's own framing: "I think we can make ephor the open source version of Salus."
Salus (YC W26, closed-source, $4M raised) is a runtime guardrails proxy: it intercepts every
agent tool call before execution, validates it against policy, and - when it blocks one - returns
structured feedback so the agent can self-correct in the same turn. Confirmed real, not assumed:
[usesalus.ai](https://usesalus.ai/), [Y Combinator's own
description](https://x.com/ycombinator/status/2021645412487110868). Its own feature list names
"idempotency checks" explicitly - real, direct overlap with this project's most chaos-tested,
security-benchmarked guarantee.

**Why this needed research before code, not just a feature list.** Salus's loop needs most
actions decided without a human, fast enough for the agent to retry in the same turn. Every
foundational decision in this project since ADR-0009 has stated the opposite: a human is always
the actual gate. ADR-0021/0023 made the Critic advisory-only, never a veto in either direction,
specifically to preserve that. "Open-source Salus" looked, at first read, like it required
reopening that principle wholesale - a product-direction-shaped decision, the same weight as
ADR-0014, not an engineering one. The research below found the actual shape of that question is
narrower and more interesting than it first looked.

## Research findings

**1. The core already structurally supports a non-human decision - this was never actually
enforced, only followed by convention. Checked directly in the code, not assumed.**
`ephor.approvals.Decision.actor_id` is typed `uuid.UUID | None` - already optional.
`Decision.actor_role` is a plain `str`, never an enum, never validated against an allow-list
anywhere in `ephor.approvals`. `Decision.reason: str | None` already exists, unused by any
existing detector's rejection path. `ApprovalStore.transition()` checks only
`is_valid_approval_transition()` - a pure state-adjacency check - and has **no dependency at all**
on `append_decision()` ever having been called, by a human or otherwise; the two are entirely
separate calls, linked only by convention in every demo written so far. `assert_not_self_decision`
is a plain function a caller chooses to invoke before transitioning - it is not wired into
`transition()`/`append_decision()` itself. Grepping every demo in this repo (`actor_role=`) shows
`"agent"`, `"supervisor"`, `"system"` already used as free-form strings with zero validation.
**Conclusion: nothing in `ephor.approvals` needs to change to let something call
`append_decision(actor_role="policy", actor_id=None, reason="...")` and `transition(destination=
APPROVED)` today.** The real open question was never "can the core support this" - it already
can. It's "should any of this project's *own* shipped detectors start doing it, and does the
project's *stated* principle (README, ADR-0009's own prose) need to change to describe that
honestly" - a positioning and product question, not a schema one.

**2. The retry-feedback loop is a genuinely missing feature, not a redesign.** `Decision.reason`
already exists as the field to carry "why" - but no code path in this repo today ever surfaces a
rejection's reason back to anything an agent would read; a human reviews a rejected request
later, in a queue, with no live caller waiting on an answer. Building a synchronous "decide now,
return allow or blocked+structured-reason immediately" surface (a real request/response contract,
not just a data field) is new work, cleanly additive to the existing schema.

**3. The integration-model gap is real, and it's the biggest piece of new infrastructure here -
not a checkbox feature.** Salus's own description: "integration requires only an endpoint URL
change - no agent rewrite," across OpenAI/Anthropic/Gemini/LangChain/LangGraph/CrewAI/custom
tools. That's a live proxy sitting in an agent's tool-call path. `ephor` today is a library a
human-authored Detector imports and calls periodically, scanning an external system's state and
proposing - nothing in this project sits in a *live* request path today. Whatever shape "the
proxy" takes (an OpenAI-API-compatible passthrough, an MCP-facing shim, framework-specific
middleware), it's a new, standalone component built *on* the existing core, not a modification of
it - closer in size to building `stripe-recovery` itself than to adding one more Adapter.

**4. Policy DSL - real prior art exists, checked, not invented from scratch.**
[Open Policy Agent/Rego](https://www.openpolicyagent.org/docs/policy-language): mature, the
long-established general-purpose policy-as-code engine, a Datalog-derived language, a large
ecosystem, but a separate runtime/binary and a non-Python DSL to learn and ship alongside this
project's otherwise all-Python stack. **AWS Cedar**: newer, deliberately constrained
(default-deny, forbid-wins-over-permit, no side effects, easier to reason about compositionally
than Rego) - and per public reporting, AWS shipped Cedar inside Bedrock AgentCore Policy in March
2026 specifically to "intercept every agent-tool call at the gateway boundary" - the same shape of
problem, already being solved by a major vendor with a purpose-built language, not a hypothetical
fit. **A minimal homegrown format** (the allow-list-in-a-dict shape every detector already uses,
generalised into data instead of code): zero new dependencies, matches this project's declared
minimalism, but reinvents a smaller, less portable version of what Rego/Cedar already do well.
Left open, not decided here - a real three-way trade-off.

## Open questions for a grilling round (not decided here)

1. **Does ADR-0009's own stated principle change, or does auto-decide live entirely in a new,
   opt-in layer?** Two honest options: (a) rewrite the project's framing from "a human is always
   the actual gate" to "a human is the gate for anything policy doesn't confidently allow" - a
   real, deliberate reversal for the common case, or (b) keep "a human is always the actual gate"
   as this project's own unconditional promise, and build the policy/auto-decide layer as a
   distinct, clearly-labelled opt-in a caller must deliberately reach for - closer to how
   `ClaudeCritic` is real but never defaulted-to. These produce genuinely different README
   headlines, not just different code.
2. **Which policy engine**: Rego, Cedar, or a minimal homegrown format - and how much of Salus's
   own feature list (PII detection, budget/loop protection, evals) is in scope for v1 versus named
   and deferred.
3. **How much of "the proxy" is v1 scope.** A narrow, real slice (the retry-feedback API + policy
   engine, usable by anything that calls it directly) versus the full "endpoint URL swap, works
   across OpenAI/Anthropic/LangChain" integration surface Salus itself ships - the latter is
   plausibly its own multi-package effort, not one unit of work.
4. **Positioning itself**: "the open-source Salus" as the literal pitch, or "the audited,
   exactly-once execution layer a Salus-style proxy could be built on" - a narrower, still-true
   claim that doesn't require matching Salus's UX one-for-one. This is the same shape of call
   ADR-0014 made for product direction, not something to decide by momentum.

## Consequences

- Not `ready-for-agent` yet - four real open questions, at least one of them (question 1)
  touching this project's own foundational stated principle, need a grilling round first.
- If pursued: likely multiple units of work, not one - a policy engine/DSL, a retry-feedback API
  surface on top of the existing `Decision.reason` field, and (separately, larger) an actual
  proxy/interception component - each probably its own ADR and build, the way Track A/B were
  separate efforts here.
- `docs/adr/README.md`'s index gets a new row, status `Proposed` until grilled.
