# Phase 1: Schema, db functions, and pipeline wiring (persistence)

> **Parent plan:** [plan.md](plan.md)
> **Status:** Not started
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
  - [ ] Write failing test: `apply_schema` creates `runs` and
        `run_listings` with the expected columns/constraints (query
        `information_schema` or attempt a constraint-violating insert
        and expect it to fail)
  - [ ] Verify it fails (`./.venv/Scripts/python.exe -m pytest tests/test_db.py -q`)
  - [ ] Add the `CREATE TABLE IF NOT EXISTS runs (...)` and `run_listings
        (...)` statements to `scout/shared/schema.sql`
  - [ ] Verify it passes (`./.venv/Scripts/python.exe -m pytest tests/test_db.py -q`)
  - [ ] Commit: `feat(db): add runs and run_listings tables`

### Task 2: Run read/write functions

- **Files:** `scout/shared/db.py`, `scout/shared/schemas.py`, `tests/test_db.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing tests: `start_run` creates a row and is idempotent
        per `run_date`; `finish_run` updates counts/`finished_at`;
        `record_run_listings` inserts and upserts on conflict;
        `get_run_by_date`/`list_runs`/`get_run_listings` return the
        expected `Run`/`RunListing` objects
  - [ ] Verify it fails (`./.venv/Scripts/python.exe -m pytest tests/test_db.py -q`)
  - [ ] Implement `Run`/`RunListing` models in `scout/shared/schemas.py`
        and the six functions in `scout/shared/db.py`
  - [ ] Verify it passes (`./.venv/Scripts/python.exe -m pytest tests/test_db.py -q`)
  - [ ] Commit: `feat(db): add run persistence read/write functions`

### Task 3: Pipeline wiring

- **Files:** `scout/agent.py`, `tests/test_agent.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing test: a full `ScoutPipelineAgent` run (with a
        fake scorer/scraper, matching existing `test_agent.py` fixtures)
        results in a persisted run queryable by today's date
  - [ ] Verify it fails (`./.venv/Scripts/python.exe -m pytest tests/test_agent.py -q`)
  - [ ] Add the `start_run` → `record_run_listings` → `finish_run` step
        between `run_scorer` and `run_briefing` in
        `ScoutPipelineAgent._run_async_impl`
  - [ ] Verify it passes (`./.venv/Scripts/python.exe -m pytest tests/test_agent.py -q`)
  - [ ] Commit: `feat(agent): persist run results before briefing`

---

## Verification

- [ ] All phase tests pass: `./.venv/Scripts/python.exe -m pytest tests/test_db.py tests/test_agent.py -q`
- [ ] Full suite unaffected: `./.venv/Scripts/python.exe -m pytest -q`
- [ ] Manual: `docker compose up --build`, then confirm a `runs` row
      exists for today via `psql` against the `scout` database.

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

<Filled in during execution.>
