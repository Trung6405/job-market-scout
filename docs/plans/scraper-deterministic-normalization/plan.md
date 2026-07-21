# Plan: Deterministic Scraper Normalization

> **Status:** Complete
> **Created:** 2026-07-20 · **Last updated:** 2026-07-20
> **Spec:** [spec.md](../../specs/scraper-deterministic-normalization/spec.md)

---

## Overview

Replace the scraper stage's `LlmAgent` + ADK `Runner` (tool-calling and
JSON normalization done by DeepSeek) with a plain deterministic Python
pipeline that calls the `search_jobs` MCP tool directly and maps fields
in code. `run_scraper(settings)` keeps its existing signature and return
type, so nothing outside `scout/sub_agents/scraper/` needs to change.

## Acceptance Criteria

- [x] `run_scraper` makes zero LLM calls and returns `list[Listing]`
      built from a live `search_jobs` response.
- [x] `python -m scout.main` proceeds past the scraper stage without a
      JSON/schema error (may still fail later at scorer/briefing/email
      steps for unrelated reasons, e.g. missing Gmail credentials — that's
      out of scope here).
- [x] Full test suite passes with no LLM/ADK mocking required for the
      scraper's own tests.

---

## Risks & Unknowns

| Risk / unknown | Impact if wrong | Resolution |
|----------------|-----------------|------------|
| Hardcoded default site list (`indeed,linkedin,zip_recruiter,glassdoor,google`) may not match what a future operator wants | Under- or over-broad search coverage | Accepted risk — matches today's observed effective behavior; making sites configurable is explicitly out of scope (see spec) |
| `jobspy-mcp`'s job field shape could change upstream | Normalization silently drops or mis-maps fields | Accepted risk — same exposure existed with the prompt-based mapping; not new |

> No spike tasks needed — the MCP client call sequence and job field
> names were already verified live against the running container during
> the investigation that produced this plan.

## Blast Radius

- **Code that will change:** `scout/sub_agents/scraper/` (new
  `mcp_client.py`, new `normalize.py`, rewritten `runner.py`, deleted
  `agent.py` and `tools.py`), `scout/prompts.py` (remove
  `build_scraper_instruction`/`SCRAPER_INSTRUCTION_TEMPLATE`),
  `tests/test_scraper_*.py`.
- **Existing behaviour that could break:** anything depending on
  `run_scraper`'s return value — currently only `scout/agent.py`'s
  `ScoutPipelineAgent._run_async_impl`, which calls
  `await run_scraper(settings)` and only cares about the returned
  `list[Listing]`. No changes needed there.
- **Off-limits:** `scout/sub_agents/scorer/`, `scout/sub_agents/briefing/`,
  `scout/tools/tracker.py`, `scout/shared/db.py` — do not touch without
  flagging first.

---

## Phases

| # | Phase | Document | Status |
|---|-------|----------|--------|
| 1 | Deterministic scraper | [phase-1-deterministic-scraper.md](phase-1-deterministic-scraper.md) | Complete |

---

## Testing Strategy

- **Unit:** `mcp_client`'s response-parsing function tested against a
  fake `ClientSession` stub (no network); `normalize.py`'s field mapping
  tested with plain dicts covering the happy path and each drop
  condition; `run_scraper` tested with the MCP-calling function
  monkeypatched, matching the existing test style used for the scorer and
  briefing runners.
- **Integration:** manual run of `python -m scout.main` against the live
  `jobspy-mcp` + `postgres` containers (already running from this
  session) to confirm the scraper stage completes with real data.
- **Manual:** none beyond the integration run above.

---

## Key Decisions & Constraints

- Only the scraper's tool-invocation and normalization step changes.
  Scorer and briefing keep using `LlmAgent`, since scoring fit and
  writing prose are genuine judgment calls, not mechanical mapping.
- No new `Settings` field is added for site selection in this pass.

## Out of Scope

- Making the job-site list configurable via `Settings`.
- Any change to `jobspy-mcp-server` beyond the already-applied
  `docker-compose.yaml` build patch.
- Addressing the scorer/briefing stages' own prompt-based JSON parsing
  (tracked separately if it becomes a problem — it hasn't yet).

---

## Definition of Done

- [x] All acceptance criteria met
- [x] All phase verification steps pass
- [x] Feature verified manually in a running environment
      (`python -m scout.main` against live `jobspy-mcp`/`postgres` — full
      pipeline completed: 34 listings scraped, tracked, scored, and
      briefing email sent)
- [x] No new lint or type-check warnings

## Update Rules

- Phase docs hold task-level detail; this file holds phase-level status only.
- When a phase's scope changes, update its row here **in the same commit**.
- On conflict, this file wins for *what* the phases are; the phase doc
  wins for *how* its tasks are done.
