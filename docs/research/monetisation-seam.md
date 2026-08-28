# Monetisation seam research (Wayfinder: research)

_Issue #6 — "where a future hosted/paid edge would attach, kept open, not built."_
_This is a no-code research task. The goal is to stop today's architecture from foreclosing
a future paid edge, not to build one. Every non-obvious claim is cited to a primary source._

## Question

AgentOps is being open-sourced as a reusable **safe-action layer for AI agents**: an agent
proposes an Action, a human approves a frozen Snapshot, the core executes it exactly-once and
records it on a hash-chained Audit chain (Python/FastAPI core, Adapter interface, Stripe
revenue-recovery flagship Detector). Assuming the core stays genuinely open, **where would a
future paid edge attach without forking the OSS**, and which seam(s) should we keep open now?

## How comparable OSS-companies monetise

The consistent pattern across mature OSS-companies: **the code that runs on the user's own
machine is free; what gets sold is the thing that is painful to operate, or that only an
organisation buys** — a hosted/managed control plane, managed connectors, usage-metered
compute, or enterprise governance (SSO / RBAC / audit retention / support / SLA). The licence
is chosen to make that hosted edge defensible.

| Company | Core licence | What is monetised (the paid boundary) | Source |
|---|---|---|---|
| **Temporal** | MIT (self-hosted server free; you run the cluster + DB) | **Temporal Cloud**: usage-metered **Actions** (~$50 / million, volume-tiered) + **Storage**, plus a paid **Plan** bundling **Support/SLA** (Essentials $100/mo → Business $500/mo → Enterprise/Mission-Critical). Pure hosted-runner + usage metering; the OSS is fully permissive. | [Temporal Cloud pricing](https://docs.temporal.io/cloud/pricing), [pricing update](https://temporal.io/blog/temporal-cloud-pricing-update) |
| **Dagster** | Apache-2.0 (framework, APIs, integrations "forever and always open source") | **Dagster+**: the **control plane** (hosted UI, scheduler, metadata store) sold as **Serverless** (they run control plane + compute) or **Hybrid** (they run control plane, you run compute), plus **Enterprise-complexity** features — **RBAC, federated identity/SSO, audit logs, multi-team collaboration**. Explicit open-core: "operational complexity" and "enterprise complexity" are paid; application complexity is free. | [Dagster open-core blog](https://dagster.io/blog/open-core-business-model-dagster), [OSS vs Dagster+](https://github.com/dagster-io/dagster/discussions/25313) |
| **Airbyte** | Core **ELv2** (Elastic License v2); **connectors** MIT; protocol MIT | **Airbyte Cloud**: managed hosting + managed connectors, priced on **compute capacity** ("Data Workers"), not rows moved. ELv2's one restriction: you may not "provide the software to others as a managed service" — i.e. you may self-host at any scale, but only Airbyte may resell it as a SaaS. | [Airbyte licenses](https://docs.airbyte.com/community/licenses), [license FAQ](https://docs.airbyte.com/community/licenses/license-faq), [pricing](https://airbyte.com/pricing) |
| **n8n** | **Sustainable Use License** (fair-code, source-available, **not** OSI-open) | **n8n Cloud** (hosted) + **Enterprise licence** for SSO, environments, and scaling features. SUL's three restrictions: internal-business/personal use only; redistribution only free + non-commercial; keep notices. You may not host n8n-for-money or white-label it — but consulting/support on n8n is explicitly allowed. | [Sustainable Use License](https://docs.n8n.io/privacy-and-security/sustainable-use-license), [LICENSE.md](https://github.com/n8n-io/n8n/blob/master/LICENSE.md), [announcement](https://blog.n8n.io/announcing-new-sustainable-use-license/) |
| **Sentry** | **FSL** (Functional Source License; was BSL) | **Sentry Cloud** (hosted SaaS) + enterprise. FSL: do anything "**except undermine its producer**" — i.e. no competing commercial product — and each released version **auto-converts to MIT/Apache-2.0 after two years**. Chosen so self-hosting stays free but a hosted competitor cannot free-ride. | [FSL announcement](https://blog.sentry.io/introducing-the-functional-source-license-freedom-without-free-riding), [fsl.software](https://fsl.software/) |
| **PostHog** | MIT (self-hostable via Docker Compose) | **PostHog Cloud**: **usage-based** metering after a large free tier, plus **platform add-ons** for **SSO, governance, security, support**. Self-host is MIT and free but explicitly "unlikely to scale" without real effort — the managed scale + governance is the product. | [Self-host docs](https://posthog.com/docs/self-host), [pricing](https://checkthat.ai/brands/posthog/pricing) |
| **Supabase** | Apache-2.0 (Postgres, PostgREST, Auth, Realtime, Storage all open) | **Supabase Cloud**: the hosted **platform** — the parts **not** open-sourced are precisely the "integrations and services that connect the components": **billing, internal monitoring, cloud infra/control-plane management**. The seam is the operational glue, not the primitives. | [Self-host discussion #17876](https://github.com/orgs/supabase/discussions/17876) |

**What repeats across all seven:**

1. **Hosted runner / managed operation** — the single most common paid boundary (Temporal,
   Dagster, Airbyte, PostHog, Supabase, n8n, Sentry all sell "we run it for you").
2. **Usage metering** — where there is a natural billable unit, it is metered (Temporal
   Actions, PostHog events, Airbyte compute). The unit is a *first-class object in the OSS
   data model* long before it is billed.
3. **Control-plane / dashboard SaaS** — the multi-tenant UI, scheduler, metadata store
   (Dagster's control plane; Supabase's "connecting glue").
4. **Enterprise governance** — SSO/SAML, advanced RBAC, audit-log retention, support/SLA
   (Dagster, n8n, PostHog, Sentry). Universally "the thing organisations will sign a contract
   for" (Dagster's words).
5. **Licence chosen to fit the seam** — permissive (MIT/Apache) when the moat is operational
   scale (Temporal, Supabase, PostHog); source-available (ELv2/SUL/FSL/BSL) when the fear is a
   hosted free-rider (Airbyte, n8n, Sentry).

## Candidate seams for AgentOps (trade-offs)

Mapped onto this project's own vocabulary (Core / Adapter / Worker / Audit chain / Detector).

**A. Hosted runner (managed Worker + Outbox)** — run the exactly-once execution loop as a
service so users don't operate Postgres, the Worker, and the durable Outbox themselves.
- _For:_ the most-proven seam; matches Temporal almost exactly; the operational pain is real
  (transactional outbox + leased workers is genuinely hard to run well).
- _Against:_ heaviest to build; only attractive once someone is running Actions at volume.

**B. Managed / certified Adapters** — the OSS ships the Adapter *interface* + a few reference
Adapters; a catalogue of maintained, credential-managed Adapters (Stripe, and later billing /
cloud-cost / seats systems) is the paid tier.
- _For:_ maps to Airbyte's connectors and to this project's own "roadmap of Detectors";
  natural recurring value (someone must keep Adapters working against changing APIs).
- _Against:_ risks looking like the OSS is deliberately connector-starved; keep enough real
  Adapters open that the core is independently useful.

**C. Control-plane / dashboard SaaS** — a hosted, multi-tenant **Approval** surface: where
Approvers see Snapshots, decide, and browse the Audit chain across teams, with notifications
and reviewer routing. The OSS keeps a single-tenant local UI.
- _For:_ the approval/audit UI is exactly what a *team* (not a solo dev) needs, and where
  governance naturally lives; mirrors Dagster's control plane and Supabase's "glue".
- _Against:_ must not let the OSS approval surface rot — the local loop has to stay fully
  functional or the project isn't credibly open.

**D. Usage metering** — meter a natural billable unit (an approved-and-executed Action, or a
unit of Recoverable value surfaced) and bill on it.
- _For:_ cleanest alignment-of-incentives ("you pay a slice of value recovered"); Temporal/
  PostHog precedent. Needs almost nothing built now — only that the unit exists as a
  first-class, countable object.
- _Against:_ premature to price; but cheap to keep open by naming the unit now.

**E. Enterprise governance** — SSO/SAML, advanced RBAC beyond the OSS permission set, long
**Audit-chain retention / export / compliance attestation**, support + SLA.
- _For:_ universal upsell; a **safe-action / audit** product is unusually well-placed to sell
  audit-retention and compliance because that *is* the value proposition; sits cleanly above a
  permissive core.
- _Against:_ don't gate basic multi-user RBAC — the OSS `Permission` model must stay usable, or
  the security story of the open core is hollow.

## Recommendation

**Keep three seams open now; commit to building none of them.** They are cheap to preserve as
architectural boundaries and expensive to retrofit:

1. **The Adapter interface as a stable, public contract (seam B, and it enables A).** This is
   already a locked roadmap decision — protect it as the *one* extension point through which
   both the OSS and any future managed-Adapter catalogue plug in. Concretely: the Core must
   depend only on the `Action`/`Effect` Adapter interface, never on a concrete Adapter; Adapter
   discovery/registration must be pluggable (entry-points / registry), so a closed Adapter
   loads with zero core changes; and the **credential/secrets model must be Adapter-scoped**
   (already a Wayfinder decision) so a hosted runner can inject managed credentials without a
   fork. This keeps A (hosted runner) and B (managed Adapters) both reachable.

2. **A clean Core ↔ control-plane boundary (seam C + E).** Keep the Core as a headless library
   plus a thin API, with the **Approval / Decision / Audit surface behind an interface**, not
   wired directly into one bundled UI. Practically: expose **control-plane hooks** — a stable
   read model / event stream for `Approval request` state changes and Audit entries, and
   pluggable notification + reviewer-routing points — so a multi-tenant hosted dashboard can
   sit on the same events the local UI uses. Keep the **Audit store behind a pluggable
   persistence interface** (append-only writer + verifier) so "long-retention / export /
   compliance" can be a hosted implementation of an interface the OSS already defines. Keep the
   OSS `Permission` check as the single enforcement point so enterprise RBAC/SSO extends it
   rather than replacing it.

3. **A first-class, countable billable unit (seam D).** Ensure every executed Action and every
   piece of Recoverable value carries a stable identity and is queryable as a discrete event
   (the `Correlation id` already threads this). No meter, no pricing — just guarantee the unit
   exists so usage metering can attach later without a schema migration or a fork.

Seam A (full hosted runner) is the eventual big prize, but it is *reachable through* seams B and
C above — a stable Adapter contract + a clean control-plane boundary + Adapter-scoped
credentials are exactly what a managed runner needs. So we do not need to preserve anything
extra for A beyond 1–3.

**Architectural boundaries to preserve now (the actionable list):**

- Core depends only on the **Adapter interface**; Adapters are registered via a pluggable
  registry; credentials are **Adapter-scoped**.
- **Audit store** sits behind an append-only persistence interface (writer + chain verifier),
  not a hard-coded table.
- **Approval / Decision / Audit** state is exposed as a stable **read model / event stream**
  (control-plane hooks) with pluggable **notification** and **reviewer-routing** points.
- **`Permission`** is the single enforcement point for every consequential route, so RBAC/SSO
  extends rather than forks it.
- Executed **Action** and **Recoverable value** are discrete, identified, countable events.

## Licence note

The licence choice sets which seams are *defensible*, and it should follow from where the moat
is:

- **Permissive (MIT / Apache-2.0)** — Temporal, Supabase, PostHog, Dagster. Chosen when the
  moat is **operational** (running it at scale is the hard part), so the company is relaxed
  about the code being fully free. Maximises adoption and contribution; imposes **no barrier to
  a third party hosting it** — the edge must come from operating better, not from the licence.
- **Source-available (ELv2 / SUL / FSL / BSL)** — Airbyte, n8n, Sentry. Chosen when the fear is
  a **hosted free-rider**. ELv2 blocks only "provide the software to others as a managed
  service" ([Airbyte](https://docs.airbyte.com/community/licenses/license-faq)); FSL is "do
  anything except undermine the producer" and **auto-converts to MIT/Apache after two years**
  ([FSL](https://fsl.software/)); n8n's SUL forbids hosting-for-money / white-labelling
  ([SUL](https://docs.n8n.io/privacy-and-security/sustainable-use-license)). The cost is that
  none of these are OSI-"open source", which dampens some adoption and contribution.

**Implication for AgentOps.** Because the recommended seams (hosted runner, managed Adapters,
control-plane, usage) are all **operational/hosted**, a **permissive licence (Apache-2.0)** is
sufficient to keep a hosted edge viable *and* maximises the adoption a launch depends on — the
Temporal/Supabase pattern. **Note the one-way door:** a project can relicense a permissive core
to source-available later only for *future* versions (all seven prove the moat lives in the
hosted service, not the licence), and doing so is reputationally costly (see Sentry/HashiCorp
backlash). If protection against a hosted free-rider is ever wanted, the low-regret options are
(a) ship under permissive now and add a source-available licence *only* to a future
control-plane/enterprise component, or (b) FSL, which at least auto-heals to open source in two
years. Recommendation: **Apache-2.0 for the Core, decision deferred for any future hosted
component** — do not adopt a restrictive licence pre-emptively; it buys nothing today and costs
adoption.

## Consequences (what to avoid foreclosing)

No code changes follow from this file. It exists to stop the following from being designed out:

- **Don't hard-wire a concrete Adapter into the Core.** If the Core imports Stripe directly,
  the managed-Adapter and hosted-runner seams (B, A) are foreclosed. Keep the interface the
  only coupling.
- **Don't bake credentials into the Core or a single Adapter.** Adapter-scoped credentials are
  what let a hosted runner inject managed secrets later; global/hard-coded credentials foreclose
  seam A.
- **Don't fuse the Approval/Audit UI into the Core.** If there is no read-model/event boundary,
  a hosted multi-tenant control plane (C) can only be built by forking. Expose the events.
- **Don't hard-code the Audit store.** Long-retention / export / compliance (E) needs the
  append-only store to be an interface, or that enterprise seam is a fork.
- **Don't make the executed Action / Recoverable value un-countable.** If these aren't discrete
  identified events, usage metering (D) requires a later schema migration. Name the unit now.
- **Don't gate basic RBAC or a working local approval loop.** The OSS must be independently,
  credibly useful — a connector-starved or governance-hollow core kills adoption, and adoption
  is the precondition for every seam above. Sell scale, operation, and org-features; give away
  the working loop.
- **Don't pre-emptively adopt a restrictive licence.** It deters contribution and adoption for
  a hosted free-rider risk that does not exist until there is something worth free-riding on.
  Keep the licence decision for hosted components open, exactly as this seam decision is.
