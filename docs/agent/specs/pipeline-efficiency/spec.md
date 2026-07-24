# Spec: Pipeline Efficiency — LLM Consolidation, Listing Lifecycle & Cleanup

> **Status:** Draft
> **Created:** 2026-07-24 · **Approved:** —
> **Implementation plan:** [plan.md](../../plans/pipeline-efficiency/plan.md) *(created after approval)*

---

## Problem

The daily pipeline repeatedly pays for language-model work it has already
done, or has already decided to throw away. Every listing's description is
sent to the model twice — once to be scored, once to have its requirements
extracted — even though both readings answer overlapping questions about
the same text. Listings that the configured location, remote and salary
preferences have already rejected are still sent for extraction, and their
results are then discarded unused. Separately, the listing lifecycle churns:
a listing that merely drops out of the search window is recorded as closed
and, on reappearing, is treated as brand new and paid for again, and any
cosmetic edit to a description has the same effect. Because this project runs
unattended on a schedule against a metered API, the waste compounds silently
and scales with the size of the job market rather than with anything the
student actually gains. A second, smaller problem sits alongside it: a
same-day re-run degrades the stored record of the earlier run rather than
adding to it, so the dashboard can show a day's work as less than it was.

## Success Criteria

- A listing's description is sent to the language model at most once per
  run in which that listing is analysed.
- A listing rejected by the configured preferences never reaches the
  language model at all.
- A listing that remains genuinely open, but is absent from a given day's
  search results, is not re-analysed at full cost when it reappears.
- A run's score and its extracted requirements always reflect the same
  reading of the listing, and cannot disagree.
- A single malformed listing from the scraper cannot terminate the run.
- A batch whose response fails to parse costs that batch's listings, not
  the whole day.
- A second run on the same date never reduces the recorded scraped or
  scored counts of the first, and never removes gaps the first recorded
  for listings it did not itself re-analyse.
- The history page renders without loading every stored listing description
  for the last thirty runs.

---

## Requirements

### Must have

- Scoring and requirements extraction performed by a single model call per
  batch, emitting score, reasoning, requirement lists and the seniority /
  work-type / team facts together.
- Preference filtering applied once, in the pipeline, before any model
  call — not inside a stage's construction.
- Listing closure driven by how long a listing has gone unseen rather than
  by absence from the current run's results.
- Content-change detection insensitive to description-only edits.
- A same-day re-run that updates the run record in place without lowering
  its counts, and that replaces only the gap rows for listings it
  re-analysed.
- Per-listing tolerance in scraper normalisation: a listing missing an
  identifying field, or failing validation, is skipped and logged rather
  than propagating an exception.
- Per-batch tolerance in analysis: a batch that fails to parse is retried
  once and then skipped with a warning.
- The history page's per-run statistics obtained without fetching full
  listing rows per run.

### Should have

- Batches dispatched concurrently under a bounded limit rather than
  strictly sequentially.
- A one-off backfill that recomputes stored content hashes under the new
  definition, so the first run after deployment does not re-analyse the
  entire table.
- Removal of the accumulated dead weight identified in review: the empty
  tool modules, the always-true `has_profile` flag, the unused port
  exposure on a batch job, and the duplicated match join between the
  pipeline and the briefing.

### Won't have

- Splitting runs into per-timestamp rows. The same-`run_date` model is kept
  deliberately, consistent with the decision recorded in the
  pipeline-hardening spec; this work makes that model non-destructive
  rather than replacing it.
- Changing the scoring rubric or the extraction instructions themselves.
  Their text is carried across verbatim so that any score movement is
  attributable to consolidation, not to reworded guidance.
- Removal of `get_run_by_date` and `get_run_listings`. They appear unused
  by production code but are test assertion probes; they stay, and the
  reason is recorded so a later cleanup does not remove them.
- Any change to the scraping source, search parameters, or infrastructure
  topology.

---

## Proposed Approach

Three workstreams, each a phase, ordered so the riskiest lands first while
the test suite is still shaped around it.

**1. Consolidate the model layer.** The agent framework currently wraps
every model call in a per-call runner and session, and each call is a
single stateless turn with no tools, delegation or retained history. It is
replaced by one small helper that takes a prompt and a schema and returns a
validated object, so the framework leaves the dependency set entirely and
the pipeline itself becomes a plain asynchronous function that logs its
progress. On top of that helper, scoring and extraction merge into one
analysis stage producing a single per-listing result. The stage that owns
this call is separated from the stage that interprets it: one package for
what the model concluded, another for the deterministic banding, gap
matching and rendering built on top. Preference filtering moves ahead of
the call, and batching — now governing a larger per-listing output —
gains a smaller default, bounded concurrency, and per-batch failure
isolation.

**2. Make the listing lifecycle and run record non-destructive.** Closure
becomes a function of elapsed time since a listing was last seen, using the
timestamp the upsert already maintains, rather than of membership in the
current result set; this removes the close-then-reopen cycle that makes the
system pay twice for one listing. The content fingerprint narrows to the
fields that change a listing's substance, so re-wording does not trigger
re-analysis. The run record's scored count becomes derived from the rows
actually stored rather than reported by whichever execution finished last,
and its scraped count is not lowered by a later, quieter execution; the gap
replacement narrows from the whole run to the listings being rewritten.

**3. Robustness and cleanup.** Normalisation and analysis both gain the
per-item tolerance described above. The history page gets a dedicated
aggregate query in place of a per-run detail fetch, and moves out of the
run's transaction. The remaining dead weight is removed.

## Alternatives Considered

| Alternative | Why rejected |
|-------------|--------------|
| Keep scoring and extraction as separate calls, and only fix the wasted ones | Smaller blast radius, but leaves the description tokens paid for twice — the single largest recurring cost — and leaves score and requirements free to reflect two different readings of the same listing. |
| Keep the agent framework and merely consolidate its setup | The framework's cost is paid per call for capabilities the pipeline does not use: no tools, no delegation, no retained session. Consolidating the setup keeps the dependency and the indirection while removing only the smallest part of the cost. |
| Age listings out, but leave the content fingerprint as-is | Addresses the larger churn source only. Description-only re-analysis remains, and it is common: boards re-word and re-timestamp postings routinely. |
| Narrow the fingerprint, but leave closure as-is | Cheapest possible change, and the one that leaves the dominant cost driver — the close/reopen cycle — untouched. |
| Split into two or three separate specs | The three areas overlap in the same files and share one rationale; separate approval gates would multiply bookkeeping without improving isolation. |
| Do nothing | The waste scales with the job market rather than with the value delivered, and the same-day re-run continues to under-report completed work on the dashboard. |

---

## Open Questions

| Question | Who decides | Blocks planning? |
|----------|-------------|------------------|
| Whether a narrowed content fingerprint should still treat a *materially* rewritten description as a change. The spec accepts that it will not — a rewrite that genuinely alters requirements goes unnoticed until the listing changes another tracked field. | human | no |
| Whether the run's scraped count, on a same-day re-run, should be the larger of the two executions (reads as "size of today's market snapshot") or their sum (reads as "work performed"). The spec assumes the former. | human | no |

> Questions marked "blocks planning: yes" must be resolved before
> plan.md is written. The rest carry into the plan's Risks & Unknowns.

---

## Amendments *(only after approval — never silently edit approved content)*

- —
