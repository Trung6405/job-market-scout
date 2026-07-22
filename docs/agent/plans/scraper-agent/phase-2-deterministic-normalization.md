# Phase 1: Deterministic scraper

> **Parent plan:** [plan.md](plan.md)
> **Status:** Complete
> **Depends on:** nothing

---

## Goal

Replace the scraper's LLM-driven tool call + normalization with
deterministic Python, keeping `run_scraper(settings) -> list[Listing]`'s
signature and behavior unchanged for callers. Done when
`python -m scout.main` gets past the scraper stage using live
`jobspy-mcp` data with no LLM involved in that stage.

## Safety Checklist

- **Touches user input, auth, secrets, or external calls?** Yes — calls
  the `jobspy-mcp` SSE endpoint. Failure handling: let connection/tool
  errors propagate naturally out of `run_scraper` (matches existing
  behavior and the existing test `test_run_once_propagates_stage_exception`
  in `tests/test_main_entrypoint.py`, which requires stage exceptions to
  reach `main()` unmodified).
- **Contains a one-way door (schema, public API shape, new dependency)?**
  No. `run_scraper`'s signature and `Listing` schema are unchanged. No
  new dependency (`mcp` is already pinned in `requirements.txt`).

---

## Tasks

### Task 1: MCP response parsing (testable without a live server)

- **Files:** `scout/sub_agents/scraper/mcp_client.py`,
  `tests/test_scraper_mcp_client.py`
