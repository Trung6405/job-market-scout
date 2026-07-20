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

    async def _fake_run_briefing(listings, scores, settings):
        return EmailMessage()

    monkeypatch.setattr("scout.agent.run_scraper", _fake_run_scraper)
    monkeypatch.setattr("scout.agent.track_listings", _fake_track_listings)
    monkeypatch.setattr("scout.agent.run_scorer", _fake_run_scorer)
    monkeypatch.setattr("scout.agent.run_briefing", _fake_run_briefing)

    from scout.main import run_once

    await run_once()


def test_main_exits_nonzero_when_run_once_raises(monkeypatch):
    async def _fake_run_once():
        raise RuntimeError("boom")

    monkeypatch.setattr("scout.main.run_once", _fake_run_once)

    from scout.main import main

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
