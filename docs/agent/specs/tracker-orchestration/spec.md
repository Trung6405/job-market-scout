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
