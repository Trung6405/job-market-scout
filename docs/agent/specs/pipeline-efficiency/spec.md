# Spec: Pipeline Efficiency — Model Layer, Listing Lifecycle & Cleanup

> **Status:** Amended
> **Created:** 2026-07-24 · **Approved:** 2026-07-24 · **Amended:** 2026-07-24
> **Implementation plan:** [plan.md](../../plans/pipeline-efficiency/plan.md)

---

## Problem

The daily pipeline applies the student's preferences at a stage that makes
them destructive, and carries a batching bug it has already been bitten by
once. A listing that fails the configured location, remote or salary
preferences is withheld from scoring, so it never appears on the dashboard
at all — yet it is still sent for requirements extraction. The pipeline pays
for it and then hides it, inverting the intended split between the two
outputs: the dashboard is meant to be the full picture of the day's market,
and the brief the narrow slice worth acting on. Meanwhile the Scorer issues
a single model call covering every listing in the run, the same shape that
truncated the Advisor's output and aborted a run; it survives only because a
score is smaller per listing than a requirement list. Separately the listing
lifecycle churns: a listing that merely drops out of the search window is
recorded as closed and, on reappearing, is treated as brand new and analysed
again, and any cosmetic edit to a description has the same effect. Because
this project runs unattended on a schedule against a metered API, the waste
compounds silently. A smaller problem sits alongside: a same-day re-run
degrades the stored record of the earlier run rather than adding to it.

## Success Criteria

- Every listing tracked as new or changed in a run is scored and appears on
  that run's dashboard, whatever the student's stated preferences.
- The brief contains only listings that satisfy those preferences and the
  minimum score, so the two outputs differ by audience rather than by which
  listings were paid for.
- A score expresses how well the student fits the role, and is not depressed
  by a preference the brief already enforces.
- Requirements extraction continues to run without sight of the student's
  profile, so a stated requirement cannot be softened or omitted because the
  student happens not to meet it.
- No model call's output size scales with the number of listings in a run.
- A listing that remains genuinely open, but is absent from a given day's
  search results, is not re-analysed at full cost when it reappears.
- A single malformed listing from the scraper cannot terminate the run.
- A batch whose response fails to parse costs that batch's listings, not the
  whole day, and a failure in extraction never removes a listing from the
  dashboard.
- A second run on the same date never reduces the recorded scraped or scored
  counts of the first, and never removes gaps the first recorded for
  listings it did not itself re-analyse.
- The history page renders without loading every stored listing description
  for the last thirty runs.

---

## Requirements

### Must have

- Scoring applied to every new or changed listing in the run, with no
  preference-based exclusion beforehand.
- Preference filtering applied at brief selection only, alongside the
  existing minimum-score and maximum-match limits.
- Scores computed without reference to location, remote or salary
  preference, so that a role the student fits well is scored as such even
  when the brief will exclude it.
- Scoring batched on the same principle as extraction, so neither stage's
  response size grows with the run.
- Scoring and extraction kept as separate model calls, each reading the full
  description: the Scorer with the profile in context, the Extractor without
  it.
- Listing closure driven by how long a listing has gone unseen rather than
  by absence from the current run's results.
- Content-change detection insensitive to description-only edits.
- A same-day re-run that updates the run record in place without lowering
  its counts, and that replaces only the gap rows for listings it
  re-analysed.
- Per-listing tolerance in scraper normalisation: a listing missing an
  identifying field, or failing validation, is skipped and logged rather
  than propagating an exception.
- Per-batch tolerance in both model stages: a batch that fails to parse is
  retried once and then skipped with a warning.
- The history page's per-run statistics obtained without fetching full
  listing rows per run.

### Should have

- Batches dispatched concurrently under a bounded limit rather than strictly
  sequentially.
- An investigation into whether ordering both prompts so their listing
  payloads form a byte-identical prefix lets the second call bill against
  the provider's automatic prefix cache. Adopted only if measurement shows a
  real reduction — this is the one remaining way to stop paying twice for
  description tokens without merging the two stages.
