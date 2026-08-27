# Agents

How work happens in this repo. Two kinds of agent, one human gate.

## The loop

1. **Wayfinder** turns open questions into locked specs. It opens a `wayfinder:map` issue that
   names the decisions a phase depends on, then settles each one:
   - `wayfinder:research` — **autonomous (AFK).** Investigate and write up a recommendation.
   - `wayfinder:grilling` — **human-in-the-loop.** Pressure-test a decision with the maintainer before locking it.
   - `wayfinder:prototype` — **human-in-the-loop.** Build a throwaway spike to answer a question, then discard it.
   A settled decision is written up as an ADR (`docs/adr/`) and its build work is labelled `ready-for-agent`.

2. **Implementation agents** pick up **only `ready-for-agent`** issues, work on a **worktree
   branch** (one issue per branch), and open a PR that references the issue.

3. **A human reviews and merges.** No self-merges. Every phase ends in a tagged build.

## Ground rules

- Build nothing that isn't `ready-for-agent`. If a spec is ambiguous, kick it back to Wayfinder — don't guess.
- One issue per branch; keep tracks (`track-a`, `track-b`) on separate files where possible so agents don't collide.
- Use the exact terms in [CONTEXT.md](CONTEXT.md). If a needed term is missing, add it there in the same PR.
- Determinism holds: the core stays offline-testable; external adapters use sandbox credentials only.

## Labels

- **Phase:** `phase-0` … `phase-5` — where the work sits on the [roadmap](ROADMAP.md).
- **Track:** `track-a` (core framework), `track-b` (flagship detector).
- **Wayfinder:** `wayfinder:map` / `:research` / `:grilling` / `:prototype` / `:task` — deciding *what and how*.
- **`ready-for-agent`** — spec is locked; an implementation agent may build it.

## Domain docs

- [CONTEXT.md](CONTEXT.md) — the ubiquitous language. Read it before writing code or issues.
- `docs/adr/` — architecture decision records. One ADR per locked decision.
- [ROADMAP.md](ROADMAP.md) — phases, tracks, tagged builds, open decisions.
- The per-component notes in `docs/` (see [docs/architecture.md](docs/architecture.md)) describe the built platform (S0–S10).
