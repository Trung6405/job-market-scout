# Spec: Career Coach P1 — Resource Aggregator

> **Status:** Approved
> **Created:** 2026-07-24 · **Approved:** 2026-07-25
> **Implementation plan:** [plan.md](../../plans/career-coach-p1-aggregator/plan.md) *(created after approval)*
> **Umbrella PRS:** `docs/project/specification/career-coach-agent-prs.md` (v1.1) — this is phase **P1** of Stage 1.
> **Depends on:** P0 (`resources` table + pgvector, merged).

---

## Problem

The `resources` table exists (P0) but is empty, and nothing populates it. Every
later Career Coach phase — the retriever (P2), the grounded-tip stage (P3) —
needs a corpus of real, verifiable learning resources to search, keyed off the
same normalized skill names gap detection already produces. Without an
aggregator, there is no corpus, so retrieval and grounding cannot be built or
tested.

## Success Criteria

- Given a skill gap that exists in `listing_gaps` (e.g. `"kubernetes"`), the
  `resources` table contains at least one row whose `skills[]` includes that
  skill, with a real, reachable GitHub URL, a non-empty summary, and a
  384-dim embedding.
- Running the aggregator twice in a row does not duplicate rows or re-spend
  LLM/embedding cost on resources already stored.
- The aggregator runs on its own weekly cadence without adding a new
  always-on process or a second VM wake/deallocate cycle.

---

## Requirements

### Must have

- Query the GitHub Search API per normalized skill (from `listing_gaps`),
  authenticated with a GitHub PAT, filtered to `stars > 200`, pushed within
  ~18 months, not archived, has a README; take the top N candidates per skill.
- Seed initial coverage by harvesting repo links from a configured set of
  "awesome-X" meta-lists.
- Deduplicate candidates against `resources.url` before doing any LLM/embedding
  work — an already-stored URL is skipped entirely, not re-fetched or re-tagged.
- Run an LLM tagging pass (DeepSeek via the existing `complete_json` helper)
  over each new candidate's README, producing skill(s), resource type, level,
  and a one-line summary; store the **summary**, not the raw README.
- Produce a 384-dim embedding of the summary via a local model
  (`sentence-transformers/all-MiniLM-L6-v2`) and store it alongside the row.
- Insert each new resource into `resources` via a single, reusable DB helper.
- Run on a weekly cadence, without requiring the VM to wake outside its
  existing schedule.

### Should have

- A configurable top-N-per-skill and configurable awesome-list URLs, following
  the existing `Settings` dataclass / env-var convention.
- A `get_distinct_gap_skills` query so the skill list driving aggregation stays
  live (grows automatically as new gap types appear), not hand-maintained.

### Won't have

- The retriever (P2) — this phase only writes to `resources`, it does not
  query it for similarity.
- The Advisor grounded-tip stage or its URL validator (P3).
- Non-`repo` resource types (`doc`/`course`/`note`) — the schema already
  allows them (P0); only `repo` is populated here (umbrella Q4).
- Link-health re-verification of already-stored resources (P5) — P1 only
  verifies reachability implicitly by requiring a README to exist at
  candidate time; it does not re-check `last_verified` later.
- A dedicated GitHub client library — see Alternatives.

---

## Proposed Approach

A new `scout/sub_agents/coach/` package, mirroring the existing `advisor` /
`scorer` sub-agent layout, plus a thin top-level entrypoint
(`scout/coach_aggregator.py`, mirroring `scout/main.py`):

- **`github_search.py`** — calls the GitHub Search API directly via `requests`
  (already a project dependency), PAT-authenticated, applying the
  stars/pushed/archived/README filters and taking the top N per skill.
- **`bootstrap.py`** — harvests repo links from a configured set of "awesome-X"
  meta-list URLs, for initial coverage before per-skill search has run enough
  cycles.
- **`tagging.py`** — one LLM call per new candidate via the existing
  `scout/shared/llm.complete_json(prompt, schema, settings)` pattern (same one
  the Scorer/Advisor already use), returning skill(s), resource type, level,
  and summary as a pydantic model.
