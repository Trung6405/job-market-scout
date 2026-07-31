# Spec: Coach Aggregator Completion & Ordering

> **Status:** Draft
> **Created:** 2026-07-30 · **Approved:** —
> **Implementation plan:** [plan.md](../../plans/coach-aggregator-completion/plan.md) *(created after approval)*

---

## Problem

The resource corpus now holds 957 resources and still produces zero grounded
tips: the 2026-07-30 20:10 UTC run skipped all 20 listings with
"no corpus coverage". Two independent defects, both observed in production
rather than inferred, explain it.

A seed run cannot finish. One candidate whose LLM tagging returned malformed
JSON raised out of the ingest loop and ended a 90-minute run at candidate 920
of 1,534 — every remaining candidate lost, and the run reported failure after
doing most of its work.

Worse, what survives a partial run is the *least* useful corpus available.
Ingest processes awesome-list candidates before search-derived ones, so the
resources keyed to actual gap skills are always last. The run died 46
candidates short of that boundary. The corpus is therefore Python and
web-framework material (python 398, docker 145, react 112, typescript 110)
while the gaps are cloud and enterprise (AWS 79, Terraform 40, CI/CD 39,
Azure 38, Java 38, .NET 22, C# 20). Retrieval pre-filters on exact normalised
skill match, so that mismatch yields nothing at all — the whole visible product
of the coach feature stays blank.

## Success Criteria

- A run that encounters malformed LLM output for one candidate finishes,
  reporting that candidate as skipped, and persists every other resource.
- After one further aggregation run, listings whose gaps include the most
  frequent skills (AWS, Terraform, Azure, Java, CI/CD) retrieve at least one
  resource, and grounded tips render on their job-detail pages.
- If a run is cut short for any reason, the resources it did persist are the
  ones tied to real detected gaps, not incidental bootstrap material.
- A run that fails systematically — many candidates failing, or a rate limit —
  still aborts loudly rather than completing with a quietly thin corpus.
- A full seed run completes inside the existing 120-minute bound without
  raising that bound.

---

## Requirements

### Must have

- Search-derived candidates ingested before awesome-list survivors, so partial
  completion always favours resources matching detected gaps.
- Per-candidate failures during ingest — malformed LLM output, an unreadable
  README, any single-candidate error — logged, counted, and skipped rather
  than ending the run.
- A systemic-failure guard that aborts the run when failures exceed
  max(10, 20% of candidates processed), so isolation never becomes silent
  degradation.
- GitHub rate-limit responses (403 with exhausted quota) remain loud and fatal,
  as the bootstrap metadata filter already treats them.
- The end-of-run summary reports inserted, duplicate, skipped-no-README and
  failed counts, so a partially-degraded run is legible from the log alone.

### Should have

- Candidate ingest performed concurrently at a configurable width (default 4),
  with database writes remaining strictly serial on the single connection, and
  chunked (process N, then write that chunk) so memory stays bounded and
  progress logs state a truthful position.
- The bootstrap metadata filter given the same chunked concurrency — it is pure
  I/O against the 5,000/hr core REST limit.
- The 120-minute workflow comment updated once a completed run confirms real
  end-to-end timings.

### Won't have

- **A skill-frequency threshold.** An earlier draft proposed searching only
  skills appearing twice or more, to cut gather from ~39 to ~9 minutes. The
  measured run invalidates the trade: a full run is ~94 minutes, already inside
  the bound, and the threshold would discard 36% of gap-row coverage — coverage
  being the very thing that is broken. Revisit only if runtime becomes binding
  again.
- Any change to the 2.5s GitHub Search throttle — that is GitHub's 30/min cap.
- Retrying malformed LLM responses. Skipping is sufficient and bounded; a retry
  policy is a separate concern with its own cost and failure modes.
- Fixing the gap-extraction defects that emit prose as skills — extractor work,
  tracked separately.
- Raising `timeout-minutes`.

---

## Proposed Approach

Three changes to the aggregator's ingest phase, in decreasing order of value.

**Ordering.** The candidate list is assembled bootstrap-first today. Reversing
it so search-derived candidates lead costs one line and changes the value of
every partial run: whatever gets done is the part tied to real gaps. This alone
would have turned the failed run's 957 useless resources into 957 useful ones.

**Isolation.** The per-candidate body (README fetch, LLM tag, embed, insert)
is wrapped so any exception from a single candidate is recorded and skipped.
A running failure count is compared against the systemic threshold; crossing it
raises and ends the run. Rate-limit errors bypass isolation entirely and remain
fatal. The distinction is deliberate and mirrors the bootstrap filter: one bad
candidate is noise, a pattern of failures is a thin corpus nobody notices.

**Concurrency.** The per-candidate body becomes a coroutine; candidates run in
chunks of the configured width via `gather(return_exceptions=True)`; each
chunk's successes are inserted serially on the one open connection before the
next chunk begins. Measured per-candidate cost is 1.8s and almost entirely
network and LLM latency, so width 4 should bring a ~1,500-candidate seed run
from ~46 minutes of ingest to roughly 12-15, leaving comfortable headroom under
the bound.

Measured baseline from run 30518526859, for reference: bootstrap harvest 1,281
links → 966 kept after the quality bar (9.0 min); gather 946 distinct skills
(~39 min); ingest 1,534 deduped candidates at 1.8s each; projected total ~94
minutes. A re-run against the current corpus dedups the 957 stored rows, so
only ~577 candidates remain.

## Alternatives Considered

| Alternative | Why rejected |
|-------------|--------------|
| Skill-frequency threshold (the previous draft's headline change) | Measured data killed it: the run already fits the bound, and the threshold trades away 36% of gap-row coverage to save time that is not scarce. Recorded in Won't have. |
| Retry malformed LLM responses instead of skipping | Adds a retry budget, backoff policy, and a new failure mode, to recover a candidate the next weekly run will retry anyway via dedup. Skipping is strictly simpler and loses nothing durable. |
| Sort candidates by gap frequency rather than just search-before-bootstrap | Marginal gain over the one-line reorder, and it couples the aggregator to gap-frequency data it does not otherwise need. |
| Raise `timeout-minutes` to fit a slower run | Licenses a stuck weekly run to hold the VM for hours — the failure the bound exists to prevent. |
| Do nothing | The corpus stays 957 mismatched resources, tips stay blank, and every seed attempt keeps dying on the first malformed LLM response. |

---

## Open Questions

| Question | Who decides | Blocks planning? |
|----------|-------------|------------------|
| Does DeepSeek via LiteLLM tolerate width-4 concurrent tagging without 429s, and does `complete_json` already retry transport errors? | spike (read `scout/shared/llm.py`; confirmed by a real run) | no |
| How often does malformed JSON actually occur? One occurrence in ~920 candidates is the only datapoint; if it is far more frequent, the systemic threshold may need tuning. | observed over the next runs | no |

---

## Amendments *(only after approval — never silently edit approved content)*

### A1 — Tips do render; the split confirms the ordering diagnosis *(2026-07-30)*

The Problem section says the corpus "produces zero grounded tips". That was
drawn from one run's log, where all 20 listings reported no coverage, and it
overstates the case. A rendered job-detail page shows tips present for
**FastAPI, OAuth, RBAC, LangChain, LangGraph** — citing `fastapi/fastapi`,
`oauthlib`, `authlib`, `langchain-ai/langchain` — and absent for **AWS
SageMaker, Snowflake, AWS Cloud, EKS, ECS, Bedrock, Semantic Kernel,
HuggingFace, CI/CD**.

The pipeline therefore works end to end; the corpus is simply the wrong half.
Every gap with a tip is Python-ecosystem, matching the awesome-list harvest;
every gap without one is cloud/ML-ops, matching precisely the search-derived
candidates that were never ingested. This is stronger evidence for the ordering
requirement than the original observation, not weaker — and it raises the
stakes, because nearly all the uncovered gaps are **must-have**.

### A2 — Exact-match retrieval may defeat reordering for compound skills *(2026-07-30)*

The plan's risk table notes that a searched repo may not be tagged with the
skill that surfaced it. The real problem begins earlier, on the gap side.
`normalize_skill` maps `AWS Cloud` to `awscloud` and `AWS SageMaker` to
`awssagemaker`; the retriever pre-filters on exact normalised match, so a
resource tagged `aws` matches neither. Ingesting AWS material fixes these gaps
only if the tagger independently emits the same compound token.

This does not change any requirement here — reordering remains necessary, and
its value for single-token gaps (`terraform`, `snowflake`, `eks`, `ecs`,
`bedrock`, `cicd`) is unaffected. It does mean phase 3's coverage check must be
read as a diagnostic rather than a formality: if compound-skill gaps stay
uncovered after a full run, the follow-on work is retrieval matching or skill
normalisation, and belongs to a separate spec.

*(Related: the same page lists `HuggingFace` and `Hugging Face` as two gaps at
different requirement levels. Both normalise to `huggingface`, so retrieval is
unaffected — it is the extractor emitting one skill twice, cosmetic here and
tracked with the other gap-extraction defects.)*
