# Phase 3: Retire the Static Section

> **Parent plan:** [plan.md](plan.md)
> **Status:** In progress
> **Depends on:** Phase 2 complete (gap blocks carry their tips)

---

## Goal

Delete the static "How to position your application" section and replace the
advice it used to give, when a listing has no tips at all, with one honest line
about the corpus not covering those gaps yet. At the end of this phase no
templated generic advice remains on the page and P4's acceptance criteria are
all met.

## Safety Checklist

- **Touches user input, auth, secrets, or external calls?**
  No — a deletion and one static line.
- **Contains a one-way door (schema, public API shape, new dependency)?**
  No. The next `python -m scout.rerender` rewrites every historical page from
  the database, so this is visible across all past runs — but it is reversible
  by revert-and-re-render, since nothing stored changes.

---

## Tasks

### Task 1: The empty state

- **Files:**
  `scout/sub_agents/advisor/templates/job-detail.html.jinja`,
  `tests/test_advisor_report.py`
- **Gate:** none
- **Steps:**
  - [x] Write failing test: seed a run whose listing has two gaps and **no**
        stored tips. Assert the rendered page contains "No verified learning
        resources for these gaps yet", and that a listing which *does* have
        tips does not contain that line.
  - [x] Verify it fails (`pytest tests/test_advisor_report.py -v`)
  - [x] Implement minimal change: inside the gaps section, after the gap
        loop, render the line in a muted paragraph when `detail.tips` is
        empty. Gate on `detail.tips`, not on the cap — a listing whose only
        tips are orphans should still say the corpus covered nothing, and both
        conditions agree in every real case.
  - [x] Verify it passes (`pytest tests/test_advisor_report.py -v`) — 22 passed
  - [x] Commit: `feat(advisor): add the no-resources-yet empty state`

### Task 2: Delete the static positioning section

- **Files:**
  `scout/sub_agents/advisor/templates/job-detail.html.jinja`,
  `tests/test_advisor_report.py`
- **Gate:** none
- **Steps:**
  - [x] Write failing test: **invert** the existing assertion at
        `tests/test_advisor_report.py:211` — `"How to position your
        application" not in job_detail_html` — and add that neither
        `"the highest-impact gap"` nor `"don't over-invest before applying"`
        appears, so the three deleted branches are pinned individually rather
        than only by the heading.
  - [x] Verify it fails (`pytest tests/test_advisor_report.py -v`) — expected:
        the section is still rendered.
  - [x] Implement minimal change: delete the whole
        `{% if detail.gaps %}…{% endif %}` section (currently lines 280–301)
        and the now-unused `.tips` CSS rules, keeping `.coach` — the callout
        above the gap list still renders and still carries the must-have
        framing.
  - [x] Verify it passes (`pytest tests/test_advisor_report.py -v`) — 23 passed
  - [x] Commit: `feat(advisor): delete the static positioning advice section`

> `nice_reqs` / `nice_met` and `must_reqs` / `must_met` are set earlier in the
> template for the match-breakdown section and are unrelated to the deleted
> block's local `must_gaps` / `nice_gaps`. Delete only the latter two.

### Task 3: Historical runs re-render coherently

- **Files:** `tests/test_advisor_report.py`
- **Gate:** none
- **Steps:**
  - [x] Write failing test: extend the existing
        `test_rerender_all_regenerates_pages_from_db`
        (`tests/test_advisor_report.py:440-480`) with a run whose listings have
        gaps and no tips — the pre-P3 shape — and assert the regenerated page
        contains the empty-state line and none of the deleted static advice.
  - [x] Verify it fails — it passed on write, as the task allowed for: Tasks 1
        and 2 already implement the behaviour, and this asserts it survives the
        re-render path. Kept as the regression guard; noted below.
  - [x] Implement minimal change: none expected — this asserts Tasks 1 and 2
        hold through the re-render path, which reads only from the database.
  - [x] Verify it passes (`pytest tests/test_advisor_report.py -v`) — 24 passed
  - [x] Commit: `test(advisor): pin historical re-render of untipped runs`

### Task 4: Update the architecture overview and close out the plan

- **Files:** `docs/project/architecture-pipeline-overview.md`,
  `docs/agent/plans/career-coach-p4-report-surfacing/plan.md`,
  `docs/agent/plans/career-coach-p4-report-surfacing/phase-*.md`
- **Gate:** none
- **Steps:**
  - [ ] Update the overview wherever it describes the detail page's coaching
        advice as templated, and record that grounded tips now render per gap.
  - [ ] Tick the plan's Acceptance Criteria and Definition of Done, set all
        three phase rows to Complete, and leave the deferred end-to-end check
        explicitly unticked with a note that it waits on P3's phases 2–3.
  - [ ] Verify: `pytest -v` green.
  - [ ] Commit: `docs(advisor): record grounded tips in the report overview`

> Docs bookkeeping rides in this task's own commit rather than a trailing
> sweep, per the project's token-efficiency rule. Every earlier task's
> checkbox is ticked in the commit that completes it.

---

## Verification

- [ ] All phase tests pass: `pytest tests/test_advisor_report.py -v`
- [ ] Full suite green: `pytest -v`
- [ ] `grep -r "How to position your application" scout/` returns nothing
- [ ] Manual: render a run with tips and one without; the first shows advice
      per gap with working citations, the second shows the empty-state line
      and no generic advice.

## Rollback

Revert the phase's commits and run `python -m scout.rerender` to rebuild every
page from the database. Nothing stored is touched, so the pre-P4 pages return
exactly.

---

## Notes / Learnings

<Filled in during execution.>
