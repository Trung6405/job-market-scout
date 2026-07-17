# Listings Database Design

Date: 2026-07-17
Status: Approved

## Context

`job-market-scout` is a multi-agent job search pipeline (Scraper → Tracker → Scorer → Briefing) built on Google ADK, LiteLLM, and DeepSeek, deployed via Docker. Per the PRS (`docs/requirements/product-requirements-spec.md`), PostgreSQL is used only by the Tracker stage (single writer, Decision D2) to persist every scraped listing and track its lifecycle (new / changed / closed) via diffing against prior runs (FR-3 through FR-6). Match scores are explicitly **not** persisted in this version (Decision D4) — that's deferred.

`scout/shared/db.py` and `scout/tools/tracker.py` currently exist as empty stub files; nothing has been implemented for storage yet. There is no DB driver in `requirements.txt` and no Postgres service in `docker-compose.yaml`.

This session designs the **Postgres schema and the Storage module** (`scout/shared/db.py`) that a future Tracker session will call. The Tracker's own diff/dedup **orchestration logic** (deciding what to do with each listing's classification, wiring it into the pipeline) is out of scope here — this session builds the primitives it will need.

## Goals

- A `listings` table that stores every scraped listing (FR-3) with enough state to classify each one as new, changed, or closed on a later run (FR-5), without persisting match scores (D4).
- A Storage module (`scout/shared/db.py`) exposing the minimal set of async functions a future Tracker needs: create a connection pool, apply the schema, upsert a single listing, and close stale listings.
- Idempotent schema application (no migration framework) appropriate for a single-table, single-user tool.
- A local Postgres service in `docker-compose.yaml` so the module is runnable and testable without an external DB.

## Out of Scope

- Tracker's diff/dedup orchestration (`scout/tools/tracker.py` stays a stub) — a future session decides how the pipeline calls `upsert_listing`/`close_stale_listings`, batches the work, and routes new/changed listings into pipeline state for the Scorer.
- The deferred `matches` table (score persistence) — explicitly out of scope per PRS Decision D4 and §8.
- Root pipeline wiring (`scout/agent.py` `SequentialAgent` stays empty).
- A migration framework (Alembic or similar) — schema changes for now are additive edits to one idempotent `schema.sql`.
- Multi-search-config scoping (e.g. running two independent search configs against the same DB) — `close_stale_listings` closes globally across all open listings not seen in a run, which is correct for this project's single search configuration.

## Architecture

```
scout/shared/
  db.py        — connection pool + query functions (asyncpg, raw SQL, no ORM)
  schema.sql   — idempotent DDL (CREATE TABLE/INDEX IF NOT EXISTS)

scout/config.py        — adds Settings.database_url (env: DATABASE_URL)
docker-compose.yaml     — adds a `postgres` service; `app` depends on it
requirements.txt        — adds asyncpg
```

A future Tracker (out of scope this session) will call `create_pool` once, `apply_schema` at startup, then for each scraped listing call `upsert_listing` to get its classification, and once per run call `close_stale_listings` with the full batch's keys.

## Components

### `scout/shared/schema.sql`

Idempotent DDL for one table, `listings`:

| column | type | notes |
|---|---|---|
| `id` | `BIGSERIAL PRIMARY KEY` | surrogate key |
| `source` | `TEXT NOT NULL` | e.g. `"linkedin"` |
| `external_id` | `TEXT NOT NULL` | provider's job id |
| `title`, `company`, `location`, `url`, `description` | `TEXT NOT NULL` | mirror `Listing` |
| `is_remote` | `BOOLEAN NOT NULL` | |
| `salary_min`, `salary_max` | `DOUBLE PRECISION` | nullable |
| `date_posted` | `TIMESTAMPTZ` | nullable |
| `scraped_at` | `TIMESTAMPTZ NOT NULL` | most recent scrape's timestamp |
| `content_hash` | `TEXT NOT NULL` | sha256 over `title`, `company`, `location`, `is_remote`, `description`, `salary_min`, `salary_max` — the fields that matter for "changed" detection |
| `status` | `TEXT NOT NULL DEFAULT 'open'` | `CHECK (status IN ('open', 'closed'))` |
| `first_seen_at` | `TIMESTAMPTZ NOT NULL DEFAULT now()` | set once, never updated |
| `last_seen_at` | `TIMESTAMPTZ NOT NULL DEFAULT now()` | bumped every time the listing appears in a scrape |
| `closed_at` | `TIMESTAMPTZ` | set when status flips to `closed` |

Constraints/indexes: `UNIQUE (source, external_id)` (the dedup key and `ON CONFLICT` target); an index on `status` to make "find all open listings" cheap.

**Lifecycle model — new/changed/unchanged/closed is derived, not a stored 4-valued enum.** The persisted `status` column only ever holds `open` or `closed`. Classification of a given upsert is computed by comparing the pre-existing row (if any) to the incoming listing:

- **new** — no row existed for `(source, external_id)` before this upsert.
- **changed** — a row existed; either its `content_hash` differs from the new one, or its `status` was `closed` (a reopened listing counts as changed).
- **unchanged** — a row existed, was `open`, and the hash matches — only `last_seen_at` is bumped.
- **closed** — a previously-`open` row whose `(source, external_id)` is absent from the current scrape batch.

