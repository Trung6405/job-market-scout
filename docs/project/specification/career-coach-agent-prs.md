# Product Requirements Specification — Career Coach Agent

| | |
|---|---|
| **Version** | 1.0 |
| **Status** | Draft |
| **Author** | Trung |
| **Reviewer** | Anh Phuc |
| **Last updated** | 2026-07-24 |

> **Revision history:** v1.0 promotes the loose feature draft
> `career-coach-agent.md` (Draft v0.2) into a house-style PRS: requirements
> restated as an FR table, decisions as a decision table, and the draft's
> milestone list moved out to the (forthcoming) implementation plan. It also
> corrects a factual assumption in the draft — see the note below and D-CC-9.

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
  via the Discord HTTP Interactions API on an Azure Function.
- Moving Postgres to an **always-on** managed instance so the bot can query at
  any time, including while the scout VM is deallocated.

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
The one structural change to shared infrastructure is that Postgres moves off
the scout VM onto an always-on managed instance, so an interactive bot can query
gaps and resources during the ~23h/day the VM is deallocated.

```
        ┌──────────────────────────┐
        │   Resource Aggregator     │  weekly, decoupled from the pipeline
        │  GitHub Search API per    │  → LLM tag/summarize → local embed
        │  normalized skill tag     │
        └────────────┬─────────────┘ writes
                     ▼
   ┌────────────────────────────────────────┐
   │  Always-on Postgres (Burstable) + pgvector│
   │  resources / listing_gaps / run_listings  │
   └───────┬───────────────────────┬──────────┘
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
           └──────────────► Discord Coach Bot ◄──────────────┘
                            (Azure Function, HTTP Interactions,
                             interactive slash commands)
```

Module-level detail belongs in `docs/project/architecture-pipeline-overview.md`
once built; this section is the intended shape, not a built-state description.

---

## 4. Functional requirements

| ID | Requirement |
|---|---|
| FR-CC-1 | The corpus SHALL be auto-aggregated, keyed off the same normalized skill tags gap detection produces (`normalize_skill`), so it grows as new gap types appear with no manual list maintenance. GitHub repositories are the first source type. |
| FR-CC-2 | The aggregator SHALL query the GitHub Search API per skill, authenticated with a GitHub PAT, filtering to `stars > 200`, pushed within ~18 months, not archived, and having a README; it SHALL take the top N candidates per skill for the tagging pass. |
| FR-CC-3 | The aggregator SHALL seed initial coverage by harvesting repos from a configured set of "awesome-X" meta-lists matching the profile's domains, before per-skill dynamic search has run enough cycles. |
| FR-CC-4 | An LLM tagging pass (DeepSeek via LiteLLM) SHALL read each candidate's README and produce: skill(s) covered, resource type, estimated level, and a one-line summary. The distilled **summary** — not the raw README — SHALL be what is embedded and stored. |
| FR-CC-5 | Resources SHALL be stored in a `resources` table with a pgvector embedding column; embeddings SHALL be produced by a local model (`sentence-transformers/all-MiniLM-L6-v2`, 384-dim, CPU) with no external embeddings API call. |
| FR-CC-6 | Aggregation SHALL run on a weekly cadence, decoupled from the scheduled pipeline runs. |
| FR-CC-7 | The retriever SHALL, per detected gap, first pre-filter candidates by exact match on normalized `skills[]`, then rank the pre-filtered set by pgvector cosine similarity, returning the top 2–3 resources. |
| FR-CC-8 | A **new** Advisor coaching-tip stage SHALL generate tips via the LLM with the retrieved resources injected as structured context (title, URL, summary, type) and an explicit instruction to reference only the provided resources. This replaces the current static template tips. |
| FR-CC-9 | After generation, a **deterministic** validation step SHALL parse URLs from the LLM output and strip any URL not present in that gap's retrieved-resource set, logging it as a grounding violation. Enforcement SHALL NOT rely on the prompt instruction alone. |
| FR-CC-10 | A periodic link-health check SHALL re-verify `last_verified` for recently-surfaced resources; a resource whose URL fails verification SHALL drop out of retrieval until re-verified. |
| FR-CC-11 | Grounded tips SHALL be surfaced through the existing rendered report (per-role detail page), replacing the current templated positioning advice for listings that have gaps. |
| FR-CC-12 | A dedicated, interactive Discord bot — separate from the briefing notifier, on the same server in a new channel — SHALL support slash commands (at minimum `/tips <listing_id>` and `/resources <skill>`) via the Discord HTTP Interactions API hosted on an Azure Function, verifying Discord's request signature and responding within Discord's 3-second window. |
| FR-CC-13 | The bot SHALL be able to answer queries against `listing_gaps` and `resources` at arbitrary times, including while the scout VM is deallocated. |

---

## 5. Key design decisions

