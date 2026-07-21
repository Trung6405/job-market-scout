# Phase 2: Scraper/Scorer Runners

> **Parent plan:** [plan.md](plan.md)
> **Status:** Not started
> **Depends on:** Phase 1 complete (needs `scout.shared.parsing.strip_code_fence`)

---

## Goal

Add `run_scraper` and `run_scorer`: async functions that build each
stage's existing `LlmAgent` (`build_scraper_agent` / `build_scorer_agent`),
run it through an `InMemoryRunner` exactly as `briefing/summarize.py`'s
`_run_briefing_agent` does, and parse the final response text into
`list[Listing]` / `list[ListingScore]`. Done when both functions have
green tests and are ready for Phase 3 to call directly.

## Safety Checklist

- **Touches user input, auth, secrets, or external calls?** Yes — these
  functions invoke the Scraper/Scorer `LlmAgent`s, which call out to the
  configured LLM and (for the Scraper) the JobSpy MCP tool. Tests mock the
  runner call itself (`_run_scraper_agent` / `_run_scorer_agent`), so no
  real network call happens in the test suite.
- **Contains a one-way door (schema, public API shape, new dependency)?** No.

---

## Tasks

### Task 1: `scout/sub_agents/scraper/runner.py` — `parse_listings`

- **Files:** `scout/sub_agents/scraper/runner.py`, `tests/test_scraper_runner.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing test:

    ```python
    from __future__ import annotations

    import json
    from datetime import datetime, timezone

    from scout.shared.schemas import Listing
    from scout.sub_agents.scraper.runner import parse_listings


    def _listing_dict(**overrides):
        defaults = dict(
            source="linkedin",
            external_id="1",
            title="Backend Engineer",
            company="Acme Corp",
            location="Sydney, AU",
            is_remote=True,
            url="https://www.linkedin.com/jobs/view/1",
            description="Build backend systems.",
            scraped_at=datetime(2026, 7, 15, tzinfo=timezone.utc).isoformat(),
        )
        defaults.update(overrides)
        return defaults


    def test_parse_listings_valid_json():
        raw = json.dumps([_listing_dict()])

        listings = parse_listings(raw)

        assert listings == [Listing(**_listing_dict())]


    def test_parse_listings_strips_markdown_code_fence():
        raw = "```json\n" + json.dumps([_listing_dict(external_id="2")]) + "\n```"

        listings = parse_listings(raw)

        assert listings[0].external_id == "2"


    def test_parse_listings_empty_list():
        assert parse_listings("[]") == []
    ```

  - [ ] Verify it fails (`pytest tests/test_scraper_runner.py -v`)
    Expected: `ModuleNotFoundError: No module named 'scout.sub_agents.scraper.runner'`
  - [ ] Implement `scout/sub_agents/scraper/runner.py` (parsing half only for this task):

    ```python
    from __future__ import annotations

    from pydantic import TypeAdapter

    from scout.shared.parsing import strip_code_fence
    from scout.shared.schemas import Listing

    _LISTING_LIST_ADAPTER = TypeAdapter(list[Listing])


    def parse_listings(raw_text: str) -> list[Listing]:
        return _LISTING_LIST_ADAPTER.validate_json(strip_code_fence(raw_text))
    ```

  - [ ] Verify it passes (`pytest tests/test_scraper_runner.py -v`)
    Expected: 3 passed
  - [ ] Commit: `feat(scraper): add parse_listings`

### Task 2: `run_scraper`

- **Files:** `scout/sub_agents/scraper/runner.py`, `tests/test_scraper_runner.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing test (append to `tests/test_scraper_runner.py`):

    ```python
    import pytest

    from scout.config import Settings
    from scout.sub_agents.scraper.runner import run_scraper


    @pytest.mark.asyncio
    async def test_run_scraper_returns_parsed_listings(monkeypatch):
        raw = json.dumps([_listing_dict()])

        async def _fake_run(agent):
            return raw

        monkeypatch.setattr(
            "scout.sub_agents.scraper.runner._run_scraper_agent", _fake_run
        )

        listings = await run_scraper(Settings())

        assert listings == [Listing(**_listing_dict())]
    ```

  - [ ] Verify it fails (`pytest tests/test_scraper_runner.py -v`)
    Expected: `AttributeError` / `ImportError` — `run_scraper` not defined
  - [ ] Implement the rest of `scout/sub_agents/scraper/runner.py`:

    ```python
    from google.adk.agents import LlmAgent
    from google.adk.runners import InMemoryRunner
    from google.genai import types as genai_types

    from scout.config import Settings
    from scout.config import settings as default_settings
    from scout.sub_agents.scraper.agent import build_scraper_agent

    _APP_NAME = "scraper"
    _USER_ID = "scraper"
    _SESSION_ID = "scraper"


    async def _run_scraper_agent(agent: LlmAgent) -> str:
        runner = InMemoryRunner(agent=agent, app_name=_APP_NAME)
        await runner.session_service.create_session(
            app_name=_APP_NAME, user_id=_USER_ID, session_id=_SESSION_ID
        )
        message = genai_types.Content(
            role="user", parts=[genai_types.Part(text="Find matching listings.")]
        )
        final_text: str | None = None
        async for event in runner.run_async(
            user_id=_USER_ID, session_id=_SESSION_ID, new_message=message
        ):
            if event.is_final_response() and event.content and event.content.parts:
                final_text = event.content.parts[0].text
        if final_text is None:
            raise ValueError("scraper agent produced no final response")
        return final_text


    async def run_scraper(settings: Settings | None = None) -> list[Listing]:
        active_settings = settings or default_settings
        agent = build_scraper_agent(active_settings)
        raw_text = await _run_scraper_agent(agent)
        return parse_listings(raw_text)
    ```

    (`parse_listings`, `TypeAdapter`, `strip_code_fence`, `Listing` imports
    stay from Task 1 — add the new imports above them.)
  - [ ] Verify it passes (`pytest tests/test_scraper_runner.py -v`)
    Expected: 4 passed
  - [ ] Commit: `feat(scraper): add run_scraper`

