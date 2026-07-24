# Product Requirements Specification — Career Coach Agent

| | |
|---|---|
| **Version** | 1.1 |
| **Status** | Draft |
| **Author** | Trung |
| **Reviewer** | Anh Phuc |
| **Last updated** | 2026-07-24 |

> **Revision history:**
> - **v1.1** — Decomposes the feature into **two gated delivery stages** and
>   **eight phases (P0–P7)**, each phase delivered as its own `spec.md` +
>   `plan.md` (§4). Resolves the one planning-blocking open question — Q2, the
>   Postgres migration — as *provision a fresh managed instance and migrate*
>   (D-CC-8). Corrects two things the v1.0 draft understated: the local
>   embedding model's real cost (torch enters the pipeline container too —
>   D-CC-4, NFR-CC-1), and that Stage 2's interactive access, not the grounding
>   work, is what forces the always-on-Postgres commitment. Grounding
>   capabilities (Stage 1) now ship with **no shared-infra change**; the
>   always-on Postgres and interactive bot are isolated behind an explicit gate
>   (Stage 2).
> - **v1.0** — Promotes the loose feature draft `career-coach-agent.md`
>   (Draft v0.2) into a house-style PRS: requirements restated as an FR table,
>   decisions as a decision table, and the draft's milestone list moved out to
>   the implementation plan. Corrects a factual assumption in the draft — see
>   the note below and D-CC-9.

> **Feature-level PRS.** This document extends the product-level
> `product-requirements-spec.md` (v2.1) for one new initiative. Where it adds
> or changes scope, FRs, or decisions, it does so only for the Career Coach
> Agent; the six-stage core pipeline is unchanged. On conflict about the core
> pipeline, the product PRS wins; on conflict about this feature, this file
> wins.

> **Note for AI coding assistants (Claude Code):** As of this writing the
> Advisor's "coaching tips" are **static Jinja template branches**
> (`scout/sub_agents/advisor/templates/job-detail.html.jinja`), **not** an LLM
> call. There is no Advisor tip-generation LLM stage today. This PRS therefore
> requires *building* that stage (FR-CC-8, D-CC-9), not merely "updating a
> prompt." The `listing_gaps` table, `normalize_skill()`, DeepSeek/LiteLLM
> wiring, and a one-way Discord push notifier already exist and are reused.

---

## 1. Overview

The Career Coach Agent extends the Advisor so that, for every job listing with
detected skill gaps, the coaching output points to **real, verifiable learning
resources** rather than generic advice — closing the loop from "you're missing
X" to "here is exactly where to learn X." It adds two capabilities: a curated,
auto-aggregated corpus of learning resources that is searched per gap and used
to *ground* generated coaching tips, and a dedicated, interactive Discord bot
that serves that output on demand in its own channel.

These two capabilities are delivered in **two gated stages** (§4). **Stage 1
(Grounded coaching)** delivers the corpus, retrieval, grounded tips, and report
surfacing with **no change to shared infrastructure** — it runs inside the
existing batch pipeline against the current VM-hosted Postgres, and Discord
stays push-only. **Stage 2 (Interactive access)**, gated behind Stage 1, adds
the interactive Discord bot and the always-on managed Postgres it requires. The
split isolates the one expensive, hard-to-reverse commitment (an always-on
managed database) so it is made only after Stage 1 has proven the corpus
surfaces useful resources.

### 1.1 Problem statement

Today the Advisor names a listing's skill gaps but offers only templated,
generic positioning advice — it cannot tell the user *where* to close a gap,
and any resource it named would be at risk of being hallucinated. There is no
learning-resource corpus, no retrieval, and no grounding enforcement. Separately,
the only Discord integration is a one-way daily push (the briefing notifier);
the user cannot ask "show me resources for Kubernetes" on demand, and could not
be answered anyway because Postgres lives on a VM that is deallocated ~23h/day.

### 1.2 Target user

The single job seeker of Job Market Scout (initially the author). Single-user by
design, consistent with the product PRS.

---

## 2. Scope

### 2.1 In scope

- A `resources` corpus, **auto-aggregated** (not hand-seeded), keyed off the
  same normalized skill tags gap detection already produces; GitHub repositories
  are the first source type.
- A weekly aggregation job: GitHub Search API per skill + an "awesome-X"
  bootstrap harvest + an LLM tagging/summarization pass + a local embedding pass.
- A retriever that returns the top 2–3 resources per detected gap via a
  `skills[]` pre-filter followed by pgvector semantic ranking.