- A one-off backfill that recomputes stored content hashes under the new
  definition, so the first run after deployment does not re-analyse the
  entire table.
- Removal of the accumulated dead weight identified in review: the empty
  tool modules, the always-true `has_profile` flag, the unused port exposure
  on a batch job, and the duplicated match join between the pipeline and the
  briefing.

### Won't have

- **Merging scoring and extraction into a single call.** Considered and
  rejected — see the Amendment below. The two stages read the same text but
  do different jobs under different information constraints, and merging
  would put the profile into extraction's context.
- Deriving the score from the extracted requirements rather than the
  description. The rubric depends on scope, responsibilities and the
  listing's framing, none of which extraction captures; feeding the Scorer a
  list of skill names would strip the signal that separates a 70 from an 85.
- Continued dependency on an external agent framework. The pipeline keeps
  its shape — a named agent object emitting a stream of status events
  consumed by the entrypoint — but expresses that shape in project-local
  types rather than imported ones.
- Removal of the agent shell itself. Only the dependency goes; the staged,
  event-emitting structure stays.
- Splitting runs into per-timestamp rows. The same-`run_date` model is kept
  deliberately, consistent with the decision recorded in the
  pipeline-hardening spec; this work makes that model non-destructive rather
  than replacing it.
- Any change to the scoring rubric's bands, thresholds, or skill/seniority
  reasoning. The only deliberate change to scoring is the removal of the
  preference inputs; the rubric text is otherwise carried across verbatim.
- Removal of `get_run_by_date` and `get_run_listings`. They appear unused by
  production code but are test assertion probes; they stay, and the reason
  is recorded so a later cleanup does not remove them.
- Any change to the scraping source, search parameters, or infrastructure
  topology.

---

## Proposed Approach

Three workstreams, each a phase.

**1. Replace the model layer, and move preference filtering to the brief.**
The agent framework wraps every model call in a per-call runner and session,
and each call is a single stateless turn with no tools, delegation or
retained history. It is replaced by one small helper that takes a prompt and
a schema and returns a validated object, so the framework leaves the
dependency set entirely. The pipeline keeps its agent shape — a named object
emitting status events the entrypoint logs — but the event and context types
become project-local, defined by what the pipeline actually uses.

The Scorer and Extractor remain two calls. Both gain shared batching with
bounded concurrency and per-batch failure isolation, which closes the
Scorer's latent truncation bug and stops either stage losing a whole run to
one malformed response. Preference filtering leaves the scoring path
entirely and moves to brief selection, joining the existing score threshold
and match cap; the scoring prompt correspondingly stops receiving preference
inputs, so a score describes fit alone and every listing reaches the
dashboard.

**2. Make the listing lifecycle and run record non-destructive.** Closure
becomes a function of elapsed time since a listing was last seen, using the
timestamp the upsert already maintains, rather than of membership in the
current result set; this removes the close-then-reopen cycle that makes the
system pay twice for one listing. The content fingerprint narrows to the
fields that change a listing's substance. The run record's scored count
becomes derived from the rows actually stored rather than reported by
whichever execution finished last, its scraped count is not lowered by a
later quieter execution, and gap replacement narrows from the whole run to
the listings being rewritten.

**3. Robustness and cleanup.** Normalisation gains per-item tolerance. The
history page gets a dedicated aggregate query in place of a per-run detail
fetch, and moves out of the run's transaction. The remaining dead weight is
removed.

## Alternatives Considered

