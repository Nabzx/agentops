# 0025. Toward "the open-source Salus": auto-decide, retry-feedback, a policy DSL, a proxy

- **Status:** Accepted
- **Date:** 2026-09-05
- **Driven by:** #83 (`wayfinder:research`), grilled with the maintainer in one round

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

## Grilled and locked

1. **ADR-0009's principle stays absolute. Auto-decide is a new, separate, opt-in layer, never the
   default.** Every existing detector, and any action-type nobody has deliberately opted in,
   remains exactly as human-gated as it is today - zero behaviour change. A caller explicitly
   configures specific action-types to route through the new policy layer instead; every
   auto-decision still lands in the same hash-chained audit trail, `actor_role="policy"`,
   `actor_id=None`, fully visible and reversible-by-audit even though no human clicked anything.
   This is not behind Salus's own model either - Salus itself supports human-in-the-loop
   escalation as one path, not pure auto-decide only. The auto-decide layer handles **both
   directions** - a confident allow *and* a confident block-with-reason - for whatever's opted in;
   anything the policy doesn't confidently decide either way falls through to a human exactly as
   today, never guessed at.
2. **Policy engine: AWS Cedar**, chosen for what it actually is, not just convenience: its
   authorization semantics are formally verified (a real, citable rigor claim fitting this
   project's own chaos-tested, security-benchmarked character), it ships official Python bindings
   (`cedar-policy` on PyPI, no external binary or WASM step), and it's purpose-built for
   authorization decisions specifically (default-deny, forbid-wins-over-permit, no side effects) -
   the same engine AWS shipped inside Bedrock AgentCore Policy for this exact
   agent-tool-call-interception shape of problem. Lives in **`ephor.policy`, in core** - not
   vendor-specific or paid the way `ClaudeCritic` is (ADR-0023 kept `anthropic` out of core for
   exactly that reason); Cedar is free, local, has no credential/cost gate to hold it back from,
   and the whole point of this layer is that any future detector can opt in the same way any
   detector already can use `ephor.critic`.
3. **The proxy is real v1 scope, not deferred** - at least one working integration (an
   OpenAI-chat-completions-compatible endpoint a caller points their `base_url` at) ships in this
   wave, not a named-later v2. This is a materially bigger scope than a narrow "just the API"
   cut - four sequenced units of work, not one (see Consequences).
4. **Positioning: "the open-source, self-hostable, provably-exactly-once alternative to Salus"**
   - not the literal "we are Salus" claim, and not merely "a layer Salus-style tooling could run
   on." What makes this an honest *stronger* claim rather than hype: fully open and self-hostable
   (versus a closed API to trust blindly), a 50,000-trial chaos-tested exactly-once guarantee and
   a named, scored security benchmark (versus asserted reliability), and - once Cedar lands -
   formally-verified policy semantics. Not a claim to more maturity or more integrations than a
   funded team with real customers; a claim to more provable rigor on specific, checkable axes.

## Consequences

- Unblocks four sequenced `ready-for-agent`/`wayfinder:research` build issues, phased in
  `ROADMAP.md`'s new Phase 6 - not one unit of work: (1) `ephor.policy`, the Cedar-backed policy
  engine, in core; (2) the opt-in auto-decide layer wired onto `ephor.approvals`, both directions,
  fully audited; (3) a synchronous decide-and-explain API on top of both; (4) the OpenAI-compatible
  proxy shim itself - the one genuinely novel, unproven-in-this-project technique (intercepting
  and rewriting a live LLM API response mid-flight), scoped as its own research pass before a
  build issue, not assumed.
- `ephor` gains its first new core dependency since `pydantic` (`cedar-policy`) - a deliberate,
  reasoned addition (free, local, no credential/cost gate), not a repeat of the paid-vendor
  question ADR-0021/0023 drew a hard line on.
- `README.md`'s opening framing will need a real update once phase 6's first pieces ship - not
  before; nothing changes about what this project claims until something backs the claim.
- `docs/adr/README.md`'s index status updates to `Accepted`.
