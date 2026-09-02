# Building Ephor: what's done so far

A plain-language walkthrough of the OSS pivot — what problem it solves, how the work has been
run, and what's actually been built, in order.

## The problem

AgentOps (this repo) started as a complete demo: a fictional support-ops app where an AI agent
handles tickets, and anything consequential — a refund, a subscription change — stops for a human
to approve before it happens. It works end to end, but it's just one app. The genuinely reusable
part — *propose an action, get a human's sign-off on exactly what will happen, execute it exactly
once, and prove afterwards what occurred* — was welded into that one demo. Nobody could take just
the safety mechanism and use it in a different AI agent project.

**Ephor** is that safety mechanism, pulled out into its own package, named after the Spartan
magistrates whose job was to check the king's power before it acted — the same idea, about 2,500
years earlier than this project's version of it.

## How the work is run

Before anything gets built, an open question is settled and written down as a short decision
record (an ADR — Architecture Decision Record). This stops the same design argument happening
twice, and means a stranger reading the repo can see *why* something was built the way it was, not
just *what* was built. Ten of these have been written so far, each a page or two: the framework's
name, the licence, how credentials are handled, the exact contract between the core and any
integration, and so on.

## What's been built

### 1. Getting the repo itself in order

Before touching any code: branch protection policy, CI that actually runs on every change,
contribution guidelines, and a clean issue-tracking process. Small, but it's what makes it
possible to keep score of what's actually finished versus just started.

### 2. Naming and licensing the core

The reusable package needed a name and a licence before anything could be built inside it.
**Ephor** was chosen after weighing about 35 candidates across several languages — the winner
because it's a real historical institution whose entire purpose maps onto what this package does:
an independent check on power, before it acts. The core is licensed Apache-2.0 (permissively,
matching how comparable open-source infrastructure projects — Temporal, Airbyte — are licensed),
so it stays genuinely free to build on.

### 3. Locking the hard technical decisions

Three decisions had to be settled before any code could move, because getting them wrong later
would mean redoing everything built on top:

- **What "exactly once" actually means.** If a worker process crashes halfway through executing an
  action, how do you guarantee it never runs twice (e.g. a customer charged twice) and never runs
  zero times (money silently never recovered)? The answer: the core keeps its own record of every
  attempt, and any integration that can't guarantee "doing it twice is safe" has to hand off to a
  human instead of blindly retrying. This is written up as a real, automated test — not just a
  design doc — that proves the guarantee holds, described below.
- **The interface every integration implements.** So the core never needs to know anything about
  Stripe, or any other specific system — it only knows "propose a thing, execute a thing," and each
  integration fills in the specifics behind that one interface. This was checked against a real
  throwaway prototype (a fake integration plus a Stripe-shaped stub) before being locked in.
- **What a "Snapshot" contains.** Every approval is based on a frozen, tamper-evident description
  of exactly what's about to happen. Originally this was full of fields specific to the support-ops
  demo (draft email text, policy citations). It's now a generic, opaque record that any integration
  can fill with whatever it needs — Stripe would put in a charge amount and the reason it thinks
  it's recoverable, instead of an email draft.

### 4. Extracting the three real pieces

With those decisions locked, the actual mechanism moved into the reusable package, one piece at a
time — each one built, tested on its own, and proven not to break the original demo before moving
to the next:

- **The audit trail.** Every consequential event is recorded as an entry that's chained to the one
  before it by a cryptographic hash — like a mini blockchain. If anyone edits or deletes an entry
  after the fact, the chain breaks visibly. This is what makes the audit trail *provable*, not just
  a log that says it's tamper-proof.
- **The approval gate.** The rules for what counts as a legal decision (you can't un-reject
  something; you can retry a failed execution but can't go back to "pending"), and — importantly —
  a rule that a person can never approve their own request. That specific rule used to be checked
  in three separate places in the code; it now lives in one place everyone shares.
- **The outbox and worker.** The actual "do this exactly once, even if the process crashes"
  machinery: claiming jobs safely when multiple workers are running, retrying with a backoff delay
  that spreads load instead of hammering, and a real test that deliberately crashes a fake
  execution at three different points to prove nothing ever runs twice.

Throughout all three extractions, the original demo's own test suite (423 tests) kept passing
unchanged, and the same Docker-based demo (`make up`, `make demo`) kept working exactly as before —
proving the extraction didn't quietly break the thing it was extracted from.

## What's next

One decision is still open: exactly which Stripe actions the first real-world example should
cover (retrying a failed charge, chasing a stuck subscription, and so on). Once that's settled,
the actual flagship — a bot that scans a Stripe account for recoverable revenue and proposes fixes
through the safety mechanism above — is next. After that, the plan is more of the same shape:
additional "detectors" for other kinds of business waste, all sharing the one safety mechanism
underneath.
