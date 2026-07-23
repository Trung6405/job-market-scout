# Phase 1: Typed kind + gap matching + extractor prompt

> **Parent plan:** [plan.md](plan.md)
> **Status:** Not started
> **Depends on:** nothing

---

## Goal

Introduce the closed `RequirementKind` vocabulary and a `RequirementItem`
model, thread it through the requirements schema and `SkillGap`, teach
`evaluate_requirements` to match only `skill`-kind items, and instruct the
extractor to classify each requirement. We'll know it worked when a
non-skill requirement (e.g. a STEM degree) is no longer produced as an unmet
gap while genuine skill gaps still are.

## Safety Checklist

- **Touches user input, auth, secrets, or external calls?**
  Yes — the extractor prompt/schema shape the LLM output. The new `kind`
  field defaults to `"skill"` so a missing kind still parses; an
  out-of-vocabulary kind fails pydantic validation by design (Task 1).
- **Contains a one-way door (schema, public API shape, new dependency)?**
  No — in-process schema change only; DB migration is deferred to Phase 2.

---

## Tasks

### Task 1: Closed `RequirementKind` vocabulary and `RequirementItem`

- **Files:** `scout/shared/schemas.py`, `tests/test_schemas.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing test: a `RequirementItem` accepts each of the four
        kinds, defaults `kind` to `"skill"` when omitted, and rejects an
        unknown kind (`ValidationError`).
  - [ ] Verify it fails (`python -m pytest tests/test_schemas.py -q`)
  - [ ] Add `RequirementKind = Literal["skill", "qualification",
        "experience", "soft_skill"]` and `RequirementItem(BaseModel)` with
        `name: str` and `kind: RequirementKind = "skill"`; add
        `kind: RequirementKind = "skill"` to `SkillGap`.
  - [ ] Verify it passes (`python -m pytest tests/test_schemas.py -q`)
  - [ ] Commit: `feat(advisor): add RequirementKind vocabulary and RequirementItem`

### Task 2: Requirements carry `RequirementItem` lists

- **Files:** `scout/shared/schemas.py`, `tests/test_advisor_requirements.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing test: `ListingRequirements` parses `must_have` /
        `nice_to_have` as lists of `RequirementItem` (name + kind) from JSON,
        including an item with a non-`skill` kind.
  - [ ] Verify it fails (`python -m pytest tests/test_advisor_requirements.py -q`)
  - [ ] Change `must_have` / `nice_to_have` on `ListingRequirements` from
        `list[str]` to `list[RequirementItem]`.
  - [ ] Verify it passes (`python -m pytest tests/test_advisor_requirements.py -q`)
  - [ ] Commit: `feat(advisor): type requirements as kinded items`

### Task 3: `evaluate_requirements` matches only the skill kind

- **Files:** `scout/sub_agents/advisor/gaps.py`, `tests/test_advisor_gaps.py`
- **Gate:** none
- **Steps:**
  - [ ] Update the existing `test_advisor_gaps.py` helper/tests to build
        requirements from kinded items (the type changed in Task 2), then
        write a failing test: a `qualification` item ("A STEM degree in CS")
        is returned as a check with `kind="qualification"` and is NOT a gap,
        while a missing `skill` item still yields `met=False`; non-skill
        items carry `met=True` (sentinel) and their kind.
  - [ ] Verify it fails (`python -m pytest tests/test_advisor_gaps.py -q`)
  - [ ] In `evaluate_requirements`, normalize + match against `tech_stack`
        only for `kind == "skill"` items; for other kinds emit a `SkillGap`
        with the item's kind, `met=True`, and preserve `skill=name` /
        `requirement_level`. Read `item.name` / `item.kind` from the new
        `RequirementItem`.
  - [ ] Verify it passes (`python -m pytest tests/test_advisor_gaps.py -q`)
  - [ ] Commit: `fix(advisor): gap-match only skill-kind requirements`

### Task 4: Extractor prompt classifies each requirement

- **Files:** `scout/prompts.py`, `tests/test_prompts.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing test: `build_requirements_instruction` output names the
        four kinds and instructs the model to tag each requirement with one,
        and scopes the canonical-short-name rule to skills.
  - [ ] Verify it fails (`python -m pytest tests/test_prompts.py -q`)
  - [ ] Update the instruction: each `must_have` / `nice_to_have` entry is an
        object `{ "name": ..., "kind": ... }`; describe the four kinds; scope
        the "single canonical name" guidance to `skill` items; state that
        qualifications/experience/soft skills may stay as natural phrases.
  - [ ] Verify it passes (`python -m pytest tests/test_prompts.py -q`)
  - [ ] Commit: `feat(advisor): ask extractor to classify requirement kind`

---

## Verification

- [ ] Phase tests pass: `python -m pytest tests/test_schemas.py
      tests/test_advisor_requirements.py tests/test_advisor_gaps.py
      tests/test_prompts.py -q`
- [ ] No regression in the wider non-DB suite touched by the schema change:
      `python -m pytest tests/test_advisor_report.py -q` (report still renders
      with the new item shape via existing fixtures, adjusting fixtures only
      if the type change requires it).

## Rollback

Revert the Task 1–4 commits. No persisted state changes in this phase, so
rollback is code-only.

---

## Notes / Learnings

<Filled in during execution.>
