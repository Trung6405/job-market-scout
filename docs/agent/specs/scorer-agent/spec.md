# Scorer Sub-Agent Design

Date: 2026-07-15
Status: Approved

## Context

`job-market-scout` is a multi-agent job search pipeline (Scraper → Scorer → Briefing, plus a Tracker tool) built on Google ADK, LiteLLM, and DeepSeek, deployed via Docker. The scraper sub-agent (previous session) fetches `Listing` objects from job boards via an MCP server. This session covers the **scorer sub-agent** (folder: `scout/sub_agents/scorer`, per the existing scaffold; agent name: `scorer`) — the second pipeline stage, responsible for scoring listings against the job seeker's resume and preferences.

The system-context diagram labels this stage "Scorer" and describes its job as "LLM Inference: Infers Context, Match Scoring."

## Goals

- A working ADK `LlmAgent` that scores a list of `Listing` objects against resume text and preferences, returning a numeric score and short reasoning per listing.
- A cheap, deterministic rule-based pre-filter (plain Python, not an LLM/tool call) that drops hard-reject listings (location/remote/salary) before they reach the LLM.
- A `MatchResult` schema that the briefing sub-agent can eventually consume.
- Minimal config additions (resume path, preference fields, score threshold) following the scraper's env-driven `Settings` pattern.

## Out of Scope

- Database persistence — `scout/shared/db.py` and `scout/tools/tracker.py` stay empty stubs. The scorer takes `list[Listing]` in-memory (from the scraper stage) and returns `list[MatchResult]`; it doesn't read/write the DB. This mirrors the scraper session's deferral of DB wiring.
- Briefing sub-agent (stays an empty stub).
- Root pipeline wiring (`scout/agent.py` `SequentialAgent` stays empty).
- Skill/seniority/keyword rule-filters — only location, remote, and salary are hard-filtered rule-side; everything else (skills fit, seniority nuance, career trajectory) is left to the LLM's holistic scoring against resume text.

## Architecture

```
scout/agent.py (root, untouched this session)
  └── scorer (LlmAgent, DeepSeek/LiteLLM)
        input:  list[Listing]  (from scraper stage)
        step 1: filters.filter_listings(listings, settings) — plain Python, runs BEFORE the LLM
        step 2: LlmAgent scores survivors against resume text + preferences
        output: list[MatchResult], scores below MIN_MATCH_SCORE dropped
```

Unlike the scraper (which calls an MCP tool from within the LLM's reasoning loop), the rule-based filter here runs as a plain Python pre-processing step *before* the `LlmAgent` is invoked — not as an ADK `FunctionTool` the LLM calls. This keeps the hard filter deterministic and free of LLM tool-call overhead; the LLM's only job is holistic scoring of the pre-filtered survivors.

## Components

### `scout/shared/schemas.py`
Add a `MatchResult` Pydantic model:

| field | type | notes |
|---|---|---|
| `listing` | `Listing` | the original scraped listing |
| `score` | int | 0–100 match score |
| `reasoning` | str | short LLM-generated explanation |

### `scout/config.py`
Extend `Settings` with:
- `resume_path: Path` — path to a local `.txt`/`.md` resume file (default e.g. `scout/resume.txt`), read as text at agent build time. Missing/unreadable file fails fast (config error) — scoring is meaningless without it.
- `preferred_locations: list[str]` — CSV env var, same `_split_csv` pattern as `search_locations`.
- `remote_only: bool` — env-driven boolean.
- `min_salary: float | None` — hard salary floor.
- `min_match_score: int` — threshold below which scored listings are dropped from output (default e.g. 60).

### `scout/.env.example`
Document the new vars: `RESUME_PATH`, `PREFERRED_LOCATIONS`, `REMOTE_ONLY`, `MIN_SALARY`, `MIN_MATCH_SCORE`.

### `scout/sub_agents/scorer/filters.py`
Plain function `filter_listings(listings: list[Listing], settings: Settings) -> list[Listing]`. Hard-rejects a listing if: `remote_only` is set and `listing.is_remote` is `False`; `preferred_locations` is non-empty and none match `listing.location`; `min_salary` is set and `listing.salary_max` (or `salary_min` if max is `None`) is below it, when salary data exists (missing salary data does not cause rejection — insufficient info to hard-filter on). Filtered-out listings are dropped entirely, not included in output with a zero score.

### `scout/sub_agents/scorer/agent.py`
Constructs the `LlmAgent` (`name="scorer"`): DeepSeek model via LiteLLM, no tools, `output_schema=list[MatchResult]`, instruction built from resume text + preferences + the pre-filtered listings (filtering happens before agent invocation, likely via a wrapper function `build_scorer_agent` that reads settings, runs `filter_listings`, and threshold-drops low scores after the LLM call completes — exact glue mechanism, e.g. `after_model_callback`, decided during implementation).

### `scout/prompts.py`
Add `build_scorer_instruction(settings)` — instructs the LLM to score each provided listing 0–100 against the resume text and preferences, with brief reasoning, per the project's existing convention of centralizing prompts.

## Data Flow

1. Scorer receives `list[Listing]` (from the scraper stage, in-memory — no DB read).
2. `filter_listings()` drops hard rejects based on `remote_only` / `preferred_locations` / `min_salary`.
3. Surviving listings, resume text, and preferences are formatted into the scorer's prompt.
4. DeepSeek LLM scores each survivor 0–100 with reasoning, returned as `list[MatchResult]`.
5. Results with `score < min_match_score` are dropped from the final output.
6. Agent returns `list[MatchResult]` for the future briefing stage to consume.

## Error Handling

- Missing/unreadable resume file: fails fast at config/startup time (not a silent empty resume).
- Malformed LLM score output for a given listing (e.g. missing score field): that listing is dropped, not raised — consistent with the scraper's "filter don't fail" pattern for malformed records.
- No retry logic for LLM calls yet — add once real failure modes are observed (YAGNI), same stance as the scraper spec.

## Testing

- Unit tests for `filter_listings`: fixture `Listing`s + `Settings` combinations covering remote-only rejection, location mismatch, salary floor rejection, and missing-salary-data pass-through.
- Unit tests for `MatchResult` schema: valid construction, rejection of missing required fields.
- No live LLM integration test in this session (mirrors scraper's testing scope).

## Open Questions / Follow-ups

- Exact glue mechanism for pre-filter → LLM → post-threshold (helper function vs. callback) is left to implementation-time judgment; both are consistent with ADK patterns already in use (scraper uses `after_model_callback` for `stamp_scraped_at`).
- Whether `scout/sub_agents/scorer/tools.py` stays empty/unused, since no ADK tool is needed for the pre-filter — likely resolved by deleting or leaving it as a stub during implementation.
