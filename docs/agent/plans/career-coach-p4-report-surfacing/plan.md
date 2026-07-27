# Plan: Career Coach P4 — Report Surfacing of Grounded Tips

> **Status:** In progress
> **Created:** 2026-07-27 · **Last updated:** 2026-07-27
> **Spec:** [spec.md](../../specs/career-coach-p4-report-surfacing/spec.md)

---

## Overview

Show P3's stored grounded tips on the per-role detail page. Two pure renderer
filters land first — one that turns bare URLs in tip prose into safe links up
to a limit, one that computes the page's per-gap citation cap — then the gap
blocks in "Skill gaps to close" start carrying the tip that answers each gap,
and finally the static "How to position your application" section is deleted
and replaced by an honest empty state. Done means a job-detail page for a
tipped listing shows each gap's advice and a working citation next to the gap
itself, with no templated generic advice anywhere on the page.

## Acceptance Criteria

- [ ] A gap with a stored tip renders that tip inside its own gap block, and a
      gap without one renders exactly as it does today (skill + pill).
- [ ] A tip stored for one gap never renders under a different gap.
- [ ] Gaps render must-haves before nice-to-haves.
- [ ] A tip's bare `http`/`https` URLs render as anchors labelled host + path
      with the scheme and `www.` stripped; the anchor's `href` is the full URL.
- [ ] A `[label](url)` citation renders as one anchor labelled `label`, with no
      literal brackets or parentheses left on the page.
- [ ] URLs beyond the gap's citation cap render as visible, unlinked text.
- [ ] The per-gap cap is `max(1, 3 // tipped_gaps)` counted in **distinct**
      URLs: one tipped gap gets 3, two get 1 each, three get 1 each, five get
      1 each; a tip naming one resource twice spends one unit of budget.
- [x] URL spans match what `scout/sub_agents/coach/grounding.py` finds, so
      every URL P3 stored is one P4 can linkify.
- [ ] Markup in tip text is escaped, and a non-`http(s)` scheme
      (`javascript:`, `data:`) is never turned into an anchor.
- [ ] At most one tip renders per gap even if two are stored for it; a tip
      whose `gap_skill` matches no gap renders nowhere.
- [ ] A listing with gaps but no tips renders the "no verified learning
      resources yet" line and no static positioning advice.
- [ ] The string "How to position your application" appears nowhere in a
      rendered job-detail page.
- [ ] `pytest` passes with no regression to the existing suite.

---

## Risks & Unknowns

| Risk / unknown | Impact if wrong | Resolution |
|----------------|-----------------|------------|
| The URL regex may mis-handle the shapes real tip prose contains — a trailing full stop, a URL in parentheses, a trailing comma before "and" — either swallowing punctuation into the `href` or truncating a legitimate path. | A citation links to a 404 (`…/kubernetes.` ) or a real link renders broken, which is the visible half of the trust the grounding work exists to build. | **Spike — Phase 1, Task 1.** Pin the extractor against a fixture list of real shapes before any wrapping logic exists. Tests are the deliverable either way. P3's validator has already solved this lexing problem, so Phase 1 Task 1 copies its pattern rather than inventing a second one — the two stay independent in policy but must agree on where a URL starts and ends. Note the module (`scout/sub_agents/coach/grounding.py`) does not exist yet, since P3's Phase 2 is unbuilt; take the pattern from its phase doc and re-check against the merged module once it lands. |
| P3 leaves Markdown link syntax intact for any URL it does **not** strip, so `listing_tips.tip` can contain `[label](url)`. | Brackets and parentheses render literally around the link — visibly broken output on the feature's headline surface. | Phase 1 Task 3 renders the construct as one anchor labelled `label`. Phase 2 Task 3 case (c) asserts it through real rendered HTML. |
| P3 dedupes `cited_urls` but not the prose, so one resource can appear twice in a tip. | One resource consumes the whole three-link budget while reading as three recommendations. | Phase 1 Task 4 counts the cap in distinct URLs; a repeat is still linked but spends no budget. |
| Returning `Markup` from `linkify` opts the tip text out of Jinja's autoescape, so escaping becomes the filter's job. | LLM-authored text renders as live markup — a stored-XSS-shaped bug on a local page, and the same class of defect the existing description test guards against. | Phase 1, Task 2 is escape-first-then-wrap with an explicit injection test. The existing `markdown` filter (`html=False`) and `test_advisor_report.py:355-386` are the precedent to match. |
| `detail.gaps` and `detail.tips` join on raw stored wording; if P3's phases 2–3 ever normalise `gap_skill` on write, the join silently yields nothing and every tip disappears from the page. | Page renders as if the corpus had no coverage — a silent, total failure with no error. | Accepted risk, guarded by test: Phase 2, Task 1 asserts the join on the exact wording, so a change to P3's write path fails a P4 test rather than blanking the page. `GroundedTip`'s docstring already states the contract. |
| P3's phases 2 and 3 (grounding validator, generation) are unbuilt, so no real run produces tips yet. | This phase cannot be verified end to end against live data before merge. | Accepted and planned around: every phase here is verified against seeded tips, which is how `test_advisor_report.py` already works. The end-to-end manual check moves to after P3 lands — see Definition of Done. |
| Deleting the positioning section changes every historical page on the next `rerender.py` run. | Pages that used to end with advice end with an empty-state line. | Intended, and the reason the empty state exists. Reversible — see Rollout & Reversibility. |

