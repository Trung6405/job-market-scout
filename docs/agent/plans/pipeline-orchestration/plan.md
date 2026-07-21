# Plan: Pipeline Orchestration

> **Status:** Not started
> **Created:** 2026-07-20 · **Last updated:** 2026-07-20
> **Spec:** [spec.md](../../specs/pipeline-orchestration/spec.md)

---

## Overview

Builds the missing wiring between Scraper, Tracker, Scorer, and Briefing: a
`ScoutPipelineAgent` (custom ADK `BaseAgent`) that runs the four stages in
order and reports progress after each one, exported as `root_agent` so
`adk web` can drive it interactively; and a `scout/main.py` batch
entrypoint that drives the same agent non-interactively, replacing the
Dockerfile's `adk api_server` CMD. Done means: `adk web` run from the repo
root lets a developer send one message and watch Scraper → Tracker →
Scorer → Briefing progress in the UI, and `docker build && docker run`
executes one full pipeline run and exits.

## Acceptance Criteria

- [ ] `adk web` (run from repo root) discovers `root_agent` in `scout/agent.py`; sending it a message runs all four stages and the UI shows a distinct status message after each stage.
- [ ] When Tracker finds zero new/changed listings, Scorer and Briefing are not called, and a distinguishing "nothing to brief" event is yielded instead.
- [ ] `python -m scout.main` runs the pipeline once and exits 0 on success, non-zero on any stage raising.
- [ ] `Dockerfile`'s `CMD` runs `scout.main`, not `adk api_server`.
- [ ] `docker build .` succeeds and `docker compose up` runs one full pipeline pass against the Docker Postgres (port 5433) without manual glue code.

---

## Risks & Unknowns

| Risk / unknown | Impact if wrong | Resolution |
|----------------|-----------------|------------|
| `adk web`'s agent-discovery convention for a repo-root `scout/agent.py` exporting `root_agent` — assumed to work the same way each sub-agent's standalone `root_agent` already does | If discovery differs at the repo-root level, the headline "watch it run in adk web" acceptance criterion fails | Accepted risk — the sub-agent convention is proven in this repo today (`scraper/agent.py`); manual check in Phase 3 verification confirms it at the top level before Phase 4 starts |
| A true end-to-end dry run needs a real `DEEPSEEK_API_KEY` and network access to the LLM — unit tests mock every stage function, so they can't catch integration issues between real stage outputs | A stage's real output shape could still break the next stage even with all unit tests green | Manual verification step in Phase 4 (local `docker compose` dry run against port 5433) — not unit-testable, called out explicitly in Definition of Done |
| `google-adk`'s `BaseAgent`/`Event`/`InvocationContext` construction pattern used here (`Event(invocation_id=..., author=..., branch=..., content=...)`) is unversioned public API surface | A library upgrade could change the constructor and silently break event content | Accepted risk — same pattern is already used inside `google/adk/agents/langgraph_agent.py`; pin stays in `requirements.txt`, revisit on any `google-adk` version bump |

## Blast Radius

- **Code that will change:** `scout/agent.py`, `scout/main.py` (new), `scout/shared/parsing.py` (new), `scout/sub_agents/scraper/runner.py` (new), `scout/sub_agents/scorer/runner.py` (new), `scout/sub_agents/briefing/summarize.py` (import change only), `Dockerfile`, `tests/` (new test files for each of the above).
- **Existing behaviour that could break:** the Briefing stage's markdown-fence parsing (`parse_briefing_prose`), if the extracted `strip_code_fence` helper behaves differently from the inline version it replaces.
- **Off-limits:** `scout/tools/tracker.py`, `scout/shared/db.py`, `scout/sub_agents/*/agent.py` (the `build_*_agent` functions), `scout/config.py`, `scout/prompts.py` — none of these need to change for this work; flag to the human first if a task turns out to need them.

---

## Phases

| # | Phase | Document | Status |
|---|-------|----------|--------|
| 1 | Shared parsing helper | [phase-1-shared-parsing.md](phase-1-shared-parsing.md) | Not started |
| 2 | Scraper/Scorer runners | [phase-2-stage-runners.md](phase-2-stage-runners.md) | Not started |
| 3 | ScoutPipelineAgent | [phase-3-pipeline-agent.md](phase-3-pipeline-agent.md) | Not started |
| 4 | Batch entrypoint + Dockerfile | [phase-4-batch-entrypoint.md](phase-4-batch-entrypoint.md) | Not started |

> All phases are planned in advance — every row above has a written,
> human-approved phase doc before phase 1 execution starts. If executing
> an earlier phase surfaces a needed change to a later phase doc, update
> that doc explicitly and record the change in its Notes / Learnings
> section; don't leave later phases undocumented.

---

## Testing Strategy

- **Unit:** per-task TDD in each phase doc — `strip_code_fence` (Phase 1), `run_scraper`/`run_scorer` parsing and monkeypatched-runner behavior (Phase 2), `ScoutPipelineAgent`'s event sequence and short-circuit behavior driven through `InMemoryRunner` with all four stage calls monkeypatched (Phase 3), `run_once`/`main`'s success and failure-exit-code behavior (Phase 4).
- **Integration:** none of the phases exercise a real LLM or real Postgres in automated tests — every stage call is monkeypatched at the `scout.agent` / `scout.main` boundary. The one thing automated tests cannot verify is "do the real stages actually compose" — that is the manual check below.
- **Manual:** after Phase 4, run the full local dry run and per-stage/edge-case checks described in Phase 4's Verification section (real `docker compose` run against the Docker Postgres on port 5433, zero-listings edge case, duplicate-run edge case, malformed-config edge case, and a hand spot-check of scored listings against the resume).

---

## Key Decisions & Constraints

- No separate `run_scout` plain-function orchestrator: `ScoutPipelineAgent._run_async_impl` is the single place the four-stage sequence is implemented, so both `adk web` and the batch path share it (per the approved spec's revision away from a plain-function-only design).
- `ScoutPipelineAgent` reports progress via ADK `Event`s carrying short human-readable text; it does not pass stage data (`Listing`, `ListingScore`) through ADK session state — that data still flows as typed Python values between direct function calls, preserving Decision D3 from the tracker-orchestration/scorer-agent specs.
- A single `Settings` instance is threaded through every stage call within one pipeline run (spec requirement) — `ScoutPipelineAgent` reads the module-level `scout.config.settings` singleton once at the top of `_run_async_impl` rather than re-reading it per stage.
- ⚠️ **One-way doors:** none identified — the `Dockerfile` `CMD` change and all new modules are ordinary code changes, fully reversible by reverting the commit; no schema or public API changes are involved.

## Out of Scope

- A scheduler / cron trigger for daily runs (PRS §7, separate work).
- Persisting match scores to a `matches` table (PRS Decision D4).
- Retry or partial-failure recovery across stages.
- CI/CD pipeline definition itself (GitHub Actions workflow) — this plan makes the pipeline runnable and dry-run-able; wiring an actual CI workflow file is separate follow-up work.

---

## Definition of Done

- [ ] All acceptance criteria met
- [ ] All phase verification steps pass
- [ ] Feature verified manually in a running environment (local `docker compose` dry run per Phase 4's Verification section, including the zero-listings, duplicate-run, and malformed-config edge cases)
- [ ] Docs / README updated where behaviour changed
- [ ] No new lint or type-check warnings

## Update Rules

- Phase docs hold task-level detail; this file holds phase-level status only.
- When a phase's scope changes, update its row here **in the same commit**.
- On conflict, this file wins for *what* the phases are; the phase doc
  wins for *how* its tasks are done.
