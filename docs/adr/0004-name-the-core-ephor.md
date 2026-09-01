# 0004. Name the core: Ephor

- **Status:** Accepted
- **Date:** 2026-09-01
- **Driven by:** #1 (`wayfinder:grilling`)

## Context

The safe-action core needs a public name before scaffolding (#9). It ships as a package inside
this repo, not a separate one (see the "single repo" decision folded into
[the ROADMAP update](../../ROADMAP.md) alongside this ADR) - so the name is a Python
package/module identity and a concept used throughout docs and code, not a GitHub org or a
`pip`-install slot under time pressure.

Two grilling rounds were run with the maintainer, moving through three separate framing changes
as the conversation progressed:

1. The original shortlist (Interlock / Airlock / Warrant) was picked to fit a "pip install this
   package" and "possibly its own repo" framing. Both premises later got dropped: the launch bar
   became clone-and-run, not `pip install`, and the core stays in this repo. Interlock was the
   strongest of the three (clean PyPI slot, blocking-mechanism metaphor) but the maintainer didn't
   like it once picked.
2. A round of English words in the "safety mechanism" register (Witness, Chaperone, Custodian,
   etc.) and then the "helpful business companion" register (Fixer, Caddie, Wingman, Mechanic,
   etc.) were considered against PyPI collision data, distinguishing a dormant/abandoned same-name
   package (low real risk) from an actively-maintained one in an adjacent domain (real risk).
3. A final round widened to real historical institutions across Greek, Roman, Arabic, Urdu,
   Persian and Latin whose actual function was checking, approving or auditing the exercise of
   power - not just words that sound protective. **Ephor** won this round decisively.

## Decision

**The core is named Ephor.**

Ephors were magistrates in ancient Sparta whose entire office existed to check and approve the
actions of the kings - a genuine historical precedent for "power doesn't act alone, an
independent party signs off first," predating this project's `Proposal → Approval → Effect` loop
by about 2,500 years. That is a stronger, more specific fit than a generic "guardian" or "watcher"
word, and gives the project a real story rather than an invented metaphor.

**Availability - known collision, accepted knowingly.** PyPI slot `ephor` is unclaimed. The
`github.com/ephor` account, however, is taken by an unrelated, active project (`ephor/vision`, a
TypeScript observability tool, 8 stars, updated within the last week). More materially,
`staqsIO/ephor` on GitHub (and a matching npm placeholder package, published 2026-07-17) describes
itself as *"a governed agent organization: a technology company where every operational role is an
AI agent, run under a human board and enforced by infrastructure, not prompts"* - a near-identical
pitch to this project's, at 1 star. A broader GitHub search for "ephor" returns 109 repositories,
several from the last year in adjacent spaces (security auditing, vulnerability management, an
MCP server).

The maintainer was shown this collision explicitly and chose to proceed with Ephor anyway: the
competing projects are small (1-8 stars), the exact scope differs, and the historical-institution
story was judged worth keeping despite the shared name. This is a conscious risk, not an oversight
- if search/discoverability becomes a real problem post-launch, revisit under a fresh Wayfinder
ticket rather than treating this ADR as having missed it.

## Alternatives considered

Full list discussed with the maintainer, for the record:

- **Interlock, Airlock, Warrant** - original shortlist; dropped once the launch framing changed
  and per maintainer preference. Warrant and Airlock both had real PyPI collisions in the
  auth/identity domain.
- **Witness, Chaperone, Custodian, Steward, Proctor, Notary, Escrow, Ratify, Attest** - safety/
  oversight register in plain English. Chaperone and Witness scored well; not chosen once the
  historical-institution framing landed better with the maintainer.
- **Fixer, Caddie, Concierge, Wingman, Mechanic, Valet, Deputy, Scout, Broker, Foreman** -
  "helpful business companion" register. Foreman was dropped for colliding with the real
  `theforeman.org` project.
- **Recoup, Endorse, Greenlight, Reclaim, Clear, Ledger, Verdict, Mandate, Clearance, Accord,
  Gardien, Veille, Aval, Fiador, Custode, Custodia, Bürge, Wächter, Mamori, Cavere** - verbs,
  abstract nouns and single borrowed words. Mamori and Fiador were maintainer favourites but lost
  out once the "real historical office" framing was introduced.
- **Amin, Wakeel, Kafeel, Zamin, Nigraan, Fidus, Hafiz, Phylax, Praetor** - Arabic/Urdu/Persian/
  Latin/Greek words for guardian, agent or authoriser. Hafiz, Phylax and Praetor were ruled out
  for colliding with actively-maintained, domain-adjacent PyPI packages (an LLM-agent memory
  layer, an LLM-output regression checker, and a provenance tool, respectively).
- **Euthyna, Muhtasib, Nomophylax, Augur, Tribune, Censor, Quaestor, Veto** - other real
  historical offices. Veto was ruled out for colliding with an actively-maintained "policy runtime
  for AI agent tool calls" package - nearly the same category as this project. Euthyna (the
  mandatory audit Athenian magistrates underwent on leaving office) was the closest runner-up to
  Ephor.

## Consequences

- Unblocks #9 (scaffold the core package layout) - no other open decision blocks it.
- The package directory, Python module name, and CLI/docs vocabulary going forward use `ephor`
  (lower-case, single word) as the identifier.
- `github.com/ephor` (the account/org) is not available - but the repo itself was renamed from
  `agentops` to `ephor` immediately after this ADR landed (`github.com/Nabzx/ephor`), so the
  single-repo decision holds, just under the new name. Note this makes the repo's own name lead
  with one internal package (the core) rather than the umbrella project - AgentOps the demo and
  the Stripe flagship both still live here too, as consumers of Ephor.
- `PyPI: ephor` is worth claiming defensively once the package is real, even though nothing
  publishes there yet.
- README/marketing copy should lean on the historical story (a 2,500-year-old check on power) to
  differentiate from the same-named "governed agent organization" project rather than relying on
  the bare word "Ephor" for search visibility.