- **Gate:** none
- **Steps:**
  - [x] Write failing test: given a fake session object whose
        `call_tool` returns an object with
        `.content[0].text == '{"jobs": [{"id": "1"}], "count": 1}'`,
        `parse_search_jobs_result(await session.call_tool(...))` (or
        equivalent) returns `[{"id": "1"}]`.
  - [x] Verify it fails (`ImportError`/`AttributeError` — module/function
        doesn't exist yet):
        `PYTHONPATH=. .venv/Scripts/python.exe -m pytest tests/test_scraper_mcp_client.py -q`
  - [x] Implement `mcp_client.py`: a small function that takes the
        `CallToolResult`-shaped object returned by `session.call_tool`
        and returns `json.loads(result.content[0].text).get("jobs", [])`.
  - [x] Verify it passes:
        `PYTHONPATH=. .venv/Scripts/python.exe -m pytest tests/test_scraper_mcp_client.py -q`
  - [ ] Commit: `feat(scraper): parse search_jobs MCP tool responses`
        *(deferred — commits are only made when explicitly requested;
        see Notes / Learnings)*

### Task 2: MCP session wrapper (`fetch_jobs`)

- **Files:** `scout/sub_agents/scraper/mcp_client.py`
- **Gate:** none
- **Steps:**
  - [x] Implement `async def fetch_jobs(url: str, **params) -> list[dict]`
        using `mcp.client.sse.sse_client` + `mcp.ClientSession` to open a
        session against `f"{url}/sse"`, call `session.initialize()`, call
        `session.call_tool("search_jobs", params)`, and return the parsed
        job list via Task 1's function.
  - [x] No dedicated unit test for this function itself (it's a thin SSE
        session wrapper around already-tested parsing logic; verified by
        the Phase Verification manual run below) — `run_scraper`'s own
        tests (Task 4) monkeypatch this function directly, matching the
        existing pattern used for the scorer/briefing runners
        (`monkeypatch.setattr(".._run_scraper_agent", ...)`).
  - [ ] Commit: `feat(scraper): add fetch_jobs MCP session wrapper`
        *(deferred — see Notes / Learnings)*

### Task 3: Field normalization

- **Files:** `scout/sub_agents/scraper/normalize.py`,
  `tests/test_scraper_normalize.py`
- **Gate:** none
- **Steps:**
  - [x] Write failing tests for `normalize_job(job: dict, scraped_at: datetime) -> Listing | None`:
        - happy path: a full job dict (fields per spec: `id`, `site`,
          `jobUrl`, `title`, `company`, `location`, `datePosted`,
          `minAmount`, `maxAmount`, `isRemote`, `description`) maps to
          the expected `Listing`.
        - missing `title` → `None`.
        - missing `company` (including `company: None`, observed live
          from real jobspy data) → `None`.
        - missing `jobUrl` → `None`.
        - `isRemote` missing/`None`/`False` → `Listing.is_remote is False`.
        - missing `minAmount`/`maxAmount`/`datePosted` → corresponding
          `Listing` fields are `None`, no exception.
  - [x] Verify failing:
        `PYTHONPATH=. .venv/Scripts/python.exe -m pytest tests/test_scraper_normalize.py -q`
  - [x] Implement `normalize_job` per the field mapping in the spec.
  - [x] Verify passing (same command).
  - [ ] Commit: `feat(scraper): normalize raw job dicts to Listing`
        *(deferred — see Notes / Learnings)*

### Task 4: Rewrite `run_scraper`

- **Files:** `scout/sub_agents/scraper/runner.py`,
  `tests/test_scraper_runner.py`
- **Gate:** none
- **Steps:**
  - [x] Write failing tests (replacing the current LLM-mocking tests):
        - `run_scraper` calls `fetch_jobs` once per
          `settings.search_roles` entry, with `location` set from
          `",".join(settings.search_locations)`, `resultsWanted` from
          `settings.results_wanted`, `hoursOld` from
          `settings.hours_old`.
        - results from all roles are normalized and combined.
        - a duplicate `(source, external_id)` returned by two different
          role searches appears only once in the final list.
        - a row that fails normalization (e.g. missing `company`) is
          silently dropped, not raised.
  - [x] Verify failing:
        `PYTHONPATH=. .venv/Scripts/python.exe -m pytest tests/test_scraper_runner.py -q`
  - [x] Implement the new `run_scraper`, monkeypatching-friendly (module-level
        `fetch_jobs` reference, matching the existing monkeypatch style
        in the codebase).
  - [x] Verify passing (same command).
  - [ ] Commit: `refactor(scraper): drive run_scraper from fetch_jobs + normalize_job`
        *(deferred — see Notes / Learnings)*

### Task 5: Remove the now-dead LLM scaffolding

- **Files:** delete `scout/sub_agents/scraper/agent.py`,
  `scout/sub_agents/scraper/tools.py`,
  `tests/test_scraper_agent.py`, `tests/test_scraper_tools.py`; edit
  `scout/prompts.py` to remove `SCRAPER_INSTRUCTION_TEMPLATE` and
  `build_scraper_instruction`.
- **Gate:** none
- **Steps:**
  - [x] Confirm nothing else imports `scout.sub_agents.scraper.agent`,
        `scout.sub_agents.scraper.tools`, or
        `scout.prompts.build_scraper_instruction`
        (`grep -rn "scraper.agent\|scraper.tools\|build_scraper_instruction" scout tests`)
        — also found and removed the now-dead `ListingBatch` schema and
        the `tests/test_prompts.py` scraper-instruction tests, which
        weren't anticipated in the original task list.
  - [x] Delete the files/functions.
  - [x] Verify full suite still passes:
        `PYTHONPATH=. .venv/Scripts/python.exe -m pytest -q`
  - [ ] Commit: `chore(scraper): remove LLM-based tool-calling and normalization`
        *(deferred — see Notes / Learnings)*

---

## Verification

- [x] All phase tests pass: `PYTHONPATH=. .venv/Scripts/python.exe -m pytest -q`
      (109 passed)
- [x] Manual: `PYTHONPATH=. .venv/Scripts/python.exe -m scout.main` against
      the live `jobspy-mcp` + `postgres` containers gets past the scraper
      stage — and in this run went further than required, completing the
      *entire* pipeline: 34 listings scraped, tracked, scored, and a
      briefing email sent.

## Rollback

Revert the commits from this phase; `agent.py`/`tools.py`/the prompt
template are restorable from git history if the deterministic approach
needs to be abandoned.

---

## Notes / Learnings

- **Commits deferred:** every task's "Commit" step was left unticked.
  This session's standing rule is to only create git commits when the
  human explicitly asks, which takes precedence over the phase template's
  default commit-per-task cadence. All changes are complete and verified
  in the working tree, uncommitted.
- **Unplanned but necessary cleanup:** deleting `agent.py`/`tools.py` in
  Task 5 also orphaned `ListingBatch` in `scout/shared/schemas.py` (added
  earlier in this session for a since-superseded output-schema fix) and
  three scraper-instruction tests in `tests/test_prompts.py` that Task 5
  didn't originally list. Both were removed as part of Task 5 rather than
  left as dead code.
- **Went further than the phase required:** the manual verification run
  didn't just clear the scraper stage — the full pipeline completed
  (scraper → tracker → scorer → briefing → email sent), which also
  incidentally confirms the earlier `response_format: json_object` fix to
  the scorer and briefing agents (from the broader "fix them all" session
  context preceding this plan) is holding under live conditions.
