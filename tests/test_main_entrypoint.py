from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

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
async def test_run_once_completes_without_raising(monkeypatch, db_pool):
    listing = _make_listing()
    score = ListingScore(source="linkedin", external_id="1", score=80, reasoning="Good fit.")

    async def _fake_run_scraper(settings):
        return [listing]

    async def _fake_track_listings(listings, settings=None):
        return listings

    async def _fake_run_scorer(listings, settings):
        return [score]

    async def _fake_run_briefing(matches, settings, report_path=None):
        return {}

    class _UnclosablePool:
        """Wraps db_pool so scout.agent's `finally: await pool.close()` doesn't
        tear down the shared test fixture pool."""

        def acquire(self):
            return db_pool.acquire()

        async def close(self):
            pass

    async def _fake_create_pool(settings):
        return _UnclosablePool()

    async def _fake_render_run(conn, run_id, settings):
        return {"dashboard": Path("reports/2026-07-21/dashboard.html")}

    async def _fake_render_history(conn, settings):
        return Path("reports/history.html")

    def _fake_render_profile(profile, settings):
        return Path("reports/profile.html")

    monkeypatch.setattr("scout.agent.run_scraper", _fake_run_scraper)
    monkeypatch.setattr("scout.agent.track_listings", _fake_track_listings)
    monkeypatch.setattr("scout.agent.run_scorer", _fake_run_scorer)
    monkeypatch.setattr("scout.agent.run_briefing", _fake_run_briefing)
    # run_once() resolves the real Settings().database_url and renders real
    # report files. Left unmocked, this smoke test writes a fixture run into
    # the DEV database (and ./reports) whenever Postgres happens to be
    # reachable — polluting real dashboard data. Point it at the isolated
    # scout_test pool and stub the renderers instead.
    monkeypatch.setattr("scout.agent.create_pool", _fake_create_pool)
    monkeypatch.setattr("scout.agent.render_run", _fake_render_run)
    monkeypatch.setattr("scout.agent.render_history", _fake_render_history)
    monkeypatch.setattr("scout.agent.render_profile", _fake_render_profile)
    # Profile is always present now (committed profile.json), so gap detection
    # runs; mock the advisor LLM call so this smoke test stays hermetic.
    async def _fake_requirements(listings, settings=None):
        return []

    monkeypatch.setattr("scout.agent.run_requirements_extraction", _fake_requirements)

    from scout.main import run_once

    await run_once()


@pytest.mark.asyncio
async def test_run_once_propagates_stage_exception(monkeypatch):
    """A real exception raised inside a stage (run_scraper) must propagate
    all the way out of run_once() rather than being swallowed while
    iterating the agent's event stream."""

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
