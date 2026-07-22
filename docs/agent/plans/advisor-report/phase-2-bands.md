# Phase 2: Success-band classification

> **Parent plan:** [plan.md](plan.md)
> **Status:** Complete
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
  - [x] Write failing tests: scores at/above `strong_match_score` →
        `strong_match`; at/above `min_match_score` but below
        `strong_match_score` → `competitive`; below `min_match_score` →
        `reach`; boundary values on both thresholds
  - [x] Verify it fails (`./.venv/Scripts/python.exe -m pytest tests/test_advisor_bands.py -q`)
  - [x] Add `strong_match_score: int` field to `Settings` (default 85);
        implement `classify_band(score, settings)` in
        `scout/sub_agents/advisor/bands.py`
  - [x] Verify it passes (`./.venv/Scripts/python.exe -m pytest tests/test_advisor_bands.py -q`)
  - [x] Commit: `feat(advisor): add success-band classification` (b0a4457)

### Task 2: Persist band on `run_listings`

- **Files:** `scout/shared/schema.sql`, `scout/shared/db.py`, `tests/test_db.py`
- **Gate:** ⚠️ human sign-off required before applying against a real
  (non-test) database.
- **Steps:**
  - [x] Write failing test: `record_run_listings` accepts and persists
        a band per listing; `get_run_listings` returns it
  - [x] Verify it fails (`./.venv/Scripts/python.exe -m pytest tests/test_db.py -q`)
  - [x] Add `ALTER TABLE run_listings ADD COLUMN IF NOT EXISTS band
        TEXT;` to `scout/shared/schema.sql`. Change
        `record_run_listings`'s signature from `matches: list[MatchResult]`
        to `matches: list[tuple[MatchResult, str]]` (each pair is a
        match and its already-classified band string) and persist the
        band alongside score/reasoning. Add `band: str` to the
        `RunListing` model and have `get_run_listings` return it.
  - [x] Verify it passes (`./.venv/Scripts/python.exe -m pytest tests/test_db.py -q`)
  - [x] Commit: `feat(db): persist success band on run_listings` (7cd39c8)

### Task 3: Wire `classify_band` into the pipeline

*(Added after Task 1/2 were scoped — the original two tasks added band
storage but never actually computed a real band value at the one call
site that persists listings. Without this task `run_listings.band`
would stay unused/always-null in practice, contradicting this phase's
own Goal. See Notes / Learnings.)*

- **Files:** `scout/agent.py`, `tests/test_agent.py`
- **Gate:** none
- **Steps:**
  - [x] Write failing test: the persistence step in `ScoutPipelineAgent`
        now passes each match's real classified band (not a hardcoded
        placeholder) into `record_run_listings`
  - [x] Verify it fails (`./.venv/Scripts/python.exe -m pytest tests/test_agent.py -q`)
  - [x] In `ScoutPipelineAgent._run_async_impl`, after building `matches`
        via `join_match_results` and before calling `record_run_listings`,
        build `[(match, classify_band(match.score, settings)) for match in matches]`
        and pass that list instead of the bare `matches` list (matching
        Task 2's new `record_run_listings` signature)
  - [x] Verify it passes (`./.venv/Scripts/python.exe -m pytest tests/test_agent.py -q`)
  - [x] Commit: `feat(agent): classify and persist success band per listing` (bd53c5d)

---

## Verification

- [x] All phase tests pass: `./.venv/Scripts/python.exe -m pytest tests/test_advisor_bands.py tests/test_db.py tests/test_agent.py -q`
- [x] Full suite unaffected: `./.venv/Scripts/python.exe -m pytest -q` — 158/158 passing

## Rollback

Revert Task 3's wiring (stop calling `classify_band` / pass an empty
band or skip persistence entirely) to fall back to Phase 1's
band-less persistence; revert Task 2's migration usage similarly. The
nullable `band` column can stay unused harmlessly. Task 1's
`classify_band` has no external effect if unused.

---

## Notes / Learnings

- 2026-07-21: Pre-flight review of Task 2 (before dispatch) found the
  original two-task phase never wired `classify_band` into
  `scout/agent.py` — `record_run_listings` would gain a `band` column
  but nothing would ever compute a real value for it at the pipeline's
  one call site. Added Task 3 to close that gap before executing Task 2,
  and changed Task 2's `record_run_listings` signature to
  `list[tuple[MatchResult, str]]` so the band travels with each match
  rather than needing a separate parallel list or lookup.
- 2026-07-21: Task 2's review flagged (Important, non-blocking) that
  `run_listings.band` is nullable with no default while `RunListing.band`
  is a non-Optional `str` — a `run_listings` row written before this
  migration (or by any future caller that skips banding) would crash
  `get_run_listings`'s Pydantic validation on read. No pre-existing data
  currently exists in this project's database, and Task 3 ensures every
  pipeline write now always supplies a real band, so this is a latent
  risk rather than an active bug. Revisit if this schema ever needs to
  run against a database with rows written before this migration.
