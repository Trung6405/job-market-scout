# Phase 1: Schema, extension & image

> **Parent plan:** [plan.md](plan.md)
> **Status:** Complete
> **Depends on:** nothing (this is P0, the foundation)

---

## Goal

Add the `vector` extension and an empty `resources` table to the shared schema,
on a Postgres image that carries pgvector, so a 384-dim embedding round-trips and
no existing test regresses.

## Safety Checklist

- **Touches user input, auth, secrets, or external calls?**
  No — DDL and a container image tag only.
- **Contains a one-way door (schema, public API shape, new dependency)?**
  Schema + image change, but **not** a one-way door: the DDL is additive and
  idempotent (`CREATE … IF NOT EXISTS`), and the image swap keeps the identical
  PG16 on-disk format so the data volume mounts unchanged and the swap is
  reversible. No human-sign-off gate required. (The irreversible infra
  commitment lives in a different phase, P6.)

---

## Pre-execution (docs commit)

Per the repo's doc-gating rule, the approved docs are committed **once, right
before this phase's code changes** — not earlier:

- [x] Commit the approved planning docs:

```bash
git add docs/project/specification/career-coach-agent-prs.md \
        docs/agent/specs/career-coach-p0-schema/spec.md \
        docs/agent/plans/career-coach-p0-schema/plan.md \
        docs/agent/plans/career-coach-p0-schema/phase-1-schema-and-image.md
git commit -m "docs: Career Coach PRS v1.1 + P0 schema spec & plan

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Tasks

### Task 1: `resources` table + `vector` extension on a pgvector image

- **Files:**
  - Create: `tests/test_resources_schema.py`
  - Modify: `scout/shared/schema.sql` (append extension + table)
  - Modify: `docker-compose.yaml` (postgres `image:`)
  - Modify: `.github/workflows/deploy.yml:28` (postgres service `image:`)
  - Modify: `tests/conftest.py` (add `resources` to the `TRUNCATE`)
- **Gate:** none.
- **Interfaces:**
  - Consumes: the existing `db_pool` fixture (`tests/conftest.py`) and
    `apply_schema` (`scout/shared/db.py`) — both unchanged in signature.
  - Produces: a `resources` relation with columns
    `id BIGSERIAL, url TEXT UNIQUE, title TEXT, resource_type TEXT,
    skills TEXT[], level TEXT, summary TEXT, embedding VECTOR(384),
    source TEXT, last_verified TIMESTAMPTZ, created_at TIMESTAMPTZ`.
    Later phases (P1 writer, P2 reader) rely on exactly these names/types.

- [x] **Step 1: Write the failing test**

Create `tests/test_resources_schema.py`:

```python
from __future__ import annotations

import asyncpg
import pytest


@pytest.mark.asyncio
async def test_vector_extension_installed(db_pool):
    async with db_pool.acquire() as conn:
        installed = await conn.fetchval(
            "SELECT 1 FROM pg_extension WHERE extname = 'vector'"
        )
    assert installed == 1


@pytest.mark.asyncio
async def test_resources_table_exists(db_pool):
    async with db_pool.acquire() as conn:
        relname = await conn.fetchval("SELECT to_regclass('public.resources')")
    assert relname == "resources"