- A **new Advisor coaching-tip stage** that generates tips grounded in the
  retrieved resources, with **deterministic post-generation URL validation**.
- A periodic link-health check that ages dead resources out of retrieval.
- A **new, dedicated, interactive Discord bot** (separate from the briefing
  notifier), on the same server in its own channel, supporting slash commands
  via the Discord HTTP Interactions API on an Azure Function. *(Stage 2)*
- Moving Postgres to an **always-on** managed instance so the bot can query at
  any time, including while the scout VM is deallocated. *(Stage 2)*

### 2.2 Out of scope (this version)

- Re-scoring or re-ranking job listings — that remains the Scorer/Advisor's job.
- Changing `profile.json` or gap-detection logic — this feature *consumes*
  `listing_gaps`, it does not change how gaps are found.
- Paid or login-gated course content — the corpus indexes only publicly
  reachable, freely accessible resources.
- Non-repo resource types (docs, courses, notes) in the first version — the
  schema allows them, but only `repo` is populated initially (see Open Q4).

---

## 3. Architecture

The Career Coach Agent runs as its own module/service, reusing Job Market
Scout's Postgres, skill-name normalization, and DeepSeek/LiteLLM integration.
The one structural change to shared infrastructure — moving Postgres off the
scout VM onto an always-on managed instance — belongs to **Stage 2** and exists
solely so an interactive bot can query gaps and resources during the ~23h/day
the VM is deallocated. Stage 1 adds the `resources` table and the pgvector
extension to the **existing VM-hosted Postgres** and needs no such move.

```
        ┌──────────────────────────┐
        │   Resource Aggregator     │  weekly, decoupled from the pipeline
        │  GitHub Search API per    │  → LLM tag/summarize → local embed
        │  normalized skill tag     │
        └────────────┬─────────────┘ writes
                     ▼
   ┌────────────────────────────────────────┐
   │  Postgres + pgvector                      │  Stage 1: existing VM instance
   │  resources / listing_gaps / run_listings  │  Stage 2: always-on managed
   └───────┬───────────────────────┬──────────┘        (Burstable) — see D-CC-8
   top-k query                query gaps/history
           ▼                        │
   ┌───────────────┐                │
   │  Retriever     │  per gap,      │
   │  (pre-filter + │  top 2–3       │
   │  pgvector)     │                │
   └───────┬────────┘                │
           ▼ context injection       │
   ┌────────────────────┐            │
   │ Advisor tip stage   │─► grounded │
   │ (LLM) + URL validator│   tips     │
   └───────┬─────────────┘            │
           ├──────────────► Report/Dashboard (existing Jinja UI)
           └──────────────► Discord Coach Bot ◄──────────────┘  (Stage 2)
                            (Azure Function, HTTP Interactions,
                             interactive slash commands)
```

The top box is the Stage-2 end state: in Stage 1, `resources` and pgvector are
added to the existing VM-hosted Postgres (top-left path only); the interactive
bot and the move to the always-on managed instance arrive in Stage 2 (P6–P7).
Module-level detail belongs in
`docs/project/architecture-pipeline-overview.md` once built; this section is the
intended shape, not a built-state description.

---

## 4. Delivery: stages & phases

The feature decomposes into **two gated stages** and **eight phases (P0–P7)**.
Each phase has a single purpose, a clean interface, and can be built and tested
on its own. **Each phase is delivered as its own `spec.md` + `plan.md`** under
`docs/agent/specs/<phase-slug>/` and `docs/agent/plans/<phase-slug>/`
(plan-standards house structure), authored one at a time **when that phase is
undertaken** — not all up front. This PRS is the umbrella that enumerates and
sequences them; the per-phase spec says *what and why* for that phase, its plan
says *how and in what order*. An agent building a phase loads only that phase's
two documents, never the whole feature.

### 4.1 Stage 1 — Grounded coaching *(no shared-infra change; Discord stays push-only)*

