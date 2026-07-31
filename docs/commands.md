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
- Builds the `app`, `jobspy-scraper`, and `jobspy-mcp` images and pulls the
  `postgres` (pgvector) image.
- Applies the Postgres schema automatically on first run.
- All `docker compose` commands require `scout/.env` to exist (see the setup
  section in the top-level `README.md`) — compose loads it via `env_file`.
- Writes HTML into `./reports/` and posts matches above `MIN_MATCH_SCORE`
  to Discord.

Run the pipeline once without rebuilding images:
```bash
docker compose up
```

Run the pipeline directly on the host (needs `postgres` reachable at the
`DATABASE_URL`, default `localhost:5433`, and `jobspy-mcp` running). The
default `JOBSPY_MCP_URL` points at the compose-internal hostname, so override
it with the published port:
```bash
JOBSPY_MCP_URL=http://localhost:9423 python -m scout.main
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

### Career Coach jobs (aggregator, link-health)
The scheduled run wires these in automatically (aggregator weekly, link-health
daily); run either manually against the compose stack:
```bash
docker compose -f docker-compose.yaml -f docker-compose.prod.yaml \
  run --rm app python -m scout.coach_aggregator

docker compose -f docker-compose.yaml -f docker-compose.prod.yaml \
  run --rm app python -m scout.coach_link_health
```
Read-only audits, safe to run against production at any time — they never
issue a check or write a row:
```bash
# link-health distribution of the resource corpus
docker compose -f docker-compose.yaml -f docker-compose.prod.yaml \
  run --rm app python -m scripts.audit_link_health

# citations actually rendered into the reports (companion to the above)
docker compose -f docker-compose.yaml -f docker-compose.prod.yaml \
  run --rm app python -m scripts.audit_rendered_citations
```

### Maintenance one-offs
Recompute every stored `content_hash` after a change to the hash definition,
so the next run doesn't re-analyse the whole table (idempotent, safe to
re-run):
```bash
python -m scout.backfill_hashes
```
Other one-off migration scripts live in `scripts/` (each documents its own
usage in its docstring); they have already been run against production and are
kept for reference.

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
pytest -m "not db"                          # skip DB-backed tests (no Postgres needed)
pytest -m db                                # only the DB-backed tests
```

If Postgres is unreachable, the DB-backed tests **skip** (they don't fail) —
but `-m "not db"` is faster, since it deselects them instead of waiting out a
connection timeout in each one.

Lint and type-check (same commands CI runs before every deploy):
```bash
pip install -r requirements-dev.txt
ruff check scout scripts tests
mypy
```

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
Or serve the directory (avoids `file://` quirks):
```bash
python -m http.server 8080 --directory reports
```
- `reports/history.html` — all past days
- `reports/<YYYY-MM-DD>/dashboard.html` — a day's scored listings
- `reports/<YYYY-MM-DD>/job-detail-<id>.html` — one role's detail + gaps
- `reports/profile.html` — the candidate profile

### On the deployed server
The dashboard is published to an Azure Storage static website after each run,
landing on `history.html` (see the Live dashboard links in the top-level
`README.md`, and [deployment](#deploy) below).

---

## Deploy

Deployment is automated: pushing to `main` runs the tests, then rsyncs the repo
to the Azure VM and rebuilds the stack (see
[.github/workflows/deploy.yml](../.github/workflows/deploy.yml)).
```bash
git push origin main        # triggers test + deploy
```
The deploy can also be run manually from the Actions tab (`workflow_dispatch`);
on a branch other than `main` a manual dispatch runs the tests only.

Related workflows, both in `.github/workflows/`:
- [scheduled-run.yml](../.github/workflows/scheduled-run.yml) — the daily
  pipeline run on the VM; it also publishes the rendered reports to the Azure
  Storage static website (the live dashboard).
- [infra-provision.yml](../.github/workflows/infra-provision.yml) — manual
  (`workflow_dispatch`) provisioning of the Azure infra from `infra/*.bicep`.

To force a refresh of the live dashboard after a deploy (without waiting for
the next scheduled run), manually dispatch **Scheduled run** from the Actions
tab — publishing happens from that workflow, not from the VM. Running
`scout.rerender` on the VM only rewrites the VM's local `./reports` and does
not update the live dashboard.
