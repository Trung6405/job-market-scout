# Plan: Career Coach P3 — Grounded Tip Stage & URL Validator

> **Status:** Not started
> **Created:** 2026-07-27 · **Last updated:** 2026-07-27
> **Spec:** [spec.md](../../specs/career-coach-p3-grounded-tips/spec.md)

---

## Overview

Turn detected skill gaps plus P2's retrieved resources into coaching tips that
cite only real corpus URLs, and store them against the run. One LLM call per
listing generates a tip per covered gap; a deterministic validator then strips
any URL the model invented before anything is persisted. Done means a run
writes validated, cited tips into a new `listing_tips` table and reads them
back with the rest of a run's detail — with the job-detail template still
untouched, because displaying them is P4.

## Acceptance Criteria

- [ ] A run with gaps that have corpus coverage stores one `listing_tips` row
      per covered gap, each with a non-empty tip and at least one cited URL.
- [ ] Every stored `cited_urls` entry appears in the resources retrieved for
      **that gap** — a URL retrieved for a different gap on the same listing is
      stripped, not stored.
- [ ] A tip whose URLs are all stripped is not stored at all.
- [ ] Each strip is logged with the listing, the gap skill, and the offending
      URL.
- [ ] A listing whose gaps retrieve no resources produces no LLM call and no
      rows.
- [ ] A listing whose LLM call fails or returns unparseable JSON is logged and
      skipped; every other listing in the run still gets its tips.
- [ ] Retrieval runs once per run over the union of gap skills, not once per
      listing.
- [ ] `get_run_details` returns each listing's stored tips, so `rerender.py`
      loads them with no LLM call.
- [ ] Tips are written inside the existing run transaction — a failure after
      generation leaves no partially-tipped run.
- [ ] `pytest` passes with no regression to the existing suite.

---

## Risks & Unknowns

| Risk / unknown | Impact if wrong | Resolution |
|----------------|-----------------|------------|
| P2 is branched but unmerged; P3 branches off its tip and calls `retrieve_for_skills`. If P2's API changes before merge, P3's call site is wrong. | One call site in `tips.py` needs updating; nothing structural. | Accepted risk, bounded. The signature and return shape are already built and tested on P2's branch. P3 cannot merge to `main` before P2 does — noted in Rollout. |
| A regex URL extractor may mis-handle trailing punctuation (`…see https://x/y.`) or Markdown link syntax, either stripping a legitimate URL or leaving a fabricated one. | Either a real citation is lost (visible, annoying) or a hallucinated URL survives (silent, and the exact failure FR-CC-9 exists to prevent). | **Spike — Phase 2, Task 1.** Pin the extractor's behaviour against a fixture list of the real shapes an LLM emits before any stripping logic is written. Tests are the deliverable either way. |
| The model may return tips for skills that were not in the prompt, or omit gaps that were. | Tips get stored against a gap the listing does not have, or coverage is silently incomplete. | Handled in Phase 3, Task 4: tips whose `gap_skill` is not one of the listing's requested gaps are dropped before validation. Missing gaps are simply not tipped — no error. |
| The retriever loads the sentence-transformers model into the **pipeline** container to embed gap queries, adding cold-start time to the nightly run. | Slower runs on the ~1h/day-booted VM. | Accepted risk, already decided upstream — D-CC-4 accepts torch in the pipeline image explicitly, and P2 introduced the dependency. P3 adds no new load. |
| Tips are generated but nothing displays them until P4. | LLM spend on invisible output for the window between P3 and P4 merging. | Accepted, explicit in the spec's Won't-have. Bounded by keeping P4 next. |

## Blast Radius

- **Code that will change:** `scout/shared/db.py`, `scout/shared/schemas.py`,
  `scout/shared/schema.sql`, `scout/prompts.py`, `scout/config.py`,
  `scout/sub_agents/coach/` (new `tips.py`, `grounding.py`), `scout/agent.py`,
  `tests/`
- **Existing behaviour that could break:**
  - `scout/agent.py` — the run transaction gains a write. A failure in the new
    stage must not fail the run; generation therefore happens *before* the
    transaction is opened, and only the (cheap, local) write is inside it.
  - `get_run_details` — consumed by `report.py` and `rerender.py`. The new
    `tips` field defaults to `[]`, so both keep working before P4.
  - `scout/config.py` — new `Settings` fields must have defaults so every
    existing construction site keeps working.
- **Off-limits:** Do not modify anything outside the directories above without
  flagging it to the human first. In particular: **no change to
  `scout/sub_agents/advisor/templates/`** (the static tips block is P4's to
  replace), no change to `scout/sub_agents/coach/retriever.py` or the
  aggregator's write path, and no change to gap detection.

