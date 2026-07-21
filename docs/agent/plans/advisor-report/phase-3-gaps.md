# Phase 3: Requirements extraction & gap detection

> **Parent plan:** [plan.md](plan.md)
> **Status:** Complete
> **Depends on:** Phase 2 complete; `profile-schema` sub-project complete (needs `Profile`/`load_profile`)

---

## Goal

Every relevant listing gets a structured must-have/nice-to-have
requirements list (via LLM extraction) and a diffed list of skill gaps
against the student's profile, persisted in `listing_gaps`.

## Safety Checklist

- **Touches user input, auth, secrets, or external calls?** Yes — new
  LLM call (DeepSeek via the existing `LiteLlm`/ADK setup) per batch of
  listings; failure handling matches the scorer's existing pattern
  (`run_single_turn` raising if no final response).
- **Contains a one-way door (schema, public API shape, new dependency)?**
  Yes — new `listing_gaps` table. ⚠️ Task 2 (migration) is gated on
  human sign-off before applying against a real database.

---

## Tasks

### Task 1: Requirements extraction agent

- **Files:** `scout/sub_agents/advisor/agent.py`, `scout/sub_agents/advisor/runner.py`, `scout/shared/schemas.py`, `scout/prompts.py`, `tests/test_advisor_requirements.py`
- **Gate:** none
- **Steps:**
  - [x] Write failing tests: `parse_requirements` parses a fake
        structured LLM response into `list[ListingRequirements]`
        (mirroring `test_scorer_runner.py`'s pattern for `parse_scores`)
  - [x] Verify it fails (`./.venv/Scripts/python.exe -m pytest tests/test_advisor_requirements.py -q`)
  - [x] Add `ListingRequirements` to `scout/shared/schemas.py`; add a
        requirements-extraction prompt builder to `scout/prompts.py`;
        implement `build_requirements_agent` (`scout/sub_agents/advisor/agent.py`,
        mirroring `build_scorer_agent`) and `run_requirements_extraction`
        (`scout/sub_agents/advisor/runner.py`, mirroring `run_scorer`)
  - [x] Verify it passes (`./.venv/Scripts/python.exe -m pytest tests/test_advisor_requirements.py -q`)
  - [x] Commit: `feat(advisor): add requirements extraction agent` (2d5756f)

### Task 2: Gap detection and persistence

- **Files:** `scout/sub_agents/advisor/gaps.py`, `scout/shared/schema.sql`, `scout/shared/db.py`, `tests/test_advisor_gaps.py`, `tests/test_db.py`
- **Gate:** ⚠️ human sign-off required before applying the
  `listing_gaps` migration against a real database.
- **Steps:**
  - [x] Write failing tests: `detect_gaps` flags must-have and
        nice-to-have skills missing from a profile's `tech_stack`,
        correctly ignores skills the profile does cover (case-
        insensitive), and returns an empty list when fully covered
  - [x] Verify it fails (`./.venv/Scripts/python.exe -m pytest tests/test_advisor_gaps.py -q`)
  - [x] Implement `detect_gaps` in `scout/sub_agents/advisor/gaps.py`;
        add `CREATE TABLE IF NOT EXISTS listing_gaps (...)` to
        `scout/shared/schema.sql`; add `record_listing_gaps`/
        `get_listing_gaps` to `scout/shared/db.py`
  - [x] Verify it passes (`./.venv/Scripts/python.exe -m pytest tests/test_advisor_gaps.py tests/test_db.py -q`)
  - [x] Commit: `feat(advisor): add gap detection and persistence` (2f1761a, fix 9cd9f3a)

### Task 3: Pipeline wiring

- **Files:** `scout/agent.py`, `tests/test_agent.py`
- **Gate:** none
- **Steps:**
  - [x] Write failing test: a full pipeline run persists a band and any
        expected gaps for a listing with a known missing skill
  - [x] Verify it fails (`./.venv/Scripts/python.exe -m pytest tests/test_agent.py -q`)
  - [x] Add requirements extraction + `detect_gaps` + persistence calls
        into `ScoutPipelineAgent._run_async_impl`, after scoring and
        alongside the Phase 1 persistence step
  - [x] Verify it passes (`./.venv/Scripts/python.exe -m pytest tests/test_agent.py -q`)
  - [x] Commit: `feat(agent): wire requirements extraction and gap detection into pipeline` (8f9230d)

---

## Verification

- [x] All phase tests pass: `./.venv/Scripts/python.exe -m pytest tests/test_advisor_requirements.py tests/test_advisor_gaps.py tests/test_db.py tests/test_agent.py -q`
- [x] Full suite unaffected: `./.venv/Scripts/python.exe -m pytest -q` — 188/188 passing
- [ ] Manual: run against a real listing + `profile.json.example`,
      confirm the flagged gaps are actually absent from the profile
      (no fabricated skills). **Not yet done** — deferred to the
      full end-to-end manual pass once all 5 phases are wired.

## Observability

Pipeline status events (`scout/main.py`'s `logger.info` output) report
counts of listings with extracted requirements and total gaps flagged
per run — enough to sanity-check behavior without a DB query.

## Rollback

Revert Task 3's wiring to stop calling requirements extraction/gap
detection. Task 1/2's code and the `listing_gaps` table can stay in
place unused.

---

## Notes / Learnings

- Batched extraction (mirroring the scorer's one-call-per-batch pattern)
  worked without needing a per-listing fallback — no token-limit issue
  surfaced during implementation. Revisit only if real usage with large
  listing batches hits DeepSeek's context limits.
- `scout/config.py`'s new `profile_path` setting is deliberately NOT
  eagerly loaded (unlike `resume_path`/`resume_text`) since
  `scout/profile.json` doesn't ship by default — only
  `profile.json.example` does. `scout/agent.py`'s pipeline wiring
  catches `FileNotFoundError` from `load_profile` and skips gap
  detection gracefully rather than crashing the whole run. This means
  gap detection is currently a no-op for every deployment until a
  student creates a real `scout/profile.json` — expected and by design,
  not a bug.
- Task 2's `record_listing_gaps` needed a scope extension beyond its
  brief's file list (adding `SkillGap` to `scout/shared/schemas.py`)
  and a DELETE-then-INSERT idempotency design (not specified in the
  original brief) to correctly support same-day pipeline re-runs
  without duplicating gap rows — both resolved by the controller before
  dispatch rather than left for the implementer to invent.
