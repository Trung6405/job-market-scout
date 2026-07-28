# Spec: Career Coach P5 — Link-Health Checker

> **Status:** Approved
> **Created:** 2026-07-27 · **Approved:** 2026-07-28
> **Implementation plan:** [plan.md](../../plans/career-coach-p5-link-health/plan.md)
> **Umbrella PRS:** `docs/project/specification/career-coach-agent-prs.md` (v1.1) — this is phase **P5** of Stage 1, delivering FR-CC-10.

---

## Problem

The corpus records a resource once, at aggregation time, and never looks at it
again. Repositories get deleted, renamed, or made private, and the URLs the
coach hands the user are the exact URLs stored months earlier. Nothing in the
system ever observes whether one of them still resolves: `last_verified` was
added to the schema for precisely this purpose and no code has ever written to
it, so the retriever's staleness filter reads a column that is always NULL and
therefore excludes nothing. The whole point of grounding tips in a corpus is
that the resources are real and reachable; a confidently-cited 404 is
indistinguishable, from the user's side, from the hallucinated URL the
grounding work exists to prevent.

## Success Criteria

- Every resource in the corpus carries a recent verification record, acquired
  and maintained without anyone doing anything by hand.
- A resource whose URL is permanently gone stops being offered to the user
  within one check cycle of going dead, rather than lingering for months.
- A resource removed for failures returns to circulation on its own once its
  URL works again — no manual reinstatement, no re-aggregation.
- A network blip, rate limit, or brief host outage does not cost the corpus a
  healthy resource.
- Checking imposes no latency on tip generation and cannot fail the daily
  pipeline or the weekly aggregation.

---

## Requirements

### Must have

- A periodic process that verifies resource URLs over the network and records
  the outcome against each resource.
- Coverage of the **whole corpus**, oldest-checked-first, with a per-run cap so
  any single run is bounded and the corpus cycles through over consecutive
  runs.
- A successful check stamps the verification time and clears any accumulated
  failure state.
- A **permanent** failure — the URL definitively no longer exists (HTTP 404 /
  410) — removes the resource from retrieval immediately, on the first
  observation.
- A **transient** failure — timeout, DNS/connection error, 5xx, rate limiting,
  or an ambiguous authorization refusal — is tolerated up to a configured
  number of *consecutive* failures before the resource is removed.
- Removal is a reversible state: a later successful check restores the resource
  to retrieval automatically.
- Retrieval honours the removal, so a resource marked dead cannot be returned
  to the grounded-tip stage and therefore cannot be cited.
- The checker runs as its own independently-invocable job on its own periodic
  trigger, distinct from both the pipeline run and the weekly aggregation; a
  failed check run does not fail either of them.
- Per-run work is bounded by request timeout, concurrency, and the batch cap,
  so the job cannot hang or hammer a host.

### Should have

- A per-run summary of what happened — checked, healthy, newly dead, recovered,
  still failing — logged the way the aggregator logs its run summary.
- The reason a resource last failed retained on the row, so "why did this drop
  out" is answerable from the database without re-running anything.
- Redirects followed, with the final response deciding the outcome — a moved
  repository is healthy, not dead.

### Won't have

- **Quality or freshness judgements** — archived repos, abandoned projects,
  changed READMEs, star-count decay. Link health answers "does this URL still
  resolve", nothing more; content curation is the aggregator's filtering job
  (FR-CC-2).
- **Re-tagging or re-embedding** of resources whose content changed. That is
  aggregation work, and adds LLM and embedding cost to a job that should be
  pure network I/O.
- **Deleting dead rows.** Exclusion is reversible and deletion is not; a URL
  that 404s during an outage window should not be permanently unrecoverable,
  and the aggregator's duplicate-suppression relies on knowing a URL was
  already seen.
- **Notifying anyone** about dead links — no Discord push, no report section.
  Silent, self-healing corpus maintenance; the user's signal is simply that
  dead resources stop appearing.
- **Verification at retrieval time.** A synchronous network check inside the
  Advisor stage would blow NFR-CC-2's sub-100 ms retrieval budget and make tip
  generation depend on third-party availability.
- **Non-HTTP resource types.** Only `repo` is populated today and every source
  type the schema allows is URL-addressable.

---

## Proposed Approach

A standalone, periodically-triggered job that walks the corpus in
least-recently-checked order, requests each URL, and writes a health verdict
back to the resource row; retrieval then filters on that verdict.

**Health state on the resource.** Two additive columns join the existing
`last_verified`: a count of consecutive failed checks, and a timestamp marking
when the resource was judged dead (null while it is live). They are added
through the same idempotent `ALTER TABLE … ADD COLUMN IF NOT EXISTS` mechanism
the schema already uses, so no migration tooling is introduced and existing
rows default to healthy-and-unchecked.

**Verdicts.** Each check resolves to one of three outcomes, and the outcome
alone determines the state transition:

| Outcome | Observed | Effect on the row |
|---|---|---|
| Healthy | Final response after redirects is a success | Stamp `last_verified`, reset the failure count, clear the dead marker |
| Permanently gone | 404 / 410 | Mark dead immediately, increment the failure count |
| Transient failure | Timeout, DNS/connection error, 5xx, 429, or an ambiguous 401/403 | Increment the failure count; mark dead only once it reaches the threshold |

An ambiguous authorization refusal is deliberately classed as transient rather
than permanent: hosts return 403 for anti-bot and rate-limit reasons far more
often than because a resource is genuinely gone, and the consecutive-failure
threshold is exactly the mechanism for "probably fine, but prove it".

