# Portfolio & interview notes

AgentOps as a talking piece: what to say about it, how to demo it, and the questions it is
built to withstand. Everything here maps to something real in the repo — no invented metrics.

## One-liner

> AgentOps is a production-shaped AI customer-support **operations** platform: support
> tickets flow through an explicit, evaluated pipeline that classifies, grounds and drafts a
> response, and stops every consequential action at a human approval gate before a durable
> worker executes it **exactly once** — all deterministic, offline, audited and simulated.

## CV bullets

- Built an end-to-end AI support-ops platform (FastAPI · PostgreSQL/pgvector · Next.js 15)
  where a **deterministic rules engine is the authority** and the model only ever *proposes* —
  turning an ambiguous business process into an auditable, testable workflow.
- Engineered **exactly-once** consequential actions with a transactional **outbox** and a
  hash-chained, tamper-evident **audit log**, proven by hard-gated evaluations (42 end-to-end
  + adversarial cases across **9 hard gates, all at 0**) rather than asserted.
- Hardened for production and prompt-injection: JWT + RBAC, PII-safe structured logging, a
  config guard, rate/size/timeout middleware and a threat model — backed by **440 automated
  tests** running fully offline in CI (no paid APIs, no external network).

## Project story

**Problem.** "Let an AI handle refunds and cancellations" is easy to demo and dangerous to
ship. The risk isn't language quality — it's letting a probabilistic model take an
irreversible, money-moving action. I wanted to build the *operations* system that makes such
automation safe: one a support team and an auditor would both trust.

**Approach.** I inverted the usual chatbot design. The model is confined to **proposals**
validated against strict schemas and safety rules; **deterministic rules** own ownership,
eligibility, limits, risk and routing; and **nothing consequential executes** without a named
supervisor approving a hashed snapshot of exactly what they were shown. A granted approval
enqueues its execution in the *same transaction* via a durable outbox, and a worker applies
the **simulated** effect exactly once with a final revalidation.

**What makes it production-shaped.** Every consequential and security event is written to a
hash-chained audit log in the same transaction, so the record is tamper-evident. The whole
system is observable (one correlation id from API to execution), reliable (timeouts, size and
rate limits, a provider circuit breaker, readiness that checks DB *and* migrations) and
**deterministic and offline by construction** — a mock provider, a seed clock and synthetic
data mean CI reproduces every run with no network. Correctness is enforced by hard-gated
evaluation suites, not vibes.

**What I'd do next.** Swap the simulated effect adapters for real payment/carrier
integrations behind the same outbox contract; add a live model provider behind the existing
abstraction with online-eval guardrails; and scale the worker horizontally (the
`FOR UPDATE SKIP LOCKED` claim already makes that safe).

## Demo script (what to click)

Follow [demo-runbook.md](demo-runbook.md): `make up && make seed`, then
`make demo-seed-approval`, sign in as a Supervisor, approve the refund, run one outbox job,
and show the simulated refund landing in **Actions** and the **Audit** trail ("chain intact").
Finish with `make verify-all`. Then sign in as an Agent to show role-gating.

## Interview talking points & likely Q&A

**Why an outbox instead of a queue (Celery/SQS/Rabbit)?** The decision and its execution job
must be atomic — an approval that "succeeds" but loses its job, or a job with no approval,
would both be unacceptable. Writing the job to the same Postgres transaction as the approval
makes that impossible. A worker then claims jobs with `FOR UPDATE SKIP LOCKED`. It also keeps
the system single-dependency and offline-testable. The trade-off is throughput ceiling vs. a
broker — fine at support-ops scale, and swappable later behind the same contract.

**Exactly-once — isn't that impossible?** End-to-end exactly-*delivery* is; what I guarantee
is exactly-once *effect*. Each action is keyed by an idempotency key and guarded by a final
revalidation, so retries and reprocessing are no-ops. `make demo` demonstrates a reprocess
producing zero second refunds; a hard gate enforces it.

**How is the audit log tamper-evident?** Each row stores `entry_hash = H(previous_hash ‖
canonical_payload)`, forming a chain. Editing or deleting any row breaks every subsequent
hash, which `make audit-verify` recomputes and detects. It's append-only and written in the
same transaction as the event it records.

**How do you stop prompt injection?** An instruction hierarchy: untrusted ticket content is
data, never instructions. Model output is a proposal validated against a tool allowlist,
citations must be a subset of what was supplied, the action must be in the allowed list, and
it can't claim to have executed anything. Deterministic rules — not model text — make the
actual decision, and adversarial fixtures are isolated from authoritative evidence. There's a
threat model and adversarial eval cases behind this.

**Why deterministic/offline? Doesn't that dodge the "AI" part?** It targets the hard part on
purpose: the *engineering* around the model — safety, idempotency, auditability, recovery.
The provider is abstracted, so a real model drops in behind the same interface; the mock makes
the system reproducible and CI cheap. Language quality is explicitly out of scope.

**Where would this break at real scale, and what would you change?** Single-Postgres outbox
throughput and a single worker are the first ceilings; I'd add worker replicas (already safe
under the skip-locked claim) and partition the outbox before reaching for a broker. Synchronous
model calls in the pipeline would move behind the same durable-job pattern. The audit chain is
serial by design — I'd shard by subject if verification cost grew.

**What are you least happy with?** The default provider is a mock, so I haven't tuned real
prompt quality; the reference clock being fixed makes some relative times look stale in the UI;
and two moderate `npm audit` advisories live inside Next's bundled `postcss` copy and can't be
resolved without downgrading Next. All are documented, not hidden.

## If I had more time

- Real integration adapters (payment/carrier/email) behind the current simulated-effect
  contract, gated by environment.
- A live model provider with online-evaluation guardrails and cost/latency budgets surfaced
  in the dashboard.
- Supervisor analytics (approval SLAs, refund exposure) and horizontal worker scaling.
- Per-subject audit sharding if chain-verification cost became material.

## Fast facts

| | |
| --- | --- |
| Stack | Python 3.12 · FastAPI · PostgreSQL 16 + pgvector · Next.js 15 · React 19 · TypeScript |
| Tests | 440 automated (420 backend · 20 frontend), fully offline in CI |
| Evaluations | six hard-gated suites (retrieval, model, workflow, approvals, observability, end-to-end); every hard gate at 0 |
| Guarantees | human-in-the-loop approvals · exactly-once effects · tamper-evident audit · deterministic & offline |
| Effects | all simulated — no payment processor, carrier, store or email is ever contacted |
