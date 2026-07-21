# Spec: Tracker Orchestration

> **Status:** Approved
> **Created:** 2026-07-17 · **Approved:** 2026-07-17
> **Implementation plan:** [plan.md](../../plans/tracker-orchestration/plan.md) *(created after approval)*

---

## Problem

`job-market-scout`'s pipeline (Scraper → Tracker → Scorer → Briefing) needs its Tracker stage implemented. Per the PRS, the Tracker is deterministic code (Decision D1) that persists every scraped listing to PostgreSQL, deduplicates, classifies each as new/changed/unchanged/closed by diffing against prior runs, and forwards only new/changed listings to the Scorer (FR-3 through FR-6).

The approved Storage module design (`docs/agent/specs/listings-db/spec.md`) defined the persistence primitives but explicitly deferred the Tracker's own orchestration — batching, calling convention, and how relevant listings reach the Scorer. `scout/shared/db.py` and `scout/tools/tracker.py` are currently empty stubs. The root `SequentialAgent` wiring and scheduler do not exist yet (PRS §7); existing stages are plain builder functions called directly with `list[Listing]`.

## Success Criteria

- Calling `track_listings` with a scraped batch persists every listing (FR-3) and returns only those classified new or changed, in classification order (FR-6).
- Unchanged listings update only `last_seen_at` and are excluded from the result.
- Previously-open listings absent from the current batch are marked closed (FR-5).
- A re-run after a partial failure is safe: already-committed listings classify as "unchanged" on retry.
- The Tracker is runnable and testable in isolation, matching the existing per-stage pattern.

---

## Requirements

### Must have

- Storage module implemented exactly per the approved Storage design (schema.sql, db.py, `database_url` in config, postgres service in docker-compose, asyncpg dependency) — unchanged.
- A single async entry point `track_listings(listings, pool=None, settings=None) -> list[Listing]` that a future root-agent wiring calls directly.
- Self-managed pool lifecycle when no pool is passed (create pool + apply idempotent schema), with support for a caller-supplied long-lived pool.
- Fail-fast error handling: DB failures raise and fail the run; no silent fallback, no retry.

### Should have

- Stale-listing closing scoped to one call per batch, after all upserts.

### Won't have

- Root `scout/agent.py` `SequentialAgent` wiring — a future session decides how (or whether) ADK session state carries data between stages.
- Scheduler / Azure hosting / CI/CD (PRS §7, planned separately).
- The deferred `matches` table (score persistence, PRS Decision D4 / §8).
- Retry/reconnect beyond asyncpg's pool defaults — YAGNI until a real failure mode is observed.

---

## Proposed Approach

Tracker is a plain async function in `scout/tools/tracker.py` orchestrating the Storage module's primitives: acquire one connection for the whole batch, upsert each listing sequentially and collect those classified new/changed, then close stale listings once using the batch's `(source, external_id)` keys, and return the new/changed listings for the caller to pass to the Scorer.

No transaction wraps the batch: a mid-batch failure leaves prior upserts committed, skips stale-closing for that batch, and propagates the exception. This is acceptable for a daily single-user batch job because a failed run is simply re-triggered and re-upserts are idempotent.

Key interface:

```python
async def track_listings(
    listings: list[Listing],
    pool: asyncpg.Pool | None = None,
    settings: Settings | None = None,
) -> list[Listing]: ...
```

Testing strategy: integration tests against a real Postgres via `DATABASE_URL`, auto-skipped when unreachable, with per-test state isolation. Detailed test cases belong in plan.md.

## Alternatives Considered

*(Reconstructed during migration from justifications in the original design doc — the alternatives were discussed during brainstorming but not tabulated.)*

| Alternative | Why rejected |
|-------------|--------------|
| Wrap the batch in a transaction | Fail-fast without partial-success handling is consistent with the Storage module's and project's existing error stance; idempotent re-runs make rollback unnecessary for a daily single-user job |
| Require the caller to always supply a pool | Each stage must be runnable in isolation without external setup, mirroring how existing builder functions default their own `settings` |
| Pass data between stages via ADK session state | No root wiring exists yet; existing stages use direct function calls with `list[Listing]`, and Tracker follows the same pattern |
| Retry/reconnect logic | YAGNI — deferred until a real failure mode is observed |

---

## Open Questions

