# Phase 4: Templates and rendering module

> **Parent plan:** [plan.md](plan.md)
> **Status:** Not started
> **Depends on:** Phase 1 and Phase 3 complete (needs `run_listings`/`listing_gaps` to read); `profile-schema` complete (needs `Profile`/`load_profile`)

---

## Goal

Given a `run_id` and a `Profile`, produce the four rendered HTML files
on disk with correct data and working cross-screen links — verified by
opening them in a browser, before any pipeline wiring exists.

## Safety Checklist

- **Touches user input, auth, secrets, or external calls?** No — reads
  already-persisted DB data and a local `profile.json`, writes local
  files only.
- **Contains a one-way door (schema, public API shape, new dependency)?**
  New dependency: `jinja2`. Not a one-way door (easy to swap/remove
  before anything depends on it) — no gate needed.

---

## Tasks

### Task 1+2 (merged): Templates and rendering module

*(Merged before dispatch — as originally split, Task 1's own test step
required `render_run`, which Task 2 was scoped to build; testing
"the templates have the right shape" is meaningless without a render
function, and the render function can't exist without templates to
render. Splitting them would only create a circular dependency between
tasks. See Notes / Learnings.)*

- **Files:** `scout/sub_agents/advisor/templates/*.html.jinja`,
  `scout/sub_agents/advisor/report.py`, `scout/config.py`,
  `requirements.txt`, `tests/test_advisor_report.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing tests: `render_run` writes `dashboard.html` and
        one `job-detail-<id>.html` per scored listing to
        `report_output_dir/<run_date>/`, containing a known fixture
        listing's title, score, and band label; `render_history` writes
        `history.html` reflecting `list_runs()`, including a zero-match
        day; `render_profile` writes `profile.html` from a `Profile`
  - [ ] Verify it fails (`./.venv/Scripts/python.exe -m pytest tests/test_advisor_report.py -q`)
  - [ ] Copy `docs/prototypes/{dashboard,history,job-detail,profile}.html`
        into `scout/sub_agents/advisor/templates/` as `.html.jinja`,
        replacing hardcoded sample content with `{{ }}`/`{% %}`
        template expressions. Add `jinja2` to `requirements.txt`; add
        `report_output_dir: str` to `Settings` (default `"reports"`);
        implement `render_run`/`render_history`/`render_profile` in
        `scout/sub_agents/advisor/report.py`
  - [ ] Verify it passes (`./.venv/Scripts/python.exe -m pytest tests/test_advisor_report.py -q`)
  - [ ] Commit: `feat(advisor): add Jinja2 report templates and rendering module`

### Task 2: Spike — verify cross-screen links resolve

- **Files:** none (manual verification, may produce follow-up fixes to Task 1/2)
- **Gate:** none
- **Steps:**
  - [ ] Render a fixture run + profile to a scratch directory, open
        `dashboard.html` in a browser, click through to job-detail,
        profile, and history, confirm every link resolves to an
        existing file (addresses the relative-link risk in plan.md)
  - [ ] Fix any broken relative paths found, re-verify
  - [ ] Commit: `fix(advisor): correct report cross-screen link paths` *(only if fixes were needed)*

---

## Verification

- [ ] All phase tests pass: `./.venv/Scripts/python.exe -m pytest tests/test_advisor_report.py -q`
- [ ] Full suite unaffected: `./.venv/Scripts/python.exe -m pytest -q`
- [ ] Manual: Task 3's browser click-through completed with no broken
      links.

## Rollback

Delete `scout/sub_agents/advisor/report.py`,
`scout/sub_agents/advisor/templates/`, and revert the `Settings`/
`requirements.txt` additions. Nothing else depends on this module yet
(wiring is Phase 5).

---

## Notes / Learnings

- 2026-07-21: Merged Task 1 and Task 2 before dispatch — as originally
  split, Task 1's failing test referenced `render_run` (Task 2's
  deliverable), creating a circular dependency between the two tasks.
  Combined into one task; the spike (link verification) remains
  separate as the new Task 2.
