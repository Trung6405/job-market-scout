from __future__ import annotations

from datetime import datetime, timezone
from email.message import EmailMessage

import pytest
from google.adk.runners import InMemoryRunner
from google.genai import types as genai_types

from scout.shared.db import get_run_by_date, get_run_listings, upsert_listing
from scout.shared.schemas import Listing, ListingScore
from scout.sub_agents.scorer.results import join_match_results

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

    class _FakeConn:
        pass

    class _FakePoolAcquire:
        async def __aenter__(self):
            return _FakeConn()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _FakePool:
        def acquire(self):
            return _FakePoolAcquire()

        async def close(self):
            calls.append("pool_closed")

    async def _fake_create_pool(settings):
        calls.append("create_pool")
        return _FakePool()

    async def _fake_start_run(conn, run_date):
        calls.append(("start_run", run_date))
        return 1

    async def _fake_record_run_listings(conn, run_id, matches):
        calls.append(("record_run_listings", run_id, matches))

    async def _fake_finish_run(conn, run_id, *, listings_scraped, listings_scored):
        calls.append(
            ("finish_run", run_id, listings_scraped, listings_scored)
        )

    monkeypatch.setattr("scout.agent.run_scraper", _fake_run_scraper)
    monkeypatch.setattr("scout.agent.track_listings", _fake_track_listings)
    monkeypatch.setattr("scout.agent.run_scorer", _fake_run_scorer)
    monkeypatch.setattr("scout.agent.run_briefing", _fake_run_briefing)
    monkeypatch.setattr("scout.agent.create_pool", _fake_create_pool)
    monkeypatch.setattr("scout.agent.start_run", _fake_start_run)
    monkeypatch.setattr("scout.agent.record_run_listings", _fake_record_run_listings)
    monkeypatch.setattr("scout.agent.finish_run", _fake_finish_run)

    texts = await _run_pipeline_agent()

    assert calls[0] == "scraper"
    assert calls[1] == ("tracker", [listing])
    assert calls[2] == ("scorer", [listing])
    assert calls[3] == "create_pool"
    assert calls[4][0] == "start_run"
    assert calls[5][0] == "record_run_listings"
    assert calls[5][2] == join_match_results([listing], [score])
    assert calls[6] == ("finish_run", 1, 1, 1)
    assert calls[7] == "pool_closed"
    assert calls[8] == ("briefing", [listing], [score])
    assert any("Scraper: 1 listing" in t for t in texts)
    assert any("Tracker: 1 new/changed" in t for t in texts)
    assert any("Scorer: 1 scored" in t for t in texts)
    assert any("Run persisted:" in t for t in texts)
    assert any("Briefing: email sent" in t for t in texts)


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


@pytest.mark.asyncio
async def test_scout_pipeline_agent_persists_run(monkeypatch, db_pool):
    listing = _make_listing()
    score = ListingScore(
        source="linkedin", external_id="1", score=80, reasoning="Good fit."
    )

    # Seed the listings table so record_run_listings can join on it.
    async with db_pool.acquire() as conn:
        await upsert_listing(conn, listing)

    async def _fake_run_scraper(settings):
        return [listing]

    async def _fake_track_listings(listings, settings=None):
        return listings

    async def _fake_run_scorer(listings, settings):
        return [score]

    async def _fake_run_briefing(listings, scores, settings):
        return EmailMessage()

    monkeypatch.setattr("scout.agent.run_scraper", _fake_run_scraper)
    monkeypatch.setattr("scout.agent.track_listings", _fake_track_listings)
    monkeypatch.setattr("scout.agent.run_scorer", _fake_run_scorer)
    monkeypatch.setattr("scout.agent.run_briefing", _fake_run_briefing)

    texts = await _run_pipeline_agent()

    run_date = datetime.now(timezone.utc).date()
    async with db_pool.acquire() as conn:
        run = await get_run_by_date(conn, run_date)
        assert run is not None
        assert run.listings_scraped == 1
        assert run.listings_scored == 1

        run_listings = await get_run_listings(conn, run.id)
        assert len(run_listings) == 1
        assert run_listings[0].score == 80
        assert run_listings[0].reasoning == "Good fit."

    assert any(f"Run persisted: {run_date}" in t for t in texts)
