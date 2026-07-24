# Plan: Pipeline Efficiency — LLM Consolidation, Listing Lifecycle & Cleanup

> **Status:** In progress
> **Created:** 2026-07-24 · **Last updated:** 2026-07-24
> **Spec:** [spec.md](../../specs/pipeline-efficiency/spec.md)

---

## Overview

Drop the `google-adk` dependency while keeping the pipeline's agent shell,
give the Scorer the batching the Extractor already has, and move preference
filtering from before the model call to brief selection. Then make the
listing lifecycle and run record non-destructive, and clear the robustness
and dead-weight items found in review. Done looks like: a run scores every
tracked listing, the dashboard shows all of them, the brief shows only the
ones matching `.env` preferences, and a second run on the same date adds to
the first rather than degrading it.

The Scorer and Extractor stay separate stages. Merging them was approved and
then withdrawn — see the spec's Amendment.

## Acceptance Criteria

- [x] A full `docker compose run --rm app` cycle completes with no
      `google-adk` import anywhere in `scout/`.
- [x] Neither stage's response size scales with the number of listings in
      the run.
- [x] `build_requirements_instruction` output never contains the profile.
- [x] A listing failing `REMOTE_ONLY` / `PREFERRED_LOCATIONS` / `MIN_SALARY`
      appears on the run's dashboard with a score, and is absent from the
      Discord brief.
- [x] A score is unchanged by editing the three preference settings.
- [ ] A listing absent from one day's scrape but seen within
      `LISTING_STALE_DAYS` stays `open` and is not re-analysed.
- [ ] Editing only a listing's description text does not mark it `changed`.
- [ ] Running the pipeline twice on one date leaves `listings_scraped` and
      `listings_scored` at or above the first run's values, and leaves the
      first run's gaps intact for listings the second did not re-analyse.
- [ ] A malformed scraper job and an unparseable model batch each produce a
      warning and a completed run.
- [ ] `pytest` passes with no new lint or type-check warnings.

---

## Risks & Unknowns

| Risk / unknown | Impact if wrong | Resolution |
|----------------|-----------------|------------|
| `litellm` may not honour `response_format={"type":"json_object"}` for `deepseek/deepseek-chat` when called directly rather than through ADK's `LiteLlm` wrapper | Phase 1's helper returns prose and every parse fails | **Spike: Phase 1 Task 1.** One live call asserting parseable JSON before the helper is built on top of it. |
| Prefix-cache ordering may not reduce billed tokens at all | The one remaining way to stop paying twice for description tokens doesn't exist, and the duplication stands | **Spike: Phase 1 Task 9.** Measure `response.usage` both ways; adopt only on evidence, never reorder the prompts speculatively. |
| A future change quietly renders the profile into the extraction prompt | Requirements get softened for skills the student lacks — a silent false clear, the failure mode this work exists to protect | Regression test in Phase 1 Task 4 asserts the profile name never appears in `build_requirements_instruction` output. |
| Removing the preference inputs changes the rubric, so scores stored before and after are not strictly comparable | The history page silently compares two rubrics | Accepted risk — recorded as a spec open question. Revisit only if the history trend reads as misleading. |
| Narrowing the content hash invalidates every stored hash | First run after deploy re-analyses the entire table at full cost | Phase 2 ships a backfill script, run **before** the first pipeline run on the new code. |
| A materially rewritten description no longer triggers re-analysis | A listing whose requirements genuinely changed is scored against stale text | Accepted risk — recorded as a spec open question. |
| `tests/test_agent.py` asserts against ADK `Event` objects throughout | Phase 1 breaks a large test file in one go | Phase 1 Task 2 lands the local event type and migrates the assertions; they xfail until Task 6 rewires the pipeline. The suite is knowingly not fully green in between. |
| Bounded-concurrency batching may trip DeepSeek rate limits | Runs fail intermittently under load | Concurrency limit is a setting (`MODEL_CONCURRENCY`, default 3); lower it if 429s appear. Per-batch retry already absorbs a single failure. |

## Blast Radius

- **Code that will change:** `scout/`, `tests/`, `requirements.txt`,
  `docker-compose.yaml`, `Dockerfile`, `docs/project/architecture-pipeline-overview.md`
- **Existing behaviour that could break:** the whole daily run (every stage
  is touched); stored `content_hash` values; the meaning of a stored `score`;
  the Discord brief's selection set; `scout.rerender` (shares the report
  module).
- **Off-limits:** Do not modify anything outside the directories above
  without flagging it to the human first. In particular: no changes to
  `vendor/`, `docker/jobspy-mcp/`, `infra/`, or `.github/workflows/`.

---

## Phases

