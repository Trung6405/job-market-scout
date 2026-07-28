# Spec: Career Coach P3 — Grounded Tip Stage & URL Validator

> **Status:** Draft
> **Created:** 2026-07-27 · **Approved:** —
> **Implementation plan:** [plan.md](../../plans/career-coach-p3-grounded-tips/plan.md) *(created after approval)*
> **Umbrella PRS:** `docs/project/specification/career-coach-agent-prs.md` (v1.1) — this is phase **P3** of Stage 1.
> **Depends on:** P0 (`resources` table + pgvector, merged), P1 (corpus
> aggregator, merged as #28), P2 (`retrieve_for_skills`, merged as #30 — this
> phase consumes its public API unchanged).

---

## Problem

The pipeline can now name a listing's skill gaps and, since P2, find real
learning resources for each of them — but nothing joins the two into advice the
job seeker actually reads. The "How to position your application" section of
every job-detail page is still a static template that restates the gap list in
prose: it cannot name a resource, because a hand-written template has no way to
know which resources exist for a given skill.

Filling that section with generated prose is the obvious move and the dangerous
one. An LLM asked to recommend learning resources will invent plausible URLs,
and a confidently-cited dead or fictional link is worse than the generic advice
it replaced — the seeker spends time discovering the recommendation was never
real, and loses trust in every other recommendation on the page. So the value
of this phase depends entirely on a guarantee that no cited resource can be
fabricated, and that guarantee cannot rest on asking the model nicely.

## Success Criteria

- For a listing with detected gaps whose skills have corpus coverage, the run
  stores one tip per covered gap, each citing at least one resource URL that
  demonstrably exists in the corpus.
- No stored tip contains a URL absent from the resources retrieved for that
  specific gap — including when the model returns a URL that was in the prompt
  but belonged to a different gap.
- A grounding violation is observable after the fact: it is logged when it
  happens, and the surviving citations are stored, so violation frequency can
  be counted across runs rather than inferred.
- A listing whose gaps have no corpus coverage costs no LLM call, and a
  listing whose call fails does not fail the run.
- Re-rendering an existing run's reports loads that run's stored tips from the
  database without spending another LLM call — so that when P4 displays them,
  a re-render is free.

---

## Requirements

### Must have

- Generate coaching tips via the LLM with each gap's retrieved resources
  injected as structured context (title, URL, summary, type) and an explicit
  instruction to reference only the provided resources (FR-CC-8).
- After generation, deterministically parse URLs from the tip text and strip
  any URL not present in **that gap's** retrieved-resource set, logging each
  strip as a grounding violation. Enforcement never relies on the prompt
  instruction alone (FR-CC-9, D-CC-5, NFR-CC-3).
- Drop any tip left citing no valid URL after stripping — uncited prose is the
  static-template problem this phase exists to remove.
- Retrieve once per run for the union of the run's gap skills, not per listing,
  so a skill that is a gap on many listings is embedded and queried once.
- Issue one LLM call per listing, carrying all of that listing's gaps and their
  resources, run concurrently under the existing model-concurrency limit.
- Skip the LLM call entirely for a listing whose gaps retrieved no resources.
- Persist tips durably, keyed to the run listing and the gap skill they answer,
  alongside the surviving cited URLs.
- Persist tips inside the existing single run transaction, so a mid-run failure
  leaves no partially-tipped run.
- Read stored tips back with the rest of a run's detail, so a re-render needs
  no LLM call.
- A failed or unparseable LLM call for one listing is logged and skipped; the
  run continues and every other listing still gets its tips.

### Should have

- Configurable tip-generation limits (resources injected per gap, tips
  requested per listing) following the existing `Settings` dataclass / env-var
  convention.
- A run-level log line reporting tips generated, listings skipped for lack of
  coverage, and grounding violations stripped — the same shape as the existing
  per-stage pipeline events.

### Won't have

- Any change to the job-detail template or the static tips block — that is
  **P4** (FR-CC-11). The static `<ol>` keeps rendering untouched until then,
  which means this phase generates tips nothing yet displays. Accepted as the
  cost of the phase split; P4 should follow closely.
- Any change to gap detection, `listing_gaps`, or `profile.json` — the umbrella
  puts these out of scope (§2.2); this phase consumes gaps as stored.
- Any change to the retriever or its API — P3 is a consumer of P2, not a
  revision of it.
- Link-health re-verification of cited resources (P5) — a URL is trusted
  because it is in the corpus, and P5 is what ages dead ones out.
- Tips for listings with no detected gaps — there is nothing to close, and the
  page already says so.
- Tips for non-`skill` gap kinds (degrees, years of experience, soft skills) —
  they are never gaps by construction (`evaluate_requirements` passes them
  through as met) and the corpus has no resources for them.
- Serving tips on demand over Discord (P7) — this phase only produces and
  stores them.

---

## Proposed Approach

The stage lives in `scout/sub_agents/coach/`, not `advisor/`. The umbrella PRS
calls it "the Advisor coaching-tip stage" because it replaces the Advisor's
tips, but the machinery is Coach domain: it consumes the retriever and the
corpus, and having `advisor/` import `coach/` would point the dependency the
wrong way — the same reasoning that moved `normalize_skill` into
`scout/shared/skills.py` in P1's amendment. `agent.py` orchestrates both, as it
already does for every other stage.

