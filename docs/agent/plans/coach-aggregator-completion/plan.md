# Plan: Coach Aggregator Completion & Ordering

> **Status:** Not started
> **Created:** 2026-07-30 · **Last updated:** 2026-07-30
> **Spec:** [spec.md](../../specs/coach-aggregator-completion/spec.md)

---

## Overview

Make an aggregation run survive a single bad candidate, and make whatever it
finishes be the part that matters. Ingest currently processes awesome-list
candidates before search-derived ones and dies on the first malformed LLM
response, which is why 957 resources exist and zero tips render. Done means a
run completes despite per-candidate failures, gap-relevant resources land
first, and job-detail pages show grounded tips for the most frequent gap
skills.

## Acceptance Criteria

- [ ] A candidate whose tagging returns malformed JSON is logged and skipped;
      the run continues and persists every other resource.
- [ ] Search-derived candidates are ingested before awesome-list survivors.
- [ ] A run whose failures exceed max(10, 20% processed) aborts with a clear
      error naming the count.
- [ ] A GitHub rate-limit 403 during the bootstrap filter still aborts the run.
- [ ] The end-of-run summary reports inserted, duplicate, no-README and failed
      counts.
- [ ] After one aggregation run, `resources` contains rows whose `skills`
      include single-token gaps observed uncovered in production —
      `terraform`, `snowflake`, `eks`, `ecs`, `bedrock`, `cicd`.
- [ ] After the following scout cycle, a job-detail page renders grounded tips
      for gaps outside the Python ecosystem — today only FastAPI/OAuth/RBAC/
      LangChain/LangGraph-style gaps are covered (spec A1).
- [ ] Compound-skill gaps (`awscloud`, `awssagemaker`) are reported as covered
      or uncovered, either way — that answer decides whether follow-on work on
      retrieval matching is needed (spec A2).
- [ ] A full run completes inside the 120-minute step bound.

---

## Risks & Unknowns

| Risk / unknown | Impact if wrong | Resolution |
|----------------|-----------------|------------|
| DeepSeek/LiteLLM behaviour under width-4 concurrent tagging — 429s, or throughput that does not scale | Phase 2's concurrency yields little, or introduces a new failure class | Spike: Phase 2 Task 1 measures a bounded concurrent batch before the loop is rewritten. Phases 1 and 3 do not depend on it |
| Malformed-JSON frequency is characterised by exactly one observation in ~920 candidates | The systemic threshold (20%) is mistuned — too loose to catch a real problem, or too tight and aborts healthy runs | Accepted risk, instrumented: the failed count is in the summary line, so the next runs characterise it. Threshold is a module constant, cheap to change |
| Exact-match retrieval defeats reordering for compound skills: `AWS Cloud` normalises to `awscloud`, which no resource tagged `aws` will ever match (spec A2). Separately, a searched repo may not be tagged with the skill that surfaced it | Reordering lands the right candidates but compound-skill gaps stay uncovered — the most valuable ones on the observed page are compound | Spike: Phase 3 Task 2 queries single-token and compound gap skills separately and reports each. A null result for compounds scopes a follow-on spec (retrieval matching / skill normalisation), it does not invalidate this plan |
| `complete_json` has no retry; a transient provider error is indistinguishable from malformed output at the call site | Transient blips consume the failure budget and could trip the systemic abort | Accepted risk: skipping is per-candidate and the next weekly run retries via dedup. Revisit only if the failed count is routinely non-trivial |
| The corpus already holds 957 rows from the partial run | A re-run's dedup makes phase 3's timings unrepresentative of a true cold seed | Accepted and noted: phase 3 records that it measured a warm run (~577 remaining candidates), not a cold seed |

## Blast Radius

- **Code that will change:** `scout/sub_agents/coach/runner.py`, `tests/`, and
  in phase 2 only, `scout/config.py` for the concurrency setting. Phase 3 may
  touch `.github/workflows/scheduled-run.yml` (comment only).
- **Existing behaviour that could break:** the weekly `Run coach aggregator`
  step; the ingest loop's insert path; nothing in the read path (retriever,
  tips, report) is touched.
