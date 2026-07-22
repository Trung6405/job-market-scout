# Plan: Profile as the single candidate source

> **Status:** Complete
> **Created:** 2026-07-22 · **Last updated:** 2026-07-22
> **Spec:** [spec.md](../../specs/profile-candidate-source/spec.md)

---

## Overview

Retire `resume.txt` and make `profile.json` the single, required candidate
source. A pure `render_profile_text(profile)` turns the structured profile
into a resume-like block that the scorer and briefing prompts consume;
`Settings` loads and validates the profile at construction (fail-fast).
"Done" means scoring/briefing reason about the real profile, gap detection
always runs, and every trace of `resume.txt` is gone with all tests green.

## Acceptance Criteria

- [x] `Settings()` exposes `settings.profile: Profile`, loaded from
      `profile_path`, and raises a clear error when the file is missing/invalid.
- [x] The scorer and briefing prompts contain the rendered profile text and
      no longer reference `resume_text`.
- [x] The pipeline no longer branches on a missing profile; gap detection
      always runs. *(Amended: it keeps a required `load_profile` call rather than
      reading `settings.profile` — see spec Amendments.)*
- [x] `resume.txt`, `resume.txt.example`, the compose mount, `RESUME_PATH`,
      and the deploy/CI resume steps are removed.
- [x] `pytest` passes with no reference to `resume_text`/`resume_path` in code.

---

## Risks & Unknowns

| Risk / unknown | Impact if wrong | Resolution |
|----------------|-----------------|------------|
| `load_profile` importing `Settings` would create a circular import when config imports it | Phase 1 config change fails to import | Spike task 1.1 — verified statically (profile.py imports only `schemas`), confirmed at runtime |
| Making the profile always-present means the advisor LLM call always runs in tests that persist a run | Previously-hermetic tests would hit the real LLM | Phase 2 task updates those tests to mock `run_requirements_extraction` (existing pattern in test_agent.py) |
| `profile.json` holds real personal data and is committed to git | Personal data public if repo is public | Accepted risk — repo is going private (spec Open Question, non-blocking) |

## Blast Radius

- **Code that will change:** `scout/config.py`, `scout/shared/profile.py`,
  `scout/prompts.py`, `scout/agent.py`, `scout/.env.example`,
  `docker-compose.yaml`, `.github/workflows/deploy.yml`, `tests/`
- **Existing behaviour that could break:** scorer prompt content, briefing
  prompt content, pipeline persist path (gap detection now unconditional),
  config construction (raises without a profile), CI test job.
- **Off-limits:** Do not modify anything outside the directories above
  without flagging it to the human first.

---

## Phases

| # | Phase | Document | Status |
|---|-------|----------|--------|
| 1 | Profile rendering + Settings ownership | [phase-1-render-and-config.md](phase-1-render-and-config.md) | Complete |
| 2 | Wire prompts + pipeline to the profile | [phase-2-wire-consumers.md](phase-2-wire-consumers.md) | Complete |
| 3 | Retire resume.txt across infra | [phase-3-retire-resume.md](phase-3-retire-resume.md) | Complete |

> All phases are planned in advance — every row above has a written,
> human-approved phase doc before phase 1 execution starts.

---

## Testing Strategy

- **Unit:** per-task TDD — `render_profile_text` output, `Settings` profile
  loading + fail-fast, scorer/briefing prompt content, config no longer
  exposing `resume_text`.
- **Integration:** `test_agent.py` persist-path tests exercise scoring +
  gap detection end-to-end against the real local Postgres with the advisor
  LLM mocked; full `pytest` run after each phase.
- **Manual:** after merge + deploy, confirm the VM dashboard shows profile-
  informed scores (a spread, not all "reach") on a run with all roles.

---

## Key Decisions & Constraints

- Profile is the single required candidate source; `resume.txt` retired
  entirely (approved during brainstorming).
- Profile is rendered to natural-language text (not raw JSON) so the
  existing scorer rubric shape is preserved.
- Operational filters (`preferred_locations`, `remote_only`, `min_salary`)
  are unchanged; the profile's `target_locations`/`target_role` stay
  informational.
- `render_profile_text` lives in `scout/shared/profile.py` beside
  `load_profile`; `prompts.py` imports it.
- No one-way doors: no schema/migration change, no new dependency.

## Out of Scope

- Scraper/proxy reliability (the cloud-IP scrape shortfall) — separate issue.
- Requirements-extraction and gap-detection logic changes.
- Moving `profile.json` into a `PROFILE_JSON` secret.

---

## Definition of Done

- [x] All acceptance criteria met
- [x] All phase verification steps pass (`pytest`: 205 passed)
- [ ] Feature verified manually in a running environment *(pending post-deploy: confirm scored listings show a spread, not all "reach")*
- [x] Docs / README updated where behaviour changed (`infra/README.md` resume secret removed; `.gitignore`/`.dockerignore` resume entries dropped)
- [x] No new lint or type-check warnings

## Update Rules

- Phase docs hold task-level detail; this file holds phase-level status only.
- When a phase's scope changes, update its row here **in the same commit**.
- On conflict, this file wins for *what* the phases are; the phase doc
  wins for *how* its tasks are done.