| Phase | Purpose | Depends on | Delivers FRs |
|---|---|---|---|
| **P0 — Schema & pgvector foundation** | Add the pgvector extension to the existing VM Postgres image; create the `resources` table. Prerequisite for all later phases. | — | FR-CC-5 (schema) |
| **P1 — Resource aggregator** | Weekly job: GitHub Search per skill (PAT) + "awesome-X" bootstrap + LLM tag/summarize + embed-on-write. *Writes* `resources`. | P0 | FR-CC-1, 2, 3, 4, 5, 6 |
| **P2 — Retriever** | Per gap: exact `skills[]` pre-filter → pgvector cosine rank → top 2–3. *Reads* `resources`; testable on seeded rows independent of P1. | P0 | FR-CC-7 |
| **P3 — Advisor grounded-tip stage + URL validator** | New LLM call with retrieved resources injected; deterministic post-generation URL allow-list enforcement. | P2 | FR-CC-8, 9 |
| **P4 — Report surfacing** | Replace the static Jinja tips on the per-role detail page with grounded tips. | P3 | FR-CC-11 |
| **P5 — Link-health checker** | Periodic re-verify `last_verified`; dead URLs drop out of retrieval until re-verified. | P0 | FR-CC-10 |

### 4.2 Stage 2 — Interactive access *(GATED behind Stage 1 sign-off; carries the infra commitment)*

| Phase | Purpose | Depends on | Delivers FRs |
|---|---|---|---|
| **P6 — Always-on managed Postgres** | Provision a fresh Azure DB for PostgreSQL Flexible Server (Burstable) + pgvector; migrate `resources` / `listing_gaps` / `run_listings` / `runs` off the VM Postgres; repoint the pipeline. Resolves Q2. | Stage 1 complete | FR-CC-13 (enabling half) |
| **P7 — Discord coach bot** | Azure Function behind the Discord HTTP Interactions endpoint; register + serve slash commands (`/tips <listing_id>`, `/resources <skill>`), signature-verify, respond within 3 s; queries the now-always-on Postgres. | P6 | FR-CC-12, 13 |

### 4.3 The Stage 1 → Stage 2 gate

The transition from Stage 1 to Stage 2 is an explicit **human sign-off gate**,
because P6 is a **one-way door**: the always-on managed Postgres carries a
standing monthly cost on the Azure-for-Students subscription and the migration
is hard to reverse once the pipeline points at it. Stage 2 is not begun until
Stage 1 is complete and the corpus has demonstrably surfaced useful resources,
and until that cost is explicitly accepted.

---

## 5. Functional requirements

| ID | Phase | Requirement |
|---|---|---|
| FR-CC-1 | P1 | The corpus SHALL be auto-aggregated, keyed off the same normalized skill tags gap detection produces (`normalize_skill`), so it grows as new gap types appear with no manual list maintenance. GitHub repositories are the first source type. |
| FR-CC-2 | P1 | The aggregator SHALL query the GitHub Search API per skill, authenticated with a GitHub PAT, filtering to `stars > 200`, pushed within ~18 months, not archived, and having a README; it SHALL take the top N candidates per skill for the tagging pass. |
| FR-CC-3 | P1 | The aggregator SHALL seed initial coverage by harvesting repos from a configured set of "awesome-X" meta-lists matching the profile's domains, before per-skill dynamic search has run enough cycles. |
| FR-CC-4 | P1 | An LLM tagging pass (DeepSeek via LiteLLM) SHALL read each candidate's README and produce: skill(s) covered, resource type, estimated level, and a one-line summary. The distilled **summary** — not the raw README — SHALL be what is embedded and stored. |
| FR-CC-5 | P0, P1 | Resources SHALL be stored in a `resources` table with a pgvector embedding column (schema: P0); embeddings SHALL be produced by a local model (`sentence-transformers/all-MiniLM-L6-v2`, 384-dim, CPU) with no external embeddings API call (embed-on-write: P1). |
| FR-CC-6 | P1 | Aggregation SHALL run on a weekly cadence, decoupled from the scheduled pipeline runs. |
| FR-CC-7 | P2 | The retriever SHALL, per detected gap, first pre-filter candidates by exact match on normalized `skills[]`, then rank the pre-filtered set by pgvector cosine similarity, returning the top 2–3 resources. |
| FR-CC-8 | P3 | A **new** Advisor coaching-tip stage SHALL generate tips via the LLM with the retrieved resources injected as structured context (title, URL, summary, type) and an explicit instruction to reference only the provided resources. This replaces the current static template tips. |
| FR-CC-9 | P3 | After generation, a **deterministic** validation step SHALL parse URLs from the LLM output and strip any URL not present in that gap's retrieved-resource set, logging it as a grounding violation. Enforcement SHALL NOT rely on the prompt instruction alone. |
| FR-CC-10 | P5 | A periodic link-health check SHALL re-verify `last_verified` for recently-surfaced resources; a resource whose URL fails verification SHALL drop out of retrieval until re-verified. |
| FR-CC-11 | P4 | Grounded tips SHALL be surfaced through the existing rendered report (per-role detail page), replacing the current templated positioning advice for listings that have gaps. |
| FR-CC-12 | P7 | A dedicated, interactive Discord bot — separate from the briefing notifier, on the same server in a new channel — SHALL support slash commands (at minimum `/tips <listing_id>` and `/resources <skill>`) via the Discord HTTP Interactions API hosted on an Azure Function, verifying Discord's request signature and responding within Discord's 3-second window. |
| FR-CC-13 | P6, P7 | The bot SHALL be able to answer queries against `listing_gaps` and `resources` at arbitrary times, including while the scout VM is deallocated. |

