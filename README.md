# job-market-scout
Multi-agent job market scout, scrapes listings, matches them to a resume, tracks changes, and briefs daily

## Getting started

### Prerequisites
- Docker Desktop (running, with its socket available — `jobspy-mcp` shells
  out to `docker run` per search and mounts `/var/run/docker.sock`)
- A [DeepSeek API key](https://platform.deepseek.com/)
- A Gmail account with 2FA enabled, so you can generate an
  [app password](https://myaccount.google.com/apppasswords) (your regular
  Gmail password won't work for SMTP)

### Setup
1. Clone with submodules (the scraper vendors `jobspy-mcp-server`):
   ```
   git clone --recurse-submodules <repo-url>
   ```
   If you already cloned without `--recurse-submodules`, run:
   ```
   git submodule update --init --recursive
   ```
2. Copy the example config and fill in your own values:
   ```
   cp scout/.env.example scout/.env
   ```
   At minimum set `DEEPSEEK_API_KEY`, `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`,
   and `GMAIL_RECIPIENT`. Adjust `SEARCH_ROLES`, `SEARCH_LOCATIONS`,
   `PREFERRED_LOCATIONS`, `REMOTE_ONLY`, `MIN_SALARY`, and
   `MIN_MATCH_SCORE` to taste.
3. Copy the resume template and replace it with your own resume:
   ```
   cp scout/resume.txt.example scout/resume.txt
   ```
4. (Optional) `scout/profile.json` ships with a placeholder profile so the
   Advisor report has something to render out of the box. Replace it with
   your own tech stack, domain knowledge, and background — `scout/profile.json.example`
   shows the expected shape:
   ```
   cp scout/profile.json.example scout/profile.json
   ```
   The pipeline scores and emails matches either way; an accurate profile
   just makes skill-gap detection in the Advisor report meaningful.
5. Run the pipeline:
   ```
   docker compose up --build
   ```
   This builds the app, the vendored `jobspy` scraper image, and the
   `jobspy-mcp` and `postgres` services, then runs one scrape → score →
   track → brief cycle via `python -m scout.main`. The Postgres schema is
   applied automatically on first run — no manual migration step needed.
   Matches above `MIN_MATCH_SCORE` are emailed to `GMAIL_RECIPIENT`.

### Advisor report output

Each run also renders an HTML report — a daily dashboard of scored
listings (with success bands and skill gaps, if `scout/profile.json`
exists) with prev/next links to adjacent days, a per-role detail page
(role snapshot, match-breakdown bars, a full requirements-vs-profile
checklist, and gap-closing coaching tips when a profile exists), a
history of past days, and a profile page — into `./reports` on the
host (mounted from the container's `/app/reports`). Open
`./reports/history.html` to browse past days. GitHub learning-resource
links per skill gap are not implemented yet — gaps are shown by name
only.

By default the briefing email just shows the report's path as plain
text (e.g. `reports/2026-07-21/dashboard.html`) — the app runs inside a
container, so it has no way to know the report's absolute location on
your host machine, and a `file://` link built from the container's own
path (`/app/reports/...`) would not open on your host. To get a
clickable link in the email instead, set `REPORT_HOST_DIR` in your
`.env` to the absolute path of this project's `reports` directory on
your host machine, e.g.:
```
REPORT_HOST_DIR=/home/you/job-market-scout/reports
```

### Live dashboard

The deployed instance publishes the same dashboard to an Azure Storage
static website, so it's reachable 24/7 — independent of the VM, which is
deallocated ~23h/day to control cost. `scheduled-run.yml` refreshes it
after each scheduled pipeline run (see
[docs/commands.md](docs/commands.md#deploy) and
[infra/README.md](infra/README.md)).

| Page | Link |
|------|------|
| Daily reports (home / history) | <https://trung6405scoutdash.z44.web.core.windows.net/> |
| History | <https://trung6405scoutdash.z44.web.core.windows.net/history.html> |
| My profile | <https://trung6405scoutdash.z44.web.core.windows.net/profile.html> |
| A given day | `https://trung6405scoutdash.z44.web.core.windows.net/<YYYY-MM-DD>/dashboard.html` |
| Hello smoke-test page | <https://trung6405scoutdash.z44.web.core.windows.net/hello/> |

The root serves the history index (the static-website host allows only
one global index document, so `index.html` is a copy of `history.html`).
The `z44` zone in the hostname is region-derived and would change if the
storage account is recreated in a different region — the current
endpoint is emitted as the `dashboardWebEndpoint` output of
`infra/dashboard.bicep`.

To browse the reports locally instead (no Azure), serve the `reports/`
folder and open it in a browser:
```
python -m http.server 8080 --directory reports
# then open http://127.0.0.1:8080/history.html
```

### Running tests
```
pip install -r requirements.txt
pytest
```
The suite needs a live Postgres — start it first with `docker compose up -d postgres`.

### Command reference

See [docs/commands.md](docs/commands.md) for a single cheatsheet of every
command to **run** (full pipeline, re-render reports, manage the stack),
**test**, **show** the rendered reports, and **deploy**.
