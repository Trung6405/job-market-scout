# Phase 2: Wire prompts + pipeline to the profile

> **Parent plan:** [plan.md](plan.md)
> **Status:** Complete
> **Depends on:** Phase 1 complete (`render_profile_text` and `settings.profile` exist)

---

## Goal

Switch the scorer prompt, the briefing prompt, and the pipeline's gap path
to read `settings.profile` via `render_profile_text`. Gap detection becomes
unconditional. `resume_text` still exists (removed in Phase 3) but nothing
reads it after this phase.

## Safety Checklist

- **Touches user input, auth, secrets, or external calls?**
  Yes — the scorer/briefing prompts feed the LLM; content change only, no
  new external call. The persist path now always calls the advisor LLM
  (`run_requirements_extraction`); tests mock it.
- **Contains a one-way door (schema, public API shape, new dependency)?**
  No.

---

## Tasks

### Task 2.1: Scorer prompt uses the profile

- **Files:** `scout/prompts.py`, `tests/test_prompts.py` (and
  `tests/test_scorer_agent.py` if it asserts on `resume_text`)
- **Gate:** none
- **Steps:**
  - [ ] Update the failing test in `tests/test_prompts.py`: find the test that
        builds the scorer instruction and asserts `settings.resume_text` appears
        in it. Replace that assertion with:

    ```python
    from scout.shared.profile import render_profile_text
    # ... within the scorer-instruction test:
    instruction = build_scorer_instruction(settings, listings)
    assert render_profile_text(settings.profile) in instruction
    assert "Candidate profile:" in instruction
    ```

  - [ ] Verify it fails: `pytest tests/test_prompts.py -k scorer -v`
        Expected: FAIL (the rendered profile text is not yet in the instruction).
  - [ ] Implement in `scout/prompts.py`:
    - Add import: `from scout.shared.profile import render_profile_text`
    - In `build_scorer_instruction`, replace the block

      ```
      Resume:
      {settings.resume_text}
      ```

      with

      ```
      Candidate profile:
      {render_profile_text(settings.profile)}
      ```
  - [ ] Verify it passes: `pytest tests/test_prompts.py tests/test_scorer_agent.py -v` → PASS
        (update any `resume_text` assertion in `test_scorer_agent.py` the same way).
  - [ ] Commit: `git add scout/prompts.py tests/test_prompts.py tests/test_scorer_agent.py && git commit -m "feat(scorer): score against the rendered profile"`

### Task 2.2: Briefing prompt uses the profile

- **Files:** `scout/prompts.py`, `tests/test_briefing_agent.py` (whichever test
  asserts the briefing instruction content)
- **Gate:** none
- **Steps:**
  - [ ] Update/add a failing test asserting the briefing instruction contains
        the rendered profile:

    ```python
    from scout.shared.profile import render_profile_text
    instruction = build_briefing_instruction(settings, matches)  # match existing call shape
    assert render_profile_text(settings.profile) in instruction
    ```

  - [ ] Verify it fails: `pytest tests/test_briefing_agent.py -v`
        Expected: FAIL (rendered profile not yet in the instruction).
  - [ ] Implement in `scout/prompts.py`: in `build_briefing_instruction`, replace
        the `Resume:\n{settings.resume_text}` block with
        `Candidate profile:\n{render_profile_text(settings.profile)}` (same edit as 2.1).
  - [ ] Verify it passes: `pytest tests/test_briefing_agent.py -v` → PASS
  - [ ] Commit: `git add scout/prompts.py tests/test_briefing_agent.py && git commit -m "feat(briefing): use the rendered profile"`

### Task 2.3: Pipeline reads `settings.profile`; gaps always run

