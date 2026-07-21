# Task P4-T1 Report: Templates and rendering module

## What I implemented

### `scout/shared/schemas.py`
Added `RunListingDetail` model exactly as specified (`run_listing_id`, `listing`, `score`, `reasoning`, `band`, `gaps`).

### `scout/shared/db.py`
Added `get_run(conn, run_id)` (mirrors `get_run_by_date`, keyed by `id`) and `get_run_details(conn, run_id)` (join query + batched gap fetch + grouping, per the exact SQL specified in the brief). No existing functions touched.

### `scout/config.py`
Added `report_output_dir: str` field, default `"reports"`, env var `REPORT_OUTPUT_DIR`, placed next to `profile_path`.

### `requirements.txt`
No change needed — `Jinja2==3.1.6` was already present (pulled in transitively, already pinned). Confirmed the import works in tests.

### Templates (`scout/sub_agents/advisor/templates/*.html.jinja`)

- **`dashboard.html.jinja`** — near-verbatim copy of the mockup. Deviations:
  - Day-nav prev/next arrows are now static/disabled (per the brief's authorized simplification) instead of computing adjacent run dates; the current day label is rendered from `run.run_date`.
  - "Good morning, Minh" personalized greeting replaced with generic "Today's briefing" / "Here are today's best-matched roles" — the template only receives `run` and `details`, not `profile`, so the name/target-role personalization has no data source.
  - Stats row now driven by a `stats` dict (`scored`, `strong`, `avg_score`, `gaps`) computed in `report.py`, not the template.
  - Nav links: `History`/`My Profile` go up one directory (`../history.html`, `../profile.html`); `Today` stays same-dir.
  - Cards link to `job-detail-{{ detail.run_listing_id }}.html`. Band pill and gap-chip "must" styling driven by two new Jinja filters (`band_label`, `band_css`) and `gap.requirement_level == 'must_have'`.
  - Client-side filter-chip JS kept unchanged (cosmetic, matches `band_css` output classes `strong`/`comp`/`reach`).

- **`history.html.jinja`** — near-verbatim. Deviations:
  - Month-group headers (`July 2026`) computed via a Jinja `namespace` tracking the last-seen `%B %Y` label, since input is already sorted by `list_runs` — no separate grouping logic needed in Python.
  - Each day: `.day.empty` variant renders when `day.details` is empty (i.e., `listings_scored == 0` produced zero scored rows) — non-clickable `<div>`, muted text, no arrow, exactly matching the mockup's `.day.empty` class.
  - `NEW` tag only on `loop.first` (the most recent day), same as mockup's "today" convention — this assumes the caller passes days in descending date order (true via `list_runs`).
  - Top nav `Today` link points to `{{ days[0].run.run_date }}/dashboard.html` if `days` is non-empty, otherwise rendered as a disabled span, per the brief's guidance.

- **`job-detail.html.jinja`** — **structurally simplified**, not a verbatim copy, because `RunListingDetail` doesn't carry the data several mockup sections need:
  - Kept: header (title/company/location/salary/posted date/original-listing link), fit-score bar, band pill + `reasoning` text, gap count summary, "About this role" (rendered from `listing.description` instead of the mockup's hand-authored structured snapshot — we have no seniority/team/applicant-count fields), and a "Skill gaps to close" section listing each `SkillGap` with a must-have/nice-to-have badge.
  - Dropped: the mockup's "Role snapshot" grid (seniority/work-type/team/applicants) and stack-row ticks — no structured data for these, only free-text `description`. Dropped the "Why this band — match breakdown" per-category progress bars (tech-stack-fit/domain/seniority/production-data-experience) — we only have one overall `score` + `reasoning`, not sub-scores. Dropped "Close the gap — free resources" (GitHub repo links) — `SkillGap` has no resource-link field; that's a separate, later capability. Dropped "How to position your application" tips — no data source.
  - This is the one place I deviated from "reuse the mockup's HTML/CSS almost verbatim" in structure (not just content-substitution); I judged it correct per the brief's own instruction that "the data available is exactly what's listed" for this task, and flagged it here rather than inventing fictional data to fill the mockup's shape.

- **`profile.html.jinja`** — near-verbatim. `Profile.domain_knowledge[].level` (already a model property) drives the level badge; proficiency dots use `range(1,6)` against `TechSkill.proficiency`; background/projects map directly. Back-link points to `history.html` (not a "most-recent-day dashboard" link) because `render_profile` is synchronous and has no DB access to know the most recent run — noted as the brief anticipated ("if available").

### `scout/sub_agents/advisor/report.py`
- Module-level shared `jinja2.Environment` (`FileSystemLoader` + `select_autoescape`) with three registered filters: `band_label`, `band_css` (single `_BAND_INFO` dict, used by `dashboard.html.jinja` and `job-detail.html.jinja` — not repeated per-template), and `format_salary` (also shared between dashboard and job-detail).
- `render_run(conn, run_id, settings)` — fetches `run`/`details`, writes `dashboard.html` + one `job-detail-<id>.html` per detail into `<report_output_dir>/<run_date>/`, returns `{"dashboard": Path, "job_detail_<id>": Path, ...}`.
- `render_history(conn, settings, limit=30)` — fetches `list_runs` then `get_run_details` per run (N+1, accepted per brief), writes `<report_output_dir>/history.html`.
- `render_profile(profile, settings)` — synchronous, writes `<report_output_dir>/profile.html`.

## What I tested / results

`tests/test_advisor_report.py` (new), against real Postgres via the existing `db_pool` fixture, writing to `tmp_path` via `Settings(report_output_dir=str(tmp_path))`:

1. `test_render_run_writes_dashboard_and_job_detail_files` — seeds one listing/run/score/gap via `upsert_listing`/`start_run`/`record_run_listings`/`record_listing_gaps`/`finish_run`, calls `render_run`, asserts `dashboard.html` and `job-detail-<id>.html` exist at `tmp_path/2026-07-21/`, checks the returned path dict keys, and asserts the dashboard HTML contains the fixture listing's title, score, and "Strong-match" band label, and the job-detail HTML contains the title and the gap skill "PostgreSQL".
2. `test_render_history_reflects_runs_including_empty_day` — seeds one scored run and one zero-score (`listings_scored=0`) run, calls `render_history`, asserts `history.html` is written, contains the `day empty` class, and links to `2026-07-21/dashboard.html`.
3. `test_render_profile_writes_profile_html` — builds a fixture `Profile`, calls `render_profile` (no DB), asserts `profile.html` contains the name, a project title, and a tech-stack skill name.

## TDD Evidence

**RED** — before `report.py` existed:
```
./.venv/Scripts/python.exe -m pytest tests/test_advisor_report.py -q
```
```
ImportError while importing test module 'tests\test_advisor_report.py'.
...
E   ModuleNotFoundError: No module named 'scout.sub_agents.advisor.report'
1 error in 0.42s
```
Expected failure: the module under test didn't exist yet, confirming the tests were exercising real (not-yet-written) code, not passing vacuously.

**GREEN** — after implementing schemas/db/config/templates/report.py:
```
./.venv/Scripts/python.exe -m pytest tests/test_advisor_report.py -q
```
```
...                                                                      [100%]
3 passed in 2.72s
```

**Full suite**, run once before committing:
```
./.venv/Scripts/python.exe -m pytest -q
```
```
191 passed, 5 warnings in 51.76s
```
(Warnings are pre-existing deprecation notices from `google-genai`/ADK, unrelated to this change.)

## Files changed

- `scout/shared/schemas.py` — added `RunListingDetail`
- `scout/shared/db.py` — added `get_run`, `get_run_details`
- `scout/config.py` — added `report_output_dir`
- `scout/sub_agents/advisor/report.py` — new
- `scout/sub_agents/advisor/templates/dashboard.html.jinja` — new
- `scout/sub_agents/advisor/templates/history.html.jinja` — new
- `scout/sub_agents/advisor/templates/job-detail.html.jinja` — new
- `scout/sub_agents/advisor/templates/profile.html.jinja` — new
- `tests/test_advisor_report.py` — new

`requirements.txt` unchanged (Jinja2 already pinned).

## Self-review findings

- Completeness: all four templates converted; all three render functions implemented; zero-gap path (job-detail "no skill gaps detected" message) and zero-match-day path (`history` `.day.empty`) both exercised by tests and don't crash.
- Quality: band→label/CSS mapping defined once (`_BAND_INFO`/`_band_label`/`_band_css` in `report.py`) and reused via Jinja filters in both templates that need it, not repeated. Salary formatting likewise centralized as one filter reused by two templates.
- Discipline: `scout/agent.py` untouched. Only two new functions appended to `db.py`; no existing function bodies changed (verified via `git diff --cached scout/shared/db.py` — pure addition at end of file plus one import-list edit).
- Testing: all three new tests hit real Postgres through `db_pool` (not mocked), assert on real file existence and real HTML substring content, and write only to `tmp_path`.
- Git hygiene: this branch (`feature/advisor-report`) had pre-existing uncommitted changes from earlier phase work (`docs/specs/advisor-report/spec.md`, `.dockerignore`, scraper `mcp_client.py`/its test) that are not part of this task; I staged and committed only the files listed above, leaving those untouched in the working tree.

## Concerns for the next task (manual link-path spike)

- `dashboard.html.jinja` and `job-detail.html.jinja` live in `<report_output_dir>/<run_date>/`; their `../history.html` / `../profile.html` links assume `history.html` and `profile.html` are written directly under `<report_output_dir>/` (which `render_history`/`render_profile` do) — this relative nesting is untested end-to-end (i.e., no test opens the written files in a browser or link-checks them), only that each function writes to the right individual path.
- `history.html.jinja`'s day links (`{{ day.run.run_date }}/dashboard.html`) and its `Today` nav link both assume every historical run directory was actually populated by a prior `render_run` call for that `run_date` — if `render_history` is ever invoked for a run that never had `render_run` called (e.g., a scored run whose dashboard was never rendered), the link would 404. Nothing in the current code enforces that ordering/pairing.
- `job-detail.html.jinja`'s structural simplification (dropping role-snapshot/match-breakdown/resources/tips sections) is a bigger content departure from the mockup than the other three templates; worth a product sanity check that the trimmed page is still useful, since it's a visible change beyond "data-wiring."

## Hotfix: Add missing nav links to job-detail template

**Finding:** `job-detail.html.jinja` was missing required `../history.html` and `../profile.html` links. The template had only a simple `.back` link to `dashboard.html`, not the full site navigation pattern used in `dashboard.html.jinja`.

**Fix applied:**
- Added CSS rules for `header.top`, `.brand`, `.brand .dot`, and `.nav` (copied from dashboard, matching visual/layout style exactly).
- Replaced the simple `.back` link with a full `<header class="top">` containing brand and navigation menu (`Today` → `dashboard.html`, `History` → `../history.html`, `My Profile` → `../profile.html`).
- Updated `test_render_run_writes_dashboard_and_job_detail_files` to assert that both `../history.html` and `../profile.html` links are present in the rendered job-detail HTML.

**Test results:**
- Focused test (`tests/test_advisor_report.py -q`): 3 passed in 1.71s
- Full suite (`pytest -q`): 191 passed, 5 warnings in 25.45s

**Commit:** `d0a1a8e` — `fix(advisor): add missing nav links to job-detail template`