**Generation** — a per-listing pass. For a run, the union of every unmet skill
gap's name goes to `retrieve_for_skills` in one call, yielding resources keyed
by the caller's original gap wording. Each listing then gets one LLM call
through the existing `complete_json` helper, carrying its gaps and their
resources, returning one tip per gap as a pydantic model. Calls run
concurrently under the existing model-concurrency limit, matching how the
Scorer and requirements extraction already behave. A listing whose gaps
retrieved nothing is skipped before the call — there is nothing to ground on,
and an ungrounded call would produce exactly the uncited advice this phase
removes.

**Enforcement** — a separate, pure module. URL validation is deliberately not
folded into the generation code: it is the integrity boundary FR-CC-9 and
NFR-CC-3 name, and keeping it free of I/O and LLM calls is what makes it
exhaustively testable on plain strings. It takes a tip's text and the allowlist
of URLs retrieved **for that gap** — not for the listing — and returns the
cleaned text plus whatever it stripped. Scoping the allowlist per gap rather
than per listing is the non-obvious half: every gap's resources appear in the
same prompt, so the cheapest hallucination for a model to make is citing a
real, present URL under the wrong skill. Comparison normalizes only scheme/host
case and a trailing slash — enough that a genuine URL is not stripped over
formatting, not so much that a fabricated path slips through.

**Persistence** — a new `listing_tips` table mirroring `listing_gaps`: same
parent (`run_listings`), same cascade delete, same additive `schema.sql` style
the project already uses. It stores the gap skill in its raw stored wording (as
`listing_gaps.skill` does), the tip text, and the surviving cited URLs. Storing
the citations rather than only logging them is what makes a grounding violation
auditable after the run, instead of visible only in a log line that has since
rotated. The write joins the existing single run transaction next to
`record_listing_gaps`, and the read joins `get_run_details`, so tips travel
with the rest of a run's detail and a re-render costs nothing.

This phase owns the full round trip — write and read — and stops at the
template. P4 changes only Jinja; if the read-back were deferred to P4, P4 would
have to reach into the DB layer to render a page, and P3 would ship a table
nothing can read.

```
checks_by_match ──► unmet skill gaps
                      │
                      ▼
        retrieve_for_skills(conn, union of gap skills)   ← P2, once per run
                      │  dict[skill, list[RetrievedResource]]
                      ▼
        generation: one LLM call per listing, concurrent
                      │  tip per gap
                      ▼
        validation: strip non-allowlisted URLs (per gap), drop uncited tips
                      │
                      ▼
        listing_tips ──► get_run_details ──► (P4 renders)
```

## Alternatives Considered

| Alternative | Why rejected |
|-------------|--------------|
| Enforce grounding by prompt instruction alone | Directly contradicts D-CC-5 and NFR-CC-3, and the product PRS's "LLM proposes, deterministic code enforces" rule. A prompt instruction is best-effort wording; the whole value of the feature rests on the citation being trustworthy. |
| One LLM call per gap | Maximum isolation — cross-gap URL leakage becomes impossible before the validator runs — but multiplies calls from listings (~10–30) to gaps (~50–150) per run, and no tip can weigh a gap against the others. The per-gap allowlist gets the same guarantee deterministically, at the lower call count. |
| Batch several listings per call (the requirements-extraction pattern) | Fewest calls, but each prompt carries N listings × gaps × 2–3 resources, so prompts grow large and one malformed reply costs a whole batch of listings their tips. Per-listing keeps the blast radius of a bad reply to one listing. |
| Hold tips in memory and pass them to the renderer | Smallest change, but `rerender.py` renders purely from the DB, so every re-render would silently lose its tips, and P7's `/tips <listing_id>` would have nothing to query without re-running the LLM. |
| Store tips as a JSONB column on `run_listings` | Avoids a table, but does not model the gap→tip relationship `listing_gaps` already establishes, and makes per-skill querying (P7) awkward. |
| Generate ungrounded tips when a listing has no corpus coverage | Fills the section every time, but reintroduces the unverifiable generic advice this feature exists to remove — and the validator would strip every URL such a call produced anyway. |
| Drop a whole tip on any grounding violation | Strictest reading of integrity, but discards otherwise-sound advice over a single bad link. FR-CC-9 says *strip the URL*; dropping only the tips left citing nothing preserves the guarantee without the collateral loss. |
| Put the stage in `scout/sub_agents/advisor/` | Matches the PRS's naming, but would make the Advisor depend on the Coach's retriever and corpus, inverting the dependency direction P1's amendment already corrected once. |
| Do nothing | The corpus (P1) and retriever (P2) exist and are consumed by nothing; without this phase both are dead weight and the seeker still sees static template advice. |

---

## Open Questions

| Question | Who decides | Blocks planning? |
|----------|-------------|------------------|
| Whether a listing should get a tip for a gap the corpus does not cover, once P4 can show a mixed state (some gaps cited, some not). | human (P4) | No — this phase stores nothing for uncovered gaps, which is the strictly smaller behaviour; P4 can choose what absence renders as without a schema change. |

> No question blocks planning.

---

## Amendments *(only after approval — never silently edit approved content)*

- **2026-07-27 — P2 merged; dependency and open question updated.** The spec
  was written while P2 was an unmerged branch, so it recorded P3 as branched
  off P2's tip and carried an open question about P2's API changing before
  merge. P1 and P2 have since squash-merged to `main` (#28, #30), and the P3
  branch was rebuilt on the updated `main` — `retrieve_for_skills` is now a
  merged, stable API. The dependency line and that open question are updated
  accordingly. No scope or requirement changed.