@pytest.mark.asyncio
async def test_resources_embedding_roundtrips(db_pool):
    # pgvector accepts a bracketed, comma-separated text form cast to ::vector.
    embedding = "[" + ",".join("0.1" for _ in range(384)) + "]"
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO resources (url, title, resource_type, skills, source, embedding)
            VALUES ($1, $2, $3, $4, $5, $6::vector)
            """,
            "https://example.com/repo",
            "Example Repo",
            "repo",
            ["python", "fastapi"],
            "test",
            embedding,
        )
        stored = await conn.fetchval(
            "SELECT embedding::text FROM resources WHERE url = $1",
            "https://example.com/repo",
        )
    assert stored is not None
    # 384 components → 383 separating commas in pgvector's text output.
    assert stored.count(",") == 383


@pytest.mark.asyncio
async def test_resources_url_is_unique(db_pool):
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO resources (url, title, resource_type, skills, source) "
            "VALUES ($1, $2, $3, $4, $5)",
            "https://example.com/dup", "One", "repo", ["python"], "test",
        )
        with pytest.raises(asyncpg.UniqueViolationError):
            await conn.execute(
                "INSERT INTO resources (url, title, resource_type, skills, source) "
                "VALUES ($1, $2, $3, $4, $5)",
                "https://example.com/dup", "Two", "repo", ["go"], "test",
            )
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_resources_schema.py -v`
Expected: FAIL (4 failed) — `test_resources_table_exists` sees `None` (no
`resources` relation), `test_vector_extension_installed` finds no `vector`
extension, and both `test_resources_embedding_roundtrips` and
`test_resources_url_is_unique` error with `UndefinedTableError: relation
"resources" does not exist`. (If Postgres is unreachable the tests `skip`
instead — start the stack first: `docker compose up -d postgres`.)

- [x] **Step 3: Write minimal implementation**

**3a.** Append to the end of `scout/shared/schema.sql`:

```sql

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS resources (
    id BIGSERIAL PRIMARY KEY,
    url TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    resource_type TEXT NOT NULL
        CHECK (resource_type IN ('doc', 'course', 'repo', 'note')),
    skills TEXT[] NOT NULL,
    level TEXT CHECK (level IN ('beginner', 'intermediate', 'advanced')),
    summary TEXT,
    embedding VECTOR(384),
    source TEXT NOT NULL,
    last_verified TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

**3b.** In `docker-compose.yaml`, change the `postgres` service image:

```yaml
  postgres:
    image: pgvector/pgvector:pg16
```

**3c.** In `.github/workflows/deploy.yml` (the `test` job's `postgres`
service, line 28), change:

```yaml
      postgres:
        image: pgvector/pgvector:pg16
```

**3d.** In `tests/conftest.py`, add `resources` to the reset in the `db_pool`
fixture:

```python
        await conn.execute(
            "TRUNCATE TABLE run_listings, runs, listings, resources CASCADE"
        )
```

**3e.** Recreate the local Postgres container so it actually carries pgvector:

```bash
docker compose up -d --force-recreate postgres
```

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_resources_schema.py -v`
Expected: PASS (4 passed).

Then the regression gate — the whole suite on the new image:

Run: `pytest`
Expected: PASS (no existing DB test regresses; the image swap is transparent).

- [x] **Step 5: Commit**

```bash
git add tests/test_resources_schema.py tests/conftest.py \
        scout/shared/schema.sql docker-compose.yaml \
        .github/workflows/deploy.yml
git commit -m "feat(db): add resources table and pgvector extension (P0)

Move Postgres to pgvector/pgvector:pg16 (local + CI) and add an empty
resources table with a VECTOR(384) embedding column via the existing
idempotent schema.sql. Foundation for Career Coach retrieval; no reader
or writer yet.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Verification

- [x] `pytest tests/test_resources_schema.py -v` → 4 passed.
- [x] `pytest` → full suite green on `pgvector/pgvector:pg16` (247 passed).
- [x] Manual: `docker compose exec postgres psql -U scout -d scout -c "\dx vector"`
  lists the `vector` extension, and `\d resources` shows the columns above.

## Rollback

Revert the five edited files (`git revert` the feat commit) and recreate the
container on the old image: set `docker-compose.yaml` / `deploy.yml` back to
`postgres:16-alpine` and run `docker compose up -d --force-recreate postgres`.
The `resources` table and `vector` extension are inert and may be left or
dropped (`DROP TABLE resources; DROP EXTENSION vector;`). No data to migrate.
State-level notes (musl↔glibc collation) are in `plan.md` → Rollout &
Reversibility.

---

## Notes / Learnings

- The dev `scout` database only gets `apply_schema` run against it when the
  pipeline actually runs — it was never initialized in this session, so the
  first manual verification attempt (`psql -c "\dx vector"`) correctly showed
  nothing installed. Applying `scout/shared/schema.sql` directly (same as CI's
  "Load DB schema" step) confirmed the extension (`vector` 0.8.5) and the
  `resources` table shape, and reconfirmed the pre-existing DDL is still
  idempotent.
- One run of `test_resources_embedding_roundtrips` alone (in a small,
  filtered `pytest` invocation) was reported `SKIPPED — Postgres unreachable`,
  but passed both in isolation and in the full 247-test suite run immediately
  after. Consistent with a transient pool-creation race in the shared
  `db_pool` fixture (`tests/conftest.py`, 2s connection timeout under
  contention) — pre-existing test-infra behavior, not caused by this phase's
  changes, and not reproduced on the full-suite regression run.
