# Spec: Career Coach P4 — Report Surfacing of Grounded Tips

> **Status:** Draft
> **Created:** 2026-07-27 · **Approved:** —
> **Implementation plan:** [plan.md](../../plans/career-coach-p4-report-surfacing/plan.md) *(created after approval)*
> **Umbrella PRS:** `docs/project/specification/career-coach-agent-prs.md` (v1.1) — this is phase **P4** of Stage 1.
> **Depends on:** P0 (`resources` + pgvector, merged), P1 (aggregator, merged as
> #28), P2 (`retrieve_for_skills`, merged as #30), P3 (grounded tips — this
> phase branches off `feat/career-coach-p3-grounded-tips` and consumes the
> persistence round trip its Phase 1 landed).

---

## Problem

Since P3 the pipeline generates coaching tips that cite only resources proven
to exist in the corpus, and stores them against each run — but the job seeker
never sees them. The per-role detail page still ends with the same static
"How to position your application" block it has always had: three hard-coded
branches that read the gap list back as prose ("Prioritize Kubernetes — it's
the highest-impact gap"), naming no resource and telling the reader nothing
they cannot see in the gap list two inches above.

So the whole Stage 1 chain — a weekly-aggregated corpus, semantic retrieval,
grounded generation, deterministic URL validation — currently terminates in a
database table nothing reads. Every run spends LLM calls producing advice that
is discarded at the last step. Until the report shows the tips, none of the
preceding four phases has delivered anything the user of this product can act
on, and the grounding guarantee that justified the whole approach is
unobservable to the person it was built to protect.

## Success Criteria

- Opening a job-detail page for a listing whose gaps have stored tips shows,
  for each such gap, the advice written for that gap and a working link to the
  cited resource.
- A reader can tell which gap a piece of advice answers without matching names
  across two sections of the page.
- A page never stacks citations to the point of being skimmed past: advice for
  a single gap may carry up to three links, while several tipped gaps carry
  one each — and no gap's advice names a resource the reader cannot open.
- A gap with no stored tip, and a listing with no stored tips at all, render
  without generic filler advice and without a visibly broken or empty section.
- Re-rendering a historical run recorded before tips existed produces a page
  that is coherent and honest about having no advice, rather than one missing
  a section or asserting templated claims.
- Tip text cannot inject markup into the page, and a citation cannot navigate
  the reader anywhere but an `http`/`https` address.

---

## Requirements

### Must have

- Surface each stored grounded tip on the per-role detail page, replacing the
  static templated positioning advice for listings that have gaps (FR-CC-11).
- Render a tip inside the gap block of the gap it answers, matched on the gap
  skill's raw stored wording, so advice and gap are adjacent rather than
  cross-referenced by name.
- Render at most one tip per gap. If more than one stored tip matches a gap,
  the first in stored order wins and the rest are not rendered.
- Render no tip whose gap skill matches none of the listing's gaps.
- Hold the whole listing to a citation budget of three links, divided evenly
  across the gaps that have tips: a gap's cap is `max(1, 3 // tipped_gaps)`,
  so one tipped gap may show three links and three tipped gaps show one each.
  Any remainder goes unused — every tipped gap gets the same cap.
- Never drop a tipped gap's only citation to stay inside the budget: with four
  or more tipped gaps the cap floors at one link each and the page carries
  more than three, rather than showing advice whose resource is unreachable.
- Render cited URLs as working links, with a readable label rather than a bare
  URL string. Beyond a gap's cap, a URL still in the tip's prose renders as
  inert text, not a link.
- Render a Markdown-style citation, `[label](url)`, as a single anchor whose
  visible text is the label — never as literal brackets and parentheses around
  a link. P3 leaves that syntax intact for any URL it does not strip, so it
  reaches this phase as stored text.
- Count the citation budget in distinct URLs. A tip naming the same resource
  twice spends one link, not two.
- Find URLs with the same lexing P3's validator uses, so a URL P3 validated and
  stored is always one this phase can linkify.
- Escape tip text before any link markup is inserted — tip text is LLM output
  and reaches the page through a filter that opts out of Jinja autoescape, so
  the filter itself must neutralise markup.
- Restrict linkification to `http` and `https`; any other scheme renders as
  inert text.
- Render a gap that has no stored tip exactly as the page renders it today —
  skill name and requirement pill, no placeholder.
- Render a listing that has gaps but no stored tips with a single explicit
  line stating that no verified resources exist for them yet.
- Delete the static "How to position your application" section and its three
  hard-coded branches outright — no fallback path that resurrects them.
- Order gaps must-have first, so priority is carried by position and pill
  rather than by prose restating the list.
- Change no schema, no persistence code, and no coach-stage code — P3's read
  path already supplies everything this phase displays.

### Should have

- The linkified label drops scheme and `www.`, so a citation reads as
  `github.com/kubernetes/kubernetes`.
- The citation budget is a named constant in the renderer, not an env-var
  setting — it is a layout judgement about how many links a page can carry
  before they stop being read, not something a deployment tunes.
- Tip styling reuses the detail page's existing visual vocabulary (the gap
  block and callout treatments already defined) rather than introducing a new
  component.

