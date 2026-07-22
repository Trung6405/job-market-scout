# Phase 5: Pipeline and email wiring (rendering)

> **Parent plan:** [plan.md](plan.md)
> **Status:** Complete
> **Depends on:** Phase 4 complete

---

## Goal

A real pipeline run renders that day's report to the mounted output
directory and the resulting email links to it, with the
no-report-available case falling back to today's plain email.

## Safety Checklist

- **Touches user input, auth, secrets, or external calls?** No new
  external calls — writes to a mounted local volume; email sending
  itself is unchanged (still Gmail SMTP via existing
  `notification.py`).
- **Contains a one-way door (schema, public API shape, new dependency)?**
  No.

---

## Tasks

### Task 1: Pipeline wiring

- **Files:** `scout/agent.py`, `tests/test_agent.py`
- **Gate:** none
- **Steps:**
  - [x] Write failing test: a full pipeline run produces rendered
        report files for that run (asserted via the fake/stub rendering
        call, matching how other pipeline stages are tested in
        `test_agent.py`)
  - [x] Verify it fails (`./.venv/Scripts/python.exe -m pytest tests/test_agent.py -q`)
  - [x] Call `render_run` + `render_history` + `render_profile` in
        `ScoutPipelineAgent._run_async_impl`, after the Phase 3
        enrichment step and before `run_briefing`
  - [x] Verify it passes (`./.venv/Scripts/python.exe -m pytest tests/test_agent.py -q`)
  - [x] Commit: `feat(agent): render advisor report before briefing` (359c493)

### Task 2: Email link

- **Files:** `scout/sub_agents/briefing/briefing.py`, `scout/sub_agents/briefing/email_builder.py`, `tests/test_briefing_email_builder.py`, `tests/test_briefing_agent.py`
- **Gate:** none
- **Steps:**
  - [x] Write failing test: `build_email` includes a link/path to the
        day's `dashboard.html` when given a report path; omits it
        (renders identically to today) when no report path is given
  - [x] Verify it fails (`./.venv/Scripts/python.exe -m pytest tests/test_briefing_email_builder.py -q`)
  - [x] Add an optional `report_path` parameter to `build_email` and
        thread it through from `run_briefing`
  - [x] Verify it passes (`./.venv/Scripts/python.exe -m pytest tests/test_briefing_email_builder.py -q`)
  - [x] Commit: `feat(briefing): link the day's report from the email` (beb7191, fix 25c9958)

### Task 3: Docker volume mount

- **Files:** `docker-compose.yaml`, `README.md`
- **Gate:** none
- **Steps:**
  - [x] Add `./reports:/app/reports` under the `app` service's volumes
        in `docker-compose.yaml`
  - [x] Document the new `reports/` output directory in `README.md`'s
        setup/usage section
  - [x] Commit: `chore(docker): mount reports output directory` (84d986a)

---

## Verification

- [x] All phase tests pass: `./.venv/Scripts/python.exe -m pytest tests/test_agent.py tests/test_briefing_email_builder.py tests/test_briefing_agent.py -q`
- [x] Full suite unaffected: `./.venv/Scripts/python.exe -m pytest -q` — 197/197 passing
- [ ] Manual: `docker compose up --build`, confirm `./reports/<date>/`
      appears on the host with real content, and the received email
      contains a working link/path to it. **Not yet done** — a
      scripted equivalent (real Postgres, real render/email-building
      functions, no Docker) was run during Phase 4's spike and this
      phase's task reviews; the full `docker compose up --build`
      end-to-end pass (including actually receiving an email) is
      deferred to before merge.

## Observability

Pipeline status events report the rendered report's path; the email's
new line is visible directly in the received message — no separate
monitoring needed for a personal single-user tool.

## Rollback

Revert Task 1 (stop rendering), Task 2 (email reverts to today's
plain form since `report_path` is optional and defaults to omitted),
and Task 3 (remove the volume mount) independently — none depend on
each other to be reverted together.

---

## Notes / Learnings

- Task 2's file/link construction initially used `str(report_path)`
  raw in a `file://` URI, which produces backslash-separated (invalid,
  unclickable) URIs on this project's Windows dev environment — task
  review caught it; fixed by resolving to an absolute path and using
  `Path.as_uri()`.
- Task 2's brief named `tests/test_briefing_agent.py`, but the actual
  `run_briefing` tests live in `tests/test_briefing_entrypoint.py` —
  the implementer correctly used the real file; the brief's filename
  was simply imprecise.
- A stray `reports/` directory (real rendered HTML from manual
  verification against the actual local dev Postgres) appeared in the
  project root during Task 1's execution — cleaned up and `/reports/`
  added to `.gitignore` alongside `.superpowers/` (a subagent had
  earlier accidentally committed a scratch file from that directory
  too; both are now excluded).
