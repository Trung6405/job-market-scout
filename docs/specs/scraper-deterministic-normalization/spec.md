# Spec: Deterministic Scraper Normalization

> **Status:** Approved
> **Created:** 2026-07-20 · **Approved:** 2026-07-20
> **Implementation plan:** [plan.md](../../plans/scraper-deterministic-normalization/plan.md) *(created after approval)*

---

## Problem

The scraper stage of the pipeline (`scout/sub_agents/scraper/`) uses an
`LlmAgent` to (a) call the `search_jobs` MCP tool with parameters taken
verbatim from `Settings`, and (b) copy the tool's JSON response
field-by-field into the `Listing` schema. Neither step involves judgment
— both are fixed, mechanical transformations. Routing them through an LLM
made the stage fail in four distinct ways during live testing this
session: an upstream MCP server crash exposed a missing tool entirely; an
unenforced `output_schema` let the model answer in prose instead of JSON;
DeepSeek rejected the OpenAI-style strict `json_schema` response format
LiteLLM sent; and, once that was worked around, DeepSeek corrupted JSON
escaping while transcribing large (multi-KB) job descriptions verbatim.
Each fix uncovered a new failure in the same code path, which is the
signature of an architecture mismatch rather than a sequence of unrelated
bugs. The pipeline currently cannot complete a real run because of this.

## Success Criteria

- `run_scraper(settings)` returns normalized `Listing` objects sourced
  from a live `search_jobs` call and completes reliably regardless of
  description length or content.
- The scraper stage makes zero LLM calls.
- `python -m scout.main` gets past the scraper stage without a parsing
  or schema-enforcement failure.
- Scorer and briefing stages are unaffected — they still use `LlmAgent`
  since they require judgment (fit scoring, prose writing).

---

## Requirements

### Must have

- `run_scraper` calls the `search_jobs` MCP tool directly (no
  `LlmAgent`/ADK `Runner` involved) once per role in
  `settings.search_roles`, passing `location`, `resultsWanted`, and
  `hoursOld` from `Settings`.
- Each returned job dict is mapped to `Listing` in plain Python using the
  same field rules the current prompt encodes: `source` ← `site`,
  `external_id` ← `id`, `title`/`company`/`location` as-is, `url` ←
  `jobUrl`, `description` ← `description`, `is_remote` ← `isRemote`
  (true only if explicitly true), `date_posted` ← `datePosted`,
  `salary_min`/`salary_max` ← `minAmount`/`maxAmount`.
- Rows missing `title`, `company`, or `url` are dropped, not guessed —
  matching current behavior.
- Duplicate `(source, external_id)` pairs across roles in one run are
  deduplicated (the old LLM-driven path had no such guarantee either way,
  but nothing downstream expects duplicates within one batch).
- `run_scraper(settings)`'s public signature and behavior on callers
  (`scout/agent.py`, `scout/main.py`) is unchanged.

### Should have

- Keep the low-level "call the tool and parse the response" function
  separate from the "manage the SSE session" function, so the parsing
  logic is unit-testable without a live MCP server.

### Won't have

- No new `Settings` field for choosing which job sites to search — the
  current default site list is hardcoded to preserve today's effective
  behavior. Making it configurable is a separate, later change.
- No change to the scorer or briefing stages' use of `LlmAgent`.
- No further changes to the vendored `jobspy-mcp-server` beyond the
  build-time patch already applied in `docker-compose.yaml`.

---

## Proposed Approach

Replace the scraper's `LlmAgent` + ADK `InMemoryRunner` with a plain
async pipeline:

1. A thin MCP client module wraps the official `mcp` SDK (`ClientSession`
   + `sse_client`, both already a pinned dependency) to open a session
   against `{settings.jobspy_mcp_url}/sse`, call `search_jobs` with
   explicit keyword arguments, and return the parsed `jobs` list from the
   tool's JSON response. The "call the tool given an open session" step
   is split out as its own function so it can be unit-tested against a
   fake session object, independent of the "open a real SSE connection"
   step.
2. A normalization function maps one raw job dict to a `Listing`,
   returning `None` for rows that fail the required-field check instead
   of raising — mirroring the "drop, don't guess" rule already in the
   prompt.
3. `run_scraper` loops over `settings.search_roles`, calls the MCP client
   once per role, normalizes and deduplicates the results, and returns
   the combined list — same return type and call signature as today.

`scout/sub_agents/scraper/agent.py`, `tools.py`, and the
`build_scraper_instruction` prompt are deleted, since nothing calls an
LLM for this stage anymore.

## Alternatives Considered

| Alternative | Why rejected |
|-------------|--------------|
| Keep the LLM approach; add a JSON-repair fallback and truncate/sanitize descriptions before they reach the model | Patches the fourth symptom, not the root cause. Long or unusually-formatted descriptions would keep finding new ways to break transcription; ongoing latency and DeepSeek cost for a step that makes no judgment calls. |
| Keep the LLM approach but switch model/provider | Doesn't address the underlying issue — transcription-heavy structured output from large text blocks is fragile on any provider, and switching providers has its own migration cost. |
| Do nothing | Pipeline cannot complete a real run today. |

---

## Open Questions

| Question | Who decides | Blocks planning? |
|----------|-------------|------------------|
| None outstanding — job field names, the MCP client API, and the exact SSE call sequence were verified directly against the running `jobspy-mcp` container and its source during this investigation. | — | no |

---

## Amendments *(only after approval — never silently edit approved content)*

- none yet