---

## Phases

| # | Phase | Document | Status |
|---|-------|----------|--------|
| 1 | Persistence & schema | [phase-1-persistence.md](phase-1-persistence.md) | Not started |
| 2 | Grounding validator | [phase-2-grounding-validator.md](phase-2-grounding-validator.md) | Not started |
| 3 | Generation stage & wiring | [phase-3-generation-and-wiring.md](phase-3-generation-and-wiring.md) | Not started |

> All phases are planned in advance — every row above has a written,
> human-approved phase doc before phase 1 execution starts. If executing
> an earlier phase surfaces a needed change to a later phase doc, update
> that doc explicitly and record the change in its Notes / Learnings
> section; don't leave later phases undocumented.

---

## Testing Strategy

- **Unit:** Per-task TDD in the phase docs. The validator (Phase 2) is a pure
  function over strings and carries the densest tests in the phase — every
  hallucination shape, plus every legitimate URL shape that must survive.
  Generation (Phase 3) is tested with `complete_json` monkeypatched, following
  `tests/test_coach_tagging.py`.
- **Integration:** Phase 1's DB helpers run against the real `scout_test`
  Postgres via the existing `db_pool` fixture (skipped automatically when
  Postgres is unreachable). Phase 3's final task asserts the whole stage
  end-to-end against seeded `resources` rows with a stubbed LLM, including that
  a cross-gap URL is stripped on the round trip through the database.
- **Manual:** One real pipeline run against the dev database with a populated
  corpus, checking that `listing_tips` fills, that the logged violation count
  is plausible, and that a second `rerender.py` costs no LLM call.

## Rollout & Reversibility

- **Feature flag:** No. The stage self-disables where it cannot work — a run
  whose gaps retrieve nothing generates nothing, which is the state before the
  corpus is populated anyway.
- **Migrations:** Reversible. `listing_tips` is a new, additive table appended
  to `schema.sql` in the project's existing `CREATE TABLE IF NOT EXISTS` style;
  no existing table or column is altered. Undo is `DROP TABLE listing_tips`.
- **Rollback plan:** Revert the branch. The dropped table takes only generated
  tips with it — every input (gaps, resources) is still stored, so a later
  re-run reproduces them. Nothing outside this feature reads `listing_tips`
  until P4.
- **Merge order:** P3 must not merge to `main` before P2 — it calls
  `retrieve_for_skills`, which exists only on P2's branch.

---

## Key Decisions & Constraints

- The stage lives in `scout/sub_agents/coach/`, not `advisor/`: it consumes the
  retriever and corpus, and `advisor/` importing `coach/` would invert the
  dependency direction P1's amendment already corrected once.
- Grounding is enforced deterministically after generation, never by the prompt
  instruction alone (D-CC-5, NFR-CC-3).
- The allowlist is scoped **per gap**, not per listing. Every gap's resources
  share one prompt, so citing a real URL under the wrong skill is the cheapest
  hallucination available and the one a per-listing allowlist would miss.
- A tip left citing nothing after stripping is dropped — uncited prose is the
  static-template problem this phase removes.
- One LLM call per listing, issued as size-1 batches through the existing
  `run_batches`, which already gives per-call concurrency limiting and
  skip-on-failure without new machinery.
- Generation runs *outside* the run transaction (it takes minutes); only the
  write is inside it, matching how the Scorer and Extractor are already
  sequenced in `agent.py`.
- ⚠️ **One-way doors:** None. The schema change is additive and reversible, no
  new dependency is introduced (P1 and P2 already added
  `sentence-transformers`), and no external service is provisioned.

## Out of Scope

- The job-detail template and the static tips block — **P4** (FR-CC-11).
- Link-health re-verification of cited URLs — **P5**.
- Serving tips over Discord — **P7**.
- Any change to gap detection, `listing_gaps`, `profile.json`, or the retriever.

---

## Definition of Done

- [ ] All acceptance criteria met
- [ ] All phase verification steps pass
- [ ] Feature verified manually in a running environment (one real pipeline run
      writes `listing_tips`; a `rerender.py` re-render spends no LLM call)
- [ ] `docs/project/architecture-pipeline-overview.md` updated with the new
      stage and table
- [ ] `scout/.env.example` updated with the new `COACH_TIPS_*` variables
- [ ] No new lint or type-check warnings

## Update Rules

- Phase docs hold task-level detail; this file holds phase-level status only.
- When a phase's scope changes, update its row here **in the same commit**.
- On conflict, this file wins for *what* the phases are; the phase doc
  wins for *how* its tasks are done.
