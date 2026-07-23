# Phase 2: Persistence Robustness

> **Parent plan:** [plan.md](plan.md)
> **Status:** Complete
> **Depends on:** nothing (independent of Phase 1)

---

## Goal

A run that dies partway through the Advisor persistence never leaves a
half-written, unfinished run live on the dashboard, and silently dropped
listings become visible. Achieved by wrapping the final persistence block
in one transaction and logging extraction drops.

## Safety Checklist

- **Touches user input, auth, secrets, or external calls?**
  No new external calls. Touches DB write ordering.
- **Contains a one-way door (schema, public API shape, new dependency)?**
  No — transaction wrapping is code-only, no migration.

---

## Tasks

### Task 1: Warn when the extraction LLM drops scored listings

- **Files:** `scout/agent.py`, `tests/test_agent.py` (or the existing agent-level test module)
- **Gate:** none
- **Steps:**
  - [x] Write failing test: given `matches` of length 3 and a `requirements` list covering only 2 of them, the pipeline emits a status/log warning naming the dropped count.
  - [x] Verify it fails (`pytest tests/ -k drop -q`)
  - [x] Implement: after building `matches_with_requirements`, if `len(matches_with_requirements) < len(matches)`, yield a `_status_event` (and/or log) noting `len(matches) - len(matches_with_requirements)` listings had no extracted requirements.
  - [x] Verify it passes (`pytest tests/ -k drop -q`)
  - [x] Commit: `fix(pipeline): warn when extraction drops scored listings`

### Task 2: Wrap the final persistence block in one transaction

- **Files:** `scout/agent.py`, `tests/` (agent-level integration test)
- **Gate:** none
- **Steps:**
  - [x] Write failing test: inject a failure (monkeypatch `finish_run` to raise) after `record_run_listings`/`record_listing_gaps`/`record_listing_meta`; assert that after the exception the DB has **no** `run_listings` rows and no `listing_gaps` for that `run_id`, and `runs.finished_at` is NULL. (Uses the existing DB integration harness / test database — `test_scout_pipeline_agent_rolls_back_on_mid_persist_failure`.)
  - [~] Verify it fails / passes — **DB-backed, skips locally** (no Postgres in the dev sandbox); runs against Postgres in CI. Non-DB agent ordering tests were verified green locally (17 passed).
  - [x] Implement: open a single `async with conn.transaction():` spanning `record_run_listings`, `record_listing_gaps`, `record_listing_meta`, `finish_run`, and the run/history renders (which read this run's rows through the same connection). `record_run_listings` moved out of its early standalone acquire into this block so nothing persists until both LLM passes have completed. Kept the inner `conn.transaction()` in `record_listing_gaps` (asyncpg nests it as a harmless savepoint) because `test_record_listing_gaps_rolls_back_delete_when_insert_fails` encodes its self-atomic contract.
  - [x] Commit: `fix(pipeline): persist run atomically in a single transaction`

### Task 3: Confirm re-run idempotency under the new transaction

- **Files:** `tests/` (agent-level integration test)
- **Gate:** none
- **Steps:**
  - [x] Write characterization test: run the full pipeline twice for the same `run_date`; assert exactly one `runs` row and `run_listings` upserted (no duplicates), stable score — `test_scout_pipeline_agent_same_date_rerun_is_idempotent`.
  - [~] Verify — **DB-backed, skips locally**; runs against Postgres in CI. Collection + non-DB tests green locally.
  - [x] Implement: no code change needed — `start_run` upserts on `run_date`, `record_run_listings` upserts on `(run_id, listing_id)`, `record_listing_gaps` delete-then-inserts; the transaction change preserved all three. Test locks the guarantee.
  - [x] Commit: `test(pipeline): lock same-date re-run idempotency`

---

## Verification

- [~] All phase tests pass: `pytest tests/test_agent.py -q` — non-DB green locally (5 passed); the three DB-backed tests (`drop` warning aside) skip without Postgres and run in CI.
- [ ] Manual: trigger a run, kill it after scoring (or via the injected fault in the test), then trigger a fresh run for the same date and confirm the dashboard shows a complete, consistent run.

## Observability

- New status/log line: dropped-listing count when extraction is short.
- On failure, the absence of a `finished_at` on the `runs` row is the
  signal that a run did not complete; the next same-date run heals it.

## Rollback

Revert the commits; persistence returns to per-call connections. No state
migration to undo.

---

## Notes / Learnings

<Filled in during execution.>