### Task 3: `scout/sub_agents/scorer/runner.py` — `parse_scores`

- **Files:** `scout/sub_agents/scorer/runner.py`, `tests/test_scorer_runner.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing test:

    ```python
    from __future__ import annotations

    import json

    from scout.shared.schemas import ListingScore
    from scout.sub_agents.scorer.runner import parse_scores


    def _score_dict(**overrides):
        defaults = dict(source="linkedin", external_id="1", score=75, reasoning="Good fit.")
        defaults.update(overrides)
        return defaults


    def test_parse_scores_valid_json():
        raw = json.dumps([_score_dict()])

        scores = parse_scores(raw)

        assert scores == [ListingScore(**_score_dict())]


    def test_parse_scores_strips_markdown_code_fence():
        raw = "```json\n" + json.dumps([_score_dict(external_id="2")]) + "\n```"

        scores = parse_scores(raw)

        assert scores[0].external_id == "2"


    def test_parse_scores_empty_list():
        assert parse_scores("[]") == []
    ```

  - [ ] Verify it fails (`pytest tests/test_scorer_runner.py -v`)
    Expected: `ModuleNotFoundError: No module named 'scout.sub_agents.scorer.runner'`
  - [ ] Implement `scout/sub_agents/scorer/runner.py` (parsing half only):

    ```python
    from __future__ import annotations

    from pydantic import TypeAdapter

    from scout.shared.parsing import strip_code_fence
    from scout.shared.schemas import ListingScore

    _SCORE_LIST_ADAPTER = TypeAdapter(list[ListingScore])


    def parse_scores(raw_text: str) -> list[ListingScore]:
        return _SCORE_LIST_ADAPTER.validate_json(strip_code_fence(raw_text))
    ```

  - [ ] Verify it passes (`pytest tests/test_scorer_runner.py -v`)
    Expected: 3 passed
  - [ ] Commit: `feat(scorer): add parse_scores`

### Task 4: `run_scorer`

- **Files:** `scout/sub_agents/scorer/runner.py`, `tests/test_scorer_runner.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing test (append to `tests/test_scorer_runner.py`):

    ```python
    from datetime import datetime, timezone

    import pytest

    from scout.config import Settings
    from scout.shared.schemas import Listing
    from scout.sub_agents.scorer.runner import run_scorer


    def _make_listing(**overrides):
        defaults = dict(
            source="linkedin",
            external_id="1",
            title="Backend Engineer",
            company="Acme Corp",
            location="Sydney, AU",
            is_remote=True,
            url="https://www.linkedin.com/jobs/view/1",
            description="Build backend systems.",
            scraped_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
        )
        defaults.update(overrides)
        return Listing(**defaults)


    @pytest.mark.asyncio
    async def test_run_scorer_returns_parsed_scores(monkeypatch):
        raw = json.dumps([_score_dict()])

        async def _fake_run(agent):
            return raw

        monkeypatch.setattr(
            "scout.sub_agents.scorer.runner._run_scorer_agent", _fake_run
        )

        scores = await run_scorer([_make_listing()], Settings())

        assert scores == [ListingScore(**_score_dict())]
    ```

  - [ ] Verify it fails (`pytest tests/test_scorer_runner.py -v`)
    Expected: `AttributeError` / `ImportError` — `run_scorer` not defined
  - [ ] Implement the rest of `scout/sub_agents/scorer/runner.py`:

    ```python
    from google.adk.agents import LlmAgent
    from google.adk.runners import InMemoryRunner
    from google.genai import types as genai_types

    from scout.config import Settings
    from scout.config import settings as default_settings
    from scout.shared.schemas import Listing
    from scout.sub_agents.scorer.agent import build_scorer_agent

    _APP_NAME = "scorer"
    _USER_ID = "scorer"
    _SESSION_ID = "scorer"


    async def _run_scorer_agent(agent: LlmAgent) -> str:
        runner = InMemoryRunner(agent=agent, app_name=_APP_NAME)
        await runner.session_service.create_session(
            app_name=_APP_NAME, user_id=_USER_ID, session_id=_SESSION_ID
        )
        message = genai_types.Content(
            role="user", parts=[genai_types.Part(text="Score these listings.")]
        )
        final_text: str | None = None
        async for event in runner.run_async(
            user_id=_USER_ID, session_id=_SESSION_ID, new_message=message
        ):
            if event.is_final_response() and event.content and event.content.parts:
                final_text = event.content.parts[0].text
        if final_text is None:
            raise ValueError("scorer agent produced no final response")
        return final_text


    async def run_scorer(
        listings: list[Listing], settings: Settings | None = None
    ) -> list[ListingScore]:
        active_settings = settings or default_settings
        agent = build_scorer_agent(listings, active_settings)
        raw_text = await _run_scorer_agent(agent)
        return parse_scores(raw_text)
    ```

    (`parse_scores`, `TypeAdapter`, `strip_code_fence`, `ListingScore`
    imports stay from Task 3 — add the new imports above them.)
  - [ ] Verify it passes (`pytest tests/test_scorer_runner.py -v`)
    Expected: 4 passed
  - [ ] Commit: `feat(scorer): add run_scorer`

---

## Verification

- [ ] All phase tests pass: `pytest tests/test_scraper_runner.py tests/test_scorer_runner.py -v`
- [ ] Full suite still green: `pytest -v`

## Observability

Not applicable yet — these are library functions with no logging of their
own; Phase 3's `ScoutPipelineAgent` is what surfaces their results as
visible progress.

## Rollback

Delete `scout/sub_agents/scraper/runner.py` and
`scout/sub_agents/scorer/runner.py` and their tests; nothing else depends
on them until Phase 3.

---

## Notes / Learnings

<Filled in during execution — anything that should inform later phases.>
