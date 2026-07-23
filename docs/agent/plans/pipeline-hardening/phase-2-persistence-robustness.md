# Phase 2: Persistence Robustness

> **Parent plan:** [plan.md](plan.md)
> **Status:** Not started
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
  - [ ] Write failing test: given `matches` of length 3 and a `requirements` list covering only 2 of them, the pipeline emits a status/log warning naming the dropped count.
  - [ ] Verify it fails (`pytest tests/ -k drop -q`)
  - [ ] Implement: after building `matches_with_requirements`, if `len(matches_with_requirements) < len(matches)`, yield a `_status_event` (and/or log) noting `len(matches) - len(matches_with_requirements)` listings had no extracted requirements.
  - [ ] Verify it passes (`pytest tests/ -k drop -q`)
  - [ ] Commit: `fix(pipeline): warn when extraction drops scored listings`

### Task 2: Wrap the final persistence block in one transaction

- **Files:** `scout/agent.py`, `tests/` (agent-level integration test)
- **Gate:** none
- **Steps:**
  - [ ] Write failing test: inject a failure (monkeypatch `finish_run` to raise) after `record_run_listings`/`record_listing_gaps`/`record_listing_meta`; assert that after the exception the DB has **no** `run_listings` rows and no `listing_gaps` for that `run_id`, and `runs.finished_at` is NULL. (Uses the existing DB integration harness / test database.)
  - [ ] Verify it fails (`pytest tests/ -k partial_persistence -q`) — currently rows persist because each call is its own connection.
  - [ ] Implement: acquire one connection and open a single `async with conn.transaction():` spanning `record_run_listings`, `record_listing_gaps`, `record_listing_meta`, `finish_run`, and the run/history render calls that read this run's uncommitted rows. Keep `render_profile` (no DB) outside. Remove the now-redundant inner `conn.transaction()` in `record_listing_gaps` or confirm nested transaction (savepoint) is harmless — prefer removing to avoid a savepoint per call.
  - [ ] Verify it passes (`pytest tests/ -k partial_persistence -q`)
  - [ ] Commit: `fix(pipeline): persist run atomically in a single transaction`

### Task 3: Confirm re-run idempotency under the new transaction

- **Files:** `tests/` (agent-level integration test)
- **Gate:** none
- **Steps:**
  - [ ] Write failing//characterization test: run the persistence block twice for the same `run_date` with the same inputs; assert exactly one `runs` row, `run_listings` upserted (no duplicates), `listing_gaps` fully replaced (delete-then-insert), and counts stable.
  - [ ] Verify current behaviour (`pytest tests/ -k idempotent -q`)
  - [ ] Implement only if the transaction change broke idempotency (e.g. gap delete must stay inside the same txn); otherwise this task just locks the guarantee with a test.
  - [ ] Verify it passes (`pytest tests/ -k idempotent -q`)
  - [ ] Commit: `test(pipeline): lock same-date re-run idempotency`

---

## Verification

- [ ] All phase tests pass: `pytest tests/ -k "partial_persistence or idempotent or drop" -q`
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