**Request shape.** A cheap request that does not download the body, falling
back to a full request for hosts that refuse the cheap one, with a short
timeout and modest concurrency. Checking is pure HTTP against the public URL —
no GitHub API, no PAT — so it stays source-agnostic as non-repo resource types
arrive, and consumes none of the aggregator's rate-limit budget.

**Retrieval.** The retriever's existing pre-filter gains one condition: a
resource marked dead is excluded, exactly as an unembedded or stale one already
is. The existing max-age rule is unchanged, and a never-checked resource
(`last_verified` null) still counts as live — new resources must be retrievable
before their first check, and once this phase ships that null is a transient
state the checker fills in rather than a permanent hole.

**Cadence.** The job is its own module entrypoint, mirroring the aggregator's,
invoked by its own step on the existing daily scheduled run — the VM is already
booted for the pipeline, so the check costs no additional boot. Running daily
against a per-run cap means the corpus is continuously cycled through between
weekly aggregations, satisfying NFR-CC-4, and a resource that dies is caught
within days rather than at the 90-day staleness horizon.

**Dependencies.** This phase depends on P0 (the `resources` table) and touches
P2's retrieval filter. It reads neither `listing_tips` nor the report, so it is
independent of P3 and P4 as *work*. It is not independent of them in *effect*:
P3 has merged, so the grounded-tip stage now calls the retriever on every
pipeline run, and excluding a dead resource from retrieval stops it reaching a
user's tips from the next run onward. Tips already stored from earlier runs keep
whatever URLs they cited — this phase changes what gets retrieved, not what was
already written.

## Alternatives Considered

| Alternative | Why rejected |
|-------------|--------------|
| Check only recently-surfaced URLs (those cited in `listing_tips`) — the literal reading of FR-CC-10 | Cheapest and prioritises what the user actually saw, but a dead resource that has not yet been cited stays retrievable indefinitely — so the first user-visible citation of it is guaranteed to be the dead one, which is exactly the failure this phase exists to prevent. Whole-corpus batching covers the same URLs, because the corpus is small enough to cycle. |
| Surfaced-first, then backfill the oldest with leftover budget | Best theoretical coverage, but adds prioritisation logic and a read of `listing_tips` to buy an ordering advantage that a small, fully-cycled corpus does not need. |
| Passive aging only: a failed check simply withholds the `last_verified` stamp and the row ages out after the 90-day window | Requires no schema or retriever change at all, but a 404'd repository keeps being cited for up to three months, which is precisely the user-visible failure this phase exists to remove. |
| Passive aging with a much shorter max-age window (e.g. 14 days) | Same zero-schema appeal and dead links expire fast, but it conflates "unchecked" with "dead": any missed run — the VM boots ~1 h/day — silently expires healthy resources, and the corpus can empty itself through infrastructure downtime alone. |
| Remove a resource on its first failure of any kind | Simple and strictly safe against dead links, but a single timeout or 429 discards a good resource until the next aggregation re-inserts it, and on a small corpus that measurably degrades coverage. |
| Delete dead rows outright | Loses the reversibility that makes an aggressive permanent-failure rule safe, and defeats the aggregator's duplicate suppression, which relies on knowing a URL was already seen. |
| Fold the check into the weekly aggregation run | Fewest moving parts, but it then runs only weekly and never *between* aggregations as NFR-CC-4 requires, and it couples corpus maintenance to a job that already carries the GitHub and LLM budget. |
| Run the check as a stage of the daily pipeline | Guaranteed to run whenever the VM is up with no new trigger, but it adds third-party network latency and a new failure mode to the run that produces the user's daily output, for work unrelated to it. |
| Do nothing | `last_verified` stays unwritten, the retriever's staleness filter stays inert, and the corpus decays silently — undermining the grounding guarantee the whole Career Coach feature is built on. |

---

## Open Questions

| Question | Who decides | Blocks planning? |
|----------|-------------|------------------|
| The concrete defaults for the consecutive-failure threshold, per-run batch cap, request timeout, and concurrency | human | No — all are environment-tunable settings alongside the existing `COACH_*` ones; sensible defaults can ship and be adjusted from observed run summaries. |
| Whether a never-checked resource should eventually stop counting as live once the checker has been running for a while | human | No — treating null as live is correct on day one and can only be revisited with real data about how quickly the corpus cycles. |
| Whether the daily cadence should be reduced once the corpus grows enough that a full cycle takes longer than intended | human | No — cadence lives in the schedule configuration and changes without code. |

> No question blocks planning.

---

## Amendments *(only after approval — never silently edit approved content)*

- **2026-07-28:** P3 merged to `main` (#33) between this spec's approval and the
  plan being written. Two consequences recorded rather than left stale: the
  Proposed Approach's dependency paragraph now says the grounded-tip stage is a
  *live* consumer of retrieval, so exclusion takes effect from the next pipeline
  run rather than "once P3 lands"; and the two surfaced-first alternatives no
  longer cite "depends on P3" as a reason for rejection, since that reason has
  expired. Both rejections stand on their coverage argument alone, so the chosen
  approach is unchanged.
- **2026-07-28:** P4 merged (#35), and with it the removal of its per-page link
  budget — every citation now renders as a live anchor on the job-detail page.
  No requirement changes; the stakes do. A dead URL is now a clickable 404 in
  front of the user rather than bare text, and the page's own empty state
  already promises "no *verified* learning resources," which only this phase
  makes literally true.
- **2026-07-28:** Recorded a consequence that only became real once tips are
  persisted: `listing_tips` rows written before a resource died keep citing its
  URL, because this phase changes what is retrieved, not what was already
  stored. No requirement changes — re-running the pipeline regenerates tips from
  the healthy corpus — but it is now stated rather than implied.