- **Files:** `scout/agent.py`, `tests/test_agent.py`, `tests/test_main_entrypoint.py`
- **Gate:** none
- **Steps:**
  - [ ] Update the three affected tests to the profile-always-present world.
        `test_scout_pipeline_agent_records_gaps_when_profile_exists`
        (tests/test_agent.py:432) is the reference pattern — it mocks
        `run_requirements_extraction`. Apply the same mock to the tests that
        currently stub `load_profile`:
    - In `tests/test_agent.py::test_scout_pipeline_agent_persists_run` and
      `::test_scout_pipeline_agent_reports_progress_for_full_run`: remove
      `monkeypatch.setattr("scout.agent.load_profile", lambda path: None)` and
      add a requirements mock:

      ```python
      from scout.shared.schemas import ListingRequirements

      async def _fake_requirements(listings, settings=None):
          return [
              ListingRequirements(
                  source=l.source, external_id=l.external_id,
                  must_have=[], nice_to_have=[],
              )
              for l in listings
          ]
      monkeypatch.setattr("scout.agent.run_requirements_extraction", _fake_requirements)
      ```

      Then update the `reports_progress` call-order assertions: gap detection now
      runs, so `render_profile` **is** called and a `"Gaps detected: ..."` status
      is emitted — assert those are present instead of absent.
    - In `tests/test_main_entrypoint.py::test_run_once_completes_without_raising`:
      remove the `load_profile` stub and add the same
      `run_requirements_extraction` mock.
  - [ ] Verify they fail: `pytest tests/test_agent.py tests/test_main_entrypoint.py -v`
        Expected: FAIL (agent still calls `load_profile`; `scout.agent.load_profile`
        stub removed, gap path assertions not yet matching).
  - [ ] Implement in `scout/agent.py`:
    - Remove the `from scout.shared.profile import load_profile` import.
    - Replace the profile-load + branch (the `try/except FileNotFoundError`,
      `profile = None`, and `if profile is None: … else:`) with a direct read
      and an unconditional gap block:

      ```python
                      profile = settings.profile

                      requirements = await run_requirements_extraction(
                          relevant, settings
                      )
                      requirements_by_key = {
                          (r.source, r.external_id): r for r in requirements
                      }
                      matches_with_requirements = [
                          (
                              match,
                              requirements_by_key[
                                  (match.listing.source, match.listing.external_id)
                              ],
                          )
                          for match in matches
                          if (match.listing.source, match.listing.external_id)
                          in requirements_by_key
                      ]
                      checks_by_match = [
                          (match, evaluate_requirements(req, profile))
                          for match, req in matches_with_requirements
                      ]
                      await record_listing_gaps(conn, run_id, checks_by_match)
                      await record_listing_meta(conn, run_id, matches_with_requirements)
                      gap_count = sum(
                          1 for _, checks in checks_by_match for c in checks if not c.met
                      )
                      yield _status_event(
                          ctx,
                          self.name,
                          f"Gaps detected: {gap_count} "
                          f"across {len(checks_by_match)} listing(s)",
                      )
      ```

    - Set `has_profile = True` (replacing `has_profile = profile is not None`),
      and make the profile render unconditional (replace `if profile is not None:
      render_profile(profile, settings)` with a plain `render_profile(profile, settings)`).
  - [ ] Verify they pass: `pytest tests/test_agent.py tests/test_main_entrypoint.py -v` → PASS
  - [ ] Commit: `git add scout/agent.py tests/test_agent.py tests/test_main_entrypoint.py && git commit -m "feat(pipeline): read settings.profile; gap detection always runs"`

---

## Verification

- [ ] Phase tests pass: `pytest tests/test_prompts.py tests/test_scorer_agent.py tests/test_briefing_agent.py tests/test_agent.py tests/test_main_entrypoint.py -v`
- [ ] Full suite green: `pytest`
- [ ] Grep shows no production reader of `resume_text` remains:
      `grep -rn "resume_text" scout/` returns only the (now-unused) config
      definition, to be removed in Phase 3.

## Observability

Pipeline logs should now always show a `Gaps detected: N across M listing(s)`
status (never `Gap detection: skipped`), confirming the profile is present
and the gap path runs every time.

## Rollback

Revert this phase's three commits; Phase 1's additions remain and the
pipeline returns to reading `resume_text`.

---

## Notes / Learnings

- **Deviation from Task 2.3 as written:** the pipeline keeps a *required*
  `load_profile(settings.profile_path)` call instead of reading `settings.profile`.
  `Settings` is a `frozen=True` import-time singleton, so tests can't inject a
  profile by patching it; several agent tests (esp. `records_gaps`) inject via the
  `scout.agent.load_profile` seam. Keeping the required call preserves that seam
  and meets all observable requirements. Recorded as a spec amendment (2026-07-22).
- The scorer prompt test lives in `tests/test_scorer_agent.py` (not `test_prompts.py`);
  the briefing prompt test lives in `tests/test_prompts.py`.
- Deleted `test_scout_pipeline_agent_skips_gap_detection_when_no_profile` — the
  no-profile skip path no longer exists.
