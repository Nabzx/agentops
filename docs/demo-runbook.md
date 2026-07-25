# Demo runbook

A ~10-minute walkthrough that takes AgentOps from a clean checkout to a worked refund and
the proof gates behind it. Every command here has been run; every effect is **simulated**
and **offline** — no paid API, no external network.

> Reference clock: the synthetic data is anchored to **2026-07-16**, so in-app relative
> times ("expires 8d ago") are relative to that date, not today. This is deliberate and
> deterministic.

## 0. Bring up the stack (≈2 min)

```bash
cp .env.example .env          # safe local defaults, no real secrets
make up                       # db + backend + worker + frontend (applies migrations)
make seed                     # synthetic Meridian & Co dataset
make index-policies           # build the policy retrieval index
make list-users               # note the seeded users
```

- Frontend: <http://localhost:3000>
- Backend API + Swagger: <http://localhost:8000/docs>

**Dev password for every seeded user:** `agentops-dev`

| Role | Example sign-in |
| --- | --- |
| Supervisor (can decide) | `super.george@meridian.example` |
| Support Agent (raises requests) | `agent.amara@meridian.example` |

## 1. Terminal story (30 sec)

See the whole human-in-the-loop, exactly-once path in one command:

```bash
make demo
```

It requests an approval, refuses the agent's own approval and self-approval, approves as a
supervisor, enqueues exactly one outbox job, executes a **simulated refund**
(`SIM-REF-2026-000001`), proves reprocessing is a no-op (still one effect), then shows the
cancellation and manual-action branches.

## 2. Work an approval in the dashboard (≈4 min)

`make demo` leaves the queue empty, so put a fresh pending approval back:

```bash
make demo-seed-approval       # one pending refund on DEMO-REFUND-APPROVAL-001
```

Then, in the browser:

1. **Sign in** at <http://localhost:3000> as `super.george@meridian.example` / `agentops-dev`.
2. **Approvals** → open *Request Supervisor Refund Approval* (High risk, £59.00). Note the
   frozen snapshot: requested/maximum amounts, evidence-snapshot hash, policy citation, and
   the empty decision history.
3. Click **Approve**. The status moves to **Execution Pending**, the decision history records
   *Pending → Approved (supervisor)*, and the decision panel now reads
   "no action is available" — the job is queued.
4. **Health** → the Outbox shows **Pending 1**. Click **Run one job** (a dev-only worker tick).
   It flips to **Succeeded 1**.
5. **Actions** → the simulated refund `SIM-REF-2026-000001`, £59.00, **Succeeded**.
6. **Audit** → the header reads **Chain intact · N events**; the trail shows, in order,
   *Approval Requested → Approval Approved → Outbox Job Created → Action Executed*.
7. **Journey** → paste the correlation id from the audit trail (e.g.
   `act-3aea0bc674ea21bcace617430cf44ebd`) and **Trace** to see the same story as a timeline.

## 3. Role-gating (30 sec)

Sign out and sign in as `agent.amara@meridian.example` / `agentops-dev`:

- The nav shows **no Outbox or Audit** — those require `outbox_inspect`.
- The overview's Outbox card reads *"Supervisor-only"*.
- An agent can raise approvals but can never decide one (and never their own).

## 4. Proof gates (≈3 min)

One command runs every hard-gated evaluation, verifies the audit chain, checks the pinned
offline dependencies, and runs the frontend checks — non-zero exit if anything fails:

```bash
make verify-all
```

Or individually:

```bash
make eval-end-to-end     # 42 end-to-end + adversarial cases, 9 hard gates all 0
make audit-verify        # recompute and confirm the hash-chain
make deps-audit          # lockfile pinned & consistent, offline
```

## Reset

```bash
make reseed              # DEV ONLY: drop, recreate and reseed the database
make down                # stop the stack (db volume preserved)
```

## What this proves

- **Human-in-the-loop**: nothing consequential executes without a named supervisor decision
  on a hashed snapshot; self-approval is impossible.
- **Exactly-once**: one approval → one job → one effect, reprocessing is a no-op.
- **Tamper-evident**: every step is on an unbroken hash-chained audit trail.
- **Deterministic & offline**: the same result every time, with no external calls.

See [architecture.md](architecture.md) for how the pieces fit and [portfolio.md](portfolio.md)
for the talking points.