### Won't have

- Any change to `listing_tips`, `record_listing_tips`, `get_run_details`, or
  the `GroundedTip` model — P3 owns them and landed them complete.
- Resource **titles** on citations. `listing_tips` stores URLs only; showing
  titles would mean joining `cited_urls` back to `resources` in the read path,
  which is a P3-owned change for a cosmetic gain.
- Surfacing tips on the dashboard, history, or profile pages — FR-CC-11 names
  the per-role detail page, and the dashboard is a ranked index, not a place
  for per-gap advice.
- Re-verifying that a cited URL is still reachable at render time — a URL is
  trusted because it is in the corpus, and ageing dead ones out is P5.
- Any change to gap detection, `listing_gaps`, or `profile.json` — out of
  scope for the whole feature (umbrella §2.2).
- Serving tips over Discord (P7).

---

## Proposed Approach

The change is confined to the Advisor's presentation layer: the job-detail
template and one new Jinja filter registered beside the four the renderer
already has. Nothing is added to the render context — P3's Phase 1 put
`tips: list[GroundedTip]` on `RunListingDetail` and populated it in
`get_run_details`, so the template already receives everything it needs and a
re-render costs no LLM call.

**One home for coaching.** The page currently splits the topic across two
adjacent sections: "Skill gaps to close" lists gaps with no advice, and "How
to position your application" gives advice naming no resource. Tips are keyed
per gap, so the split has no reason to survive: the gap block becomes the
single place where a gap and its advice appear together, and the positioning
section is deleted. Matching is on `GroundedTip.gap_skill` against
`SkillGap.skill` — both hold `listing_gaps.skill`'s raw stored wording, which
is precisely why P3 chose to store it unnormalized.

Deleting rather than keeping the old block as a fallback is the deliberate
call. A fallback would look harmless — old runs keep rendering as they do
today — but it would preserve the generic restate-the-gap-list prose this
feature exists to remove, permanently, in a second template path that only
ever runs when the real feature has nothing to say. The honest empty state is
one line admitting the corpus has no coverage yet, which is both true and
more useful than advice that was never specific in the first place.

Losing the static block also loses the one thing it did that no tip replaces:
prioritisation. A grounded tip says how to learn a skill, not which skill to
learn first. That is recovered structurally rather than in prose — gaps render
must-haves first, the requirement pill already marks each one, and the
existing callout above the list already frames must-haves as the ones that
matter. No sentence needs to name them.

**Citation rendering.** A `linkify` filter takes the tip text and a link limit
and returns markup. It locates URLs in the raw stored text, then builds its
output piecewise — each run of prose escaped, each anchor assembled around an
escaped URL — so every character passes through escaping exactly once and the
anchors, being assembled last, cannot be destroyed by it. Locating URLs before
escaping rather than after is what keeps the spans identical to the ones P3
validated; matching on escaped text would also collide with entities, since a
URL ending in `&` becomes `&amp;` and trailing-punctuation trimming would then
corrupt it.

A URL written as Markdown, `[label](url)`, becomes one anchor carrying the
model's own label — the tip was written around that wording, so it reads better
than a derived one and leaves no stray punctuation. A bare URL gets a derived
label instead: host plus path, scheme and `www.` removed. Any URL past the
limit is left as escaped text — visible, unclickable, and not silently deleted
from advice that was written around it.

Escaping is the security-relevant half and is the filter's own responsibility:
returning `Markup` opts the value out of Jinja's autoescape, so nothing else
will do it. This is the same shape as
the existing `markdown` filter, which renders listing descriptions with
`html=False` for the same reason and is already covered by an
injection-neutralisation test. Restricting to `http`/`https` means a
`javascript:` or `data:` URL in tip text renders as visible inert text, not a
link — defence against a class of input that the corpus should never contain
but that arrives via an LLM.

**Relationship to P3's extractor.** The two stay separate in policy and
identical in lexing. P3's validator decides what may be *stored*; this filter
decides what is *clickable*, and folding them together would let a presentation
change alter the grounding guarantee. But they must agree on where a URL starts
and ends: if this phase found a different span than P3 did, it could fail to
linkify a URL P3 validated and stored, or link a fragment of one. So the URL
pattern and the trailing-punctuation trimming are deliberately copied from
`scout/sub_agents/coach/grounding.py` rather than reinvented, with a comment on
each side saying so.

Keeping the citation inline rather than as a separate chip row follows from
what P3 stores: the surviving URLs are already embedded in the tip's prose,
and `cited_urls` is the post-validation audit record, not a display list.
Rendering both would print each URL twice; rendering only the chips would mean
re-parsing URLs out of the text in the renderer, duplicating the extractor
that is P3's grounding boundary.

