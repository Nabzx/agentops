# Contributing

AgentOps runs on a Wayfinder loop, not a free-for-all issue queue. Read [AGENTS.md](AGENTS.md)
first - it's short and explains the whole thing. This file is the quick version for a
human contributor.

## The loop, in short

1. Open questions are settled by **Wayfinder** before anyone builds anything: a `wayfinder:map`
   issue names the decisions a phase depends on, and each is closed by `wayfinder:research`
   (autonomous), `wayfinder:grilling` (pressure-tested with a maintainer) or a throwaway
   `wayfinder:prototype`. A settled decision becomes an ADR in [`docs/adr/`](docs/adr/) and its
   build work is labelled `ready-for-agent`.
2. **Only pick up `ready-for-agent` issues.** If an issue looks interesting but isn't labelled
   that way, its spec isn't locked yet - comment on it or open a `wayfinder:map` question instead
   of guessing.
3. **One issue, one branch, one PR.** Branch off `main`, reference the issue in the PR body
   (`Closes #NN`), keep the PR scoped to that issue.
4. **No self-merges.** Every PR needs a review before it lands, maintainer included.

## Before you start

- Read [CONTEXT.md](CONTEXT.md) - it's the project's glossary. Use its terms exactly; if you need
  a term it doesn't have, add it in the same PR.
- Check [`docs/adr/`](docs/adr/) for decisions that touch the area you're working in. If your
  change would contradict an Accepted ADR, say so in the PR rather than silently overriding it.
- Check [ROADMAP.md](ROADMAP.md) for which phase/track the issue belongs to.

## Running it locally

```bash
make up && make seed      # stack + synthetic data
make demo                 # approval -> simulated execution, exactly once
make verify-all           # every hard-gated eval + audit chain + deps + frontend checks
```

See [docs/demo-runbook.md](docs/demo-runbook.md) for the full walkthrough and
[docs/architecture.md](docs/architecture.md) for how the pieces fit together.

## Filing an issue

Use the templates - they route you to the right shape (bug, feature request, or a Wayfinder
ticket) and ask for what the loop actually needs (repro steps, or the decision a Wayfinder ticket
is meant to settle).

## Determinism

Nothing in this repo talks to a paid API, a hosted model, or real money. CI enforces this
(`LLM_DEFAULT_PROVIDER=mock`, Stripe test mode only). Keep it that way - PRs that add a dependency
on live credentials or an unpinned network call will be asked to route around it.