| # | Phase | Document | Status |
|---|-------|----------|--------|
| 1 | Model layer & brief-time filtering | [phase-1-model-layer.md](phase-1-model-layer.md) | Complete |
| 2 | Listing lifecycle & run record | [phase-2-lifecycle.md](phase-2-lifecycle.md) | Not started |
| 3 | Robustness & cleanup | [phase-3-robustness.md](phase-3-robustness.md) | Not started |

> All phases are planned in advance — every row above has a written,
> human-approved phase doc before phase 1 execution starts. If executing
> an earlier phase surfaces a needed change to a later phase doc, update
> that doc explicitly and record the change in its Notes / Learnings
> section; don't leave later phases undocumented.

---

## Testing Strategy

- **Unit:** Per-task TDD in the phase docs. New coverage for the JSON
  completion helper, shared batching and per-batch tolerance, the
  profile-blindness regression guard, brief-time preference filtering,
  time-based closure, the narrowed hash, run-record accumulation, scoped gap
  replacement, and per-item tolerance in scraper normalisation.
- **Integration:** `pytest tests/test_agent.py` exercises the pipeline
  end-to-end against the `scout_test` database with the model call stubbed;
  it runs at the end of every phase.
- **Manual:** One `docker compose run --rm app` against the dev database
  after each phase, checked for a completed run, a rendered dashboard
  containing preference-failing listings, and a Discord brief containing
  only preference-passing ones.

## Rollout & Reversibility

- **Feature flag:** no. The change is a single-user batch job with no live
  traffic; a flag would cost more than a revert.
- **Migrations:** `schema.sql` is unchanged — no DDL in this work. The
  content-hash backfill is a **data** migration and is irreversible in the
  sense that the pre-backfill hashes are not recoverable; it is, however,
  re-runnable and idempotent, and the worst case of skipping it is one
  expensive run rather than data loss.
- **Rollback plan:** `git revert` the phase's commits and restore
  `google-adk==2.4.0` / `google-genai==2.11.0` to `requirements.txt`.
  Stored scores from the new rubric are left in place; they remain valid
  scores, just computed preference-neutrally.

---

## Key Decisions & Constraints

- Drop `google-adk`, keep the agent shell. The staged, event-emitting
  structure is retained in project-local types; only the dependency goes.
- **Scoring and extraction stay separate calls.** Merging them was approved
  and then withdrawn — the Scorer needs the whole description *and* the
  profile; the Extractor needs the whole description and must **not** see
  the profile, or a requirement the student fails can be silently softened
  away. Full reasoning in the spec's Amendment.
- The Scorer gets the batching the Extractor already has. Its single-call
  shape is the same one that truncated the Advisor and aborted a run.
- Every new-or-changed listing is scored. The dashboard is the day's full
  market picture; the brief is the narrow slice.
- Preference filtering therefore moves **later** — out of the scorer and
  into `select_top_matches` — not earlier.
- Scoring is preference-neutral: `preferred_locations`, `remote_only` and
  `min_salary` leave the prompt so preferences are not counted twice.
- The same-`run_date` model is kept, consistent with the pipeline-hardening
  spec; a re-run is made non-destructive rather than split into intraday rows.
- `strip_code_fence` is retained as defensive parsing even with
  `response_format` set — it is already tested and costs nothing.
- ⚠️ **One-way doors:**
  - **Phase 1 Task 4** (preference inputs removed from the scoring prompt)
    changes the meaning of every score stored afterwards. Requires human
    sign-off.
  - **Phase 2 Task 2** (content-hash backfill) rewrites a column across the
    whole `listings` table. Requires human sign-off.

## Out of Scope

- Merging scoring and extraction into one model call, or deriving the score
  from the extracted requirements. Both considered and rejected — see the
  spec's Amendment and Alternatives table.
- Splitting runs into per-timestamp rows.
- Changes to the scoring rubric's bands, thresholds, or skill/seniority
  reasoning, beyond removing the preference inputs.
- Removal of `get_run_by_date` / `get_run_listings` — they are test
  assertion probes, deliberately kept.
- Any change to the scraping source, search parameters, or infrastructure
  topology (`vendor/`, `docker/`, `infra/`, `.github/workflows/`).

---

## Definition of Done

- [ ] All acceptance criteria met
- [ ] All phase verification steps pass
- [ ] Feature verified manually in a running environment
- [ ] Docs / README updated where behaviour changed
- [ ] No new lint or type-check warnings

## Update Rules

- Phase docs hold task-level detail; this file holds phase-level status only.
- When a phase's scope changes, update its row here **in the same commit**.
- On conflict, this file wins for *what* the phases are; the phase doc
  wins for *how* its tasks are done.
