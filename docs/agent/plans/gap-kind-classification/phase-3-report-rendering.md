# Phase 3: Report rendering

> **Parent plan:** [plan.md](plan.md)
> **Status:** Not started
> **Depends on:** Phase 2 complete (`RunListingDetail.requirements` carry `kind`)

---

## Goal

Render the job-detail page so the pass/fail skill checklist, match breakdown,
gap list, and must-have coverage count use `skill`-kind requirements only,
and non-skill requirements appear in a separate "Role also asks for" section
with no met/unmet mark. We'll know it worked when a listing with a degree or
experience requirement shows it as context and never as a gap or a coverage
miss.

## Safety Checklist

- **Touches user input, auth, secrets, or external calls?**
  No — template rendering of already-validated data. Autoescaping stays on.
- **Contains a one-way door (schema, public API shape, new dependency)?**
  No.

---

## Tasks

### Task 1: Skill-only checklist, breakdown, and coverage counts

- **Files:** `scout/sub_agents/advisor/templates/job-detail.html.jinja`,
  `tests/test_advisor_report.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing test: rendering a detail whose requirements include a
        `qualification` must-have shows must-have coverage counting only the
        `skill` must-haves (the qualification is excluded from the
        denominator), and the qualification does not appear in the
        "Requirements vs your profile" pass/fail list.
  - [ ] Verify it fails (`python -m pytest tests/test_advisor_report.py -q`)
  - [ ] In the template, filter `must_reqs` / `nice_reqs` (and the derived
        coverage/breakdown numbers) to `requirement_level` **and**
        `kind == 'skill'`.
  - [ ] Verify it passes (`python -m pytest tests/test_advisor_report.py -q`)
  - [ ] Commit: `fix(advisor): render skill-only requirement checklist`

### Task 2: "Role also asks for" context section

- **Files:** `scout/sub_agents/advisor/templates/job-detail.html.jinja`,
  `tests/test_advisor_report.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing test: a detail with `qualification` / `experience` /
        `soft_skill` requirements renders a "Role also asks for" section
        listing them by name with no ✓/✕ mark; a detail with none of them
        omits the section.
  - [ ] Verify it fails (`python -m pytest tests/test_advisor_report.py -q`)
  - [ ] Add the section: iterate `detail.requirements` where
        `kind != 'skill'`, grouped or labelled by kind, rendered as plain
        context (reuse existing card styling; no mark element).
  - [ ] Verify it passes (`python -m pytest tests/test_advisor_report.py -q`)
  - [ ] Commit: `feat(advisor): show non-skill requirements as context`

### Task 3: Reconcile gap-semantics docs

- **Files:** `docs/agent/specs/advisor-report/spec.md` and/or
  `docs/project/specification/product-requirements-spec-amendments.md` (only
  the section describing what counts as a gap)
- **Gate:** none
- **Steps:**
  - [ ] Update the prose that describes gap detection to state that only
        technical-skill requirements are matched and eligible to be gaps, and
        that non-skill requirements are shown as context. Cross-link this
        spec.
  - [ ] Commit: `docs(advisor): note kind-based gap semantics`

---

## Verification

- [ ] Phase tests pass: `python -m pytest tests/test_advisor_report.py -q`
- [ ] Manual: render a real run's job-detail page and confirm a listing with
      a degree/experience requirement shows it under "Role also asks for",
      the gap list holds only missing technical skills, and must-have
      coverage counts only skills.

## Rollback

Revert the Task 1–3 commits; template-only changes, no state involved.

---

## Notes / Learnings

<Filled in during execution.>
