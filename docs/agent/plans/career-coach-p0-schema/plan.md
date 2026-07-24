# Plan: Career Coach P0 — Schema & pgvector Foundation

> **Status:** Not started
> **Created:** 2026-07-24 · **Last updated:** 2026-07-24
> **Spec:** [spec.md](../../specs/career-coach-p0-schema/spec.md)

---

## Overview

Make the database able to store learning resources and their 384-dim
embeddings, so every later Career Coach phase has a corpus to write to and query.
Concretely: move Postgres onto a pgvector-capable image and add a `resources`
table plus the `vector` extension through the existing idempotent `schema.sql`.
"Done" means the schema applies cleanly on the new image, a `resources` row with
a `vector(384)` embedding round-trips, and every pre-existing database test still
passes.

## Acceptance Criteria

- [ ] `CREATE EXTENSION IF NOT EXISTS vector` and a `resources` table exist in
  `scout/shared/schema.sql`, applied via the unchanged `apply_schema` path.
- [ ] The local (`docker-compose.yaml`) and CI (`.github/workflows/deploy.yml`)
  Postgres both run `pgvector/pgvector:pg16`.
- [ ] A test inserts a `resources` row with a 384-dim embedding and reads it
  back, and asserts the `vector` extension is installed and the `resources`
  relation exists.
- [ ] `pytest` passes in full against the new image (no regression in existing
  DB-backed tests).

---

## Risks & Unknowns

| Risk / unknown | Impact if wrong | Resolution |
|----------------|-----------------|------------|
| Prod's existing `postgres-data` volume was created under `postgres:16-alpine` (musl); mounting it under `pgvector/pgvector:pg16` (debian/glibc) | musl↔glibc collation ordering differences could, in principle, make an existing text B-tree index mis-ordered | **Accepted risk.** The on-disk format is identical PG16 (same major, no dump/restore, no data loss); the only text indexes here are trivial (`idx_listings_status` over an enum-like value). Resolution if any index anomaly appears in prod: `REINDEX DATABASE scout`. Called out again in the phase Rollback. |
| `CREATE EXTENSION vector` requires privilege | Schema application fails everywhere (breaks every DB test + the pipeline) | Not an unknown in practice: the official image creates `POSTGRES_USER=scout` as a superuser, and CI applies the schema as `scout`; `CREATE EXTENSION` succeeds. Verified by the round-trip test itself (Task 1). |
| Coupling: adding `CREATE EXTENSION` to `schema.sql` before the image carries pgvector | Every `db_pool`-backed test errors, not just the new one | Sequenced deliberately: the failing test is verified to fail on *missing table* with the schema untouched, then image + DDL land together in one implementation step and one commit (see phase doc). |

> No spike task needed — the schema shape and mechanism are fully determined by
> the spec; the round-trip test is itself the verification of the extension/image.

## Blast Radius

- **Code that will change:** `scout/shared/schema.sql`, `docker-compose.yaml`,
  `.github/workflows/deploy.yml`, `tests/conftest.py`, and one new test file
  under `tests/`.
- **Existing behaviour that could break:** every database-backed test (all go
  through the `db_pool` fixture → `apply_schema`); the pipeline's own
  `apply_schema` call in `scout/sub_agents/tracker/runner.py`; the prod/dev
  Postgres container identity (recreated on a new image).
- **Off-limits:** no changes to `scout/shared/db.py` query functions, no
  `Resource` model in `scout/shared/schemas.py`, no aggregator/retriever code —
  those belong to P1/P2. Do not touch anything outside the files above without
  flagging it.

---

## Phases

| # | Phase | Document | Status |
|---|-------|----------|--------|
| 1 | Schema, extension & image | [phase-1-schema-and-image.md](phase-1-schema-and-image.md) | Not started |

> P0 is a single small phase; this plan has one phase doc holding its task-level
> detail. Later Career Coach phases (P1–P7) are separate spec+plan pairs, not
> phases of this plan.

---

## Testing Strategy

- **Unit:** none — there is no application logic in P0, only DDL.
- **Integration:** one new pytest module (`tests/test_resources_schema.py`) runs
  against a live Postgres via the existing `db_pool` fixture: it asserts the
  `vector` extension is present, the `resources` relation exists, and a 384-dim
  embedding round-trips through an insert/select. It `pytest.skip`s if Postgres
  is unreachable, matching the existing DB tests. The full `pytest` run is the
  regression gate confirming the image swap broke nothing.
- **Manual:** recreate the local Postgres container on the new image
  (`docker compose up -d --force-recreate postgres`) before running the suite,
  since the running container must actually carry pgvector.

## Rollout & Reversibility

- **Feature flag:** no — an empty, unread table and an extension are inert; no
  code path reads `resources` until P2.
- **Migrations:** additive and idempotent (`CREATE EXTENSION IF NOT EXISTS`,
  `CREATE TABLE IF NOT EXISTS`). No destructive change. The image swap keeps the
  same PG16 on-disk format, so the `postgres-data` volume mounts as-is with no
  dump/restore.
- **Rollback plan:** revert the four edited files and recreate the container on
  `postgres:16-alpine`; the `resources` table can be left in place harmlessly or
  dropped (`DROP TABLE resources; DROP EXTENSION vector;`). No data migration to
  unwind.

---

## Key Decisions & Constraints

- Reuse the existing `schema.sql` + `apply_schema` mechanism; introduce no
  migration tool or second schema file (one schema source of truth).
- `resources` follows existing table conventions: `BIGSERIAL` PK (not the draft's
  `UUID`), `CHECK` constraints on `resource_type`/`level`, `url` `UNIQUE`.
- `embedding VECTOR(384)`, nullable — the writer phase (P1) chooses its
  insert-then-embed pattern.
- No ANN index (ivfflat rejected as wrong for an empty/incremental table; hnsw
  recorded as the future upgrade path). Sequential scan is correct at
  single-user scale.
- Image: official `pgvector/pgvector:pg16`, not a from-source alpine build.
- ⚠️ **One-way doors:** none. The schema change is additive/idempotent and the
  image swap is volume-compatible and reversible. (The genuinely irreversible
  infra commitment — always-on managed Postgres — is a *different* phase, P6.)

## Out of Scope

- `Resource` pydantic model and any CRUD/query helpers (P1 writer, P2 reader).
- Populating the table with any data (P1 aggregator).
- Any ANN / vector index.
- Managed/Azure Postgres provisioning or migration (P6).

---

## Definition of Done

- [ ] All acceptance criteria met.
- [ ] Phase 1 verification steps pass.
- [ ] Local Postgres recreated on the pgvector image and full `pytest` green.
- [ ] README/compose comments updated only if behaviour described there changed
  (the compose `postgres` image line is the sole doc-relevant change).
- [ ] No new lint or type-check warnings.

## Update Rules

- Phase docs hold task-level detail; this file holds phase-level status only.
- When the phase's scope changes, update its row here **in the same commit**.
- On conflict, this file wins for *what* the phase is; the phase doc wins for
  *how* its tasks are done.
