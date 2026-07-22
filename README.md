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

### Running tests
```
pip install -r requirements.txt
pytest
```
