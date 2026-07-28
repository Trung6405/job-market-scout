# Phase 1: Health-State Schema & Settings

> **Parent plan:** [plan.md](plan.md)
> **Status:** Complete
> **Depends on:** nothing (P0's `resources` table is on `main`)

---

## Goal

Give `resources` somewhere to record link health — a consecutive-failure count,
a dead-since marker, and the last failure reason — and add the environment
settings that bound a check run. Done when the columns exist on a freshly
applied schema with every existing row healthy-and-unchecked, and the new
settings read from the environment with defaults.

## Safety Checklist

- **Touches user input, auth, secrets, or external calls?**
  No. Schema and configuration only; the network code arrives in Phase 2.
- **Contains a one-way door (schema, public API shape, new dependency)?**
  No. The change is three additive `ADD COLUMN IF NOT EXISTS` statements on a
  table only the Career Coach reads; no column is dropped and no data is
  rewritten. No new dependency.

---

## Tasks

### Task 1: Health columns on `resources`

- **Files:** `scout/shared/schema.sql`, `tests/test_resources_schema.py`
- **Gate:** none
- **Steps:**
  - [x] Write failing test: after `apply_schema`, `resources` has
        `consecutive_failures` (`integer`, `NOT NULL`, default `0`),
        `dead_since` (`timestamptz`, nullable) and `last_check_error` (`text`,
        nullable); and a row inserted with none of them set reads back
        `consecutive_failures == 0` and `dead_since is None`
  - [x] Verify it fails (`pytest tests/test_resources_schema.py -q`)
  - [x] Implement: append three
        `ALTER TABLE resources ADD COLUMN IF NOT EXISTS …` statements after the
        `CREATE TABLE resources` block, matching how `listing_gaps` adds its
        `met` / `kind` columns
  - [x] Verify it passes (`pytest tests/test_resources_schema.py -q`)
  - [x] Commit: `feat(coach): add link-health columns to resources`

### Task 2: Link-health settings

- **Files:** `scout/config.py`, `tests/test_coach_config.py`
- **Gate:** none
- **Steps:**
  - [x] Write failing test: `Settings()` exposes
        `coach_link_health_batch` (default 50),
        `coach_link_health_max_failures` (default 3) and
        `coach_link_health_timeout_seconds` (default 10), each overridable via
        its `COACH_LINK_HEALTH_*` environment variable
  - [x] Verify it fails (`pytest tests/test_coach_config.py -q`)
  - [x] Implement: three `_env_int`-backed fields beside the existing `coach_*`
        settings, each with a comment saying what it bounds — batch size caps
        one run's work, max-failures is the transient-failure tolerance,
        timeout bounds a single request
  - [x] Verify it passes (`pytest tests/test_coach_config.py -q`)
  - [x] Commit: `feat(coach): add link-health run settings`

---

## Verification

- [x] All phase tests pass:
      `pytest tests/test_resources_schema.py tests/test_coach_config.py -q`
- [x] The full suite still passes against the updated schema — every
      database-backed test runs `apply_schema`: `pytest -q`
- [x] Applying the schema twice in a row is still a no-op (covered by the
      existing idempotency test)

## Rollback

Revert the two commits. The columns can be left on an already-migrated database
without effect — nothing reads them until Phase 3.

---

## Notes / Learnings

Straightforward as planned: three additive columns, three settings. No
deviations.
