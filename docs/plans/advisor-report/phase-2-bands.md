# Phase 2: Success-band classification

> **Parent plan:** [plan.md](plan.md)
> **Status:** Not started
> **Depends on:** Phase 1 complete (needs `run_listings` to persist the band into)

---

## Goal

Every scored listing gets a deterministic `strong_match` /
`competitive` / `reach` band, stored in `run_listings.band`, matching
the `min_match_score`/`strong_match_score` thresholds in `Settings`.

## Safety Checklist

- **Touches user input, auth, secrets, or external calls?** No — pure
  function over an existing integer score.
- **Contains a one-way door (schema, public API shape, new dependency)?**
  Yes — `ALTER TABLE run_listings ADD COLUMN band`. ⚠️ Task 2 (migration)
  is gated on human sign-off before applying against a real database.

---

## Tasks

### Task 1: `classify_band`

- **Files:** `scout/sub_agents/advisor/bands.py`, `scout/config.py`, `tests/test_advisor_bands.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing tests: scores at/above `strong_match_score` →
        `strong_match`; at/above `min_match_score` but below
        `strong_match_score` → `competitive`; below `min_match_score` →
        `reach`; boundary values on both thresholds
  - [ ] Verify it fails (`./.venv/Scripts/python.exe -m pytest tests/test_advisor_bands.py -q`)
  - [ ] Add `strong_match_score: int` field to `Settings` (default 85);
        implement `classify_band(score, settings)` in
        `scout/sub_agents/advisor/bands.py`
  - [ ] Verify it passes (`./.venv/Scripts/python.exe -m pytest tests/test_advisor_bands.py -q`)
  - [ ] Commit: `feat(advisor): add success-band classification`

### Task 2: Persist band on `run_listings`

- **Files:** `scout/shared/schema.sql`, `scout/shared/db.py`, `tests/test_db.py`
- **Gate:** ⚠️ human sign-off required before applying against a real
  (non-test) database.
- **Steps:**
  - [ ] Write failing test: `record_run_listings` accepts and persists
        a band per listing; `get_run_listings` returns it
  - [ ] Verify it fails (`./.venv/Scripts/python.exe -m pytest tests/test_db.py -q`)
  - [ ] Add `ALTER TABLE run_listings ADD COLUMN IF NOT EXISTS band
        TEXT;` to `scout/shared/schema.sql`; extend
        `record_run_listings`/`get_run_listings` and the `RunListing`
        model to carry `band`
  - [ ] Verify it passes (`./.venv/Scripts/python.exe -m pytest tests/test_db.py -q`)
  - [ ] Commit: `feat(db): persist success band on run_listings`

---

## Verification

- [ ] All phase tests pass: `./.venv/Scripts/python.exe -m pytest tests/test_advisor_bands.py tests/test_db.py -q`
- [ ] Full suite unaffected: `./.venv/Scripts/python.exe -m pytest -q`

## Rollback

Revert Task 2's migration usage (stop passing `band` into
`record_run_listings`); the nullable `band` column can stay unused
harmlessly. Task 1's `classify_band` has no external effect if unused.

---

## Notes / Learnings

<Filled in during execution.>
