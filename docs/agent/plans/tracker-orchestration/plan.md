# Plan: Tracker Orchestration

> **Status:** Complete
> **Created:** 2026-07-17 · **Last updated:** 2026-07-17
> **Spec:** [spec.md](../../specs/tracker-orchestration/spec.md)

---

## Overview

Implements the Tracker stage of the Scraper → Tracker → Scorer → Briefing
pipeline: a Postgres-backed Storage module (`scout/shared/schema.sql`,
`scout/shared/db.py`) per the approved design in
`docs/agent/specs/listings-db/spec.md`, plus the orchestration entry point
`track_listings()` in `scout/tools/tracker.py` that upserts a scraped
batch, classifies each listing new/changed/unchanged/closed, and returns
only new/changed listings for the Scorer. Done means both empty stub files
are implemented, tested against a real local Postgres, and `track_listings`
is callable in isolation with no other pipeline wiring required.

## Acceptance Criteria

- [ ] `apply_schema` creates the `listings` table idempotently (safe to run twice).
- [ ] `upsert_listing` persists a listing and correctly classifies it as `new`, `changed`, or `unchanged`, including a closed listing reopening as `changed`.
- [ ] `close_stale_listings` closes previously-open rows absent from the current batch's keys and leaves seen rows open.
- [ ] `track_listings(listings)` persists every listing, returns only new/changed listings in classification order, and excludes unchanged ones.
- [ ] `track_listings` self-manages a pool (create + apply schema + close) when none is passed, and reuses a caller-supplied pool without closing it.
- [ ] A re-run of `track_listings` after a prior partial failure is safe: already-committed listings classify as `unchanged` on retry.
- [ ] Both modules are runnable and testable in isolation against a local Postgres started via `docker-compose`.

---

## Risks & Unknowns

| Risk / unknown | Impact if wrong | Resolution |
|----------------|-----------------|------------|
| Local dev interpreter may be newer (3.14) than the Docker image (3.12-slim); `asyncpg` may lack a prebuilt wheel for the newer interpreter | `pip install asyncpg` fails locally even though it would work in the container | Accepted risk — Task 1 of Phase 1 installs it and records the resolved version; if the wheel is missing, tests fall back to running inside the `app` container (`docker compose run app pytest`) instead of the host venv |
| No `pytest-asyncio` or async test infra exists yet in this repo | Integration tests can't `await` fixtures | Phase 1 Task 1 adds `pytest-asyncio` and a `pytest.ini` with `asyncio_mode = auto` before any async test is written |
| Tests need a reachable Postgres; CI/dev machines may not have one running | Tests fail with a connection error instead of skipping cleanly | Phase 1 Task 2 adds a `db_pool` fixture in `tests/conftest.py` that catches connection errors and calls `pytest.skip(...)`, per the spec's "auto-skipped when unreachable" testing strategy |

## Blast Radius

- **Code that will change:** `scout/shared/db.py`, `scout/shared/schema.sql` (new), `scout/tools/tracker.py`, `scout/config.py`, `scout/.env.example`, `docker-compose.yaml`, `requirements.txt`, `tests/conftest.py` (new), `tests/test_db.py` (new), `tests/test_tracker.py` (new), `tests/test_config.py`, `pytest.ini` (new).
- **Existing behaviour that could break:** None — `db.py` and `tracker.py` are currently empty stubs, and all other touched files (`config.py`, `docker-compose.yaml`, `requirements.txt`, `.env.example`) only gain new fields/services, they don't change existing ones.
- **Off-limits:** Do not modify `scout/agent.py`, the Scraper/Scorer/Briefing sub-agents, or the `matches` table design — all explicitly out of scope per the spec's "Won't have" section.

---

## Phases

| # | Phase | Document | Status |
|---|-------|----------|--------|
| 1 | Storage module | [phase-1-storage-module.md](phase-1-storage-module.md) | Complete |
| 2 | Tracker orchestration | [phase-2-tracker-orchestration.md](phase-2-tracker-orchestration.md) | Complete |
| 3 | Pipeline: shared parsing helper *(merged from pipeline-orchestration)* | [phase-3-pipeline-shared-parsing.md](phase-3-pipeline-shared-parsing.md) | Complete |
| 4 | Pipeline: Scraper/Scorer runners *(merged from pipeline-orchestration)* | [phase-4-pipeline-stage-runners.md](phase-4-pipeline-stage-runners.md) | Complete |
| 5 | Pipeline: ScoutPipelineAgent *(merged from pipeline-orchestration)* | [phase-5-pipeline-agent.md](phase-5-pipeline-agent.md) | Complete |
| 6 | Pipeline: batch entrypoint + Dockerfile *(merged from pipeline-orchestration)* | [phase-6-pipeline-batch-entrypoint.md](phase-6-pipeline-batch-entrypoint.md) | Complete |