| Question | Who decides | Blocks planning? |
|----------|-------------|------------------|
| Root `SequentialAgent` wiring and whether ADK session state carries Tracker output to the Scorer | Future design session | No |
| `matches` table design (score persistence) | Future design session | No |
| Scoping `close_stale_listings` if multiple search configs ever share one DB | Deferred (YAGNI) — revisit if multi-config happens | No |

---

## Amendments

- 2026-07-17: Migrated from the original superpowers-format design doc (`docs/superpowers/specs/2026-07-17-tracker-orchestration-design.md`) into the plan-standards spec template. Content unchanged in substance; Alternatives table reconstructed from inline rationale; enumerated test cases moved to plan.md scope.
- 2026-07-21: Merged in the `listings-db`, `pipeline-orchestration`, and `azure-vm-cicd-deploy` specs (see appendices below) — each was a small, closely-related design that didn't warrant its own top-level doc once implemented. Content unchanged in substance; original files deleted.

---

## Appendix A: Listings Database Design *(merged from `docs/agent/specs/listings-db/spec.md`, approved 2026-07-17)*

This is the Storage module design this Tracker orchestrates. Originally a separate spec because it was written before the Tracker's own orchestration logic was scoped — see the Problem statement above for how the two fit together.

### Context

`job-market-scout` is a multi-agent job search pipeline (Scraper → Tracker → Scorer → Briefing) built on Google ADK, LiteLLM, and DeepSeek, deployed via Docker. Per the PRS (`docs/project/specification/product-requirements-spec.md`; note Decision D4 was later revised to persist scores — see `docs/project/specification/product-requirements-spec-amendments.md`), PostgreSQL is used only by the Tracker stage (single writer, Decision D2) to persist every scraped listing and track its lifecycle (new / changed / closed) via diffing against prior runs (FR-3 through FR-6). Match scores are explicitly **not** persisted in this version (Decision D4) — that's deferred.

This design covers the **Postgres schema and the Storage module** (`scout/shared/db.py`); the Tracker's own diff/dedup orchestration logic is covered in the main spec above.

### Goals

- A `listings` table that stores every scraped listing (FR-3) with enough state to classify each one as new, changed, or closed on a later run (FR-5), without persisting match scores (D4).
- A Storage module (`scout/shared/db.py`) exposing the minimal set of async functions the Tracker needs: create a connection pool, apply the schema, upsert a single listing, and close stale listings.
- Idempotent schema application (no migration framework) appropriate for a single-table, single-user tool.
- A local Postgres service in `docker-compose.yaml` so the module is runnable and testable without an external DB.

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

### `scout/shared/db.py`

- `async def create_pool(settings: Settings | None = None) -> asyncpg.Pool` — one pool per process; DSN from `settings.database_url`.
- `async def apply_schema(pool: asyncpg.Pool) -> None` — reads and executes `schema.sql`. Safe to call on every startup (all statements are `IF NOT EXISTS`).
- `async def upsert_listing(conn: asyncpg.Connection, listing: Listing) -> Literal["new", "changed", "unchanged"]` — one round trip: a CTE reads the existing row's `content_hash`/`status` and performs `INSERT ... ON CONFLICT (source, external_id) DO UPDATE` in the same statement; the function then classifies the result in Python by comparing old vs. new hash/status. Always sets `status = 'open'` and bumps `last_seen_at` on write.
- `async def close_stale_listings(conn: asyncpg.Connection, seen_keys: list[tuple[str, str]]) -> list[str]` — one bulk `UPDATE listings SET status = 'closed', closed_at = now() WHERE status = 'open' AND (source, external_id) NOT IN (<batch>)`, returning the `external_id`s it closed.

### `scout/config.py` / `docker-compose.yaml` / `requirements.txt`

`database_url: str` added to `Settings` (env `DATABASE_URL`, default `postgresql://scout:scout@localhost:5433/scout`); a `postgres` service (`postgres:16-alpine`, named volume, `pg_isready` healthcheck, host port `5433:5432` — see Amendments below) added to `docker-compose.yaml` with `app` depending on it healthy; `asyncpg` added to `requirements.txt`.

### Error Handling

- `apply_schema` failing (unreachable Postgres, bad DSN) raises and fails fast at startup — no silent fallback.
- `upsert_listing` / `close_stale_listings` do not catch or swallow errors — failures bubble up to the caller.
- No retry/reconnect logic beyond what `asyncpg`'s connection pool already does.

### Testing

