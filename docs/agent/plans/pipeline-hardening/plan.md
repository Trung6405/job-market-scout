# Plan: Pipeline Hardening — Gap Accuracy & Persistence Robustness

> **Status:** Complete
> **Created:** 2026-07-23 · **Last updated:** 2026-07-23
> **Spec:** [spec.md](../../specs/pipeline-hardening/spec.md)

---

## Overview

Harden the Advisor stage and its persistence path against three
review-surfaced weaknesses: false gaps from naive skill matching, a
partial-persistence window when a run dies mid-Advisor, and implicit
contracts (run identity, idempotency, band vocabulary). Done means gaps
match on canonical skill names, the run persists all-or-nothing with
dropped listings logged, and the run-identity/idempotency/band contracts
are explicit in code types and docs.

## Acceptance Criteria

- [x] A profile skill stated as a common variant in a listing is not
  reported as a gap (covered by unit tests for `React.js`/`React`,
  `Postgres`/`PostgreSQL`, `JS`/`JavaScript`).
- [x] The final persistence block commits all-or-nothing under a single
  transaction; an injected mid-block failure leaves no `run_listings`,
  `listing_gaps`, or `finished_at` written for that run. *(Test written;
  DB-backed, verified in CI — skips in the local sandbox with no Postgres.)*
- [x] A short extraction result (fewer listings than scored) produces a
  visible warning.
- [x] `band` is a closed typed vocabulary end-to-end; a bad band value
  fails type-check/validation.
- [x] `architecture-pipeline-overview.md` documents same-`run_date`
  overwrite and re-run idempotency.

---

## Risks & Unknowns

| Risk / unknown | Impact if wrong | Resolution |
|----------------|-----------------|------------|
| ADK `output_schema` may constrain how much extra prompt guidance the extraction agent honors for canonical names | Canonicalization under-delivers; relies more on the deterministic `normalize_skill()` fallback | Phase 1 keeps the deterministic normalizer as the guarantee; the prompt is best-effort improvement, so this is an accepted risk. |
| Wrapping report renders inside the DB transaction holds the connection during Jinja rendering | Slightly longer-held connection; rendering that reads the same `conn` must stay inside the txn to see uncommitted rows | Keep render calls that read run data inside the txn (they must, to reflect this run); `render_profile` (no DB) stays outside. Verified in Phase 2. |
| Changing `band` to a `Literal`/enum may ripple into Jinja templates that compare band strings | Templates render blank/incorrect band styling | Phase 3 greps templates for band literals and keeps the enum's `.value` as the wire string so template comparisons are unchanged. |

## Blast Radius

- **Code that will change:** `scout/sub_agents/advisor/` (`gaps.py`,
  `bands.py`), `scout/prompts.py`, `scout/agent.py`, `scout/shared/db.py`,
  `scout/shared/schemas.py`, `tests/`, and docs under `docs/agent/` +
  `docs/project/architecture-pipeline-overview.md`.
- **Existing behaviour that could break:** gap rendering on job-detail
  pages (matching logic), run persistence ordering, band styling in
  templates.
- **Off-limits:** Do not modify anything outside the directories above
  without flagging it to the human first. No infra/workflow/Bicep changes.

---

## Phases

| # | Phase | Document | Status |
|---|-------|----------|--------|
| 1 | Gap-matching accuracy | [phase-1-gap-matching-accuracy.md](phase-1-gap-matching-accuracy.md) | Complete |
| 2 | Persistence robustness | [phase-2-persistence-robustness.md](phase-2-persistence-robustness.md) | Complete |
| 3 | Contracts & typing | [phase-3-contracts-and-typing.md](phase-3-contracts-and-typing.md) | Complete |

> All phases are planned in advance — every row above has a written phase
> doc before phase 1 execution starts. Phases are independent and could be
> executed in any order; the numbering is a suggested sequence
> (highest-value bug first).

---

## Testing Strategy

- **Unit:** `normalize_skill()` and `evaluate_requirements()` variant
  cases (Phase 1); `classify_band()` returns typed band (Phase 3). All via
  per-task TDD.
- **Integration:** an agent-level test that injects a failure between
  `record_run_listings` and `finish_run` and asserts the run has no
  persisted listings/gaps and `finished_at` is NULL (Phase 2). Requires a
  test Postgres (existing db integration test harness).
- **Manual:** render a run's dashboard/job-detail after Phase 1 and
  confirm a known held skill is no longer flagged as a gap.

## Rollout & Reversibility

- **Feature flag:** no.
- **Migrations:** none required. `band` stays a `TEXT` column storing the
  enum's string value; the typing change is code-only, backward-compatible
  with existing rows.
- **Rollback plan:** revert the phase commits; no data migration to undo.

---

## Key Decisions & Constraints

- Skill-name canonicalization happens in the extraction prompt, backed by
  a deterministic `normalize_skill()` fallback — the fallback is the
  guarantee, the prompt is the improvement.
- Same-`run_date` overwrite is kept intentionally; documented, not
  changed.
- Proficiency-aware matching is deferred (presence-only).
- No one-way doors: no schema migration, no infra change, all reversible.

## Out of Scope

- Proficiency-aware gap matching.
- Per-timestamp intraday run rows.
- Infra rethink (ACI/Container App Jobs) and missed-run alerting.

---

## Definition of Done

- [x] All acceptance criteria met (DB-backed ones verified in CI)
- [x] All phase verification steps pass (non-DB locally; DB-backed in CI)
- [ ] Feature verified manually in a running environment (one dashboard
  render with a corrected gap) — **pending**, needs a run against Postgres
- [x] Docs updated: architecture overview + naming reconciliation
- [x] No new lint or type-check warnings

## Update Rules

- Phase docs hold task-level detail; this file holds phase-level status only.
- When a phase's scope changes, update its row here **in the same commit**.
- On conflict, this file wins for *what* the phases are; the phase doc
  wins for *how* its tasks are done.
