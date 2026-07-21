# Phase 1: Schema, db functions, and pipeline wiring (persistence)

> **Parent plan:** [plan.md](plan.md)
> **Status:** Complete
> **Depends on:** nothing

---

## Goal

A pipeline run persists its scored listings under a stable `run_date`
key, readable back via `get_run_by_date`/`list_runs`/`get_run_listings`,
wired into `ScoutPipelineAgent` without changing existing scraper/
scorer/briefing behavior.

## Safety Checklist

- **Touches user input, auth, secrets, or external calls?** No — DB
  writes only, same connection pool already used for `listings`.
- **Contains a one-way door (schema, public API shape, new dependency)?**
  Yes — new `runs`/`run_listings` tables. ⚠️ Task 1 (schema) is gated on
  human sign-off before running against a real database.

---

## Tasks

### Task 1: Schema migration

- **Files:** `scout/shared/schema.sql`, `tests/test_db.py`
- **Gate:** ⚠️ human sign-off required before applying against a real
  (non-test) database — new tables are a one-way door once data
  accumulates.
- **Steps:**
  - [x] Write failing test: `apply_schema` creates `runs` and
        `run_listings` with the expected columns/constraints (query
        `information_schema` or attempt a constraint-violating insert
        and expect it to fail)
  - [x] Verify it fails (`./.venv/Scripts/python.exe -m pytest tests/test_db.py -q`)
  - [x] Add the `CREATE TABLE IF NOT EXISTS runs (...)` and `run_listings
        (...)` statements to `scout/shared/schema.sql`
  - [x] Verify it passes (`./.venv/Scripts/python.exe -m pytest tests/test_db.py -q`)
  - [x] Commit: `feat(db): add runs and run_listings tables` (14a153a)

### Task 2: Run read/write functions

- **Files:** `scout/shared/db.py`, `scout/shared/schemas.py`, `tests/test_db.py`
- **Gate:** none
- **Steps:**
  - [x] Write failing tests: `start_run` creates a row and is idempotent
        per `run_date`; `finish_run` updates counts/`finished_at`;
        `record_run_listings` inserts and upserts on conflict;
        `get_run_by_date`/`list_runs`/`get_run_listings` return the
        expected `Run`/`RunListing` objects
  - [x] Verify it fails (`./.venv/Scripts/python.exe -m pytest tests/test_db.py -q`)
  - [x] Implement `Run`/`RunListing` models in `scout/shared/schemas.py`
        and the six functions in `scout/shared/db.py`
  - [x] Verify it passes (`./.venv/Scripts/python.exe -m pytest tests/test_db.py -q`)
  - [x] Commit: `feat(db): add run persistence read/write functions` (c51fb19)

### Task 3: Pipeline wiring

- **Files:** `scout/agent.py`, `tests/test_agent.py`
- **Gate:** none
- **Steps:**
  - [x] Write failing test: a full `ScoutPipelineAgent` run (with a
        fake scorer/scraper, matching existing `test_agent.py` fixtures)
        results in a persisted run queryable by today's date
  - [x] Verify it fails (`./.venv/Scripts/python.exe -m pytest tests/test_agent.py -q`)
  - [x] Add the `start_run` → `record_run_listings` → `finish_run` step
        between `run_scorer` and `run_briefing` in
        `ScoutPipelineAgent._run_async_impl`
  - [x] Verify it passes (`./.venv/Scripts/python.exe -m pytest tests/test_agent.py -q`)
  - [x] Commit: `feat(agent): persist run results before briefing` (4eb8f6d, fix 34bd886)

---

## Verification

- [x] All phase tests pass: `./.venv/Scripts/python.exe -m pytest tests/test_db.py tests/test_agent.py -q` — 22/22 passing
- [x] Full suite unaffected: `./.venv/Scripts/python.exe -m pytest -q` — 152/152 passing
- [ ] Manual: `docker compose up --build`, then confirm a `runs` row
      exists for today via `psql` against the `scout` database. **Not
      yet done** — deferred to a full end-to-end manual pass once all
      5 phases are wired (see plan.md Testing Strategy).

## Observability

A new status event (`"Run persisted: <run_date>"` or similar) is yielded
from `ScoutPipelineAgent`, visible in the existing `logger.info` output
in `scout/main.py` — confirms persistence ran without needing to query
the database directly.

## Rollback

Revert the `scout/agent.py` wiring change (Task 3) to stop writing new
rows immediately. The schema additions (Task 1) can stay in place
harmlessly (unused tables) or be dropped manually if needed — no
existing table's shape changed.

---

## Notes / Learnings

- Task 3's first pass left `test_scout_pipeline_agent_reports_progress_for_full_run`
  (a pre-existing test) unguarded against a real Postgres dependency —
  the persistence wiring made it reach `create_pool` for real with no
  mock and no skip fixture. Task review caught this as Critical; fixed
  in 34bd886 by monkeypatching `create_pool`/`start_run`/
  `record_run_listings`/`finish_run` in that test, consistent with its
  sibling short-circuit test's style. Lesson for later phases: when
  wiring a new stage into `ScoutPipelineAgent`, check every existing
  test that exercises the full-pipeline path, not just the ones the
  task brief names.
- `record_run_listings` resolves `listing_id` via an INNER JOIN against
  `listings` on `(source, external_id)` — any match whose listing isn't
  already in the `listings` table is silently dropped, not persisted.
  This holds in practice because the tracker stage always upserts a
  listing before scoring, but it's undocumented in code (only in this
  plan's Task 2 review notes) — worth a one-line comment if this file
  is touched again.