| ID | Decision | Rationale |
|---|---|---|
| **D-CC-1** | Corpus is auto-aggregated dynamically via the GitHub Search API keyed off normalized skill tags, not a static hand-curated list. | Grows automatically as new gap types appear; no manual list maintenance; reuses the naming the pipeline already produces. |
| **D-CC-2** | Retrieval uses pgvector semantic embeddings, not keyword/BM25. | Gaps are short skill phrases whose wording won't match resource text exactly; semantic matching handles paraphrase. Postgres is already the system of record, so pgvector avoids a second database technology. |
| **D-CC-3** | Retrieval is hybrid: an exact `skills[]` pre-filter, then vector ranking of the pre-filtered set. | Prevents pure-semantic false positives (e.g. "Java" resources matched to a "JavaScript" gap) while keeping semantic ranking within the correct skill. |
| **D-CC-4** | Embeddings use the local `all-MiniLM-L6-v2` model (384-dim, CPU). | No external embeddings API cost, consistent with the project's cost posture. Upgrade path: swap to a larger local model (e.g. `all-mpnet-base-v2`) by widening the `resources.embedding` column. |
| **D-CC-5** | Grounding is enforced by deterministic post-generation URL validation (an allow-list of the retrieved set), not by prompt instruction. | Extends the project's "LLM proposes, deterministic code enforces" rule (product PRS D2/D7) to coaching tips, so a hallucinated URL cannot reach the user. |
| **D-CC-6** | The coach bot is a new, dedicated bot, separate from the briefing push notifier. | On-demand querying is a different concern from a daily push; keeping them separate avoids overloading the briefing path and keeps each bot's permissions minimal. |
| **D-CC-7** | The bot uses the Discord HTTP Interactions API on an Azure Function (Consumption), not a gateway bot. | A gateway bot must hold a persistent connection, forcing something to run 24/7 and undermining the VM-deallocation cost model; a request/response Function does not. |
| **D-CC-8** | Postgres moves to an always-on Azure Database for PostgreSQL Flexible Server (Burstable), decoupled from the scout VM. | Interactive commands must query at arbitrary times, including while the VM is deallocated. This resolves the "move Postgres to managed Azure Database" item deferred in product PRS §8. |
| **D-CC-9** | Coaching tips become an LLM-generated, grounded stage, replacing the current deterministic Jinja template tips. | The existing template branches cannot cite real, per-gap resources; grounded citation requires generated prose constrained to a retrieved set plus deterministic validation. This is new work, not a prompt edit. |

---

## 6. Non-functional requirements

| ID | Requirement |
|---|---|
| NFR-CC-1 | **Cost:** local embedding model (no API cost); pgvector on the existing Postgres (no new database technology); weekly aggregation cadence to bound scrape volume. |
| NFR-CC-2 | **Latency:** top-k vector retrieval SHALL run synchronously in the Advisor stage with no new async infrastructure (typical retrieval < 100ms). |
| NFR-CC-3 | **Grounding integrity:** enforced by deterministic post-generation URL validation (NFR follows D-CC-5), never prompt-only. |
| NFR-CC-4 | **Corpus freshness:** weekly full aggregation plus a link-health spot-check on recently-surfaced resources between aggregations. |
| NFR-CC-5 | **Availability:** interactive commands SHALL be answerable while the scout VM is deallocated (satisfied by D-CC-8 and D-CC-7). |
| NFR-CC-6 | **Rate limits:** the aggregator SHALL authenticate with a GitHub PAT (5,000 req/hr) rather than unauthenticated search (60 req/hr). |
| NFR-CC-7 | **Secrets:** the GitHub PAT, Discord coach-bot token/public key, and managed-Postgres credentials SHALL be supplied via environment/secret configuration, never committed. |

---

## 7. Deployment & operations

Nothing in this feature is built yet; all components are **Planned**.

| Component | Status |
|---|---|
| Always-on Postgres (Azure DB for PostgreSQL Flexible Server, Burstable) + `resources` table + pgvector extension | **Planned** |
| Migration of `listing_gaps` / `run_listings` / `runs` off the VM Postgres | **Planned** |
| Resource aggregator (GitHub Search API + PAT + "awesome-X" bootstrap + LLM tagging) | **Planned** |
| Local embedding pipeline (`all-MiniLM-L6-v2`) — new dependency, not in `requirements.txt` today | **Planned** |
| Retriever module (skills pre-filter + pgvector top-2/3) | **Planned** |
| Advisor grounded tip stage + deterministic URL validator | **Planned** |
| Link-health checker | **Planned** |
| Discord coach bot (Azure Function behind the Interactions endpoint, slash commands) | **Planned** |

---

## 8. Open questions

Items marked *blocks planning: yes* must be resolved before an implementation
plan is written.

| # | Question | Blocks planning |
|---|---|---|
| Q1 | Which specific "awesome-X" meta-lists to harvest for bootstrap coverage (draft proposes Python / FastAPI / React / TypeScript / Docker / Azure). | No — a default set can start; refine later. |
| Q2 | Provision a fresh Flexible Server and migrate, or reconfigure the existing instance? Any downtime window constraint for the core pipeline during the switch? | **Yes** — determines migration sequencing and the pipeline's first affected run. |
| Q3 | Beyond `/tips <listing_id>` and `/resources <skill>`, which slash commands to define up front (e.g. `/status`, `/history`)? | No — the two named commands are enough to start. |
| Q4 | Do docs/courses/notes resource types get added in a later phase, or is `resource_type` variety deferred until repos prove out the pipeline? | No — schema already allows the variety; only `repo` is populated first. |

---

## 9. Related documents

- Product-level PRS this feature extends: `product-requirements-spec.md` (v2.1)
- Original loose feature draft this supersedes: `career-coach-agent.md` (Draft v0.2)
- Current architecture and module structure: `docs/project/architecture-pipeline-overview.md` (living document)
- Static-dashboard hosting rationale (VM deallocation cost model): `docs/agent/plans/static-dashboard-hosting/plan.md`
- Implementation plan: *to be written under `docs/agent/plans/career-coach-agent/` once this PRS and its blocking open questions (Q2) are approved.*