**How many links a page carries.** P3 injects two or three resources per gap,
so a listing with several gaps could accumulate a dozen citations — at which
point the reader skims past all of them and the grounding work buys nothing.
The page therefore spends a budget of three links, divided evenly across the
gaps that actually have tips: `max(1, 3 // tipped_gaps)`, counted in distinct
URLs so a tip naming one resource twice spends one link. One gap with advice
gets the full three — which is exactly one gap's worth, since `COACH_TOP_K`
defaults to 3 and bounds what P3 can inject per gap; three gaps get one each. The division is deliberately
uniform rather than remainder-aware — two tipped gaps get one link each and
the third goes unspent — because a rule that hands a spare link to whichever
gap sorts first makes two visually equal blocks unequal for a reason the
reader cannot see, and the saving is one link.

The budget is a ceiling on stacking, not on coverage: it floors at one link
per tipped gap, so a listing with five tipped gaps carries five links rather
than leaving two gaps citing a resource the reader cannot open. Advice that
names a resource and does not link it reads as a broken page, which costs more
trust than a fourth link costs attention.

```
get_run_details ──► RunListingDetail.tips: list[GroundedTip]   ← P3, already landed
                          │
                          │  cap = max(1, 3 // number of gaps with a tip)
                          ▼
   job-detail.html.jinja: for each gap (must-haves first)
                          │
                          ├─ first matching tip? ──yes──► tip text | linkify(cap)
                          │                       ──no───► skill + pill only (as today)
                          │
                          └─ no tips at all on the listing ──► one "no verified
                                                               resources yet" line

   tips matching no gap ──► not rendered
   (section "How to position your application" — deleted)
```

## Alternatives Considered

| Alternative | Why rejected |
|-------------|--------------|
| Replace the static `<ol>` in place, keeping both sections | Closest literal reading of FR-CC-11, and the smallest diff. But it leaves gaps in one section and their advice in another, so the reader matches tip to gap by skill name across a page break — the exact indirection that makes the current advice feel generic. |
| Keep the static block as a fallback when a listing has no tips | Nothing regresses for historical runs. But it makes the templated generic advice permanent, in a branch that fires precisely when the feature has nothing real to offer, and leaves the template carrying two coaching paths indefinitely. |
| Render nothing when a listing has no tips | Least code, but a page that used to end with advice would end with a bare list of skill names and no explanation, and the reader has no way to know a tips feature exists at all. |
| Render `cited_urls` as a separate chip row below the prose | Visually tidier, but the URLs are already in the tip text, so either each appears twice or the renderer re-parses and strips URLs — re-implementing P3's extractor in the presentation layer, where a divergence would silently change what the grounding guarantee means. |
| Link every valid URL, no budget | Simplest and most faithful to the stored tip. But P3 injects 2–3 resources per gap, so a listing with five gaps could carry a dozen links; past a handful the reader stops treating any of them as a recommendation and the grounding work buys nothing. |
| Hard budget of three: gaps past the third show their URL as inert text | Honours the number exactly. But the reader sees advice naming a specific resource with no way to reach it, which reads as a rendering bug rather than a deliberate limit — a worse failure than a fourth link. |
| Hard budget of three: drop tips entirely past the third gap | Cleanest-looking page and a strict ceiling, but it discards generated, validated advice the pipeline already paid for, and the gap it hides is indistinguishable from one the corpus never covered. |
| Give the spare link to the highest-priority gap when the budget divides unevenly | Uses the full budget, and must-haves already sort first so the extra would land sensibly. Rejected because it makes two otherwise-equal gap blocks visibly unequal for a reason invisible to the reader, and buys exactly one link in the two-gap case. |
| Show resource titles instead of URL labels | Better reading, but titles are not in `listing_tips`; it needs a `cited_urls`→`resources` join in `get_run_details`, which is P3's code and a persistence change this phase's scope fence excludes for a cosmetic gain. |
| Linkify by rendering tip text through the existing `markdown` filter | Reuses a filter already present and already injection-tested. But markdown-it does not autolink bare URLs by default, tips are not authored as Markdown, and incidental characters in generated prose (`*`, `_`, `#`) would silently restyle the text. |
| Keep an explicit prioritisation sentence naming the top must-have gap | Most explicit about ordering, but it is exactly the restate-the-list template prose being removed, and must-have-first ordering plus the existing pill carries the same information without a generated-looking sentence. |
| Do nothing | P1–P3 terminate in a table nothing reads; every run spends LLM calls on advice that is discarded, and the seeker still sees static template prose. Stage 1 delivers no user-visible value without this phase. |

---

## Open Questions

P3's spec deferred one question to this phase: what a gap the corpus does not
cover should render as, once a mixed state is displayable. It is **resolved**
here — an uncovered gap renders exactly as it does today, skill name and
requirement pill with no tip and no placeholder, and only a listing with no
tips at all draws an explicit line. No schema change was needed, as P3
anticipated.

| Question | Who decides | Blocks planning? |
|----------|-------------|------------------|
| Whether P5's link-health state should visibly mark a citation whose resource has since failed verification, rather than the tip simply ageing with the run. | human (P5) | No — this phase renders what the run stored, and marking staleness needs `last_verified` on the read path, which P5 introduces. |

> No question blocks planning.

---

## Amendments *(only after approval — never silently edit approved content)*

- *(none yet)*
