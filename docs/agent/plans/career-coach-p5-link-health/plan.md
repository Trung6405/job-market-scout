# Plan: Career Coach P5 — Link-Health Checker

> **Status:** Complete
> **Created:** 2026-07-28 · **Last updated:** 2026-07-28 (all 5 phases implemented, manually verified against production, and scheduled)
> **Spec:** [spec.md](../../specs/career-coach-p5-link-health/spec.md)

---

## Overview

Build a standalone job that walks the `resources` corpus in
least-recently-checked order, requests each URL over HTTP, and records a health
verdict on the row; teach retrieval to skip resources the verdict marks dead.
Done means a resource whose URL 404s stops reaching the grounded-tip stage
within a day of dying, returns on its own if the URL works again, and survives
a transient outage untouched — with the check running on its own step of the
existing daily scheduled run and never able to fail the pipeline.

## Acceptance Criteria

- [x] A run verifies a bounded batch of resources, oldest-checked first, and
      leaves each one with an updated verification time or failure state.
- [x] A resource returning 404/410 is excluded from retrieval on the first
      observation; a resource returning 5xx/timeout/429/403 is excluded only
      after the configured number of consecutive failures.
- [x] A previously-excluded resource is retrievable again after one successful
      check, with its failure count reset.
- [x] `retrieve_for_skills` never returns a resource marked dead.
- [x] A never-checked resource (`last_verified IS NULL`) is still retrievable.
- [x] The job is invocable as its own module, logs a per-run summary, exits
      non-zero on failure, and its scheduled step cannot fail the pipeline run.
- [x] A read-only audit command reports the corpus's health distribution and
      every dead resource with its reason, safe to run against production.

---

## Risks & Unknowns

| Risk / unknown | Impact if wrong | Resolution |
|----------------|-----------------|------------|
| `HEAD` is unreliable in the wild — some hosts return 403/405/501 for it, or answer it differently from `GET` | Healthy resources accumulate failures and are wrongly excluded | Fall back to a bodyless `GET` on a non-success `HEAD`, and class ambiguous refusals as transient so they need repeated failures. Manual check against real corpus URLs is a verification step of Phase 2. |
| Unauthenticated bursts against `github.com` may be rate-limited, and every corpus URL today is a GitHub repo | A whole batch fails at once and, over enough consecutive runs, the corpus empties itself | Bounded batch, sequential requests with the same throttle discipline the aggregator uses, 429 classed as transient. Accepted risk; the per-run summary makes a mass-failure run visible immediately. |
| A host may answer a dead page with 200 and a "not found" body | A dead resource is never excluded | Accepted risk — not detectable without content heuristics, which the spec excludes. GitHub, the only source today, returns a true 404. |
| Every existing row has `last_verified IS NULL`, so oldest-first ordering has no natural tiebreak | Batches could revisit the same rows and starve the rest of the corpus | Order `NULLS FIRST` with `id` as an explicit deterministic tiebreak — covered by a test in Phase 3. |
| The check adds wall-clock time to the daily VM boot window | Longer VM uptime, marginally higher cost | Batch cap × per-request timeout bounds the worst case by construction; defaults chosen to stay well inside the existing window. Accepted. |
| Tips stored by earlier runs keep citing a URL that later dies — exclusion governs retrieval, not the `listing_tips` rows already written | Since P4 dropped its per-page link budget, *every* citation renders as a live anchor, so a stale row is a clickable 404 on the job-detail page until that listing is re-tipped | Accepted. The pipeline re-runs daily and regenerates tips from the healthy corpus, so the window is short and self-closing; retro-editing stored tips would mean rewriting generated prose around a removed citation, which is out of scope for a link checker. |
| Defaults for threshold, batch size, and timeout are unvalidated guesses | Corpus cycles too slowly, or flaps | Accepted risk — all are `COACH_*` environment settings (Phase 1) and are tunable from the observed run summary with no code change. |