- **`embeddings.py`** — a lazily-initialized, module-level
  `SentenceTransformer("all-MiniLM-L6-v2")` singleton (loaded once per process,
  not per resource) exposing `embed(text: str) -> list[float]`.
- **`runner.py`** — orchestrates one aggregation pass: fetch the current
  distinct gap skills, gather GitHub + bootstrap candidates, drop anything
  already in `resources` by URL, tag + embed + insert what's left.

**Shared additions** other phases (P2, P5) will build on:
- `scout/shared/schemas.py`: a `Resource` pydantic model matching the `resources`
  columns (`embedding`/`id`/`created_at` excluded — those are set at insert
  time, not part of the model a caller constructs).
- `scout/shared/db.py`: `insert_resource(conn, resource, embedding) -> Literal["new", "duplicate"]`
  (uses `ON CONFLICT (url) DO NOTHING`, mirroring the idempotency pattern
  `upsert_listing` already uses) and `get_distinct_gap_skills(conn) -> list[str]`.

**Config** (`scout/config.py`, following the existing `_env_*` helpers):
`github_pat: str`, `coach_top_n_per_skill: int = 5`,
`coach_awesome_lists: list[str]` (CSV, default covering the profile's current
domains: Python, FastAPI, React, TypeScript, Docker, Azure).

**New dependency:** `sentence-transformers` (pulls in `torch`) added to
`requirements.txt` — the accepted image/cold-start cost from the umbrella
PRS's D-CC-4.

**Trigger:** `.github/workflows/scheduled-run.yml` gets one additional step
after the pipeline run, gated on day-of-week (e.g. Monday), invoking
`python -m scout.coach_aggregator` over the same SSH session already opened
for the daily run. No new workflow file, no additional VM start/stop.

## Alternatives Considered

| Alternative | Why rejected |
|-------------|--------------|
| PyGithub (dedicated GitHub client library) | New dependency for a single search endpoint's worth of use; `requests` (already a project dependency) covers the one call needed, matching the PRS's own raw-GET example. |
| Dedicated weekly GitHub Actions workflow, own VM start/stop | Fully decoupled but costs an extra VM wake/deallocate cycle every week purely for this; piggybacking on the existing nightly wake achieves the same weekly cadence (FR-CC-6) at no extra infra cost. |
| Hand-maintained static skill list to drive aggregation | Contradicts FR-CC-1 (auto-aggregated, no manual list maintenance); `get_distinct_gap_skills` keeps the driving list live off `listing_gaps`. |
| Re-tag/re-embed every resource on every weekly run | Wastes LLM/embedding cost reprocessing unchanged resources; the URL-uniqueness dedupe (P0) makes skip-on-duplicate essentially free to implement and keeps weekly runs cheap. |
| Do nothing | No later phase (retriever, grounded tips) can be built or tested without a populated corpus; this is the hard prerequisite after P0's empty table. |

---

## Open Questions

| Question | Who decides | Blocks planning? |
|----------|-------------|------------------|
| Exact default awesome-list URLs (umbrella Q1) | human | No — a default set (Python/FastAPI/React/TypeScript/Docker/Azure) ships and can be refined later via config, no code change needed. |

> No question blocks planning.

---

## Amendments *(only after approval — never silently edit approved content)*

- **2026-07-27 — `resources.skills[]` is normalized on write.** Surfaced while
  brainstorming P2. As built, the tagged skills were stored verbatim from the
  LLM, relying on the tagging prompt's "use canonical names" instruction. That
  is best-effort wording, not the deterministic guarantee FR-CC-1 names
  (`normalize_skill`), so a tagger returning `"K8s"` or `"React.js"` would have
  written rows the P2 retriever's exact `skills[]` pre-filter (FR-CC-7) could
  never match. `normalize_skill` moves from `scout/sub_agents/advisor/gaps.py`
  to `scout/shared/skills.py` — it is now the shared canonical form on both
  sides of retrieval, and the Coach importing it from the Advisor would have
  been the wrong dependency direction. `runner.py` applies it (deduping
  collisions, dropping empties) before constructing each `Resource`.
  No backfill: the corpus is empty until this ships.
