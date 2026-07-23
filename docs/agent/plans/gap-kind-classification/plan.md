# Plan: Requirement Kind Classification for Skill Gaps

> **Status:** In progress
> **Created:** 2026-07-23 · **Last updated:** 2026-07-23
> **Spec:** [spec.md](../../specs/gap-kind-classification/spec.md)

---

## Overview

Stop non-skill requirements (degrees, experience thresholds, soft skills)
from surfacing as false skill gaps. Each extracted requirement gains a
closed-vocabulary `kind`; only `skill`-kind requirements are matched against
the profile and eligible to be gaps, while the rest render as display-only
context. Done means: a "STEM degree in CS" requirement is never a gap and
never dents must-have coverage, genuine technical-skill gaps still show, and
non-skill requirements are still visible as context.

## Acceptance Criteria

- [ ] A `qualification` / `experience` / `soft_skill` requirement never
      appears in a listing's gap list.
- [ ] A "STEM degree in CS" requirement, for a profile holding a CS degree,
      is not a gap and does not reduce must-have coverage counts.
- [ ] A genuinely missing technical skill is still detected and shown.
- [ ] Non-skill requirements render in a separate "Role also asks for"
      section with no met/unmet mark.
- [ ] Runs persisted before this change still render (their requirements
      default to `skill` kind).

---

## Risks & Unknowns

| Risk / unknown | Impact if wrong | Resolution |
|----------------|-----------------|------------|
| DeepSeek may omit or mis-emit the new nested `kind` field, failing pydantic validation for the whole batch and dropping extractions. | Extraction reliability regresses; listings silently lose requirements. | `RequirementItem.kind` defaults to `"skill"` so an omitted kind still parses (Phase 1); an out-of-vocabulary value still fails loudly by design. |
| Existing stored `listing_gaps` rows have no `kind` column. | Old runs render blank/incorrect. | Additive `ADD COLUMN IF NOT EXISTS kind ... DEFAULT 'skill'` (Phase 2) — legacy rows read as skill kind, i.e. current behavior. |
| DeepSeek's kind classification is imperfect (mislabels a skill as a qualification or vice versa). | An occasional item lands in the wrong section. | Accepted risk — this is a display/accuracy nicety, not a correctness regression; the prior state (everything a gap) was strictly worse. |

> Every unknown gets either a spike task or an explicit "accepted risk".

## Blast Radius

- **Code that will change:** `scout/shared/schemas.py`,
  `scout/sub_agents/advisor/gaps.py`, `scout/prompts.py`,
  `scout/shared/db.py`, `scout/shared/schema.sql`,
  `scout/sub_agents/advisor/templates/job-detail.html.jinja`, and the
  corresponding files under `tests/`.
- **Existing behaviour that could break:** requirements extraction output
  shape, gap detection, the job-detail report, and the `listing_gaps`
  persistence round-trip.
- **Off-limits:** Do not modify anything outside the directories above
  without flagging it to the human first. In particular, the scorer,
  scraper, tracker, and briefing sub-agents stay untouched.

---

## Phases

| # | Phase | Document | Status |
|---|-------|----------|--------|
| 1 | Typed kind + gap matching + extractor prompt | [phase-1-typed-kind-and-matching.md](phase-1-typed-kind-and-matching.md) | Complete |
| 2 | Persist kind + kind-based gap filter | [phase-2-persistence.md](phase-2-persistence.md) | Not started |
| 3 | Report rendering | [phase-3-report-rendering.md](phase-3-report-rendering.md) | Not started |

> All phases are planned in advance — every row above has a written,
> human-approved phase doc before phase 1 execution starts.

---

## Testing Strategy

- **Unit:** per-task TDD in the phase docs — schema vocabulary validation
  and default (`test_schemas.py`), gap matching by kind incl. the STEM-degree
  fixture (`test_advisor_gaps.py`), the extractor prompt instruction
  (`test_prompts.py`), the `listing_gaps` kind round-trip (`test_db.py`), and
  report rendering of the context section and coverage counts
  (`test_advisor_report.py`).
- **Integration:** the DB-backed tests in `test_db.py` run against a live
  Postgres (`docker compose up -d postgres`, or CI) — they verify kind
  survives the delete-then-insert persistence path.
- **Manual:** render a run's job-detail page against real data and confirm a
  listing with a degree/experience requirement shows it under "Role also
  asks for" and not as a gap.

## Rollout & Reversibility

- **Feature flag:** no.
- **Migrations:** additive and reversible in effect —
  `ALTER TABLE listing_gaps ADD COLUMN IF NOT EXISTS kind TEXT NOT NULL
  DEFAULT 'skill'`. Applied idempotently at startup like the existing
  columns; safe to re-run.
- **Rollback plan:** revert the code commits. The added `kind` column is
  harmless to leave in place (defaulted, ignored by reverted code); drop it
  manually only if a clean schema is required.

---

## Key Decisions & Constraints

- Classify by kind on a tagged list, rather than splitting the schema into
  separate skill/qualification fields — smallest change that fixes the
  correctness bug (spec Alternatives).
- Non-skill requirements are display-only: the tool makes no met/unmet
  judgement on them, avoiding the fuzzy free-text matching that caused the
  false positives.
- `kind` is a closed `Literal` vocabulary validated at the schema boundary,
  mirroring the existing `Band` vocabulary, and defaults to `"skill"` for
  backward and forward compatibility.
- No one-way doors: the schema migration is additive and safe to re-run.

## Out of Scope

- Listings that extract zero requirements (vague prose postings surfacing as
  "reach" with no gaps) — extraction-quality concern, deferred.
- Expanding skill matching beyond `profile.tech_stack`.
- Any met/unmet judgement on non-skill requirements.

---

## Definition of Done

- [ ] All acceptance criteria met
- [ ] All phase verification steps pass
- [ ] Feature verified manually in a running environment (job-detail page)
- [ ] Docs updated where behaviour changed (advisor-report spec / PRS if they
      describe gap semantics)
- [ ] No new lint or type-check warnings

## Update Rules

- Phase docs hold task-level detail; this file holds phase-level status only.
- When a phase's scope changes, update its row here **in the same commit**.
- On conflict, this file wins for *what* the phases are; the phase doc wins
  for *how* its tasks are done.