## Blast Radius

- **Code that will change:** `scout/shared/schema.sql`, `scout/shared/db.py`,
  `scout/shared/schemas.py`, `scout/config.py`,
  `scout/sub_agents/coach/` (new `link_health.py`),
  `scout/coach_link_health.py` (new), `scripts/audit_link_health.py` (new),
  `.github/workflows/scheduled-run.yml`,
  `tests/`, `docs/commands.md`,
  `docs/agent/plans/career-coach-p5-link-health/`.
- **Existing behaviour that could break:** `get_resources_for_skills` — the
  read path behind `retrieve_for_skills`, and therefore behind the grounded-tip
  stage, which since the P3 merge runs on **every** pipeline run; the daily
  scheduled run, which gains a step; `apply_schema`, which every
  database-backed test invokes.
- **Off-limits:** Do not modify anything outside the directories above without
  flagging it to the human first. In particular: no changes to the aggregator
  (`runner.py`, `github_search.py`, `bootstrap.py`, `tagging.py`), to gap
  detection, or to anything under `scout/sub_agents/advisor/`.

---

## Phases

| # | Phase | Document | Status |
|---|-------|----------|--------|
| 1 | Health-state schema & settings | [phase-1-schema-and-settings.md](phase-1-schema-and-settings.md) | Complete |
| 2 | Link checker | [phase-2-link-checker.md](phase-2-link-checker.md) | Complete |
| 3 | Health-state persistence | [phase-3-persistence.md](phase-3-persistence.md) | Complete |
| 4 | Retrieval exclusion | [phase-4-retrieval-exclusion.md](phase-4-retrieval-exclusion.md) | Complete |
| 5 | Runner, entrypoint, audit & scheduling | [phase-5-runner-and-scheduling.md](phase-5-runner-and-scheduling.md) | Complete |

> All phases are planned in advance — every row above has a written,
> human-approved phase doc before phase 1 execution starts. If executing
> an earlier phase surfaces a needed change to a later phase doc, update
> that doc explicitly and record the change in its Notes / Learnings
> section; don't leave later phases undocumented.

---

## Testing Strategy

- **Unit:** per-task TDD in the phase docs — verdict classification against
  every status class and network exception, `HEAD`→`GET` fallback, settings
  parsing, the runner's batching and summary counts, and the entrypoint's
  logging and exit code. All network access is stubbed; no test makes a real
  HTTP request.
- **Integration:** database-backed tests against the `scout_test` Postgres
  (the existing `db_pool` fixture) cover the new columns, batch selection
  ordering, each state transition end to end, and — the phase-spanning check —
  that a resource marked dead by `record_link_check` is not returned by
  `get_resources_for_skills`, while a never-checked one still is. These run in
  the normal `pytest` suite, and skip cleanly when Postgres is unreachable.
- **Manual:** the load-bearing part, for the reason P4 discovered the hard way
  (`scripts/audit_rendered_citations.py`): stubbed tests prove only the
  behaviour whoever wrote the stub imagined, and P4's per-page link budget
  passed every fixture test while being wrong about real data. The equivalent
  blind spot here is what real hosts do with a `HEAD` request, which no stub can
  answer. So: a real-URL check of the checker in Phase 2, and one real run
  against the live corpus, read back through `scripts/audit_link_health.py`
  (Phase 5), before wiring the schedule
  (Phase 5), confirming the summary counts are plausible and that healthy
  GitHub URLs are not being classed as failures — the one thing stubs cannot
  prove. Plus a YAML-level assertion that the scheduled step exists and is
  non-fatal.

## Rollout & Reversibility

- **Feature flag:** no. The batch-size setting is the effective control — a
  batch of 0 disables checking without a code change.
- **Migrations:** additive and reversible in effect — two `ALTER TABLE … ADD
  COLUMN IF NOT EXISTS` statements on `resources` through the existing
  idempotent `apply_schema` path. No column is dropped, no data rewritten,
  and defaults leave every existing row healthy-and-unchecked. Not a one-way
  door.
