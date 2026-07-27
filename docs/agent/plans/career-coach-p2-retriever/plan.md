# Plan: Career Coach P2 — Retriever

> **Status:** In progress
> **Created:** 2026-07-27 · **Last updated:** 2026-07-27
> **Spec:** [spec.md](../../specs/career-coach-p2-retriever/spec.md)

---

## Overview

Build the read side of the Career Coach: given the skill names of a run's
detected gaps, return the 2–3 most relevant resources for each from the corpus
P1 fills. Retrieval is hybrid — an exact normalized `skills[]` pre-filter, then
pgvector cosine ranking within it — so a gap never surfaces a resource for a
different technology. Done means `retrieve_for_skills` is callable, covered by
tests against real seeded rows, and returns resources P3 can ground tips on;
nothing consumes it yet.

## Acceptance Criteria

- [ ] `retrieve_for_skills(conn, skills, k)` returns, per skill, the top-`k`
      resources whose `skills[]` contains that skill, ordered by cosine
      similarity to the skill's embedding.
- [ ] A skill whose pre-filter matches nothing maps to `[]` — never to a
      resource tagged only with a different skill.
- [ ] Gap wording variants (`"K8s"`, `"React.js"`, `"  Postgres "`) retrieve
      the resources tagged `kubernetes` / `react` / `postgresql`.
- [ ] Results are keyed by the caller's original skill string, so a caller
      holding a `SkillGap` looks up its resources without re-normalizing.
- [ ] A skill repeated across many listings is embedded once and queried once.
- [ ] Rows with a `NULL` embedding, and rows whose `last_verified` predates the
      staleness window, are never returned; `NULL` `last_verified` is returned.
- [ ] Each result carries a `similarity` score.
- [ ] `pytest` passes with no regression to the existing suite.

---

## Risks & Unknowns

| Risk / unknown | Impact if wrong | Resolution |
|----------------|-----------------|------------|
| pgvector may reject a per-row `text::vector` cast inside `CROSS JOIN LATERAL` — the cast varies per row rather than being a query parameter | The one-round-trip set-based query is unworkable; the looped-per-skill form ships instead, behind an identical API | **Spike — Phase 1, Task 1.** Decided against real Postgres before any helper is written. Either outcome is a complete answer; nothing downstream depends on which wins. |
| `asyncpg` may not accept a `list[list[float]]` bound to `text[]` without explicit per-element formatting | Query binding fails; vectors must be pre-formatted into their `[a,b,c]` text form | Covered by the same spike — `insert_resource` already formats a single vector this way, so the pattern is known to work; the spike confirms it holds for an array of them. |
| Cosine ranking within a single skill may prove uninformative if the corpus holds only one resource per skill early on | No functional failure — ranking one row is still correct; the ordering simply does nothing visible until coverage grows | Accepted risk. The pre-filter is what guarantees correctness; ranking is an improvement on top, and its value scales with the corpus rather than being needed on day one. |
| The 90-day staleness window is chosen before P5 exists, so it is not yet matched to a real re-verification cadence | Resources could age out of retrieval before P5 re-stamps them, silently shrinking results | Accepted risk, bounded: the window is configurable, and until P5 ships every row has `last_verified = NULL` and is therefore always live — the filter cannot bite before P5 exists. P5 sets its cadence against this window. |

## Blast Radius

- **Code that will change:** `scout/shared/db.py`, `scout/shared/schemas.py`,
  `scout/config.py`, `scout/sub_agents/coach/` (new `retriever.py`), `tests/`
- **Existing behaviour that could break:** None by design — every change is
  additive. The one shared-file risk is `scout/config.py`: new `Settings`
  fields must have defaults so every existing construction site keeps working.
- **Off-limits:** Do not modify anything outside the directories above without
  flagging it to the human first. In particular: no change to
  `scout/sub_agents/advisor/` (gap detection and reporting are P3/P4), no
  change to the aggregator's write path, and no schema migration.

---

## Phases

