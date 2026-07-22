# Command reference

A single place for the commands to **run**, **test**, and **show** job-market-scout.
Run everything from the repo root. Local shell examples assume the project
virtualenv is active (or prefix with `.venv/Scripts/python` on Windows /
`.venv/bin/python` on macOS/Linux).

---

## Run

### Full pipeline (scrape → track → score → advise → brief)
The default container command is `python -m scout.main`, so bringing the stack
up runs one full cycle:
```bash
docker compose up --build
```
- Builds the app, the vendored `jobspy` scraper, `jobspy-mcp`, and `postgres`.
- Applies the Postgres schema automatically on first run.
- Writes HTML into `./reports/` and emails matches above `MIN_MATCH_SCORE`.

Run the pipeline once without rebuilding images:
```bash
docker compose up
```

Run the pipeline directly on the host (needs `postgres` reachable at the
`DATABASE_URL`, default `localhost:5433`, and `jobspy-mcp` running):
```bash
python -m scout.main
```

### Re-render reports only (no scrape, no LLM calls)
Regenerates every dashboard, job-detail, history, and profile page from the
runs already stored in Postgres — use this after a template or renderer change
to refresh already-generated pages:
```bash
python -m scout.rerender
```
On the server / against the compose stack (reuses the `app` service's `./reports`
mount and `DATABASE_URL`):
```bash
docker compose -f docker-compose.yaml -f docker-compose.prod.yaml \
  run --rm app python -m scout.rerender
```

### Manage the stack
```bash
docker compose up -d              # start in the background
docker compose logs -f app        # follow the pipeline's logs
docker compose ps                 # list running services
docker compose down               # stop and remove containers
docker compose down -v            # also drop the postgres volume (wipes run history)
```

---

## Test

The suite needs a live Postgres (the persist path opens a real connection). It
uses a dedicated `scout_test` database on the same server as `DATABASE_URL`, so
it never touches dev/prod run history.

```bash
# 1. Start Postgres (published on localhost:5433 by the compose stack)
docker compose up -d postgres

# 2. Install deps (first time only) and run the suite
pip install -r requirements.txt
pytest
```

Common variations:
```bash
pytest -q                                   # quiet
pytest tests/test_advisor_report.py         # one file
pytest tests/test_advisor_report.py -k markdown   # match test names
pytest -x                                   # stop at first failure
```

If Postgres is unreachable, the DB-backed tests **skip** (they don't fail).

---

## Show

### Open the rendered reports
The pipeline (and `scout.rerender`) writes static HTML to `./reports/` on the
host. Open the landing page in a browser:
```bash
# macOS
open reports/history.html
# Windows (PowerShell)
start reports/history.html
# Linux
xdg-open reports/history.html
```
- `reports/history.html` — all past days
- `reports/<YYYY-MM-DD>/dashboard.html` — a day's scored listings
- `reports/<YYYY-MM-DD>/job-detail-<id>.html` — one role's detail + gaps
- `reports/profile.html` — the candidate profile

### On the deployed server
nginx serves `./reports/` at the VM's public IP (landing on `history.html`);
the hello smoke-test page is at `/hello`. See [deployment](#deploy) below.

---

## Deploy

Deployment is automated: pushing to `main` runs the tests, then rsyncs the repo
to the Azure VM and rebuilds the stack (see
[.github/workflows/deploy.yml](../.github/workflows/deploy.yml)).
```bash
git push origin main        # triggers test + deploy
```
The deploy can also be run manually from the Actions tab (`workflow_dispatch`).

To force a report refresh on the server after a deploy (without waiting for the
next scheduled pipeline run), SSH to the VM and run the re-render one-off:
```bash
cd /opt/job-market-scout
docker compose -f docker-compose.yaml -f docker-compose.prod.yaml \
  run --rm app python -m scout.rerender
```
