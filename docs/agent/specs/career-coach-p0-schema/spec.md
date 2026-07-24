# Spec: Career Coach P0 — Schema & pgvector Foundation

> **Status:** Draft
> **Created:** 2026-07-24 · **Approved:** —
> **Implementation plan:** [plan.md](../../plans/career-coach-p0-schema/plan.md) *(created after approval)*
> **Umbrella PRS:** `docs/project/specification/career-coach-agent-prs.md` (v1.1) — this is phase **P0** of Stage 1.

---

## Problem

The Career Coach Agent must ground its coaching tips in a corpus of real
learning resources, retrieved by semantic similarity to each detected skill
gap. Every later phase depends on that corpus existing and being searchable:
the aggregator needs somewhere to write resources, the retriever needs to rank
them by vector similarity, and the grounded-tip stage needs the retriever. None
of that can be built or even tested today, because the database has no place to
store a resource or its embedding, and the Postgres image in use carries no
vector support at all. This phase lays that foundation and nothing else.

## Success Criteria

- The database can persist a learning resource — its URL, title, type, the
  normalized skills it covers, level, summary, embedding, source, and a
  last-verified timestamp — and rejects duplicate URLs.
- The database can store and compare 384-dimensional vector embeddings.
- Applying the schema remains idempotent, and every existing database-backed
  test still passes against the updated image.

---

## Requirements

### Must have

- pgvector must be available in the Postgres image used for local development
  and CI (and, in a later phase, production), so the `vector` type and
  similarity operators exist.
- A `resources` table sufficient to satisfy FR-CC-5: `id`, `url` (unique),
  `title`, `resource_type`, `skills[]`, `level`, `summary`, `embedding`
  (384-dim), `source`, `last_verified`, `created_at`.
- The table and extension are created through the existing idempotent schema
  mechanism, so applying the schema repeatedly is safe and existing tables and
  tests are unaffected.

### Should have

- The new table follows the existing schema's conventions rather than the
  original draft's: a `BIGSERIAL` primary key (not `UUID`) to match every other
  table, and `CHECK` constraints on `resource_type` and `level` mirroring how
  `status` / `requirement_level` / `kind` are constrained today.
- The test-fixture cleanup is extended to cover `resources`, so later phases'
  tests start from a clean table.

### Won't have

- **An ANN vector index (ivfflat or hnsw).** At single-user scale the corpus is
  tiny and the exact `skills[]` pre-filter narrows candidates before ranking, so
  an exact sequential scan is sub-millisecond; an index is unwarranted machinery
  now. hnsw is recorded as the upgrade path if the corpus ever grows.
- **A `Resource` model or any CRUD/query helpers** — these belong to the phases
  that consume the table (P1 writes, P2 reads); adding them now would be
  unused code.
- **Any data population** — the aggregator is P1; P0 ships an empty table.
- **Managed/Azure Postgres provisioning or migration** — that is Stage 2 (P6);
  P0 targets only the existing VM/dev/CI Postgres.

---

## Proposed Approach

Two coordinated changes, landed together because they are mutually dependent:

1. **Image.** Replace the stock `postgres:16-alpine` image (which has no
   pgvector) with the official `pgvector/pgvector:pg16` image, wherever a
   Postgres is stood up for the app or its tests. This is preferred over
   compiling pgvector from source onto the alpine base: the official image is
   zero-maintenance and always tracks PG16, and the larger Debian base is
   irrelevant on the deployment VM.

2. **Schema.** Append to the shared, idempotent schema definition (the same one
   `apply_schema` runs on every pipeline run):
   - `CREATE EXTENSION IF NOT EXISTS vector;`
   - `CREATE TABLE IF NOT EXISTS resources (…)` with the columns above, a
     `BIGSERIAL` primary key, a `UNIQUE` constraint on `url`, `CHECK`
     constraints on `resource_type` (`'doc' | 'course' | 'repo' | 'note'`) and
     `level` (`'beginner' | 'intermediate' | 'advanced'`), and `embedding`
     typed `VECTOR(384)` and left nullable so the writer phase can choose its
     insert-then-embed pattern.

The two changes are coupled: once `CREATE EXTENSION vector` is in the schema, it
runs everywhere the schema is applied — including the test fixture that backs
every database test — so the extension must be present in the image or those
tests fail. They therefore ship in one change, and the dev/CI Postgres
container is recreated on the new image as part of it.

No new persistence mechanism, migration tool, or separate schema file is
introduced: this rides entirely on the existing `schema.sql` + `apply_schema`
path, keeping one schema source of truth.

## Alternatives Considered

| Alternative | Why rejected |
|-------------|--------------|
| ivfflat index (as in the original draft) | ivfflat needs representative existing data to build good centroids; on an empty, incrementally-grown, tiny table its recall is poor and it would need rebuilding after data lands. Wrong index for this workload. |
| hnsw index now | Correct index type for incremental inserts, but unnecessary at single-user scale; deferred and documented as the upgrade path rather than built speculatively. |
| Compile pgvector from source onto `postgres:16-alpine` | Keeps the small alpine base but adds a custom Dockerfile, build dependencies, and manual tracking of pgvector releases — maintenance cost for no real benefit here. |
| `UUID` primary key (as in the draft) | Every existing table uses `BIGSERIAL`; matching that keeps the schema uniform and joins/keys consistent. |
| A separate migration tool or a dedicated resources schema file | The project already applies one idempotent `schema.sql` via `apply_schema`; a second mechanism would fragment the schema source of truth. |
| Do nothing | No later Career Coach phase can be built or tested without a place to store resources and their embeddings; this is the hard prerequisite. |

---

## Open Questions

| Question | Who decides | Blocks planning? |
|----------|-------------|------------------|
| Whether non-`repo` `resource_type` values (`doc`/`course`/`note`) are ever populated (umbrella Q4) | human | No — the `CHECK` already permits all four; only `repo` is written in later phases, no schema change needed to add the rest. |

> No question blocks planning. The schema shape is fully determined.

---

## Amendments *(only after approval — never silently edit approved content)*

- —