---

## 6. Key design decisions

| ID | Phase | Decision | Rationale |
|---|---|---|---|
| **D-CC-1** | P1 | Corpus is auto-aggregated dynamically via the GitHub Search API keyed off normalized skill tags, not a static hand-curated list. | Grows automatically as new gap types appear; no manual list maintenance; reuses the naming the pipeline already produces. |
| **D-CC-2** | P0, P2 | Retrieval uses pgvector semantic embeddings, not keyword/BM25. | Gaps are short skill phrases whose wording won't match resource text exactly; semantic matching handles paraphrase. Postgres is already the system of record, so pgvector avoids a second database technology. |
| **D-CC-3** | P2 | Retrieval is hybrid: an exact `skills[]` pre-filter, then vector ranking of the pre-filtered set. | Prevents pure-semantic false positives (e.g. "Java" resources matched to a "JavaScript" gap) while keeping semantic ranking within the correct skill. |
| **D-CC-4** | P1 | Embeddings use the local `all-MiniLM-L6-v2` model (384-dim, CPU). | No external embeddings API cost, and demonstrates a local-embedding / pgvector RAG pipeline. **Accepted cost:** the model pulls **torch** into the image, and because retrieval embeds the gap query at run time, torch is loaded in the **pipeline** container too — not only the weekly aggregator: a >1 GB image layer, slower cold start on the ~1h/day-booted VM, and higher RAM. Accepted as the price of the offline/RAG approach. Upgrade path: swap to a larger local model (e.g. `all-mpnet-base-v2`) by widening the `resources.embedding` column. |
| **D-CC-5** | P3 | Grounding is enforced by deterministic post-generation URL validation (an allow-list of the retrieved set), not by prompt instruction. | Extends the project's "LLM proposes, deterministic code enforces" rule (product PRS D2/D7) to coaching tips, so a hallucinated URL cannot reach the user. |
| **D-CC-6** | P7 | The coach bot is a new, dedicated bot, separate from the briefing push notifier. | On-demand querying is a different concern from a daily push; keeping them separate avoids overloading the briefing path and keeps each bot's permissions minimal. |
| **D-CC-7** | P7 | The bot uses the Discord HTTP Interactions API on an Azure Function (Consumption), not a gateway bot. | A gateway bot must hold a persistent connection, forcing something to run 24/7 and undermining the VM-deallocation cost model; a request/response Function does not. |
| **D-CC-8** | P6 | Postgres moves to an always-on Azure Database for PostgreSQL Flexible Server (Burstable), **by provisioning a fresh instance and migrating** `resources` / `listing_gaps` / `run_listings` / `runs` onto it (resolves Q2), decoupled from the scout VM. | A fresh instance allows connectivity and schema to be validated before any prod data is cut over, and gives a clean rollback (leave the VM Postgres intact until cutover succeeds). Interactive commands must query at arbitrary times, including while the VM is deallocated. This also resolves the "move Postgres to managed Azure Database" item deferred in product PRS §8. **Contingency** (not the chosen path): if the standing cost proves unacceptable, the Function can instead read the already-published static dashboard data in Azure Storage — read-only, no fresh queries. |
| **D-CC-9** | P3 | Coaching tips become an LLM-generated, grounded stage, replacing the current deterministic Jinja template tips. | The existing template branches cannot cite real, per-gap resources; grounded citation requires generated prose constrained to a retrieved set plus deterministic validation. This is new work, not a prompt edit. |

---

## 7. Non-functional requirements