## Blast Radius

- **Code that will change:** `scout/sub_agents/advisor/report.py`,
  `scout/sub_agents/advisor/templates/job-detail.html.jinja`, `tests/`
- **Existing behaviour that could break:**
  - `test_advisor_report.py:211` asserts `"How to position your application"`
    is present. Phase 3 inverts that assertion — a deliberate, planned break.
  - Gap ordering inside "Skill gaps to close" changes (must-haves first), so
    any test asserting gap order by position needs checking.
  - `rerender.py` rewrites every historical run's pages with the new template.
    No code change there; the behaviour change is the point.
- **Off-limits:** `scout/shared/` (schema, db, schemas) and
  `scout/sub_agents/coach/` are P3's. This phase reads what P3 stores and
  changes none of it. Do not modify anything outside the directories above
  without flagging it to the human first.

---

## Phases

| # | Phase | Document | Status |
|---|-------|----------|--------|
| 1 | Renderer filters | [phase-1-renderer-filters.md](phase-1-renderer-filters.md) | Complete |
| 2 | Tips in gap blocks | [phase-2-tips-in-gap-blocks.md](phase-2-tips-in-gap-blocks.md) | Not started |
| 3 | Retire the static section | [phase-3-retire-static-section.md](phase-3-retire-static-section.md) | Not started |

> All phases are planned in advance — every row above has a written,
> human-approved phase doc before phase 1 execution starts. If executing
> an earlier phase surfaces a needed change to a later phase doc, update
> that doc explicitly and record the change in its Notes / Learnings
> section; don't leave later phases undocumented.

---

## Testing Strategy

- **Unit:** Phase 1's two filters are pure functions of strings and a
  `RunListingDetail`, so they carry the exhaustive cases — URL shapes,
  punctuation, escaping, scheme rejection, link limits, cap arithmetic at 0/1/
  2/3/5 tipped gaps. No DB, no fixtures beyond plain values.
- **Integration:** Phases 2 and 3 assert on rendered HTML through
  `render_run`, using the existing `db_pool` fixture and seeded tips — the
  same shape as the job-detail tests already in `test_advisor_report.py`. This
  is what verifies the filters, the template, and P3's read path work
  together.
- **Manual:** Open a generated `job-detail-*.html` in a browser and confirm
  the tip sits under its gap, the citation is clickable and resolves, and a
  listing with no tips reads sensibly. Full end-to-end (a real pipeline run
  generating tips through P3 and rendering them here) is only possible once
  P3's phases 2–3 land; see Definition of Done.

## Rollout & Reversibility

- **Feature flag:** no. The change is presentational and per-run — a listing
  with no stored tips already renders the pre-tips page, so the rollout is
  gated by data rather than by a flag.
- **Migrations:** none. This phase adds no schema and writes nothing.
- **Rollback plan:** revert the commits and run `python -m scout.rerender`,
  which rebuilds every page from the database. Because no data is written or
  destroyed, the previous pages come back byte-for-byte.

---

## Key Decisions & Constraints

- Tips render inside their gap's block, not in a separate section; the static
  "How to position your application" section is deleted rather than kept as a
  fallback, so the generic templated advice does not survive anywhere.
- Prioritisation is carried by ordering (must-haves first) and the existing
  requirement pill, not by a sentence naming the top gap.
- Citations are linkified in the tip's own prose. `cited_urls` stays the
  post-validation audit record P3 designed it as and is not rendered.
- A page spends a citation budget of three links, divided evenly across
  tipped gaps (`max(1, 3 // tipped_gaps)`) and counted in distinct URLs, with
  a floor of one per tipped gap so no advice names an unreachable resource.
  The remainder is left unspent. Three is one gap's worth by construction —
  `COACH_TOP_K` defaults to 3 and bounds what P3 injects per gap.
- URL lexing is copied from P3's grounding validator, not reinvented; the two
  stay independent in policy and identical in where a URL begins and ends.
- The budget is a module constant in `report.py`, not an env-var setting.
- ⚠️ **One-way doors:** none. No schema, no stored data, no external contract
  — every change here is a revert plus a re-render.

## Out of Scope

- Any change to `listing_tips`, `record_listing_tips`, `get_run_details`, or
  `GroundedTip` — P3 owns them and landed them complete.
- Resource titles on citations (needs a `cited_urls` → `resources` join in the
  read path).
- Tips on the dashboard, history, or profile pages.
- Re-verifying that a cited URL still resolves at render time — that is P5.

---

## Definition of Done

- [ ] All acceptance criteria met
- [ ] All phase verification steps pass
- [ ] Feature verified manually: a rendered job-detail page from seeded tips
      opens in a browser with the tip under its gap and a working citation
- [ ] End-to-end check deferred and recorded: once P3's phases 2–3 land and a
      real run generates tips, re-render and confirm the live page — this
      phase must not claim end-to-end verification before then
- [ ] `docs/project/architecture-pipeline-overview.md` updated where the
      report's coaching behaviour is described
- [ ] No new lint or type-check warnings

## Update Rules

- Phase docs hold task-level detail; this file holds phase-level status only.
- When a phase's scope changes, update its row here **in the same commit**.
- On conflict, this file wins for *what* the phases are; the phase doc
  wins for *how* its tasks are done.
