# Phase 4: Templates and rendering module

> **Parent plan:** [plan.md](plan.md)
> **Status:** Complete
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
  - [x] Write failing tests: `render_run` writes `dashboard.html` and
        one `job-detail-<id>.html` per scored listing to
        `report_output_dir/<run_date>/`, containing a known fixture
        listing's title, score, and band label; `render_history` writes
        `history.html` reflecting `list_runs()`, including a zero-match
        day; `render_profile` writes `profile.html` from a `Profile`
  - [x] Verify it fails (`./.venv/Scripts/python.exe -m pytest tests/test_advisor_report.py -q`)
  - [x] Copy `docs/project/prototypes/{dashboard,history,job-detail,profile}.html`
        into `scout/sub_agents/advisor/templates/` as `.html.jinja`,
        replacing hardcoded sample content with `{{ }}`/`{% %}`
        template expressions. Add `jinja2` to `requirements.txt`; add
        `report_output_dir: str` to `Settings` (default `"reports"`);
        implement `render_run`/`render_history`/`render_profile` in
        `scout/sub_agents/advisor/report.py`
  - [x] Verify it passes (`./.venv/Scripts/python.exe -m pytest tests/test_advisor_report.py -q`)
  - [x] Commit: `feat(advisor): add Jinja2 report templates and rendering module` (401745d, fix d0a1a8e for missing job-detail nav links)

### Task 2: Spike — verify cross-screen links resolve

- **Files:** none (manual verification, may produce follow-up fixes to Task 1/2)
- **Gate:** none
- **Steps:**
  - [x] Render a fixture run + profile to a scratch directory, open
        `dashboard.html` in a browser, click through to job-detail,
        profile, and history, confirm every link resolves to an
        existing file (addresses the relative-link risk in plan.md)
  - [x] Fix any broken relative paths found, re-verify — none needed;
        23/23 internal links across 7 rendered files resolved correctly
        on the first pass (after Task 1+2's own nav-link fix)
  - [x] Commit: `fix(advisor): correct report cross-screen link paths` *(only if fixes were needed)* — not needed, no commit

---

## Verification

- [x] All phase tests pass: `./.venv/Scripts/python.exe -m pytest tests/test_advisor_report.py -q`
- [x] Full suite unaffected: `./.venv/Scripts/python.exe -m pytest -q` — 191/191 passing
- [x] Manual: link-resolution check completed with no broken links (see
      Notes / Learnings — a scripted check against real rendered output
      was used in place of a literal browser click-through, verifying
      the same thing: every generated `href` resolves to a real file).

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
- 2026-07-21: Task review caught `job-detail.html.jinja` missing the
  required `../history.html`/`../profile.html` nav links (only a
  `dashboard.html` back-link existed) — fixed and re-reviewed clean.
  The `job-detail.html.jinja` conversion also dropped several mockup
  sections (role-snapshot grid, per-category match-breakdown bars,
  full requirements-vs-profile checklist, positioning tips) beyond
  what the implementer's own self-review named — reviewer assessed all
  drops as justified by genuine data gaps in `RunListingDetail`, not
  laziness, since `docs/project/prototypes/job-detail.html`'s underlying data
  (e.g. per-category score breakdowns, full satisfied-requirements
  list) was never built by earlier phases. Revisit only if a later
  phase adds that structured data.
- 2026-07-21: Task 2's spike used a scripted link-resolution check
  (render a fixture run via the real pipeline functions against real
  Postgres + `profile.json.example`, then regex-scan every generated
  `.html` file's `href`s and confirm each resolves to a real file)
  rather than a literal manual browser click-through — verifies the
  same thing the task asked for. 23/23 links resolved on the first
  pass; no fixes needed.
- 2026-07-22: Closed the gap flagged above ("role-snapshot grid,
  per-category match-breakdown bars, full requirements-vs-profile
  checklist, positioning tips ... revisit only if a later phase adds
  that structured data"). Added the missing structured data —
  `evaluate_requirements()` (full met/unmet checklist, not just gaps),
  `seniority`/`work_type`/`team` extraction on `ListingRequirements` —
  and rendered role snapshot, must-have/nice-to-have coverage bars, the
  full requirements checklist, and derived positioning tips in
  `job-detail.html.jinja`. Per-category score breakdowns (e.g. a
  separate "domain knowledge fit" bar) stay dropped — nothing extracts
  per-category scores, and fabricating one would violate the report's
  own "band is an estimate, not a guarantee" framing. See spec.md
  Amendments (2026-07-22) for the full change list, including two
  unrelated bugs fixed in the same pass (`listings_scored` miscount,
  dead prev/next day links).
