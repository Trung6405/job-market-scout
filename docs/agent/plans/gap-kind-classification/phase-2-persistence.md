# Phase 2: Persist kind + kind-based gap filter

> **Parent plan:** [plan.md](plan.md)
> **Status:** Not started
> **Depends on:** Phase 1 complete (`SkillGap.kind` exists; `evaluate_requirements` emits kinds)

---

## Goal

Persist each requirement's `kind` through the `listing_gaps` round-trip and
make gap computation select on kind rather than only on the match flag. We'll
know it worked when a stored non-skill requirement is read back with its kind
and is excluded from `RunListingDetail.gaps`, while legacy rows default to
`skill`.

## Safety Checklist

- **Touches user input, auth, secrets, or external calls?**
  No — internal persistence only.
- **Contains a one-way door (schema, public API shape, new dependency)?**
  Yes, mild — adds a `listing_gaps.kind` column. Additive and idempotent
  (`ADD COLUMN IF NOT EXISTS ... DEFAULT 'skill'`), so not gated, but it is
  the one schema change; see plan.md → Rollout & Reversibility.

---

## Tasks

### Task 1: Add `kind` column to `listing_gaps`

- **Files:** `scout/shared/schema.sql`
- **Gate:** none
- **Steps:**
  - [x] Add `ALTER TABLE listing_gaps ADD COLUMN IF NOT EXISTS kind TEXT NOT
        NULL DEFAULT 'skill'` following the existing idempotent-ALTER pattern
        in the file (mirrors the `met` column addition).
  - [x] Commit: `feat(db): add kind column to listing_gaps`

### Task 2: Persist and read back `kind`

- **Files:** `scout/shared/db.py`, `tests/test_db.py`
- **Gate:** none (DB-backed test requires Postgres — CI or local
  `docker compose up -d postgres`)
- **Steps:**
  - [x] Write failing test: `record_listing_gaps` then `get_listing_gaps`
        round-trips a mix of skill and non-skill checks, preserving each
        `kind`.
  - [x] Verify it fails (`python -m pytest tests/test_db.py -q -k kind`)
  - [x] Thread `kind` through `record_listing_gaps` (add to the unnested
        arrays and the INSERT column list) and `get_listing_gaps` /
        `get_run_details`'s gap query (SELECT `kind`, build `SkillGap` with
        it).
  - [x] Verify it passes (`python -m pytest tests/test_db.py -q -k kind`)
  - [x] Commit: `feat(db): persist requirement kind in listing_gaps`

### Task 3: Gap computation excludes non-skill kinds

- **Files:** `scout/shared/db.py`, `tests/test_db.py`
- **Gate:** none (DB-backed)
- **Steps:**
  - [x] Write failing test: a persisted `qualification` check with `met=False`
        is NOT present in `get_run_details(...).gaps`, while a `skill` check
        with `met=False` is.
  - [x] Verify it fails (`python -m pytest tests/test_db.py -q -k gaps`)
  - [x] Change the gap comprehension in `get_run_details` from
        `[c for c in requirements if not c.met]` to
        `[c for c in requirements if c.kind == "skill" and not c.met]`.
  - [x] Verify it passes (`python -m pytest tests/test_db.py -q -k gaps`)
  - [x] Commit: `fix(db): keep non-skill requirements out of the gap list`

---

## Verification

- [x] Phase tests pass against Postgres: `python -m pytest tests/test_db.py -q`
      (start Postgres first: `docker compose up -d postgres`). If Postgres is
      unavailable locally, the DB-guarded tests skip — confirm they run green
      in CI.
- [x] `RunListingDetail.requirements` still carries every check (skill and
      non-skill) so Phase 3 can render the context section, while `.gaps`
      carries only unmet skill checks.

## Rollback

Revert the Task 2–3 code commits. The `kind` column (Task 1) is harmless to
leave — defaulted and ignored by reverted code; drop it manually only if a
clean schema is required (plan.md → Rollout & Reversibility).

---

## Notes / Learnings

- Postgres was already running locally (`job-market-scout-postgres-1`), so the
  DB-backed tests ran green here rather than only in CI. Full `test_db.py` is
  27 passed.
- `get_run_details` had no existing test; added `get_run_details` to the
  `test_db.py` imports and a dedicated gap-exclusion test.
- The kind filter (`kind == "skill" and not met`) is belt-and-suspenders with
  the Phase 1 `met=True` sentinel: either alone keeps non-skill items out of
  gaps, but the kind check is the robust guarantee.
