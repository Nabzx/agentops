# 0023. Broaden the Critic to every detector; move the seam into ephor core

- **Status:** Accepted
- **Date:** 2026-09-05
- **Driven by:** #75 (`ready-for-agent`)

## Context

ADR-0021 scoped the Critic to `cloud-waste` specifically: idle-instance detection is a real
judgement call a rule engine can't safely make alone, unlike `stripe-recovery`'s exact
decline-code allow-list or `wallet-guard`'s exact unlimited-allowance check. That reasoning still
holds - it argued the Critic wasn't *necessary* on the other two detectors. It never argued the
Critic would be harmful there, and on rereading it doesn't actually follow that an unambiguous
rule gets nothing from a second opinion.

Also, `Critique`/`Critic`/`FakeCritic` currently live inside `cloud_waste/critic.py` - fine while
exactly one package used them, awkward now that a second and third want to.

## Decision

**Extend the optional Critic to `stripe-recovery` and `wallet-guard` too.** An advisory-only
critique (ADR-0021 point 3: never a veto, in either direction) costs nothing safety-wise even on
an already-unambiguous rule - the rule still decides whether to propose at all, exactly as before.
What it adds: a second pair of eyes can flag an evidence-level anomaly the fixed rule was never
written to look at - an in-allow-list decline code on an unusually large charge, or a revocation
on a wallet that transacted with the spender an hour ago. The human approver still decides either
way; broadening this changes nothing about who holds the gate.

**Move `Critique`, the `Critic` Protocol, and `FakeCritic` into `ephor.critic`.** None of the three
need anything beyond stdlib/dataclasses/typing - zero new dependencies for `ephor`. This is the
shared, vendor-agnostic seam every detector's Snapshot can use, same shape as `ephor.actions`/
`ephor.effects` being extracted once more than one flagship needed them (ADR-0012).

**`ClaudeCritic`/`ClaudeCriticSettings` (the real, paid-API implementation) stay in
`cloud_waste/critic.py`, importing `Critique`/`Critic` from `ephor.critic`.** Keeps `anthropic` out
of `ephor`'s own dependency list - "the core never touches a paid API" stays true of `ephor`
itself, not just true by convention. `stripe-recovery` and `wallet-guard` get `FakeCritic` wired
into their demos, proving the same Snapshot-attachment shape; neither gets a real-Claude option in
this change. That's a separate, later decision if the maintainer ever wants it, not bundled in
here - ADR-0021's actual money/vendor grilling only ever covered `cloud-waste`.

## Alternatives considered

- **Leave the Critic cloud-waste-only** - the literal reading of ADR-0021's scoping. Rejected: the
  scoping there was about where the Critic is *needed* most, not a ceiling on where it's allowed.
- **Duplicate `cloud_waste/critic.py` into the other two packages** - fastest, but three copies of
  the same `Critique`/`Critic`/`FakeCritic` to keep in sync forever, exactly the copy-paste problem
  the whole `ephor` extraction exists to avoid.
- **Move `ClaudeCritic` into `ephor` too** (as an optional extra dependency) - keeps everything in
  one file, but adds packaging complexity (a `[project.optional-dependencies]` group, `uv` extras
  wiring) disproportionate to what this change actually needs: nobody has asked for a real Critic
  on `stripe-recovery`/`wallet-guard` yet, only the interface + `FakeCritic`.

## Consequences

- `ephor.critic` is a new core module (`Critique`, `Critic`, `FakeCritic`), covered by
  `ephor/tests/test_critic.py`.
- `cloud_waste/critic.py` shrinks to `ClaudeCritic`/`ClaudeCriticSettings` only, importing the
  shared types - no behaviour change, `cloud-waste`'s own tests/demo still pass unmodified in
  substance (only import paths move).
- `stripe_recovery.detector.scan_for_recoverable_charges` and
  `wallet_guard.detector.scan_for_risky_approvals` both gain `critic: Critic | None = None`,
  default `None` - zero behaviour change for any existing caller that doesn't pass one.
- Both flagships' `demo.py` wire in `FakeCritic()` and print the critique, same as `cloud-waste`'s
  demo already does - three flagships now visibly share one seam.
- `README.md`'s Status section gets a small update: "an optional LLM second opinion" is now a
  platform-wide property of the core, not a `cloud-waste`-only feature; the one real, paid
  implementation still lives only where ADR-0021 put it.
