# Phase 3: Requirements extraction & gap detection

> **Parent plan:** [plan.md](plan.md)
> **Status:** Not started
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
  - [ ] Write failing tests: `parse_requirements` parses a fake
        structured LLM response into `list[ListingRequirements]`
        (mirroring `test_scorer_runner.py`'s pattern for `parse_scores`)
  - [ ] Verify it fails (`./.venv/Scripts/python.exe -m pytest tests/test_advisor_requirements.py -q`)
  - [ ] Add `ListingRequirements` to `scout/shared/schemas.py`; add a
        requirements-extraction prompt builder to `scout/prompts.py`;
        implement `build_requirements_agent` (`scout/sub_agents/advisor/agent.py`,
        mirroring `build_scorer_agent`) and `run_requirements_extraction`
        (`scout/sub_agents/advisor/runner.py`, mirroring `run_scorer`)
  - [ ] Verify it passes (`./.venv/Scripts/python.exe -m pytest tests/test_advisor_requirements.py -q`)
  - [ ] Commit: `feat(advisor): add requirements extraction agent`

### Task 2: Gap detection and persistence

- **Files:** `scout/sub_agents/advisor/gaps.py`, `scout/shared/schema.sql`, `scout/shared/db.py`, `tests/test_advisor_gaps.py`, `tests/test_db.py`
- **Gate:** ⚠️ human sign-off required before applying the
  `listing_gaps` migration against a real database.
- **Steps:**
  - [ ] Write failing tests: `detect_gaps` flags must-have and
        nice-to-have skills missing from a profile's `tech_stack`,
        correctly ignores skills the profile does cover (case-
        insensitive), and returns an empty list when fully covered
  - [ ] Verify it fails (`./.venv/Scripts/python.exe -m pytest tests/test_advisor_gaps.py -q`)
  - [ ] Implement `detect_gaps` in `scout/sub_agents/advisor/gaps.py`;
        add `CREATE TABLE IF NOT EXISTS listing_gaps (...)` to
        `scout/shared/schema.sql`; add `record_listing_gaps`/
        `get_listing_gaps` to `scout/shared/db.py`
  - [ ] Verify it passes (`./.venv/Scripts/python.exe -m pytest tests/test_advisor_gaps.py tests/test_db.py -q`)
  - [ ] Commit: `feat(advisor): add gap detection and persistence`

### Task 3: Pipeline wiring

- **Files:** `scout/agent.py`, `tests/test_agent.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing test: a full pipeline run persists a band and any
        expected gaps for a listing with a known missing skill
  - [ ] Verify it fails (`./.venv/Scripts/python.exe -m pytest tests/test_agent.py -q`)
  - [ ] Add requirements extraction + `detect_gaps` + persistence calls
        into `ScoutPipelineAgent._run_async_impl`, after scoring and
        alongside the Phase 1 persistence step
  - [ ] Verify it passes (`./.venv/Scripts/python.exe -m pytest tests/test_agent.py -q`)
  - [ ] Commit: `feat(agent): wire requirements extraction and gap detection into pipeline`

---

## Verification

- [ ] All phase tests pass: `./.venv/Scripts/python.exe -m pytest tests/test_advisor_requirements.py tests/test_advisor_gaps.py tests/test_db.py tests/test_agent.py -q`
- [ ] Full suite unaffected: `./.venv/Scripts/python.exe -m pytest -q`
- [ ] Manual: run against a real listing + `profile.json.example`,
      confirm the flagged gaps are actually absent from the profile
      (no fabricated skills).

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

<Filled in during execution — record here if batched extraction hits
token limits and per-listing calls are needed instead (see plan.md
Risks & Unknowns).>