> Both phase documents were written up front at the human's explicit
> request, overriding plan-standards' default lazy-creation guidance.
> Phase 2 depends on Phase 1's Storage primitives (`create_pool`,
> `apply_schema`, `upsert_listing`, `close_stale_listings`) being
> implemented exactly as specified there before its tasks can run.
>
> Phases 3-6 are the `pipeline-orchestration` plan, merged in here
> 2026-07-21 (see Amendments) — they built the `ScoutPipelineAgent`
> orchestrator that runs Tracker (this plan's output) as one stage of
> the full Scraper → Tracker → Scorer → Briefing sequence. Their phase
> docs still refer to themselves as "Phase 1"-"Phase 4" internally;
> the numbers above reflect this plan's combined sequence, not a
> renumbering of the original files. Despite the original plan.md
> header reading "Not started," `scout/agent.py`, `scout/main.py`, and
> `scout/shared/parsing.py` all exist and are in active use — that
> status was never updated after the work completed.

---

## Testing Strategy

- **Unit:** None of this logic is meaningfully unit-testable without a database — `upsert_listing`'s classification depends entirely on prior row state, so all coverage is integration-level per the spec's stated approach.
- **Integration:** `tests/test_db.py` and `tests/test_tracker.py` run against a real local Postgres reached via `DATABASE_URL`/the default in `Settings`, started with `docker compose up -d postgres`. Auto-skipped via the `db_pool` fixture if unreachable. Each test truncates the `listings` table first for isolation.
- **Manual:** After Phase 2, manually run `docker compose up -d postgres` then a short Python snippet calling `track_listings` with a couple of `Listing` objects twice in a row, confirming the second call returns an empty list (all unchanged) and the DB rows show bumped `last_seen_at`.

## Rollout & Reversibility

- **Feature flag:** No — this is new, currently-unused code with no caller yet (root `SequentialAgent` wiring is out of scope per the spec).
- **Migrations:** None — `schema.sql` is additive, idempotent DDL (`CREATE TABLE/INDEX IF NOT EXISTS`), no migration framework per the listings-db spec.
- **Rollback plan:** Revert the commits; the `postgres` service and `listings` table are inert until something calls `track_listings`, so there is nothing running in production to roll back.

---

## Key Decisions & Constraints

- Fail-fast error handling throughout: DB failures raise, no silent fallback, no retry — matches the spec's Must-Have and the project's existing "resume file missing → fail fast" convention.
- No transaction wraps a `track_listings` batch — a mid-batch failure leaves prior upserts committed and skips stale-closing for that batch; safe because re-upserts are idempotent (spec's accepted alternative).
- `close_stale_listings` closes globally across all open listings — no multi-search-config scoping (YAGNI, per both specs).
- ⚠️ **One-way doors:** None identified — the schema is additive/idempotent and there's no external consumer yet, so nothing here is hard to reverse.

## Out of Scope

- Root `scout/agent.py` `SequentialAgent` wiring (future session).
- Scheduler / Azure hosting / CI-CD.
- The deferred `matches` table (score persistence).
- Retry/reconnect logic beyond asyncpg's pool defaults.

---

## Definition of Done

- [ ] All acceptance criteria met
- [ ] All phase verification steps pass
- [ ] Feature verified manually in a running environment
- [ ] Docs / README updated where behaviour changed
- [ ] No new lint or type-check warnings

## Update Rules

- Phase docs hold task-level detail; this file holds phase-level status only.
- When a phase's scope changes, update its row here **in the same commit**.
- On conflict, this file wins for *what* the phases are; the phase doc
  wins for *how* its tasks are done.

## Amendments

- 2026-07-21: Merged the `pipeline-orchestration` plan into this one as
  Phases 3-6 (their phase docs moved here unchanged, files renamed
  with a `pipeline-` prefix to avoid collisions). Rationale: that plan
  built the root orchestrator that runs this plan's Tracker as one
  stage of the full pipeline — the two are tightly coupled and
  `pipeline-orchestration` was small enough not to warrant staying a
  separate top-level plan. Original `docs/agent/plans/pipeline-orchestration/`
  folder deleted. Summary of the merged plan's own metadata below.

### Merged: Pipeline Orchestration plan summary

**Goal:** wire Scraper, Tracker, Scorer, and Briefing together via a
`ScoutPipelineAgent` (custom ADK `BaseAgent`) exported as `root_agent`
for `adk web`, plus a `scout/main.py` batch entrypoint replacing the
Dockerfile's `adk api_server` CMD.

**Acceptance criteria (all met — see phase docs for verification detail):**
- `adk web` discovers `root_agent`; sending it a message runs all four
  stages with a distinct status message after each.
- Zero new/changed listings short-circuits Scorer and Briefing.
- `python -m scout.main` runs once, exits 0/non-zero correctly.
- `Dockerfile`'s `CMD` runs `scout.main`, not `adk api_server`.

**Key decisions carried forward:** no separate `run_scout` plain-function
orchestrator — `ScoutPipelineAgent._run_async_impl` is the single place
the four-stage sequence lives, shared by both `adk web` and the batch
path; progress is reported via ADK `Event`s (short text), not by
passing stage data through ADK session state (that still flows as
typed Python values between direct function calls, preserving Decision
D3 from this plan's own spec); a single `Settings` instance is threaded
through every stage call within one run.

**Out of scope (unchanged):** a scheduler/cron trigger for daily runs
(see Appendix C in this plan's spec.md for the never-implemented
Azure VM CI/CD design); persisting match scores to a `matches` table;
retry or partial-failure recovery across stages.