| # | Phase | Document | Status |
|---|-------|----------|--------|
| 1 | Retrieval query in the shared data layer | [phase-1-retrieval-query.md](phase-1-retrieval-query.md) | Complete |
| 2 | Retriever module and config | [phase-2-retriever-module.md](phase-2-retriever-module.md) | Not started |

> All phases are planned in advance — every row above has a written,
> human-approved phase doc before phase 1 execution starts. If executing
> an earlier phase surfaces a needed change to a later phase doc, update
> that doc explicitly and record the change in its Notes / Learnings
> section; don't leave later phases undocumented.

---

## Testing Strategy

- **Unit:** Per-task TDD in the phase docs. Phase 1 covers the SQL's behaviour
  against real seeded rows (pre-filter exclusion, cosine ordering, `k` limit,
  liveness and NULL-embedding exclusion, per-skill result mapping). Phase 2
  covers the module's own logic with the database helper stubbed: normalization
  of incoming skills, dedupe, one-embed-per-distinct-skill, and mapping results
  back onto the caller's original strings.
- **Integration:** The phase-1 tests are already integration tests in the sense
  that matters — they run against a real Postgres with pgvector via the
  existing `db_pool` fixture (`scout_test` database), not a mock. Phase 2 adds
  one end-to-end test that seeds rows and calls the public
  `retrieve_for_skills` with a real connection and a stubbed `embed`, proving
  the module and the SQL compose.
- **Manual:** None required. Nothing user-facing changes in this phase — there
  is no rendered output, no pipeline step, and no consumer until P3. Manual
  verification belongs to the phase that surfaces results to a human.

---

## Key Decisions & Constraints

- **Empty pre-filter returns `[]`, with no fallback of any kind.** A fallback
  fires exactly when a skill has no genuine coverage, converting "no resource"
  into "a wrong resource" — the outcome that costs the seeker the most time.
- **The retriever normalizes on read; `listing_gaps.skill` stays raw.**
  Changing gap-detection storage is out of scope per the umbrella §2.2.
- **The corpus side of that guarantee is already in place.** P1 now applies
  `normalize_skill` to `resources.skills[]` on write (P1 spec amendment,
  2026-07-27), with `normalize_skill` living in `scout/shared/skills.py`. This
  plan assumes that commit is present — it is the precondition making an exact
  pre-filter viable at all.
- **No pgvector index.** The pre-filter reduces each ranking to one skill's
  rows; a sequential scan over tens of rows beats an approximate index, and
  `ivfflat` needs a populated table to build meaningful lists.
- **`k = 3` and a 90-day staleness window**, both configurable via `Settings`.
- **Set-based query preferred, looped query accepted.** Identical API and
  identical results either way; the choice is settled by Phase 1's spike, not
  by argument.
- ⚠️ **One-way doors:** None. Every change is additive, there is no migration,
  and no consumer exists yet — the whole phase can be reverted by deleting the
  new module and its helper.

## Out of Scope

- The Advisor grounded-tip stage, its prompt, and its URL validator (P3).
- Report and dashboard changes (P4).
- Link-health verification — writing or refreshing `last_verified` (P5). This
  phase only honours the column; it never sets it.
- Any change to gap detection, `listing_gaps`, or the aggregator write path.
- Wiring the retriever into the pipeline. It ships as a callable library
  function with no caller; P3 is what calls it.

---

## Definition of Done

- [ ] All acceptance criteria met
- [ ] All phase verification steps pass
- [ ] ~~Feature verified manually in a running environment~~ — N/A, see
      Testing Strategy → Manual: this phase has no user-facing surface and no
      pipeline caller. The real-Postgres tests are the verification.
- [ ] Docs / README updated where behaviour changed — expected to be none;
      confirm no user-facing behaviour description became stale
- [ ] No new lint or type-check warnings

## Update Rules

- Phase docs hold task-level detail; this file holds phase-level status only.
- When a phase's scope changes, update its row here **in the same commit**.
- On conflict, this file wins for *what* the phases are; the phase doc
  wins for *how* its tasks are done.
