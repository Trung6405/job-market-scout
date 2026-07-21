# Phase 1: Profile schema, loader, and example file

> **Parent plan:** [plan.md](plan.md)
> **Status:** Complete
> **Depends on:** nothing

---

## Goal

Deliver a validated `Profile` data model, a `load_profile` loader, and a
checked-in example file — provably isolated from the rest of the
pipeline (existing test suite green, no changes to `Settings`, scorer,
or briefing).

## Safety Checklist

- **Touches user input, auth, secrets, or external calls?** No — pure
  in-process JSON parsing and validation, no network/filesystem writes.
- **Contains a one-way door (schema, public API shape, new dependency)?**
  No new dependency (pydantic already used); the model shape is new but
  has no consumers yet, so it can be freely changed later.

---

## Tasks

### Task 1: Profile data model

- **Files:** `scout/shared/schemas.py`, `tests/test_profile_schema.py`
- **Gate:** none
- **Steps:**
  - [x] Write failing tests: valid/invalid data for `TechSkill`,
        `TechCategory`, `DomainKnowledge` (incl. level-threshold
        boundaries), `Background`, `Project`, `Profile`
  - [x] Verify it fails (`./.venv/Scripts/python.exe -m pytest tests/test_profile_schema.py -q`) — `ImportError: cannot import name 'Background'`
  - [x] Implement `TechSkill`, `TechCategory`, `DomainKnowledge` (with
        `.level` computed property), `Background`, `Project`, `Profile`
        in `scout/shared/schemas.py`
  - [x] Verify it passes (`./.venv/Scripts/python.exe -m pytest tests/test_profile_schema.py -q`) — 23 passed
  - [x] Commit: `feat(schemas): add student profile data model`

### Task 2: Profile loader and example file

- **Files:** `scout/shared/profile.py`, `scout/profile.json.example`, `tests/test_profile_loader.py`
- **Gate:** none
- **Steps:**
  - [x] Write failing tests: loads `scout/profile.json.example`
        end-to-end, raises `FileNotFoundError` for a missing path,
        raises `ValidationError` for malformed JSON
  - [x] Verify it fails (`./.venv/Scripts/python.exe -m pytest tests/test_profile_loader.py -q`) — `ModuleNotFoundError: No module named 'scout.shared.profile'`
  - [x] Implement `load_profile(path)` in `scout/shared/profile.py`;
        author `scout/profile.json.example` from the `profile.html`
        mockup's sample data
  - [x] Verify it passes (`./.venv/Scripts/python.exe -m pytest tests/test_profile_loader.py -q`) — 3 passed
  - [x] Commit: `feat(profile): add profile.json loader and example file`

---

## Verification

- [x] All phase tests pass: `./.venv/Scripts/python.exe -m pytest tests/test_profile_schema.py tests/test_profile_loader.py -q` — 26 passed
- [x] Full existing suite unaffected: `./.venv/Scripts/python.exe -m pytest -q` — 138 passed, 5 pre-existing warnings (unrelated third-party deprecations)

## Rollback

Delete `scout/shared/profile.py`, `scout/profile.json.example`,
`tests/test_profile_schema.py`, `tests/test_profile_loader.py`, and
revert the additive changes to `scout/shared/schemas.py`. No stored
state or migrations to unwind — nothing outside these files references
the new models yet.

---

## Notes / Learnings

- Domain-knowledge level thresholds (Solid ≥70, Good ≥50, Developing
  ≥30, else Emerging) were reverse-engineered from the five worked
  examples in `docs/project/prototypes/profile.html` (75/70→Solid, 65→Good,
  35→Developing, 20→Emerging) rather than an explicit spec — flagged as
  an accepted risk in `plan.md`.
- Test commands in this doc use the project's `.venv`
  (`./.venv/Scripts/python.exe -m pytest`) since `pytest` isn't on the
  system `PATH` in this environment.