- **Rollback plan:** revert the code. The added columns can be left in place
  harmlessly — nothing reads them once the retrieval filter is reverted, and
  the corpus returns to its pre-P5 behaviour of never expiring anything. If a
  bad run has wrongly marked resources dead, `UPDATE resources SET dead_since
  = NULL, consecutive_failures = 0` restores every one of them; no resource is
  ever deleted, so nothing is unrecoverable.

---

## Key Decisions & Constraints

- Health lives in two additive columns on `resources` (a consecutive-failure
  count and a dead-since marker) rather than a separate check-history table:
  retrieval needs one boolean answer per row, and a history table would add a
  join to the hot read path to store data nothing reads.
- Permanent (404/410) and transient (timeout, DNS, 5xx, 429, 401/403) failures
  are separated, and only permanent ones act immediately. A 403 is transient
  because hosts return it for anti-bot and rate-limit reasons far more often
  than for genuine removal.
- Exclusion is reversible state, never a delete — a successful check restores
  the resource, and the aggregator's duplicate suppression keeps working.
- Requests are issued sequentially, as the aggregator does, rather than
  concurrently. Bounded concurrency of one is the simplest thing that satisfies
  the spec's bound, keeps the throttle discipline that the GitHub-heavy corpus
  needs, and avoids introducing an async HTTP client for a job whose runtime is
  already capped by the batch size.
- Whole-corpus batching, not surfaced-first: a resource that dies before it is
  ever cited must be caught *before* its first citation, which a surfaced-first
  scope cannot do. P5 therefore reads nothing P3 or P4 owns, and can land
  alongside the still-in-flight P4.
- `last_verified IS NULL` continues to count as live, so a freshly aggregated
  resource is retrievable before its first check.
- The job rides the existing daily 19:00 UTC scheduled run as its own step —
  the VM is already booted, so the check adds no extra boot — and that step
  must not be able to fail the pipeline job.
- ⚠️ **One-way doors:** none. The schema change is additive, the data change is
  reversible with a single `UPDATE`, and no external resource is provisioned.

## Out of Scope

- Quality or freshness judgements about resource *content* (archived,
  abandoned, README changed) — that is aggregator filtering, not link health.
- Re-tagging or re-embedding resources whose content changed.
- Deleting dead rows.
- Notifying anyone about dead links — no Discord push, no report section.
- Verification at retrieval time.
- Any change to `listing_tips`, the report, or the grounded-tip prompt — P3 and
  P4 own those and are unaffected by this work.
- **An on-demand re-check tool** — a command that re-verifies a single URL and
  writes the result, answering "is this really dead, or was that a bad run?"
  Deliberately deferred, not rejected: `scripts/audit_link_health.py` (Phase 5)
  is read-only by design, and a write-capable operator tool is a different
  thing with a different blast radius — it can resurrect or kill a resource by
  hand, outside the scheduled job's control. Revisit once real runs show
  whether hand-correction is ever actually needed; until then the scheduled job
  is the only writer, which is what makes its behaviour reasonable about.

---

## Definition of Done

- [x] All acceptance criteria met
- [x] All phase verification steps pass
- [x] Feature verified manually in a running environment (real runs against
      production Postgres and the real internet — see phase-5's Notes /
      Learnings; the live corpus itself is empty, a pre-existing P1 gap, so
      verification used throwaway rows inserted and removed for the purpose)
- [x] Docs / README updated where behaviour changed (`docs/commands.md`)
- [x] No new lint or type-check warnings (project has no lint/type-check
      tooling configured)

## Update Rules

- Phase docs hold task-level detail; this file holds phase-level status only.
- When a phase's scope changes, update its row here **in the same commit**.
- On conflict, this file wins for *what* the phases are; the phase doc
  wins for *how* its tasks are done.
