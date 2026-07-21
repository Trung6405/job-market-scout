# Plan: Student Profile Schema

> **Status:** Complete
> **Created:** 2026-07-21 · **Last updated:** 2026-07-21
> **Spec:** [spec.md](../../specs/profile-schema/spec.md)

---

## Overview

Add a validated, typed data model for a student profile (tech-stack
proficiency by category, domain knowledge, background, projects) plus a
JSON loader for it, so the Advisor report mockups in `docs/project/prototypes/`
have a real data source to eventually render from. Done when the schema,
loader, and example file exist, are fully tested, and the existing
pipeline is untouched.

## Acceptance Criteria

- [x] `Profile` and its nested models (`TechSkill`, `TechCategory`,
      `DomainKnowledge`, `Background`, `Project`) exist in
      `scout/shared/schemas.py` and validate the fields shown in
      `profile.html`.
- [x] `load_profile(path)` in `scout/shared/profile.py` loads and
      validates a profile JSON file, raising `FileNotFoundError` for a
      missing file and `pydantic.ValidationError` for malformed data.
- [x] `scout/profile.json.example` parses successfully via
      `load_profile` and matches the mockup's sample data.
- [x] Full existing test suite still passes unmodified.

---

## Risks & Unknowns

| Risk / unknown | Impact if wrong | Resolution |
|----------------|-----------------|------------|
| Domain-knowledge level thresholds (70/50/30) are inferred from the mockup's five worked examples, not an explicit spec from the mockup author | A later profile with an edge-case percentage could get a label that reads oddly | Accepted risk — thresholds were chosen so all five mockup examples map correctly; revisit if the label ever looks wrong against a real profile |

## Blast Radius

- **Code that will change:** `scout/shared/schemas.py` (additive only),
  `scout/shared/profile.py` (new file), `scout/profile.json.example`
  (new file), `tests/test_profile_schema.py` (new),
  `tests/test_profile_loader.py` (new).
- **Existing behaviour that could break:** none — `Settings`, the
  scorer, the briefing pipeline, and `.env`/`.env.example` are not
  touched.
- **Off-limits:** no changes outside the files above.

---

## Phases

| # | Phase | Document | Status |
|---|-------|----------|--------|
| 1 | Profile schema, loader, and example file | [phase-1-schema-and-loader.md](phase-1-schema-and-loader.md) | Complete |

---

## Testing Strategy

- **Unit:** `tests/test_profile_schema.py` covers every model's valid
  data, field-level validation bounds (proficiency 1-5 / 0-100), and the
  domain-knowledge level-threshold boundaries. `tests/test_profile_loader.py`
  covers the missing-file, malformed-data, and real-example-file paths.
- **Integration:** none needed — this sub-project has no wiring into
  other stages yet.
- **Manual:** none — nothing user-facing changed.

---

## Key Decisions & Constraints

- `profile.json` is additive alongside `resume.txt`, not a replacement —
  the scorer's prompt is unchanged.
- Tech-stack categories are freeform strings, not an enum.
- Domain-knowledge level label is derived from the proficiency number,
  never stored separately.
- No wiring into `Settings` or any pipeline stage in this pass.
- ⚠️ **One-way doors:** none — this is a pure additive schema with no
  external consumers yet, fully reversible by deleting the new files.

## Out of Scope

- Rendering `profile.json` into `profile.html` (deferred to the report
  rendering sub-project).
- Report persistence, success-band classification, and gap detection
  (separate sub-projects in the broader Advisor feature).
- GitHub resource verification for skill gaps (descoped from the
  Advisor feature for now).

---

## Definition of Done

- [x] All acceptance criteria met
- [x] All phase verification steps pass
- [x] Feature verified manually in a running environment — N/A, no
      user-facing surface in this sub-project
- [x] Docs / README updated where behaviour changed — N/A, no
      user-facing behaviour changed
- [x] No new lint or type-check warnings

## Update Rules

- Phase docs hold task-level detail; this file holds phase-level status only.
- When a phase's scope changes, update its row here **in the same commit**.
- On conflict, this file wins for *what* the phases are; the phase doc
  wins for *how* its tasks are done.
