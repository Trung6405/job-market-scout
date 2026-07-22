# Scraper Sub-Agent Design

Date: 2026-07-15
Status: Approved

## Context

`job-market-scout` is a multi-agent job search pipeline (Scraper → Scorer → Briefing, plus a Tracker) built on Google ADK, LiteLLM, and DeepSeek, deployed via Docker. The project is currently an empty scaffold. This spec covers only the **scraper sub-agent** — the first stage of the pipeline, responsible for fetching job listings.

The system-context diagram (`docs/project/diagrams/Solution Diagram.drawio`) describes the scraper as fetching listings from job boards (Seek, LinkedIn) via "MCP/API" and searching company career pages via a web search API. This session narrows that to: job-board fetching via MCP only. Company career-page search and Seek coverage are explicitly deferred (see Out of Scope).

## Goals

- A working ADK `LlmAgent` for the scraper that fetches real job listings from LinkedIn (and other jobspy-supported boards) via a self-hosted MCP server.
- A `Listing` schema that downstream sub-agents (scorer, tracker, briefing) can eventually consume.
- Minimal config/env plumbing so the agent is runnable locally and via `docker compose up`.

## Out of Scope

- Seek.com.au coverage (no MCP server or aggregator library supports it; revisit in a future session).
- Company career-page search via a web search API.
- Scorer, briefing, and tracker sub-agents (stay empty stubs).
- Database persistence (`scout/shared/db.py` stays empty; the scraper returns data, it doesn't store it).
- Root pipeline wiring (`scout/agent.py` SequentialAgent stays empty).

## Architecture

`scout/sub_agents/scraper` is an ADK `LlmAgent` (model: DeepSeek via LiteLLM) with one tool: `search_jobs`, exposed by **jobspy-mcp-server** (https://github.com/borgius/jobspy-mcp-server), a self-hosted Node.js MCP server wrapping the open-source `python-jobspy` library. The agent connects to it over SSE using ADK's `McpToolset` + `SseConnectionParams` (confirmed available in the installed `google-adk==2.4.0`).

```
scout/agent.py (root, untouched this session)
  └── scraper (LlmAgent, DeepSeek/LiteLLM)
        └── McpToolset (SSE) → jobspy-mcp-server :9423 → search_jobs(...)
```

The agent reads search parameters (roles/keywords, locations, freshness window, result count) from `scout/config.py`, prompts the LLM to call `search_jobs` with those parameters, and normalizes the tool's raw results into a list of `Listing` objects as its output. No DB writes, no career-page search.

## Components

### `scout/shared/schemas.py`
Add a `Listing` Pydantic model — the scraper's `output_schema` and the shape downstream agents will eventually consume:

| field | type | notes |
|---|---|---|
| `source` | str | e.g. `"linkedin"` |
| `external_id` | str | provider's job id, for future dedup |
| `title` | str | |
| `company` | str | |
| `location` | str | |
| `is_remote` | bool | |
| `url` | str (HttpUrl) | apply/listing link |
| `description` | str | |
| `salary_min` | float \| None | |
| `salary_max` | float \| None | |
| `date_posted` | datetime \| None | |
| `scraped_at` | datetime | set at scrape time |

### `scout/config.py`
Minimal settings loader (env-driven), covering:
- `JOBSPY_MCP_URL` (default `http://jobspy-mcp:9423`)
- `DEEPSEEK_API_KEY`, `DEEPSEEK_MODEL`
- `SEARCH_ROLES`, `SEARCH_LOCATIONS` (scraper search defaults)
- `RESULTS_WANTED`, `HOURS_OLD`

### `scout/.env.example`
Documents the vars above with placeholder values.

### `scout/sub_agents/scraper/tools.py`
Builds the `McpToolset` with `SseConnectionParams` pointed at `JOBSPY_MCP_URL`. Kept separate from `agent.py` so the connection can be swapped or mocked independently in tests.

### `scout/sub_agents/scraper/agent.py`
Constructs the `LlmAgent`: DeepSeek model via LiteLLM, the MCP tool from `tools.py`, `output_schema` for the `Listing` list, and instructions (from `scout/prompts.py`) telling it to call `search_jobs` with the configured roles/locations and return normalized results, dropping malformed records.

### `scout/prompts.py`
Scraper's instruction prompt text, per the project's existing convention of centralizing prompts.

### `docker-compose.yaml`
Two services on a shared network:
- `app` — builds from the existing `Dockerfile`.
- `jobspy-mcp` — `build: https://github.com/borgius/jobspy-mcp-server.git`, `ENABLE_SSE=1`, exposes `9423`.
`app` depends on `jobspy-mcp`.

## Data Flow

1. Scraper agent starts; ADK connects `McpToolset` to `jobspy-mcp:9423` over SSE.
2. DeepSeek LLM, prompted with configured roles/locations, calls `search_jobs(site_names=["linkedin"], search_term=..., location=..., results_wanted=..., hours_old=...)`.
3. Tool returns raw job dicts; the LLM normalizes them into `Listing` objects matching the schema.
4. Agent returns `list[Listing]` as its output, for a future pipeline stage to consume.

## Error Handling

- MCP connection failure surfaces as a tool error reported by the agent, not a silent empty result. No retry logic yet — add it once real failure modes are observed (YAGNI).
- Malformed listings (missing title/company) are filtered out rather than raising.

## Testing

- Unit tests for the `Listing` schema: valid construction, and rejection of missing required fields.
- A test for the MCP tool wiring using a mocked/fake SSE server (or a mocked `McpToolset`), so tests don't require a live `jobspy-mcp-server` instance. No live-network integration test in this session.

## Open Questions / Follow-ups

- Seek coverage: needs a dedicated data source (no existing MCP/library support found).
- Company career-page search via web search API: separate tool/session.
- Whether `jobspy-mcp-server`'s documented Docker image is fully self-contained (no docker-in-docker) is assumed from its README's `docker run` instructions but not verified against the actual Dockerfile — verify during implementation.

## Amendments

- 2026-07-21: Merged in the `scraper-deterministic-normalization` spec (see appendix below), which replaced this design's `LlmAgent`-based scraper with a deterministic Python implementation. Content unchanged in substance; original file deleted.
- 2026-07-22: Fixed a protocol-compliance bug in the vendored `jobspy-mcp-server` build-time overrides (`docker/jobspy-mcp/`, inlined into the `jobspy-mcp` service by `docker-compose.yaml`). `search-jobs.js` sends periodic `notifications/progress` messages while a search runs; `sseManager.js` attached each one's `progressToken` from whatever the client's own request `_meta.progressToken` had been — but our client (`scout/sub_agents/scraper/mcp_client.py`) never requests progress tracking, so that value is `undefined`, and `JSON.stringify` silently drops `undefined` keys, sending the notification with no `progressToken` at all. Per the MCP spec `progressToken` is required on that notification; the Python `mcp` SDK (1.28.1) can't match a tokenless one against any known notification type in its discriminated union and raises a page-long pydantic validation error (tried every variant: `ElicitCompleteNotification`, `TaskStatusNotification`, etc., all rejected) each time it happens — cosmetic noise in the logs, not a request failure, but confusing. Reproduced locally against the installed `mcp` package: the exact wire message (minus `progressToken`) fails validation; adding the token back validates cleanly as `ProgressNotification`. Fixed by having `sseManager.notificationProgress` skip sending when there's no token to attach, rather than sending a spec-violating message — no functional loss, since our client never reads progress notifications anyway. Unrelated, still-open issue noticed in the same logs: one concurrent per-role `search_jobs` call occasionally returns `Unexpected end of JSON input` from `searchJobsHandler`'s `JSON.parse(stdout)`, most likely truncated/empty output from a `docker exec jobspy-scraper ...` call racing another concurrent one against the same long-lived container (concurrency was only just enabled — see the scraper runner's async-exec fix). Non-fatal (other roles' results still come through), not yet investigated further.

---

## Appendix: Deterministic Scraper Normalization *(merged from `docs/agent/specs/scraper-deterministic-normalization/spec.md`, approved 2026-07-20)*

### Problem

The scraper stage (`scout/sub_agents/scraper/`) originally used an `LlmAgent` to (a) call the `search_jobs` MCP tool with parameters taken verbatim from `Settings`, and (b) copy the tool's JSON response field-by-field into the `Listing` schema. Neither step involves judgment — both are fixed, mechanical transformations. Routing them through an LLM made the stage fail in four distinct ways during live testing: an upstream MCP server crash exposed a missing tool entirely; an unenforced `output_schema` let the model answer in prose instead of JSON; DeepSeek rejected the OpenAI-style strict `json_schema` response format LiteLLM sent; and, once that was worked around, DeepSeek corrupted JSON escaping while transcribing large (multi-KB) job descriptions verbatim. Each fix uncovered a new failure in the same code path, the signature of an architecture mismatch rather than a sequence of unrelated bugs.

### Success Criteria

- `run_scraper(settings)` returns normalized `Listing` objects sourced from a live `search_jobs` call and completes reliably regardless of description length or content.
- The scraper stage makes zero LLM calls.
- `python -m scout.main` gets past the scraper stage without a parsing or schema-enforcement failure.
- Scorer and briefing stages are unaffected — they still use `LlmAgent` since they require judgment (fit scoring, prose writing).

### Requirements

**Must have:** `run_scraper` calls the `search_jobs` MCP tool directly (no `LlmAgent`/ADK `Runner`) once per role in `settings.search_roles`; each returned job dict is mapped to `Listing` in plain Python using the same field rules the original prompt encoded (`source` ← `site`, `external_id` ← `id`, `url` ← `jobUrl`, `is_remote` ← `isRemote` true only if explicitly true, etc.); rows missing `title`, `company`, or `url` are dropped, not guessed; duplicate `(source, external_id)` pairs across roles in one run are deduplicated; `run_scraper(settings)`'s public signature and behavior on callers is unchanged.

**Should have:** the low-level "call the tool and parse the response" function is kept separate from the "manage the SSE session" function, so parsing logic is unit-testable without a live MCP server.

**Won't have:** no new `Settings` field for choosing which job sites to search in this pass (default site list stays hardcoded); no change to the scorer or briefing stages' use of `LlmAgent`; no further changes to the vendored `jobspy-mcp-server` beyond the already-applied build-time patch.

### Proposed Approach

Replaced the scraper's `LlmAgent` + ADK `InMemoryRunner` with a plain async pipeline: a thin MCP client module wraps the official `mcp` SDK (`ClientSession` + `sse_client`) to open a session against `{settings.jobspy_mcp_url}/sse`, call `search_jobs`, and return the parsed `jobs` list — with the "call the tool given an open session" step split out as its own function so it's unit-testable against a fake session object. A normalization function maps one raw job dict to a `Listing`, returning `None` for rows that fail the required-field check instead of raising. `run_scraper` loops over `settings.search_roles`, calls the MCP client once per role, normalizes and deduplicates the results, and returns the combined list. `scout/sub_agents/scraper/agent.py`, `tools.py`, and the `build_scraper_instruction` prompt were deleted, since nothing calls an LLM for this stage anymore.

### Alternatives Considered

| Alternative | Why rejected |
|-------------|--------------|
| Keep the LLM approach; add a JSON-repair fallback and truncate/sanitize descriptions before they reach the model | Patches the fourth symptom, not the root cause. Long or unusually-formatted descriptions would keep finding new ways to break transcription; ongoing latency and DeepSeek cost for a step that makes no judgment calls. |
| Keep the LLM approach but switch model/provider | Doesn't address the underlying issue — transcription-heavy structured output from large text blocks is fragile on any provider. |
| Do nothing | Pipeline cannot complete a real run. |
