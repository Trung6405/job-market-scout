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
  - [x] Write failing test: rendering a detail whose requirements include a
        `qualification` must-have shows must-have coverage counting only the
        `skill` must-haves (the qualification is excluded from the
        denominator), and the qualification does not appear in the
        "Requirements vs your profile" pass/fail list.
  - [x] Verify it fails (`python -m pytest tests/test_advisor_report.py -q`)
  - [x] In the template, filter `must_reqs` / `nice_reqs` (and the derived
        coverage/breakdown numbers) to `requirement_level` **and**
        `kind == 'skill'`.
  - [x] Verify it passes (`python -m pytest tests/test_advisor_report.py -q`)
  - [x] Commit: `fix(advisor): render skill-only requirement checklist`

### Task 2: "Role also asks for" context section

- **Files:** `scout/sub_agents/advisor/templates/job-detail.html.jinja`,
  `tests/test_advisor_report.py`
- **Gate:** none
- **Steps:**
  - [x] Write failing test: a detail with `qualification` / `experience` /
        `soft_skill` requirements renders a "Role also asks for" section
        listing them by name with no ✓/✕ mark; a detail with none of them
        omits the section.
  - [x] Verify it fails (`python -m pytest tests/test_advisor_report.py -q`)
  - [x] Add the section: iterate `detail.requirements` where
        `kind != 'skill'`, grouped or labelled by kind, rendered as plain
        context (reuse existing card styling; no mark element).
  - [x] Verify it passes (`python -m pytest tests/test_advisor_report.py -q`)
  - [x] Commit: `feat(advisor): show non-skill requirements as context`

### Task 3: Reconcile gap-semantics docs

- **Files:** `docs/agent/specs/advisor-report/spec.md` and/or
  `docs/project/specification/product-requirements-spec-amendments.md` (only
  the section describing what counts as a gap)
- **Gate:** none
- **Steps:**
  - [x] Update the prose that describes gap detection to state that only
        technical-skill requirements are matched and eligible to be gaps, and
        that non-skill requirements are shown as context. Cross-link this
        spec.
  - [x] Commit: `docs(advisor): note kind-based gap semantics`

---

## Verification

- [x] Phase tests pass: `python -m pytest tests/test_advisor_report.py -q`
- [~] Manual: render a real run's job-detail page and confirm a listing with
      a degree/experience requirement shows it under "Role also asks for",
      the gap list holds only missing technical skills, and must-have
      coverage counts only skills. *(Partially covered: the report tests
      render actual HTML files through the production template + DB
      round-trip and assert exactly this. A true end-to-end run with
      live LLM-extracted kinds is still pending — see Notes.)*

## Rollback

Revert the Task 1–3 commits; template-only changes, no state involved.

---

## Notes / Learnings

- Adding the "Role also asks for" section between "Requirements vs your
  profile" and "Skill gaps to close" widened the string slice used by the
  Task 1 test; retightened it to split on "Role also asks for".
- `test_main_entrypoint.py::test_run_once_completes_without_raising` failed
  after the DB changes because it mocks `track_listings` (which is where the
  real pipeline calls `apply_schema`) yet hits the real dev `scout` DB, which
  lacked the new `kind` column. Applied `apply_schema` once against the dev DB
  to add it (idempotent — production applies it on its next real run). Full
  suite then 239 passed.
- Live end-to-end verification (real LLM classifying kinds on scraped
  listings) is the one remaining manual check; the report tests otherwise
  render real HTML through the production template + DB path.
