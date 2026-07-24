# Career Coach Agent — Feature Specification
## Grounded Learning-Resource Recommendations & Discord Integration

**Status:** Draft v0.2
**Author:** Trung
**Reviewer:** Anh Phuc
**Depends on:** job-market-scout (gap detection, `listing_gaps` table)
**Date:** 2026-07-24

---

## 1. Purpose

Extend the Career Coach Agent so that, for each job listing with detected skill gaps, the Advisor stage produces coaching tips that point to **real, verifiable learning resources** rather than generic advice. This closes the loop from "you're missing X" to "here's exactly where to learn X."

Two capabilities are in scope:

1. **Resource retrieval per gap** — a curated corpus of learning resources (docs, courses, repos, notes), auto-aggregated, searchable, and injected into the Advisor's prompt so tips cite top-k matches per gap.
2. **Discord agent** — a new, dedicated bot that delivers coaching output (and optionally supports on-demand queries) in its own channel, separate from job-market-scout's existing notification bot.

## 2. Out of Scope

- Re-scoring or re-ranking job listings (job-market-scout's job).
- Editing `profile.json` or gap-detection logic itself — this feature *consumes* `listing_gaps`, it doesn't change how gaps are found.
- Paid/licensed course content behind logins (corpus only indexes publicly reachable, freely accessible resources).

## 3. Architecture Overview

```
                         ┌─────────────────────────┐
                         │   Resource Aggregator    │  (scheduled job, weekly)
                         │  GitHub Search API per   │
                         │  normalized skill tag    │
                         └────────────┬─────────────┘
                                      │ writes
                                      ▼
                    ┌────────────────────────────────────┐
                    │  Postgres Flexible Server (Burstable)│  <-- always-on, decoupled
                    │  resources / embeddings (pgvector)   │      from the scout VM
                    │  listing_gaps / run_listings / runs  │
                    └───────┬───────────────────┬──────────┘
                            │ top-k query        │ query gaps/history
                            ▼                    │
┌───────────────┐    listing_gaps                │
│ job-market-    │──────────────▶ ┌─────────────────┐        │
│ scout pipeline │                │  Retriever        │        │
│ (VM, on/off)   │                │  (per gap, top 2-3)│        │
└───────────────┘                 └─────────┬─────────┘        │
                                             │ context injection│
                                             ▼                  │
                                   ┌───────────────────┐        │
                                   │  Advisor (LLM)     │──▶ grounded tips
                                   └─────────┬─────────┘        │
                                             │                  │
                              ┌──────────────┴───────────────┐  │
                              ▼                               ▼  │
                      Report/Dashboard                 Discord Coach Bot◀───────┘
                     (existing Jinja2 UI)              (Azure Function, HTTP
                                                         Interactions API,
                                                         same server as scout,
                                                         interactive slash cmds)
```

The Career Coach Agent runs as its own service/module. It shares the Postgres instance with job-market-scout, but that instance now lives on an **always-on Postgres Flexible Server** rather than on the scout VM itself — this is what lets the interactive Discord bot (Section 7) query gaps/resources at any time, even during the ~23h/day the scout VM is deallocated.

## 4. Resource Corpus — Auto-Aggregation

**Decision:** corpus is built automatically rather than hand-seeded, starting with GitHub repos as the source type.

**4.1 Sourcing mechanism — dynamic discovery via GitHub Search API, not a static list:**

```
GET https://api.github.com/search/repositories
  ?q=topic:<normalized_skill> stars:>200 pushed:>2024-01-01 archived:false
  &sort=stars&order=desc
```

- Query keyed off the same normalized skill tags job-market-scout already produces during gap detection — so the corpus grows automatically as new gap types appear, without manual list maintenance.
- Filters: `stars > 200` (quality signal), pushed within ~18 months (excludes abandoned repos), not archived, has a README (needed for the summarization pass below).
- Take top 5 candidates per skill; the LLM tagging pass below narrows further.
- **Requires a GitHub PAT** — unauthenticated search is capped at 60 requests/hr; a PAT raises this to 5,000/hr, needed once querying per-skill across many gaps weekly.
- **Bootstrap step:** seed initial coverage by harvesting repos linked from a handful of well-known "awesome-X" meta-lists matching your profile's domains (Python, FastAPI, React/TypeScript, Docker, Azure) — gives quality-vetted coverage before the per-skill dynamic search has run enough cycles to build its own.

**4.2 Freshness and quality gate:**

- Weekly aggregation cadence, decoupled from the twice-daily scout pipeline runs.
- A lightweight LLM pass (DeepSeek via LiteLLM) reads each repo's README and tags it with: skill(s) covered, resource type (`repo`), estimated level (beginner/intermediate/advanced), and a one-line summary. This distilled text — not the raw README — is what gets embedded (see Section 5) and stored in `resources.summary`, keeping the embedding focused on skill-relevant content rather than diluted by badges/install boilerplate.

### 4.1 Proposed schema (Postgres)

```sql
CREATE TABLE resources (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    url           TEXT NOT NULL UNIQUE,
    title         TEXT NOT NULL,
    resource_type TEXT NOT NULL,   -- 'doc' | 'course' | 'repo' | 'note'
    skills        TEXT[] NOT NULL, -- normalized skill tags (reuse scout's skill-name normalization)
    level         TEXT,            -- 'beginner' | 'intermediate' | 'advanced'
    summary       TEXT,
    embedding     VECTOR(384),     -- pgvector; dim depends on embedding model chosen
    source        TEXT NOT NULL,   -- which aggregation source this came from
    last_verified TIMESTAMPTZ,     -- last time the URL was confirmed reachable (200 OK)
    created_at    TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX ON resources USING ivfflat (embedding vector_cosine_ops);
```

`last_verified` matters for grounding (Section 6) — a resource whose URL 404s should drop out of retrieval until re-verified.

## 5. Retrieval Method — Confirmed

**Confirmed: vector embeddings via pgvector**, not keyword/BM25. Top-k = **2–3 resources per gap**.

Reasoning:
- Gaps are phrased as skill names/short phrases ("Kubernetes", "event-driven architecture") and resource titles/summaries won't always share exact keywords — semantic matching handles paraphrasing much better than BM25 here.
- Postgres is already the system of record for job-market-scout; **pgvector** avoids introducing a second database technology.
- **Embedding model confirmed: `sentence-transformers/all-MiniLM-L6-v2`** — local, free, runs on CPU, 384-dim. No external embeddings API cost, consistent with the project's cost posture. Upgrade path if match quality is ever insufficient: swap to a larger local model (e.g. `all-mpnet-base-v2`), which only requires widening the `resources.embedding` column to match its output dimension.
- Fallback: keep a simple keyword filter on `skills[]` as a pre-filter before the vector search (cheap, exact match on normalized skill tags), then rank the pre-filtered set by embedding similarity. This hybrid avoids pure-semantic false positives (e.g. matching "Java" resources to a "JavaScript" gap).

## 6. Grounding the Advisor's Tips

The core requirement — tips must link to *real* resources, never hallucinated ones. Mechanism:

1. Retriever runs top-k (e.g. k=3) per detected gap **before** the Advisor LLM call.
2. Retrieved resources (title, URL, summary, type) are injected into the Advisor's prompt as structured context, with an explicit instruction: *only reference resources from the provided list; do not invent URLs or titles.*
3. **Post-generation validation step** (deterministic, not LLM-trusted): after the Advisor responds, parse out any URLs it included and check each one against the retrieved-resource list. Any URL not in that list is stripped and logged as a grounding violation — this is the actual enforcement, not just a prompt instruction.
4. Periodic link-health check (e.g. daily, alongside the weekly corpus refresh) re-verifies `last_verified` for resources actually surfaced recently, so dead links age out of circulation quickly rather than waiting for the next full re-aggregation.

This mirrors the existing pattern in job-market-scout of "LLM proposes, deterministic code persists/enforces" (e.g. `classify_band`, single-writer-per-table) — keeping that separation here too.

## 7. Discord Agent — New Dedicated, Interactive Bot

**Confirmed:** a separate bot from job-market-scout's existing Discord notifier, on the **same Discord server** (new dedicated channel), and **interactive** — supporting on-demand slash commands, not just push notifications.

**Deployment mechanism — Discord HTTP Interactions API, not a gateway bot:**

- Register slash commands via the Discord Developer Portal (e.g. `/tips <listing_id>`, `/resources <skill>`); set the Interactions Endpoint URL to point at an **Azure Function (Consumption plan)**.
- Discord POSTs each command invocation to the Function; the Function responds within Discord's 3-second window, then the Function shuts down. No persistent connection to maintain.
- This avoids the alternative — a gateway-based bot (`discord.py`/`nextcord`) that must stay connected continuously — which would force something to run 24/7 just for the bot, undermining the cost model of deallocating the scout VM ~23h/day.

**Infra consequence — Postgres must be always-on:**

Interactive commands need to query `listing_gaps`/`resources` at arbitrary times, including while the scout VM is deallocated. This means Postgres can no longer live only on that VM. Recommended fix: move Postgres to **Azure Database for PostgreSQL Flexible Server (Burstable tier)** — small, always-on, decoupled from the batch-compute VM, affordable on the Azure for Students subscription. (Alternative if budget is tight: have the Function read from the already-published static dashboard data in Azure Storage instead of live Postgres — works for read-only "show my gaps" queries but won't support anything needing a fresh, uncached query.)

## 8. Non-Functional Requirements

| Concern | Approach |
|---|---|
| Cost | Local embedding model (no API cost); pgvector on existing Postgres (no new managed service); weekly aggregation cadence to limit scrape volume |
| Latency | Retrieval (top-k vector search) is fast (<100ms typical); runs synchronously in the Advisor stage, no new async infra needed |
| Grounding integrity | Deterministic post-generation URL validation (Section 6), not prompt-only enforcement |
| Corpus freshness | Weekly full aggregation + daily link-health spot-check on recently-surfaced resources |
| Consistency with existing conventions | Reuses scout's skill-name normalization, DeepSeek/LiteLLM, Postgres, and "LLM proposes/deterministic code enforces" pattern |
| Availability for interactive Discord commands | Postgres moved to an always-on Flexible Server (Burstable), decoupled from the scout VM's on/off cycle; Discord bot hosted as an Azure Function (Consumption plan) reachable at any time |
| GitHub API rate limits | Aggregator authenticates with a GitHub PAT (5,000 req/hr) rather than unauthenticated search (60 req/hr) |

## 9. Open Questions (need a decision before implementation)

1. **Bootstrap "awesome-X" list selection** — which specific meta-lists to harvest for initial coverage (Section 4.1 proposes Python/FastAPI/React/TypeScript/Docker/Azure as a starting domain set — confirm or adjust).
2. **Postgres migration approach** — provision a fresh Flexible Server and migrate, or reconfigure the existing instance? Any downtime window constraints for job-market-scout during the switch?
3. **Slash command set** — beyond `/tips <listing_id>` and `/resources <skill>`, any other commands worth defining up front (e.g. `/status`, `/history`)?
4. **Non-skill resource types** — GitHub repos are the first source; do docs/courses/notes get added in a later phase, or should the schema's `resource_type` variety be deferred until repos prove out the pipeline?

## 10. Proposed Milestones

1. Provision always-on Postgres Flexible Server; migrate `listing_gaps`/`run_listings`/`runs`, add `resources` table + pgvector extension
2. GitHub Search API aggregator (skill-keyed queries + PAT) + "awesome-X" bootstrap harvest + LLM tagging pass + local embedding pipeline
3. Retriever module (skill pre-filter + pgvector top-2/3 search)
4. Advisor prompt update + deterministic post-generation URL-grounding validation
5. Discord bot: register slash commands, stand up Azure Function behind the Interactions endpoint, wire to Retriever/Advisor via the now-always-on Postgres
6. Manual end-to-end test: real run with known gaps → verify tips cite real, reachable resources → verify Discord slash commands return correct data while the scout VM is deallocated