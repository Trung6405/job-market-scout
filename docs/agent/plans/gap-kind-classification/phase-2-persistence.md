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
  - [ ] Add `ALTER TABLE listing_gaps ADD COLUMN IF NOT EXISTS kind TEXT NOT
        NULL DEFAULT 'skill'` following the existing idempotent-ALTER pattern
        in the file (mirrors the `met` column addition).
  - [ ] Commit: `feat(db): add kind column to listing_gaps`

### Task 2: Persist and read back `kind`

- **Files:** `scout/shared/db.py`, `tests/test_db.py`
- **Gate:** none (DB-backed test requires Postgres — CI or local
  `docker compose up -d postgres`)
- **Steps:**
  - [ ] Write failing test: `record_listing_gaps` then `get_listing_gaps`
        round-trips a mix of skill and non-skill checks, preserving each
        `kind`.
  - [ ] Verify it fails (`python -m pytest tests/test_db.py -q -k kind`)
  - [ ] Thread `kind` through `record_listing_gaps` (add to the unnested
        arrays and the INSERT column list) and `get_listing_gaps` /
        `get_run_details`'s gap query (SELECT `kind`, build `SkillGap` with
        it).
  - [ ] Verify it passes (`python -m pytest tests/test_db.py -q -k kind`)
  - [ ] Commit: `feat(db): persist requirement kind in listing_gaps`

### Task 3: Gap computation excludes non-skill kinds

- **Files:** `scout/shared/db.py`, `tests/test_db.py`
- **Gate:** none (DB-backed)
- **Steps:**
  - [ ] Write failing test: a persisted `qualification` check with `met=False`
        is NOT present in `get_run_details(...).gaps`, while a `skill` check
        with `met=False` is.
  - [ ] Verify it fails (`python -m pytest tests/test_db.py -q -k gaps`)
  - [ ] Change the gap comprehension in `get_run_details` from
        `[c for c in requirements if not c.met]` to
        `[c for c in requirements if c.kind == "skill" and not c.met]`.
  - [ ] Verify it passes (`python -m pytest tests/test_db.py -q -k gaps`)
  - [ ] Commit: `fix(db): keep non-skill requirements out of the gap list`

---

## Verification

- [ ] Phase tests pass against Postgres: `python -m pytest tests/test_db.py -q`
      (start Postgres first: `docker compose up -d postgres`). If Postgres is
      unavailable locally, the DB-guarded tests skip — confirm they run green
      in CI.
- [ ] `RunListingDetail.requirements` still carries every check (skill and
      non-skill) so Phase 3 can render the context section, while `.gaps`
      carries only unmet skill checks.

## Rollback

Revert the Task 2–3 code commits. The `kind` column (Task 1) is harmless to
leave — defaulted and ignored by reverted code; drop it manually only if a
clean schema is required (plan.md → Rollout & Reversibility).

---

## Notes / Learnings

<Filled in during execution.>
