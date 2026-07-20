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