- `tests/test_db.py`: integration tests against a real Postgres via `DATABASE_URL`, skipped automatically if unreachable/unset.
- Coverage: `apply_schema` idempotency; insert-new returns `"new"`; re-upsert unchanged returns `"unchanged"`; re-upsert changed returns `"changed"` and fields actually update; `close_stale_listings` closes the right rows; a closed listing reappearing returns `"changed"` (reopened), not `"new"`.

### Amendments (original)

- 2026-07-17: Changed the `postgres` service's host port mapping from `5432:5432` to `5433:5432`, and `Settings.database_url`'s default host port from 5432 to 5433, discovered during implementation: a pre-existing native PostgreSQL service on the development machine already binds host port 5432, making the Docker container unreachable from the host on that port. Container-to-container traffic (the `app` service's `DATABASE_URL`, pointing at `postgres:5432`) is unaffected — that's Docker-internal networking, not the host port mapping.

---

## Appendix B: Pipeline Orchestration *(merged from `docs/agent/specs/pipeline-orchestration/spec.md`, approved 2026-07-20)*

### Problem

`job-market-scout`'s four stages — Scraper, Tracker, Scorer, Briefing — each work and are tested in isolation, but nothing runs them end-to-end. `scout/agent.py`, the intended root wiring point, was an empty stub; every prior spec (tracker-orchestration, scorer-agent) explicitly deferred "root `SequentialAgent` wiring" to a later session. Two of the four stages (Scraper, Scorer) also had no code that actually invoked their `LlmAgent` and parsed its structured output — only the Briefing stage had that runner glue. Separately, the container's `Dockerfile` `CMD` started `adk api_server`, a long-running interactive chat server, which cannot execute a one-shot daily batch run even if the wiring existed.

### Success Criteria

- A single call runs the full pipeline: scraped listings are tracked, relevant (new/changed) listings are scored, and a briefing email is sent for them — with no manual gluing of stage outputs to inputs.
- When the Tracker finds no new/changed listings, the Scorer and Briefing stages are not invoked (no wasted LLM calls).
- The container's default startup command actually executes one pipeline run to completion and exits, rather than starting a chat server that never triggers the pipeline.
- A stage failure aborts the run visibly (raises), with no partial-success masking.
- A developer can run `adk web`, send one message to the root agent, and watch the pipeline progress stage by stage in the ADK web UI.

### Requirements

**Must have:** a `run_scraper` function running the Scraper `LlmAgent` via an ADK runner and returning parsed `list[Listing]`; a `run_scorer` function with the same shape returning parsed `list[ListingScore]`; a custom (non-LLM) `BaseAgent` in `scout/agent.py` — `ScoutPipelineAgent` — whose `_run_async_impl` calls, in order, `run_scraper` → `track_listings` → (short-circuit if empty) → `run_scorer` → `run_briefing`, threading one `Settings` instance through every call and yielding an ADK `Event` after each stage; `scout/agent.py` exports `root_agent = ScoutPipelineAgent()` for `adk web` discovery; a batch entrypoint (`scout/main.py`) driving `ScoutPipelineAgent` through an `InMemoryRunner` via `asyncio.run`, exiting non-zero on failure; `Dockerfile`'s `CMD` updated to invoke that batch entrypoint instead of `adk api_server`.

**Should have:** a shared parsing helper (`scout/shared/parsing.py`) extracted from `briefing/summarize.py`'s code-fence-stripping logic, reused by all three LLM-output parsers.

**Won't have:** a literal ADK `SequentialAgent` chaining the four stages as agent instances — infeasible given Decision D3 (listing data never round-trips through the LLM), which requires the Scorer and Briefing agents to be *constructed* with the previous stage's typed Python output already known; a scheduler/cron trigger (planned separately, see Appendix C); persisting match scores; retry or partial-failure recovery across stages.

### Proposed Approach

`run_scraper` and `run_scorer` are plain async Python functions, not ADK agent constructs: each builds its stage's `LlmAgent`, runs it through an `InMemoryRunner` exactly as `briefing/summarize.py`'s `_run_briefing_agent` does, and parses the final response text into the stage's Pydantic output type using `TypeAdapter(list[X]).validate_json(...)` after stripping any markdown code fence.

`ScoutPipelineAgent` (in `scout/agent.py`) is a thin `BaseAgent` subclass that is the pipeline's single orchestrator. Its `_run_async_impl` calls each stage in order, passing typed Python values from one stage's return value into the next stage's arguments, and after each stage yields an `Event` carrying a short human-readable status (e.g. `"Scraper: 18 listings found"`, `"Tracker: 5 new, 13 existing"`, `"Scorer: 5 scored"`, `"Briefing: email sent"`).

The batch entrypoint (`scout/main.py`) drives the same `ScoutPipelineAgent` through an `InMemoryRunner`, so the container path and the `adk web` path share one implementation of the stage sequence. `main.py` consumes the runner's events (logging each) and raises/exits non-zero if the run fails. The `Dockerfile`'s `CMD` was changed to run `scout/main.py`.

### Alternatives Considered

| Alternative | Why rejected |
|-------------|--------------|
| Literal ADK `SequentialAgent` wiring the four stages as agent instances | Scorer/Briefing agents must be built with the prior stage's data already baked into their instructions (D3); `SequentialAgent` shares state at runtime between pre-built agent instances, which doesn't fit that construction-time dependency. |
| Leave `Dockerfile`'s `CMD` as `adk api_server` | The orchestrator would have no caller in the running container. |
| Keep the code-fence-stripping parsing helper duplicated per stage | Low cost to extract once, reused by briefing, scraper, and scorer parsers. |
| A plain `run_scout` async function as the only orchestrator, with no ADK-discoverable agent | Simpler, but leaves no way to exercise the full pipeline through `adk web` for interactive dev/debug visibility. |
| Reuse `LlmAgent`/`SequentialAgent` itself to get `adk web` support "for free" | Same problem as the rejected literal `SequentialAgent` above. |

---

## Appendix C: CI/CD Pipeline for Azure VM Deployment *(merged from `docs/agent/specs/azure-vm-cicd-deploy/spec.md`, drafted 2026-07-20, not approved/implemented)*

### Problem

The pipeline (scraper → scorer → briefing, driven by `scout/main.py`) currently only runs locally via `docker compose up`. There is no automated way to get code changes onto a real server, and no scheduled execution — someone has to manually run the pipeline. There's also no target infrastructure yet: no Azure VM exists to host the containers. The team wants pushes to `main` to automatically deploy to a live Azure VM, and wants the scout job itself to run daily without manual intervention.

### Success Criteria

- A push to `main` that passes tests automatically updates the running containers on the Azure VM with no manual SSH steps.
- The scout pipeline job (`docker compose run --rm app`) executes once daily on the VM without anyone triggering it by hand.
- Secrets (API keys, DB credentials, SSH key) never appear in the git repo or in pipeline logs.
- The Azure VM and its network resources (NSG, public IP, disk) can be created or recreated from tracked infrastructure-as-code, not manual portal clicks.

### Proposed Approach

Two independent Azure DevOps pipelines, reflecting that infrastructure changes rarely and code changes often:

1. **`infra-provision.yml`** (manual trigger only) deploys `infra/main.bicep` — a VM, NSG (allowing SSH), public IP, and OS disk — and runs a bootstrap step (cloud-init or a `customScript` extension) that installs Docker Engine, the Docker Compose plugin, and git, then clones the repo onto the VM.
2. **`azure-pipelines.yml`** has two trigger paths into shared stages: a CI path (push to `main` → `Test` → `Deploy` via SSH: write `.env` from an ADO secret variable group, `git pull`, `docker compose up -d --build`), and a schedule path (daily cron → SSH → `docker compose run --rm app`).

Secrets live in an Azure DevOps Library variable group (secret-masked), containing the same keys as `scout/.env.example` plus `VM_SSH_PRIVATE_KEY` and `VM_HOST`, rendered into the VM's `.env` at deploy time over SSH — never committed or logged unmasked.

### Alternatives Considered

| Alternative | Why rejected |
|-------------|--------------|
| GitHub Actions | User specified Azure DevOps Pipelines as the CI/CD system to use. |
| Build & push to Azure Container Registry, pull on VM | User chose the simpler SSH + git pull + `docker compose up --build` approach. |
| Terraform for infra | User chose Bicep — no extra tooling to install in the pipeline, native ARM deployment task available. |
| Single pipeline with a conditional infra stage | User chose two separate pipelines so infra provisioning can't be triggered accidentally by a push. |
| Do nothing (keep manual local `docker compose up`) | Doesn't meet the stated goal of automated deploy + unattended daily runs. |

### Status note

This spec was still in Draft (never approved or implemented) at merge time — the Azure DevOps org, subscription, and VM don't exist yet. It's kept here as a reference design for whenever that deployment work is picked up, not as a record of shipped behavior.