This gives a future Tracker exactly the classification FR-5/FR-6 need (only new/changed listings go to the Scorer) without extra persisted state to keep in sync.

### `scout/shared/db.py`

- `async def create_pool(settings: Settings | None = None) -> asyncpg.Pool` — one pool per process; DSN from `settings.database_url`.
- `async def apply_schema(pool: asyncpg.Pool) -> None` — reads and executes `schema.sql`. Safe to call on every startup (all statements are `IF NOT EXISTS`).
- `async def upsert_listing(conn: asyncpg.Connection, listing: Listing) -> Literal["new", "changed", "unchanged"]` — one round trip: a CTE reads the existing row's `content_hash`/`status` and performs `INSERT ... ON CONFLICT (source, external_id) DO UPDATE` in the same statement; the function then classifies the result in Python by comparing old vs. new hash/status. Always sets `status = 'open'` and bumps `last_seen_at` on write.
- `async def close_stale_listings(conn: asyncpg.Connection, seen_keys: list[tuple[str, str]]) -> list[str]` — one bulk `UPDATE listings SET status = 'closed', closed_at = now() WHERE status = 'open' AND (source, external_id) NOT IN (<batch>)`, returning the `external_id`s it closed.

### `scout/config.py`

Add `database_url: str` to `Settings`, env var `DATABASE_URL`, default `postgresql://scout:scout@localhost:5433/scout` (see Amendments — host port 5433, not 5432), following the existing env-driven field pattern.

### `scout/.env.example`

Append `DATABASE_URL=postgresql://scout:scout@localhost:5433/scout`.

### `docker-compose.yaml`

Add a `postgres` service: `image: postgres:16-alpine`, `POSTGRES_USER=scout`, `POSTGRES_PASSWORD=scout`, `POSTGRES_DB=scout`, a named volume for data persistence, and a `pg_isready` healthcheck. Host port mapping is `5433:5432` (see Amendments). The `app` service adds `depends_on: postgres: condition: service_healthy` and a `DATABASE_URL` pointing at `postgres:5432` (container-to-container — unaffected by the host port remap, since containers talk to each other on the Docker network, not through the host port mapping).

### `requirements.txt`

Add `asyncpg`.

## Data Flow

1. (Future Tracker, out of scope) obtains a pool via `create_pool` and calls `apply_schema` once at startup.
2. For each listing in a scrape batch, the Tracker calls `upsert_listing`, which computes `content_hash`, upserts the row, and returns `"new"`, `"changed"`, or `"unchanged"`.
3. Once per run, the Tracker calls `close_stale_listings` with every `(source, external_id)` seen in the batch; any previously-open row not in that set is marked `closed`.
4. New/changed listings (from step 2's results) are what a future Tracker forwards to the Scorer via pipeline state (FR-6) — this routing logic itself is out of scope here.

## Error Handling

- `apply_schema` failing (unreachable Postgres, bad DSN) raises and fails fast at startup — no silent fallback, consistent with the existing "resume file missing → fail fast" convention in `scout/config.py`.
- `upsert_listing` / `close_stale_listings` do not catch or swallow errors — failures bubble up to the caller. Deciding an abort-vs-skip policy for a bad row is orchestration logic that belongs to the future Tracker session, not the Storage module.
- No retry/reconnect logic beyond what `asyncpg`'s connection pool already does — same YAGNI stance already used for the scraper and scorer ("add retry once a real failure mode is observed").

## Testing

- A new `postgres` service in `docker-compose.yaml` is what local dev and tests use — no `testcontainers` or mocked connection layer.
- `tests/test_db.py`: integration tests against a real Postgres via `DATABASE_URL`, skipped automatically if unreachable/unset (mirrors the scorer plan's "manual verification, needs a live DeepSeek key" pattern for tests that need a live external dependency).
- Coverage: `apply_schema` is idempotent (running twice doesn't error); insert-new returns `"new"`; re-upsert with unchanged content returns `"unchanged"`; re-upsert with changed content returns `"changed"` and the stored row's fields actually update; `close_stale_listings` closes the right rows and leaves seen rows open; a closed listing that reappears in a later batch returns `"changed"` (reopened), not `"new"` or silently skipped.
- Each test truncates the table (or runs inside a rolled-back transaction) so tests don't leak state into each other.

## Open Questions / Follow-ups

- Tracker orchestration (how/when `upsert_listing` and `close_stale_listings` get called, batching strategy, and how new/changed listings reach the Scorer via pipeline state) is a future session's design, building directly on this Storage module.
- The deferred `matches` table (score persistence, correlated via a `config_version` hash per PRS §8) is not designed here; when that session happens, it will need its own idempotent addition to `schema.sql`.
- `close_stale_listings`' global-close behavior assumes one search configuration; if the project ever runs multiple independent search configs against the same DB, closing would need to be scoped — not needed now (YAGNI).

## Amendments

- 2026-07-17: Changed the `postgres` service's host port mapping from `5432:5432` to `5433:5432`, and `Settings.database_url`'s default host port from 5432 to 5433, discovered during implementation: a pre-existing native PostgreSQL service on the development machine already binds host port 5432, making the Docker container unreachable from the host on that port. Container-to-container traffic (the `app` service's `DATABASE_URL`, pointing at `postgres:5432`) is unaffected — that's Docker-internal networking, not the host port mapping.