- **Off-limits:** the retriever, the tagging prompt, `scout/shared/db.py`'s
  schema, and the 2.5s search throttle. Do not modify anything outside the
  directories above without flagging it to the human first.

---

## Phases

| # | Phase | Document | Status |
|---|-------|----------|--------|
| 1 | Completion and ordering | [phase-1-completion-and-ordering.md](phase-1-completion-and-ordering.md) | Not started |
| 2 | Concurrent ingest | [phase-2-concurrent-ingest.md](phase-2-concurrent-ingest.md) | Not started |
| 3 | Seed and verify in production | [phase-3-seed-and-verify.md](phase-3-seed-and-verify.md) | Not started |

> All phases are planned in advance — every row above has a written,
> human-approved phase doc before phase 1 execution starts. If executing
> an earlier phase surfaces a needed change to a later phase doc, update
> that doc explicitly and record the change in its Notes / Learnings
> section; don't leave later phases undocumented.

---

## Testing Strategy

- **Unit:** per-task TDD in the phase docs covers the ordering of the assembled
  candidate list, per-candidate failure isolation, the systemic abort
  threshold, rate-limit escalation surviving isolation, and the summary counts.
  Phase 2 adds concurrency tests using injected delays to prove overlap and
  injected failures to prove isolation holds under `gather`.
- **Integration:** the existing suite is the regression net — the ten
  `tests/test_coach_runner.py` tests already cover a fully-successful run end
  to end against a real local Postgres, and must stay green untouched, since a
  run with no failures should behave identically.
- **Manual:** phase 3 only — one dispatched run, read the summary line, query
  `resources` for the top gap skills, then confirm a job-detail page renders a
  grounded tip with a working citation.

## Rollout & Reversibility

- **Feature flag:** no. The changes are unconditional; concurrency width is a
  setting whose default of 1 would restore serial behaviour if needed.
- **Migrations:** none. No schema change; the corpus accumulates rows exactly
  as it does today.
- **Rollback plan:** revert the phase's commit and redeploy. The corpus is
  additive and idempotent per URL, so no data written under the new code needs
  undoing — a reverted run simply resumes the old behaviour on the same rows.

---

## Key Decisions & Constraints

- **Ordering is the highest-value line in the plan.** It is one change to how
  the candidate list is assembled, and it is what makes every partial run
  useful. It ships in phase 1 ahead of everything else.
- **Isolation is deliberately asymmetric.** A single candidate failing is
  noise and is skipped; a rate limit or a pattern of failures aborts loudly.
  Silent degradation is the failure mode this whole area has been fixing.
- **No retry on malformed output.** Skipping loses nothing durable — dedup
  means the next run tries the URL again — and a retry policy is a separate
  concern with its own budget and failure modes.
- **The skill-frequency threshold was dropped**, having been the previous
  draft's headline change. Measurement showed a full run already fits the
  bound, so trading 36% of gap-row coverage for time is a bad deal.
- **Concurrency is Should-have.** Phases 1 and 3 alone deliver working tips;
  phase 2 buys headroom and faster iteration. It can be cut without
  invalidating the rest.
- ⚠️ **One-way doors:** none. No schema change, no infrastructure, no
  irreversible cost. Phase 3 dispatches a run that costs VM time and LLM spend,
  which is recoverable and bounded.

## Out of Scope

- The gap-extraction defects producing prose as skills.
- Any change to the retriever's exact-match pre-filter or the tagging prompt.
- Corpus quality curation beyond the already-merged stars/freshness bar.
- The interactive Discord bot (P7) and anything requiring an always-on
  database.

---

## Definition of Done

- [ ] All acceptance criteria met
- [ ] All phase verification steps pass
- [ ] Feature verified manually in a running environment (phase 3)
- [ ] Docs updated where behaviour changed (the workflow's timeout comment)
- [ ] No new lint or type-check warnings

## Update Rules

- Phase docs hold task-level detail; this file holds phase-level status only.
- When a phase's scope changes, update its row here **in the same commit**.
- On conflict, this file wins for *what* the phases are; the phase doc
  wins for *how* its tasks are done.
