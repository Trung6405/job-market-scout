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
