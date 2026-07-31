# Plan: Skill Alias Normalisation

> **Status:** Not started
> **Created:** 2026-07-30 · **Last updated:** 2026-07-30
> **Spec:** [spec.md](../../specs/skill-alias-normalisation/spec.md)

---

## Overview

Make common spellings of one technology reduce to one token, so a resource
tagged `Google Cloud Platform` answers a gap written `GCP`. The alias table
behind `normalize_skill` has six entries against 51 observed variant families,
and because tokens are stored normalised, every resource already in the corpus
carries a frozen spelling. Done when the measured variant families match each
other, the deliberately-separate languages still do not, and the 957 stored
rows agree with what fresh tagging would produce.

## Acceptance Criteria

- [ ] `normalize_skill` maps each observed variant family to one token —
      verified for GCP/Google Cloud Platform, Node.js/NodeJS, REST API(s)/
      RESTful APIs, CI/CD(+pipelines), Infrastructure as Code(+hyphenated),
      Vue.js/VueJS, TypeScript/Typescript.
- [ ] `C`, `C++`, `C#`, `Java` and `JavaScript` remain five distinct tokens.
- [ ] Every alias entry corresponds to a spelling actually observed in gap or
      resource data.
- [ ] After backfill, no row in `resources.skills` contains a token that the
      current rules would map elsewhere.
- [ ] Running the backfill twice reports zero changes the second time.
- [ ] A before/after count shows how many distinct gap skills have at least one
      matching corpus token.

---

## Risks & Unknowns

| Risk / unknown | Impact if wrong | Resolution |
|----------------|-----------------|------------|
| Canonical direction per family is guessed rather than measured — picking `gcp` when the tagger emits `Google Cloud Platform` moves the mismatch instead of fixing it | Aliases land but retrieval improves less than expected, or regresses for families that were previously consistent | Spike: Phase 1 Task 1 reads the actual `resources.skills` distribution and fixes each direction from data |
| An alias merges two technologies that are genuinely distinct | Retrieval precision degrades silently — the failure D-CC-3 and `_PUNCTUATED_SKILLS` both exist to prevent, and which previously marked a C++ requirement met against plain C | Every entry hand-inspected against real spellings; guard tests pin the known-dangerous separations; the spec forbids algorithmic derivation |
| `.NET` vs `.NET Core` may not be equivalent for retrieval purposes | Either a missed match or a wrong one, depending on which way it is decided | Open question in the spec — Phase 1 Task 2 surfaces the data and the human decides before the entry is written |
| Backfill rewrites rows that other code reads concurrently | A run reading mid-rewrite sees mixed tokens | Accepted risk, bounded: the aggregator runs weekly and the backfill is a single short statement set; run it while nothing else is scheduled, as Phase 2 Task 3 specifies |
| The change is correct but immaterial until the corpus holds cloud resources | Effort spent for no visible improvement now | Accepted and expected: the coverage report in Phase 2 Task 4 states the delta honestly, including if it is zero. The correctness argument stands independently |

## Blast Radius

- **Code that will change:** `scout/shared/skills.py`, a new backfill script
  under `scripts/`, and `tests/`.
- **Existing behaviour that could break:** everything that compares skills —
  gap "met" detection in the advisor, `resources.skills` on write, and the
  retriever's pre-filter on read. All three share `normalize_skill`, which is
  why it changes in one place.
- **Off-limits:** the retrieval strategy itself, the tagging prompt, the
  aggregator's intake rules, and `resources` schema. Do not modify anything
  outside the directories above without flagging it to the human first.

---

## Phases

| # | Phase | Document | Status |
|---|-------|----------|--------|
| 1 | Alias table from data | [phase-1-alias-table.md](phase-1-alias-table.md) | Not started |
| 2 | Backfill stored tokens | [phase-2-backfill.md](phase-2-backfill.md) | Not started |

> All phases are planned in advance — every row above has a written,
> human-approved phase doc before phase 1 execution starts. If executing
> an earlier phase surfaces a needed change to a later phase doc, update
> that doc explicitly and record the change in its Notes / Learnings
> section; don't leave later phases undocumented.

---

## Testing Strategy

- **Unit:** per-task TDD covers each variant family collapsing to one token,
  the dangerous separations staying separate, and the multi-word ordering case
  (`.NET Core`) that the punctuation strip currently mangles. The existing
  `tests/test_*skill*` suites are the regression net for the rules already
  relied upon.
- **Integration:** the retriever's exact-match behaviour is already covered by
  existing tests against a real local Postgres; they must stay green, since a
  token that did not change must retrieve exactly as before.
- **Manual:** Phase 2 only — run the backfill against the VM database, confirm
  the second run is a no-op, and read the coverage delta.

## Rollout & Reversibility

- **Feature flag:** no. Normalisation is a pure function; there is no partial
  state to gate.
- **Migrations:** no schema change. The backfill rewrites values inside an
  existing `text[]` column.
- **Rollback plan:** revert the `skills.py` commit; stored tokens then disagree
  with the code again, which is the state we start from, so nothing breaks that
  was not already broken. A dump is taken before the backfill (Phase 2 Task 3)
  so the pre-change `resources` table can be restored outright if needed.

---

## Key Decisions & Constraints

- **Curated, never derived.** A crude stem over this data merged `C`, `C++`
  and `C#`. Entries are added by hand from observed spellings, and guard tests
  pin the separations.
- **Aliases are normalised-to-normalised**, which is what makes the backfill a
  lookup rather than a re-tagging exercise. This is a constraint on the table's
  shape, not an implementation detail.
- **Canonical direction follows the corpus**, because the resource side cannot
  be re-asked without spending LLM calls, whereas gap strings are re-extracted
  every run.
- **Merging affects matching, never display** (spec A1). `listing_gaps.skill`
  keeps the raw extracted string and the report renders it, so a gap shown as
  `.NET Core` finds a `.NET` resource while still reading `.NET Core` on the
  page. Nothing in this plan deduplicates gap rows — `HuggingFace` and
  `Hugging Face` stay two rows with their own requirement levels.
- **`Security` and `Cloud Security` are not merged.** Every other family here is
  two spellings of one technology; this one is a generic parent and a
  specialisation. Merging would let general security material answer a
  cloud-security gap, which is a precision loss rather than a spelling fix —
  the same reasoning that keeps `Java` and `Spring Boot` apart.
- **This lands before the corpus grows.** Seeding thousands of rows under the
  old rules would multiply the number needing remapping. That sequencing is the
  whole reason this plan precedes coach-aggregator-completion.
- ⚠️ **One-way doors:** none. The backfill is reversible from the dump taken
  immediately before it, and the code change is a revert.

## Out of Scope

- Rejecting prose, generic and multi-skill gap strings (~231 of 852) — saves
  aggregation work, fixes no matching, and has its own spec to be written.
- Changing exact-match retrieval, or revisiting it for compound skills like
  `awscloud` (coach-aggregator-completion spec A2).
- Re-tagging resources with the LLM.
- The gap extractor emitting the same skill twice at different requirement
  levels.

---

## Definition of Done

- [ ] All acceptance criteria met
- [ ] All phase verification steps pass
- [ ] Backfill run against the production database and verified idempotent
- [ ] Coverage delta recorded, including if it is zero
- [ ] No new lint or type-check warnings

## Update Rules

- Phase docs hold task-level detail; this file holds phase-level status only.
- When a phase's scope changes, update its row here **in the same commit**.
- On conflict, this file wins for *what* the phases are; the phase doc
  wins for *how* its tasks are done.