| ID | Requirement |
|---|---|
| NFR-CC-1 | **Cost:** no external embeddings API cost and no new database technology in Stage 1 (pgvector rides on the existing Postgres); weekly aggregation cadence bounds scrape volume. The local embedding model's tradeoff is accepted, not free — see D-CC-4 (torch in the pipeline image, larger image, slower cold start). The only standing cloud cost this feature adds is the Stage-2 managed Postgres (D-CC-8), which is gated (§4.3). |
| NFR-CC-2 | **Latency:** top-k vector retrieval SHALL run synchronously in the Advisor stage with no new async infrastructure (typical retrieval < 100 ms, excluding the one-time model load per container start). |
| NFR-CC-3 | **Grounding integrity:** enforced by deterministic post-generation URL validation (follows D-CC-5), never prompt-only. |
| NFR-CC-4 | **Corpus freshness:** weekly full aggregation plus a link-health spot-check on recently-surfaced resources between aggregations. |
| NFR-CC-5 | **Availability:** interactive commands SHALL be answerable while the scout VM is deallocated — a Stage-2 requirement satisfied by D-CC-8 and D-CC-7. |
| NFR-CC-6 | **Rate limits:** the aggregator SHALL authenticate with a GitHub PAT (5,000 req/hr) rather than unauthenticated search (60 req/hr). |
| NFR-CC-7 | **Secrets:** the GitHub PAT, Discord coach-bot token/public key, and managed-Postgres credentials SHALL be supplied via environment/secret configuration, never committed. |

---

## 8. Deployment & operations

Nothing in this feature is built yet; all components are **Planned**. The
**Stage** column ties each component to the delivery stage in §4.

| Component | Stage | Status |
|---|---|---|
| `resources` table + pgvector extension on the existing VM Postgres | 1 (P0) | **Planned** |
| Resource aggregator (GitHub Search API + PAT + "awesome-X" bootstrap + LLM tagging) | 1 (P1) | **Planned** |
| Local embedding pipeline (`all-MiniLM-L6-v2`) — new dependency, not in `requirements.txt` today | 1 (P1) | **Planned** |
| Retriever module (skills pre-filter + pgvector top-2/3) | 1 (P2) | **Planned** |
| Advisor grounded tip stage + deterministic URL validator | 1 (P3) | **Planned** |
| Report surfacing of grounded tips | 1 (P4) | **Planned** |
| Link-health checker | 1 (P5) | **Planned** |
| Always-on Postgres (fresh Azure DB for PostgreSQL Flexible Server, Burstable) + migration off the VM | 2 (P6) | **Planned — gated** |
| Discord coach bot (Azure Function behind the Interactions endpoint, slash commands) | 2 (P7) | **Planned — gated** |

---

## 9. Open questions

Q2 — the one item that blocked planning — is **resolved** as of v1.1
(fresh-server-and-migrate; see D-CC-8). The remaining questions are all
non-blocking for Stage 1 and do not gate writing its phase specs/plans.

| # | Question | Blocks planning | Status |
|---|---|---|---|
| Q1 | Which specific "awesome-X" meta-lists to harvest for bootstrap coverage (draft proposes Python / FastAPI / React / TypeScript / Docker / Azure). | No — a default set can start; refine later. | Open (P1) |
| Q2 | Provision a fresh Flexible Server and migrate, or reconfigure the existing instance? Any downtime window constraint for the core pipeline during the switch? | Was **Yes**. | **Resolved** — fresh instance + migrate (D-CC-8, P6); no downtime for the core pipeline before cutover since the VM Postgres stays live until migration succeeds. |
| Q3 | Beyond `/tips <listing_id>` and `/resources <skill>`, which slash commands to define up front (e.g. `/status`, `/history`)? | No — the two named commands are enough to start. | Open (P7) |
| Q4 | Do docs/courses/notes resource types get added in a later phase, or is `resource_type` variety deferred until repos prove out the pipeline? | No — schema already allows the variety; only `repo` is populated first. | Open (P0/P1) |

---

## 10. Related documents

- Product-level PRS this feature extends: `product-requirements-spec.md` (v2.1)
- Original loose feature draft this supersedes: `career-coach-agent.md` (Draft v0.2)
- Current architecture and module structure: `docs/project/architecture-pipeline-overview.md` (living document)
- Static-dashboard hosting rationale (VM deallocation cost model): `docs/agent/plans/static-dashboard-hosting/plan.md`
- **Per-phase specs & plans:** each phase P0–P7 (§4) gets its own
  `docs/agent/specs/<phase-slug>/spec.md` and
  `docs/agent/plans/<phase-slug>/plan.md`, authored when that phase is
  undertaken. This umbrella PRS and its blocking question (Q2) are resolved, so
  Stage 1 phase authoring can begin with **P0**.
