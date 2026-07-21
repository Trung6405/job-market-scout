# Phase 3: ScoutPipelineAgent

> **Parent plan:** [plan.md](plan.md)
> **Status:** Not started
> **Depends on:** Phase 2 complete (needs `run_scraper`, `run_scorer`)

---

## Goal

Build `ScoutPipelineAgent` in `scout/agent.py`: a custom (non-LLM) ADK
`BaseAgent` whose `_run_async_impl` runs Scraper → Tracker → (short-circuit
if nothing new/changed) → Scorer → Briefing in order, yielding a
human-readable `Event` after each stage. Export `root_agent =
ScoutPipelineAgent()` so `adk web`, pointed at the repo root, discovers it
the same way each sub-agent's own `root_agent` already works standalone.
Done when a developer can run `adk web`, send the agent any message, and
see four (or two, on the short-circuit path) distinct progress messages in
the UI — verified here by driving the agent through `InMemoryRunner` in
tests, then manually via `adk web` itself.

## Safety Checklist

- **Touches user input, auth, secrets, or external calls?** Yes — this is
  the first place all four stages (including the real Tracker/DB write and
  Briefing's email send) get called together. Tests monkeypatch
  `scout.agent.run_scraper`, `scout.agent.track_listings`,
  `scout.agent.run_scorer`, and `scout.agent.run_briefing` directly, so no
  real DB, LLM, or email call happens in the test suite.
- **Contains a one-way door (schema, public API shape, new dependency)?** No.

---

## Tasks

### Task 1: Full-path event sequence

- **Files:** `scout/agent.py`, `tests/test_agent.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing test:

    ```python
    from __future__ import annotations

    from datetime import datetime, timezone
    from email.message import EmailMessage

    import pytest
    from google.adk.runners import InMemoryRunner
    from google.genai import types as genai_types

    from scout.shared.schemas import Listing, ListingScore

    _APP_NAME = "scout"
    _USER_ID = "scout"
    _SESSION_ID = "scout"


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


    async def _run_pipeline_agent():
        from scout.agent import ScoutPipelineAgent

        runner = InMemoryRunner(agent=ScoutPipelineAgent(), app_name=_APP_NAME)
        await runner.session_service.create_session(
            app_name=_APP_NAME, user_id=_USER_ID, session_id=_SESSION_ID
        )
        message = genai_types.Content(
            role="user", parts=[genai_types.Part(text="Run the pipeline.")]
        )
        texts = []
        async for event in runner.run_async(
            user_id=_USER_ID, session_id=_SESSION_ID, new_message=message
        ):
            if event.content and event.content.parts and event.content.parts[0].text:
                texts.append(event.content.parts[0].text)
        return texts


    @pytest.mark.asyncio
    async def test_scout_pipeline_agent_reports_progress_for_full_run(monkeypatch):
        listing = _make_listing()
        score = ListingScore(source="linkedin", external_id="1", score=80, reasoning="Good fit.")

        calls = []

        async def _fake_run_scraper(settings):
            calls.append("scraper")
            return [listing]

        async def _fake_track_listings(listings, settings=None):
            calls.append(("tracker", listings))
            return listings

        async def _fake_run_scorer(listings, settings):
            calls.append(("scorer", listings))
            return [score]

        async def _fake_run_briefing(listings, scores, settings):
            calls.append(("briefing", listings, scores))
            return EmailMessage()

        monkeypatch.setattr("scout.agent.run_scraper", _fake_run_scraper)
        monkeypatch.setattr("scout.agent.track_listings", _fake_track_listings)
        monkeypatch.setattr("scout.agent.run_scorer", _fake_run_scorer)
        monkeypatch.setattr("scout.agent.run_briefing", _fake_run_briefing)

        texts = await _run_pipeline_agent()

        assert calls[0] == "scraper"
        assert calls[1] == ("tracker", [listing])
        assert calls[2] == ("scorer", [listing])
        assert calls[3] == ("briefing", [listing], [score])
        assert any("Scraper: 1 listing" in t for t in texts)
        assert any("Tracker: 1 new/changed" in t for t in texts)
        assert any("Scorer: 1 scored" in t for t in texts)
        assert any("Briefing: email sent" in t for t in texts)
    ```

  - [ ] Verify it fails (`pytest tests/test_agent.py -v`)
    Expected: `ModuleNotFoundError: No module named 'scout.agent'` has no `ScoutPipelineAgent` (import error)
  - [ ] Implement `scout/agent.py`:

    ```python
    from __future__ import annotations

    from typing import AsyncGenerator

    from google.adk.agents import BaseAgent
    from google.adk.agents.invocation_context import InvocationContext
    from google.adk.events import Event
    from google.genai import types as genai_types

    from scout.config import settings as default_settings
    from scout.sub_agents.briefing.briefing import run_briefing
    from scout.sub_agents.scorer.runner import run_scorer
    from scout.sub_agents.scraper.runner import run_scraper
    from scout.tools.tracker import track_listings


    def _status_event(ctx: InvocationContext, author: str, text: str) -> Event:
        return Event(
            invocation_id=ctx.invocation_id,
            author=author,
            branch=ctx.branch,
            content=genai_types.Content(
                role="model", parts=[genai_types.Part.from_text(text=text)]
            ),
        )


    class ScoutPipelineAgent(BaseAgent):
        name: str = "scout"

        async def _run_async_impl(
            self, ctx: InvocationContext
        ) -> AsyncGenerator[Event, None]:
            settings = default_settings

            listings = await run_scraper(settings)
            yield _status_event(
                ctx, self.name, f"Scraper: {len(listings)} listing(s) found"
            )

            relevant = await track_listings(listings, settings=settings)
            yield _status_event(
                ctx, self.name, f"Tracker: {len(relevant)} new/changed"
            )

            scores = await run_scorer(relevant, settings)
            yield _status_event(ctx, self.name, f"Scorer: {len(scores)} scored")

            await run_briefing(relevant, scores, settings)
            yield _status_event(ctx, self.name, "Briefing: email sent")


    root_agent = ScoutPipelineAgent()
    ```

  - [ ] Verify it passes (`pytest tests/test_agent.py -v`)
    Expected: 1 passed
  - [ ] Commit: `feat(agent): add ScoutPipelineAgent full-run wiring`

### Task 2: Short-circuit when nothing new/changed

- **Files:** `scout/agent.py`, `tests/test_agent.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing test (append to `tests/test_agent.py`):

    ```python
    @pytest.mark.asyncio
    async def test_scout_pipeline_agent_short_circuits_when_nothing_relevant(
        monkeypatch,
    ):
        listing = _make_listing()
        calls = []

        async def _fake_run_scraper(settings):
            return [listing]

        async def _fake_track_listings(listings, settings=None):
            return []

        async def _fake_run_scorer(listings, settings):
            calls.append("scorer")
            return []

        async def _fake_run_briefing(listings, scores, settings):
            calls.append("briefing")
            return EmailMessage()

        monkeypatch.setattr("scout.agent.run_scraper", _fake_run_scraper)
        monkeypatch.setattr("scout.agent.track_listings", _fake_track_listings)
        monkeypatch.setattr("scout.agent.run_scorer", _fake_run_scorer)
        monkeypatch.setattr("scout.agent.run_briefing", _fake_run_briefing)

        texts = await _run_pipeline_agent()

        assert calls == []
        assert any("Tracker: 0 new/changed" in t for t in texts)
        assert any("nothing to score or brief" in t.lower() for t in texts)
    ```

  - [ ] Verify it fails (`pytest tests/test_agent.py -v`)
    Expected: `test_scout_pipeline_agent_short_circuits_when_nothing_relevant` fails — `run_scorer`/`run_briefing` still get called (`calls == ["scorer", "briefing"]` instead of `[]`)
  - [ ] Update `scout/agent.py`'s `_run_async_impl` to short-circuit after the Tracker stage:

    ```python
    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        settings = default_settings

        listings = await run_scraper(settings)
        yield _status_event(
            ctx, self.name, f"Scraper: {len(listings)} listing(s) found"
        )

        relevant = await track_listings(listings, settings=settings)
        yield _status_event(
            ctx, self.name, f"Tracker: {len(relevant)} new/changed"
        )

        if not relevant:
            yield _status_event(
                ctx,
                self.name,
                "No new or changed listings — nothing to score or brief.",
            )
            return

        scores = await run_scorer(relevant, settings)
        yield _status_event(ctx, self.name, f"Scorer: {len(scores)} scored")

        await run_briefing(relevant, scores, settings)
        yield _status_event(ctx, self.name, "Briefing: email sent")
    ```

  - [ ] Verify it passes (`pytest tests/test_agent.py -v`)
    Expected: 2 passed
  - [ ] Commit: `feat(agent): short-circuit ScoutPipelineAgent when nothing is new`

---

## Verification

- [ ] All phase tests pass: `pytest tests/test_agent.py -v`
- [ ] Full suite still green: `pytest -v`
- [ ] Manual: from the repo root, run `adk web`, open the UI, select the
  `scout` agent, send it any message, and confirm the transcript shows
  four distinct progress messages in order (or two, if you've cleared the
  local Postgres so nothing is "new"). This is the first real check of the
  acceptance criterion "watch the pipeline progress stage by stage in the
  ADK web UI" — it requires the local Docker Postgres (port 5433) and a
  valid `DEEPSEEK_API_KEY` to actually run the LLM stages, since this
  phase does not mock them at the `adk web` boundary.

## Observability

Each stage yields one `Event` with a short plain-text status
(`"Scraper: N listing(s) found"`, `"Tracker: N new/changed"`,
`"Scorer: N scored"`, `"Briefing: email sent"`, or the short-circuit
message) — this is the entire observability surface for this phase, and
is what makes `adk web`'s transcript useful for behavior testing.

## Rollback

Revert both commits; `scout/agent.py` returns to being an empty stub (its
pre-existing state). Nothing else in the codebase imports from it yet.

---

## Notes / Learnings

<Filled in during execution — anything that should inform later phases.>