| Alternative | Why rejected |
|-------------|--------------|
| Merge scoring and extraction into one call | Halves description input tokens, but puts the profile into extraction's context, where a model can soften a requirement the student doesn't meet — a silent false *clear*, worse than the false gaps the pipeline-hardening spec fixed. Also worsens failure blast radius (a skipped batch would drop listings from the dashboard entirely, not just their gaps) and does not reduce call count, since larger per-listing output forces smaller batches. |
| Chain the stages: extract first, then score from the extracted structure | Sends descriptions once and keeps extraction profile-blind, but the Scorer then never sees scope, responsibilities or the listing's framing — precisely the signal its seniority and fit rubric depends on. Trades a correctness loss for a token saving. |
| Filter on preferences *before* the model call, so rejected listings cost nothing | Cheapest option, and the one that entrenches the actual bug: the dashboard would remain a filtered view rather than the day's full market, which is the opposite of its purpose. |
| Keep preferences as scoring inputs, and filter at the brief as well | Counts preference twice — once softly in the score, once as a hard gate — so a strong role in the wrong city appears on the dashboard already marked down. |
| Keep the agent framework and merely consolidate its setup | The framework's cost is paid per call for capabilities the pipeline does not use. Consolidating the setup keeps the dependency and the indirection while removing only the smallest part of the cost. |
| Drop the agent shell along with the framework | Rejected in favour of keeping the shell. The staged, event-emitting shape is worth preserving on its own terms; only the external dependency is unwanted. |
| Age listings out, but leave the content fingerprint as-is | Addresses the larger churn source only. Description-only re-analysis remains, and it is common. |
| Do nothing | The dashboard continues to hide listings the pipeline paid to process, the Scorer keeps a known truncation bug, and the same-day re-run continues to under-report completed work. |

---

## Open Questions

| Question | Who decides | Blocks planning? |
|----------|-------------|------------------|
| Whether scores recorded before the preference inputs are removed should be marked as computed under a different rubric, or silently compared with later ones on the history page. | human | no |
| Whether a narrowed content fingerprint should still treat a *materially* rewritten description as a change. The spec accepts that it will not — a rewrite that genuinely alters requirements goes unnoticed until the listing changes another tracked field. | human | no |
| Whether the run's scraped count, on a same-day re-run, should be the larger of the two executions (reads as "size of today's market snapshot") or their sum (reads as "work performed"). The spec assumes the former. | human | no |
| Whether prefix-cache ordering actually reduces billed tokens for the second call. Resolved by measurement in Phase 1 rather than by decision. | spike | no |

> Questions marked "blocks planning: yes" must be resolved before
> plan.md is written. The rest carry into the plan's Risks & Unknowns.

---

## Amendments *(only after approval — never silently edit approved content)*

- **2026-07-24: the merge of scoring and extraction is withdrawn.** The
  approved spec required a single model call emitting score, reasoning and
  requirements together. Review before implementation found two faults in
  that decision.

  First, the stated benefit was overstated. The spec claimed merging
  guaranteed that a listing's score and its requirements "reflect the same
  reading". Nothing in the pipeline compares the two — gap detection uses
  requirements only, and the score is displayed independently — so they
  could never have disagreed in any observable way. The genuine benefit was
  narrower than described: input tokens roughly halve, but call count does
  not fall, because larger per-listing output forces a smaller batch size.

  Second, and decisive: `build_requirements_instruction` never renders the
  profile, so extraction today is profile-blind. That is load-bearing. A
  merged prompt necessarily places the student's resume in extraction's
  context, where a model can reasonably soften or omit a requirement the
  student does not meet. The result is a gap that silently disappears — a
  false clear, which is less detectable than the false gaps the
  pipeline-hardening spec was written to eliminate. Merging also worsens
  failure blast radius: under two calls a skipped extraction batch costs
  gaps, while under one it would drop those listings from the dashboard
  entirely.

  A chained variant (extract, then score from the extracted structure) was
  also considered and rejected: it preserves profile-blindness and sends
  descriptions once, but starves the Scorer of the scope and framing its
  rubric depends on.

  The two stages therefore stay separate, each reading the full description.
  Scorer batching — previously folded into the merged stage — becomes a
  requirement in its own right, since the single-call shape that truncated
  the Advisor is still present in the Scorer. The remaining opportunity to
  avoid paying twice for description tokens, prefix-cache ordering, is added
  as a Should-have gated on measurement.
