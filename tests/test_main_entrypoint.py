from __future__ import annotations

from datetime import datetime, timezone
from email.message import EmailMessage

import pytest

from scout.shared.schemas import Listing, ListingScore


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
async def test_run_once_completes_without_raising(monkeypatch):
    listing = _make_listing()
    score = ListingScore(source="linkedin", external_id="1", score=80, reasoning="Good fit.")

    async def _fake_run_scraper(settings):
        return [listing]

    async def _fake_track_listings(listings, settings=None):
        return listings

    async def _fake_run_scorer(listings, settings):
        return [score]

    async def _fake_run_briefing(listings, scores, settings, report_path=None):
        return EmailMessage()

    monkeypatch.setattr("scout.agent.run_scraper", _fake_run_scraper)
    monkeypatch.setattr("scout.agent.track_listings", _fake_track_listings)
    monkeypatch.setattr("scout.agent.run_scorer", _fake_run_scorer)
    monkeypatch.setattr("scout.agent.run_briefing", _fake_run_briefing)
    # scout/profile.json is a tracked placeholder present in CI; without this stub
    # run_once would take the advisor's real LLM path and fail on a missing API
    # key. Skip the profile-dependent path to keep this smoke test hermetic.
    monkeypatch.setattr("scout.agent.load_profile", lambda path: None)

    from scout.main import run_once

    await run_once()


@pytest.mark.asyncio
async def test_run_once_propagates_stage_exception(monkeypatch):
    """A real exception raised inside a stage (run_scraper) must propagate
    all the way out of run_once() — i.e. InMemoryRunner must not swallow it
    into an error event. This is an integration check of ADK's real runner
    behavior, not a mock of run_once itself."""

    async def _raising_run_scraper(settings):
        raise RuntimeError("scraper failed")

    monkeypatch.setattr("scout.agent.run_scraper", _raising_run_scraper)

    from scout.main import run_once

    with pytest.raises(RuntimeError, match="scraper failed"):
        await run_once()


def test_main_exits_nonzero_when_run_once_raises(monkeypatch):
    async def _fake_run_once():
        raise RuntimeError("boom")

    monkeypatch.setattr("scout.main.run_once", _fake_run_once)

    from scout.main import main

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
