# Phase 1: Storage Module

> **Parent plan:** [plan.md](plan.md)
> **Status:** Complete
> **Depends on:** nothing

---

## Goal

Implement the Postgres schema and `scout/shared/db.py` primitives
(`create_pool`, `apply_schema`, `upsert_listing`, `close_stale_listings`)
per `docs/agent/specs/listings-db/spec.md`, wired up with a local `postgres`
Docker service, `DATABASE_URL` config, and `asyncpg`/`pytest-asyncio`
dependencies. We'll know it worked when `tests/test_db.py` passes against
a locally running Postgres and `apply_schema` is safe to call twice.

## Safety Checklist

- **Touches user input, auth, secrets, or external calls?** Yes — connects
  to a Postgres database via `DATABASE_URL`. Connection failures raise
  (fail-fast), no silent fallback, per the spec.
- **Contains a one-way door (schema, public API shape, new dependency)?**
  New dependencies (`asyncpg`, `pytest-asyncio`) and a new `listings` table
  schema — but the schema is additive/idempotent DDL with no existing data
  or consumers, so it's not a one-way door. No gate required.

---

## Tasks

### Task 1: `database_url` config + dependencies

- **Files:** `scout/config.py`, `scout/.env.example`, `requirements.txt`, `pytest.ini` (new), `tests/test_config.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing test in `tests/test_config.py` (append to the file):
    ```python
    def test_settings_uses_database_url_default_when_env_unset(monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)

        settings = Settings()

        assert settings.database_url == "postgresql://scout:scout@localhost:5433/scout"


    def test_settings_reads_database_url_env_override(monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost:5433/test")

        settings = Settings()

        assert settings.database_url == "postgresql://test:test@localhost:5433/test"
    ```
  - [ ] Verify it fails (`python -m pytest tests/test_config.py -k database_url -v`)
    Expected: FAIL with `AttributeError: 'Settings' object has no attribute 'database_url'` (or similar dataclass field error).
  - [ ] Add the field to `scout/config.py`. Insert this into the `Settings` dataclass body, after the `description_char_limit` field (before `resume_text: str = field(init=False)`):
    ```python
        database_url: str = field(
            default_factory=lambda: os.getenv(
                "DATABASE_URL", "postgresql://scout:scout@localhost:5433/scout"
            )
        )
    ```
    (Host port 5433, not Postgres's usual 5432 — see plan Amendments / `docs/agent/specs/listings-db/spec.md` Amendments: a native Postgres service on the dev machine already owns 5432.)
  - [ ] Append to `scout/.env.example` (new line at end of file):
    ```
    DATABASE_URL=postgresql://scout:scout@localhost:5433/scout
    ```
  - [ ] Verify the config tests pass (`python -m pytest tests/test_config.py -v`)
    Expected: PASS, all tests including the two new ones.
  - [ ] Install `asyncpg` and `pytest-asyncio`, then pin the resolved versions:
    ```bash
    pip install asyncpg pytest-asyncio
    pip freeze | grep -iE "^(asyncpg|pytest-asyncio)=="
    ```
    Append the two resulting lines (e.g. `asyncpg==0.30.0`, `pytest-asyncio==0.24.0` — use whatever `pip freeze` actually printed) to `requirements.txt`, keeping the file's existing alphabetical order.
  - [ ] Create `pytest.ini` at the repo root:
    ```ini
    [pytest]
    asyncio_mode = auto
    ```
  - [ ] Commit:
    ```bash
    git add scout/config.py scout/.env.example requirements.txt pytest.ini tests/test_config.py
    git commit -m "feat(config): add DATABASE_URL setting and async test infra"
    ```

### Task 2: `postgres` docker-compose service + schema.sql + `create_pool`/`apply_schema`

- **Files:** `docker-compose.yaml`, `scout/shared/schema.sql` (new), `scout/shared/db.py`, `tests/conftest.py` (new), `tests/test_db.py` (new)
- **Gate:** none
- **Steps:**
  - [ ] Add a `postgres` service to `docker-compose.yaml`. Insert this as a new top-level service (alongside `app`, `jobspy-scraper`, `jobspy-mcp`):
    ```yaml
      postgres:
        image: postgres:16-alpine
        environment:
          POSTGRES_USER: scout
          POSTGRES_PASSWORD: scout
          POSTGRES_DB: scout
        volumes:
          - postgres-data:/var/lib/postgresql/data
        healthcheck:
          test: ["CMD-SHELL", "pg_isready -U scout"]
          interval: 5s
          timeout: 5s
          retries: 5
        ports:
          - "5433:5432"
    ```
    (Host port 5433, container port 5432 — a native Postgres service on the dev machine already owns host port 5432; see plan Amendments. Container-to-container traffic below still uses `postgres:5432`, unaffected.)
    And update the `app` service to depend on it — replace:
    ```yaml
        depends_on:
          - jobspy-mcp
    ```
    with:
    ```yaml
        depends_on:
          jobspy-mcp:
            condition: service_started
          postgres:
            condition: service_healthy
        environment:
          JOBSPY_MCP_URL: http://jobspy-mcp:9423
          DATABASE_URL: postgresql://scout:scout@postgres:5432/scout
    ```
    (merge the new `DATABASE_URL` line into the existing `environment:` block under `app` rather than duplicating the key).
    Finally add a top-level `volumes:` section at the end of the file:
    ```yaml
    volumes:
      postgres-data:
    ```
  - [ ] Start Postgres locally: `docker compose up -d postgres` and wait for it to become healthy (`docker compose ps`).
  - [ ] Write `scout/shared/schema.sql`:
    ```sql
    CREATE TABLE IF NOT EXISTS listings (
        id BIGSERIAL PRIMARY KEY,
        source TEXT NOT NULL,
        external_id TEXT NOT NULL,
        title TEXT NOT NULL,
        company TEXT NOT NULL,
        location TEXT NOT NULL,
        url TEXT NOT NULL,
        description TEXT NOT NULL,
        is_remote BOOLEAN NOT NULL,
        salary_min DOUBLE PRECISION,
        salary_max DOUBLE PRECISION,
        date_posted TIMESTAMPTZ,
        scraped_at TIMESTAMPTZ NOT NULL,
        content_hash TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
        first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        closed_at TIMESTAMPTZ,
        UNIQUE (source, external_id)
    );

    CREATE INDEX IF NOT EXISTS idx_listings_status ON listings (status);
    ```
  - [ ] Write `tests/conftest.py`:
    ```python
    from __future__ import annotations

    import asyncpg
    import pytest
    import pytest_asyncio

    from scout.shared.db import apply_schema


    @pytest_asyncio.fixture
    async def db_pool():
        try:
            pool = await asyncpg.create_pool(
                dsn="postgresql://scout:scout@localhost:5433/scout", timeout=2
            )
        except (OSError, asyncpg.PostgresError) as exc:
            pytest.skip(f"Postgres unreachable: {exc}")
        await apply_schema(pool)
        async with pool.acquire() as conn:
            await conn.execute("TRUNCATE TABLE listings")
        yield pool
        await pool.close()
    ```
  - [ ] Write the failing test in `tests/test_db.py`:
    ```python
    from __future__ import annotations

    import pytest

    from scout.shared.db import apply_schema


    @pytest.mark.asyncio
    async def test_apply_schema_is_idempotent(db_pool):
        await apply_schema(db_pool)
        await apply_schema(db_pool)

        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT to_regclass('public.listings') AS table_name"
            )
        assert row["table_name"] == "listings"
    ```
  - [ ] Verify it fails (`python -m pytest tests/test_db.py -v`)
    Expected: FAIL with `ImportError: cannot import name 'apply_schema' from 'scout.shared.db'` (the file is currently empty).
  - [ ] Implement `create_pool` and `apply_schema` in `scout/shared/db.py`:
    ```python
    from __future__ import annotations

    from pathlib import Path

    import asyncpg

    from scout.config import Settings
    from scout.config import settings as default_settings

    _SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


    async def create_pool(settings: Settings | None = None) -> asyncpg.Pool:
        active_settings = settings or default_settings
        return await asyncpg.create_pool(dsn=active_settings.database_url)


    async def apply_schema(pool: asyncpg.Pool) -> None:
        schema_sql = _SCHEMA_PATH.read_text(encoding="utf-8")
        async with pool.acquire() as conn:
            await conn.execute(schema_sql)
    ```
  - [ ] Verify it passes (`python -m pytest tests/test_db.py -v`)
    Expected: PASS. If Postgres isn't running, expect a `SKIPPED` result (not a failure) — start it with `docker compose up -d postgres` first to actually exercise the test.
  - [ ] Commit:
    ```bash
    git add docker-compose.yaml scout/shared/schema.sql scout/shared/db.py tests/conftest.py tests/test_db.py
    git commit -m "feat(db): add postgres service, listings schema, create_pool/apply_schema"
    ```

### Task 3: `upsert_listing` classification

- **Files:** `scout/shared/db.py`, `tests/test_db.py`
- **Gate:** none
- **Interfaces:**
  - Consumes: `Listing` from `scout.shared.schemas` (fields: `source`, `external_id`, `title`, `company`, `location`, `is_remote`, `url: HttpUrl`, `description`, `salary_min: float | None`, `salary_max: float | None`, `date_posted: datetime | None`, `scraped_at: datetime`).
  - Produces: `async def upsert_listing(conn: asyncpg.Connection, listing: Listing) -> Literal["new", "changed", "unchanged"]` — used by Phase 2's `track_listings`.
- **Steps:**
  - [ ] Add a shared test helper at the top of `tests/test_db.py` (after the existing imports):
    ```python
    from datetime import datetime, timezone

    from scout.shared.schemas import Listing


    def _make_listing(**overrides) -> Listing:
        defaults = dict(
            source="linkedin",
            external_id="job-1",
            title="Backend Engineer",
            company="Acme",
            location="Remote",
            is_remote=True,
            url="https://example.com/jobs/1",
            description="Build things.",
            salary_min=100000.0,
            salary_max=150000.0,
            date_posted=datetime(2026, 7, 1, tzinfo=timezone.utc),
            scraped_at=datetime(2026, 7, 17, tzinfo=timezone.utc),
        )
        defaults.update(overrides)
        return Listing(**defaults)
    ```
  - [ ] Write the failing tests, appended to `tests/test_db.py`:
    ```python
    @pytest.mark.asyncio
    async def test_upsert_listing_new_returns_new(db_pool):
        async with db_pool.acquire() as conn:
            classification = await upsert_listing(conn, _make_listing())

        assert classification == "new"


    @pytest.mark.asyncio
    async def test_upsert_listing_unchanged_returns_unchanged(db_pool):
        listing = _make_listing()
        async with db_pool.acquire() as conn:
            await upsert_listing(conn, listing)
            classification = await upsert_listing(conn, listing)

        assert classification == "unchanged"


    @pytest.mark.asyncio
    async def test_upsert_listing_changed_returns_changed_and_updates_row(db_pool):
        listing = _make_listing()
        changed = _make_listing(title="Senior Backend Engineer")
        async with db_pool.acquire() as conn:
            await upsert_listing(conn, listing)
            classification = await upsert_listing(conn, changed)
            row = await conn.fetchrow(
                "SELECT title FROM listings WHERE source = $1 AND external_id = $2",
                listing.source,
                listing.external_id,
            )

        assert classification == "changed"
        assert row["title"] == "Senior Backend Engineer"


    @pytest.mark.asyncio
    async def test_upsert_listing_reopened_closed_listing_returns_changed(db_pool):
        listing = _make_listing()
        async with db_pool.acquire() as conn:
            await upsert_listing(conn, listing)
            await conn.execute(
                "UPDATE listings SET status = 'closed' WHERE source = $1 AND external_id = $2",
                listing.source,
                listing.external_id,
            )
            classification = await upsert_listing(conn, listing)

        assert classification == "changed"
    ```
  - [ ] Add the two new imports at the top of `tests/test_db.py`:
    ```python
    from scout.shared.db import apply_schema, upsert_listing
    ```
    (replace the earlier single-name `from scout.shared.db import apply_schema` import with this combined line)
  - [ ] Verify it fails (`python -m pytest tests/test_db.py -v`)
    Expected: FAIL with `ImportError: cannot import name 'upsert_listing'`.
  - [ ] Implement `upsert_listing` in `scout/shared/db.py`. Add these imports at the top (merge with existing):
    ```python
    import hashlib
    from typing import Literal
    ```
    Then append the function:
    ```python
    def _content_hash(listing) -> str:
        payload = "|".join(
            [
                listing.title,
                listing.company,
                listing.location,
                str(listing.is_remote),
                listing.description,
                str(listing.salary_min),
                str(listing.salary_max),
            ]
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


    async def upsert_listing(
        conn: asyncpg.Connection, listing
    ) -> Literal["new", "changed", "unchanged"]:
        content_hash = _content_hash(listing)
        row = await conn.fetchrow(
            """
            WITH previous AS (
                SELECT content_hash, status
                FROM listings
                WHERE source = $1 AND external_id = $2
            ), upserted AS (
                INSERT INTO listings (
                    source, external_id, title, company, location, url,
                    description, is_remote, salary_min, salary_max,
                    date_posted, scraped_at, content_hash, status, last_seen_at
                )
                VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13,
                    'open', now()
                )
                ON CONFLICT (source, external_id) DO UPDATE SET
                    title = EXCLUDED.title,
                    company = EXCLUDED.company,
                    location = EXCLUDED.location,
                    url = EXCLUDED.url,
                    description = EXCLUDED.description,
                    is_remote = EXCLUDED.is_remote,
                    salary_min = EXCLUDED.salary_min,
                    salary_max = EXCLUDED.salary_max,
                    date_posted = EXCLUDED.date_posted,
                    scraped_at = EXCLUDED.scraped_at,
                    content_hash = EXCLUDED.content_hash,
                    status = 'open',
                    last_seen_at = now()
                RETURNING id
            )
            SELECT content_hash AS previous_hash, status AS previous_status
            FROM previous
            """,
            listing.source,
            listing.external_id,
            listing.title,
            listing.company,
            listing.location,
            str(listing.url),
            listing.description,
            listing.is_remote,
            listing.salary_min,
            listing.salary_max,
            listing.date_posted,
            listing.scraped_at,
            content_hash,
        )
        if row is None:
            return "new"
        if row["previous_status"] == "closed" or row["previous_hash"] != content_hash:
            return "changed"
        return "unchanged"
    ```
  - [ ] Verify it passes (`python -m pytest tests/test_db.py -v`)
    Expected: PASS (5 tests: idempotent schema + 4 classification tests).
  - [ ] Commit:
    ```bash
    git add scout/shared/db.py tests/test_db.py
    git commit -m "feat(db): implement upsert_listing classification"
    ```

### Task 4: `close_stale_listings`

- **Files:** `scout/shared/db.py`, `tests/test_db.py`
- **Gate:** none
- **Interfaces:**
  - Produces: `async def close_stale_listings(conn: asyncpg.Connection, seen_keys: list[tuple[str, str]]) -> list[str]` — used by Phase 2's `track_listings`.
- **Steps:**
  - [ ] Write the failing tests, appended to `tests/test_db.py`:
    ```python
    @pytest.mark.asyncio
    async def test_close_stale_listings_closes_unseen_and_keeps_seen_open(db_pool):
        seen = _make_listing(source="linkedin", external_id="job-seen")
        stale = _make_listing(source="linkedin", external_id="job-stale")
        async with db_pool.acquire() as conn:
            await upsert_listing(conn, seen)
            await upsert_listing(conn, stale)

            closed_ids = await close_stale_listings(conn, [(seen.source, seen.external_id)])

            seen_row = await conn.fetchrow(
                "SELECT status FROM listings WHERE external_id = $1", seen.external_id
            )
            stale_row = await conn.fetchrow(
                "SELECT status, closed_at FROM listings WHERE external_id = $1",
                stale.external_id,
            )

        assert closed_ids == ["job-stale"]
        assert seen_row["status"] == "open"
        assert stale_row["status"] == "closed"
        assert stale_row["closed_at"] is not None
    ```
  - [ ] Add `close_stale_listings` to the `tests/test_db.py` import line:
    ```python
    from scout.shared.db import apply_schema, close_stale_listings, upsert_listing
    ```
  - [ ] Verify it fails (`python -m pytest tests/test_db.py -v`)
    Expected: FAIL with `ImportError: cannot import name 'close_stale_listings'`.
  - [ ] Implement `close_stale_listings` in `scout/shared/db.py`:
    ```python
    async def close_stale_listings(
        conn: asyncpg.Connection, seen_keys: list[tuple[str, str]]
    ) -> list[str]:
        if not seen_keys:
            rows = await conn.fetch(
                """
                UPDATE listings
                SET status = 'closed', closed_at = now()
                WHERE status = 'open'
                RETURNING external_id
                """
            )
        else:
            sources = [key[0] for key in seen_keys]
            external_ids = [key[1] for key in seen_keys]
            rows = await conn.fetch(
                """
                UPDATE listings
                SET status = 'closed', closed_at = now()
                WHERE status = 'open'
                  AND NOT (source, external_id) IN (
                      SELECT * FROM unnest($1::text[], $2::text[])
                  )
                RETURNING external_id
                """,
                sources,
                external_ids,
            )
        return [row["external_id"] for row in rows]
    ```
  - [ ] Verify it passes (`python -m pytest tests/test_db.py -v`)
    Expected: PASS (6 tests total).
  - [ ] Commit:
    ```bash
    git add scout/shared/db.py tests/test_db.py
    git commit -m "feat(db): implement close_stale_listings"
    ```

---

## Verification

- [ ] All phase tests pass: `docker compose up -d postgres && python -m pytest tests/test_db.py tests/test_config.py -v`
- [ ] Manual check: run `python -m pytest tests/test_db.py -v` with Postgres stopped (`docker compose stop postgres`) and confirm tests report `SKIPPED`, not `FAILED` or `ERROR`.

## Rollback

Revert the phase's commits. `docker-compose.yaml`'s `postgres` service and
`scout/shared/schema.sql` are inert until something applies the schema and
writes to it — no running system depends on this code yet.

---

## Notes / Learnings

<Filled in during execution — anything that should inform Phase 2.>
