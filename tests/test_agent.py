from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from scout.config import settings as default_settings
from scout.shared.db import (
    finish_run,
    get_run_by_date,
    get_run_listings,
    start_run,
    upsert_listing,
)
from scout.shared.schemas import (
    Background,
    Listing,
    ListingRequirements,
    ListingScore,
    Profile,
    RequirementItem,
    TechCategory,
    TechSkill,
)
from scout.sub_agents.advisor.bands import classify_band
from scout.sub_agents.scorer.results import join_match_results


class _FakeTransaction:
    """Stand-in for asyncpg's conn.transaction() async context manager."""

    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.fixture(autouse=True)
def _discord_configured_for_briefing():
    """The pipeline only runs briefing when Discord is configured
    (scout/agent.py). Configure it on the shared settings singleton so these
    tests exercise the briefing path deterministically, independent of whether
    a local scout/.env supplies DISCORD_BOT_TOKEN / DISCORD_CHANNEL_ID."""
    saved = (default_settings.discord_bot_token, default_settings.discord_channel_id)
    object.__setattr__(default_settings, "discord_bot_token", "bot-token")
    object.__setattr__(default_settings, "discord_channel_id", "123456789")
    try:
        yield
    finally:
        object.__setattr__(default_settings, "discord_bot_token", saved[0])
        object.__setattr__(default_settings, "discord_channel_id", saved[1])


def _make_profile(**overrides):
    defaults = dict(
        name="Test Student",
        target_role="Junior Software Engineer",
        target_locations=["Sydney"],
        tech_stack=[
            TechCategory(
                category="Languages",
                skills=[TechSkill(name="Python", proficiency=4)],
            )
        ],
        domain_knowledge=[],
        background=Background(
            education="B.Sc. Computer Science",
            experience="0.5 yrs",
            preferred_roles=["Software Engineer"],
            locations=["Sydney"],
        ),
        projects=[],
    )
    defaults.update(overrides)
    return Profile(**defaults)


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

    agent = ScoutPipelineAgent()
    texts = []
    async for event in agent.run():
        texts.append(event.text)
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

    async def _fake_run_briefing(matches, settings, report_path=None):
        calls.append(("briefing", matches, report_path))
        return {}

    class _FakeConn:
        def transaction(self):
            return _FakeTransaction()

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

    async def _fake_render_run(conn, run_id, settings):
        calls.append(("render_run", run_id))
        return {"dashboard": Path("reports/2026-07-21/dashboard.html")}

    async def _fake_render_history(conn, settings):
        calls.append("render_history")
        return Path("reports/history.html")

    def _fake_render_profile(profile, settings):
        calls.append("render_profile")
        return Path("reports/profile.html")

    async def _fake_get_adjacent_runs(conn, run_date):
        return None, None

    async def _fake_requirements(listings, settings=None):
        return [
            ListingRequirements(
                source=item.source,
                external_id=item.external_id,
                must_have=[],
                nice_to_have=[],
            )
            for item in listings
        ]

    async def _fake_record_listing_gaps(conn, run_id, checks_by_match):
        pass

    async def _fake_record_listing_meta(conn, run_id, matches_with_requirements):
        pass

    monkeypatch.setattr("scout.agent.run_scraper", _fake_run_scraper)
    monkeypatch.setattr("scout.agent.track_listings", _fake_track_listings)
    monkeypatch.setattr("scout.agent.run_scorer", _fake_run_scorer)
    monkeypatch.setattr("scout.agent.run_briefing", _fake_run_briefing)
    monkeypatch.setattr("scout.agent.create_pool", _fake_create_pool)
    monkeypatch.setattr("scout.agent.start_run", _fake_start_run)
    monkeypatch.setattr("scout.agent.record_run_listings", _fake_record_run_listings)
    monkeypatch.setattr("scout.agent.finish_run", _fake_finish_run)
    monkeypatch.setattr("scout.agent.render_run", _fake_render_run)
    monkeypatch.setattr("scout.agent.render_history", _fake_render_history)
    monkeypatch.setattr("scout.agent.render_profile", _fake_render_profile)
    monkeypatch.setattr("scout.agent.get_adjacent_runs", _fake_get_adjacent_runs)
    # Profile is always present now (settings.profile from the committed
    # profile.json), so gap detection runs; mock its LLM + DB writes to keep
    # this ordering test hermetic.
    monkeypatch.setattr("scout.agent.run_requirements_extraction", _fake_requirements)
    monkeypatch.setattr("scout.agent.record_listing_gaps", _fake_record_listing_gaps)
    monkeypatch.setattr("scout.agent.record_listing_meta", _fake_record_listing_meta)

    texts = await _run_pipeline_agent()

    assert calls[0] == "scraper"
    assert calls[1] == ("tracker", [listing])
    assert calls[2] == "create_pool"
    assert calls[3][0] == "start_run"
    assert calls[4] == ("scorer", [listing])
    assert calls[5][0] == "record_run_listings"
    expected_matches = join_match_results([listing], [score])
    expected_banded_matches = [
        (match, classify_band(match.score, default_settings))
        for match in expected_matches
    ]
    assert calls[5][2] == expected_banded_matches
    assert calls[6] == ("finish_run", 1, 1, 1)
    assert calls[7] == ("render_run", 1)
    assert calls[8] == "render_history"
    # Profile is present, so render_profile runs before the pool closes.
    assert calls[9] == "render_profile"
    assert calls[10] == "pool_closed"
    assert calls[11] == (
        "briefing",
        expected_matches,
        Path("reports/2026-07-21/dashboard.html"),
    )
    assert "render_profile" in calls
    assert any("Scraper: 1 listing" in t for t in texts)
    assert any("Tracker: 1 new/changed" in t for t in texts)
    assert any("Scorer: 1 scored" in t for t in texts)
    assert any("Report rendered:" in t for t in texts)
    assert any("Run persisted:" in t for t in texts)
    assert any("Briefing: Discord message sent" in t for t in texts)


@pytest.mark.asyncio
async def test_scout_pipeline_agent_renders_report_after_persisting_run(
    monkeypatch,
):
    listing = _make_listing()
    score = ListingScore(source="linkedin", external_id="1", score=80, reasoning="Good fit.")
    profile = _make_profile()
    requirements = ListingRequirements(
        source="linkedin",
        external_id="1",
        must_have=[],
        nice_to_have=[],
    )

    calls = []

    async def _fake_run_scraper(settings):
        return [listing]

    async def _fake_track_listings(listings, settings=None):
        return listings

    async def _fake_run_scorer(listings, settings):
        return [score]

    async def _fake_run_briefing(matches, settings, report_path=None):
        calls.append("briefing")
        return {}

    class _FakeConn:
        def transaction(self):
            return _FakeTransaction()

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
        return _FakePool()

    async def _fake_start_run(conn, run_date):
        return 1

    async def _fake_record_run_listings(conn, run_id, matches):
        pass

    async def _fake_finish_run(conn, run_id, *, listings_scraped, listings_scored):
        calls.append("finish_run")

    def _fake_load_profile(path):
        return profile

    async def _fake_run_requirements_extraction(listings, settings=None):
        return [requirements]

    async def _fake_record_listing_gaps(conn, run_id, gaps_by_match):
        pass

    async def _fake_record_listing_meta(conn, run_id, meta_by_match):
        pass

    async def _fake_render_run(conn, run_id, settings):
        calls.append(("render_run", conn, run_id, settings))
        return {"dashboard": Path("reports/2026-07-21/dashboard.html")}

    async def _fake_render_history(conn, settings):
        calls.append(("render_history", conn, settings))
        return Path("reports/history.html")

    def _fake_render_profile(profile_arg, settings):
        calls.append(("render_profile", profile_arg, settings))
        return Path("reports/profile.html")

    async def _fake_get_adjacent_runs(conn, run_date):
        return None, None

    monkeypatch.setattr("scout.agent.run_scraper", _fake_run_scraper)
    monkeypatch.setattr("scout.agent.track_listings", _fake_track_listings)
    monkeypatch.setattr("scout.agent.run_scorer", _fake_run_scorer)
    monkeypatch.setattr("scout.agent.run_briefing", _fake_run_briefing)
    monkeypatch.setattr("scout.agent.create_pool", _fake_create_pool)
    monkeypatch.setattr("scout.agent.start_run", _fake_start_run)
    monkeypatch.setattr("scout.agent.record_run_listings", _fake_record_run_listings)
    monkeypatch.setattr("scout.agent.finish_run", _fake_finish_run)
    monkeypatch.setattr("scout.agent.load_profile", _fake_load_profile)
    monkeypatch.setattr(
        "scout.agent.run_requirements_extraction", _fake_run_requirements_extraction
    )
    monkeypatch.setattr("scout.agent.record_listing_gaps", _fake_record_listing_gaps)
    monkeypatch.setattr("scout.agent.record_listing_meta", _fake_record_listing_meta)
    monkeypatch.setattr("scout.agent.render_run", _fake_render_run)
    monkeypatch.setattr("scout.agent.render_history", _fake_render_history)
    monkeypatch.setattr("scout.agent.render_profile", _fake_render_profile)
    monkeypatch.setattr("scout.agent.get_adjacent_runs", _fake_get_adjacent_runs)

    texts = await _run_pipeline_agent()

    assert calls[0] == "finish_run"
    assert calls[1][0] == "render_run"
    assert calls[1][2] == 1
    assert calls[1][3] is default_settings
    assert calls[2][0] == "render_history"
    assert calls[2][2] is default_settings
    assert calls[3][0] == "render_profile"
    assert calls[3][1] is profile
    assert calls[3][2] is default_settings
    assert calls[4] == "pool_closed"
    assert calls[5] == "briefing"
    assert any("Report rendered:" in t for t in texts)
    report_text = next(t for t in texts if "Report rendered:" in t)
    assert "dashboard.html" in report_text


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

    async def _fake_run_briefing(matches, settings, report_path=None):
        calls.append("briefing")
        return {}

    class _FakeConn:
        def transaction(self):
            return _FakeTransaction()

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
        return _FakePool()

    async def _fake_start_run(conn, run_date):
        calls.append(("start_run", run_date))
        return 1

    async def _fake_finish_run(conn, run_id, *, listings_scraped, listings_scored):
        calls.append(("finish_run", run_id, listings_scraped, listings_scored))

    async def _fake_render_history(conn, settings):
        calls.append("render_history")
        return Path("reports/history.html")

    monkeypatch.setattr("scout.agent.run_scraper", _fake_run_scraper)
    monkeypatch.setattr("scout.agent.track_listings", _fake_track_listings)
    monkeypatch.setattr("scout.agent.run_scorer", _fake_run_scorer)
    monkeypatch.setattr("scout.agent.run_briefing", _fake_run_briefing)
    monkeypatch.setattr("scout.agent.create_pool", _fake_create_pool)
    monkeypatch.setattr("scout.agent.start_run", _fake_start_run)
    monkeypatch.setattr("scout.agent.finish_run", _fake_finish_run)
    monkeypatch.setattr("scout.agent.render_history", _fake_render_history)

    texts = await _run_pipeline_agent()

    assert calls[0][0] == "start_run"
    assert calls[1] == ("finish_run", 1, 1, 0)
    assert calls[2] == "render_history"
    assert calls[3] == "pool_closed"
    assert "scorer" not in [c if isinstance(c, str) else c[0] for c in calls]
    assert "briefing" not in [c if isinstance(c, str) else c[0] for c in calls]
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

    async def _fake_run_briefing(matches, settings, report_path=None):
        return {}

    render_calls = []

    async def _fake_render_run(conn, run_id, settings):
        render_calls.append(("render_run", run_id))
        return {"dashboard": Path("reports/2026-07-21/dashboard.html")}

    async def _fake_render_history(conn, settings):
        render_calls.append("render_history")
        return Path("reports/history.html")

    class _UnclosablePool:
        """Wraps db_pool so scout.agent's `finally: await pool.close()` doesn't
        tear down the shared test fixture pool out from under later assertions."""

        def acquire(self):
            return db_pool.acquire()

        async def close(self):
            pass

    async def _fake_create_pool(settings):
        return _UnclosablePool()

    monkeypatch.setattr("scout.agent.run_scraper", _fake_run_scraper)
    monkeypatch.setattr("scout.agent.track_listings", _fake_track_listings)
    monkeypatch.setattr("scout.agent.run_scorer", _fake_run_scorer)
    monkeypatch.setattr("scout.agent.run_briefing", _fake_run_briefing)
    monkeypatch.setattr("scout.agent.render_run", _fake_render_run)
    monkeypatch.setattr("scout.agent.render_history", _fake_render_history)
    monkeypatch.setattr("scout.agent.create_pool", _fake_create_pool)
    # Profile is always present now (loaded from the committed profile.json), so
    # gap detection runs. Gap detection has its own test
    # (test_scout_pipeline_agent_records_gaps_when_profile_exists); here we mock
    # the advisor LLM call and the profile render to keep the persist assertions
    # hermetic.
    async def _fake_requirements(listings, settings=None):
        return []

    def _fake_render_profile(profile, settings):
        return Path("reports/profile.html")

    monkeypatch.setattr("scout.agent.run_requirements_extraction", _fake_requirements)
    monkeypatch.setattr("scout.agent.render_profile", _fake_render_profile)

    texts = await _run_pipeline_agent()

    run_date = datetime.now(ZoneInfo("Australia/Melbourne")).date()
    async with db_pool.acquire() as conn:
        run = await get_run_by_date(conn, run_date)
        assert run is not None
        assert run.listings_scraped == 1
        assert run.listings_scored == 1

        run_listings = await get_run_listings(conn, run.id)
        assert len(run_listings) == 1
        assert run_listings[0].score == 80
        assert run_listings[0].reasoning == "Good fit."

    assert render_calls[0] == ("render_run", run.id)
    assert render_calls[1] == "render_history"
    assert any(f"Run persisted: {run_date}" in t for t in texts)


@pytest.mark.asyncio
async def test_scout_pipeline_agent_rerenders_previous_day_so_its_next_link_fills_in(
    monkeypatch, db_pool
):
    """The previous day's page was rendered before today's run existed, so its
    "next day" link was empty at the time. Persisting today's run should
    re-render that previous page too, so the link fills in without waiting for
    a full rerender."""
    listing = _make_listing()
    score = ListingScore(
        source="linkedin", external_id="1", score=80, reasoning="Good fit."
    )

    async with db_pool.acquire() as conn:
        await upsert_listing(conn, listing)
        run_date = datetime.now(ZoneInfo("Australia/Melbourne")).date()
        prev_run_id = await start_run(conn, run_date - timedelta(days=1))
        await finish_run(conn, prev_run_id, listings_scraped=1, listings_scored=1)

    async def _fake_run_scraper(settings):
        return [listing]

    async def _fake_track_listings(listings, settings=None):
        return listings

    async def _fake_run_scorer(listings, settings):
        return [score]

    async def _fake_run_briefing(matches, settings, report_path=None):
        return {}

    render_calls = []

    async def _fake_render_run(conn, run_id, settings):
        render_calls.append(("render_run", run_id))
        return {"dashboard": Path("reports/2026-07-21/dashboard.html")}

    async def _fake_render_history(conn, settings):
        render_calls.append("render_history")
        return Path("reports/history.html")

    class _UnclosablePool:
        def acquire(self):
            return db_pool.acquire()

        async def close(self):
            pass

    async def _fake_create_pool(settings):
        return _UnclosablePool()

    monkeypatch.setattr("scout.agent.run_scraper", _fake_run_scraper)
    monkeypatch.setattr("scout.agent.track_listings", _fake_track_listings)
    monkeypatch.setattr("scout.agent.run_scorer", _fake_run_scorer)
    monkeypatch.setattr("scout.agent.run_briefing", _fake_run_briefing)
    monkeypatch.setattr("scout.agent.render_run", _fake_render_run)
    monkeypatch.setattr("scout.agent.render_history", _fake_render_history)
    monkeypatch.setattr("scout.agent.create_pool", _fake_create_pool)

    async def _fake_requirements(listings, settings=None):
        return []

    def _fake_render_profile(profile, settings):
        return Path("reports/profile.html")

    monkeypatch.setattr("scout.agent.run_requirements_extraction", _fake_requirements)
    monkeypatch.setattr("scout.agent.render_profile", _fake_render_profile)

    await _run_pipeline_agent()

    async with db_pool.acquire() as conn:
        run = await get_run_by_date(conn, run_date)
        assert run is not None

    assert render_calls[0] == ("render_run", run.id)
    assert render_calls[1] == "render_history"
    assert render_calls[2] == ("render_run", prev_run_id)


@pytest.mark.asyncio
async def test_scout_pipeline_agent_warns_when_extraction_drops_listings(monkeypatch):
    listing = _make_listing()
    score = ListingScore(
        source="linkedin", external_id="1", score=80, reasoning="Good fit."
    )
    profile = _make_profile()

    async def _fake_run_scraper(settings):
        return [listing]

    async def _fake_track_listings(listings, settings=None):
        return listings

    async def _fake_run_scorer(listings, settings):
        return [score]

    async def _fake_run_briefing(matches, settings, report_path=None):
        return {}

    class _FakeConn:
        def transaction(self):
            return _FakeTransaction()

    class _FakeTransaction:
        async def __aenter__(self):
            return None

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _FakePoolAcquire:
        async def __aenter__(self):
            return _FakeConn()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _FakePool:
        def acquire(self):
            return _FakePoolAcquire()

        async def close(self):
            pass

    async def _fake_create_pool(settings):
        return _FakePool()

    async def _fake_start_run(conn, run_date):
        return 1

    async def _noop(*args, **kwargs):
        return None

    async def _fake_get_adjacent_runs(conn, run_date):
        return None, None

    def _fake_load_profile(path):
        return profile

    # Extraction returns nothing, so the one scored listing is "dropped".
    async def _fake_run_requirements_extraction(listings, settings=None):
        return []

    async def _fake_render_run(conn, run_id, settings):
        return {"dashboard": Path("reports/2026-07-21/dashboard.html")}

    async def _fake_render_history(conn, settings):
        return Path("reports/history.html")

    def _fake_render_profile(profile_arg, settings):
        return Path("reports/profile.html")

    monkeypatch.setattr("scout.agent.run_scraper", _fake_run_scraper)
    monkeypatch.setattr("scout.agent.track_listings", _fake_track_listings)
    monkeypatch.setattr("scout.agent.run_scorer", _fake_run_scorer)
    monkeypatch.setattr("scout.agent.run_briefing", _fake_run_briefing)
    monkeypatch.setattr("scout.agent.create_pool", _fake_create_pool)
    monkeypatch.setattr("scout.agent.start_run", _fake_start_run)
    monkeypatch.setattr("scout.agent.record_run_listings", _noop)
    monkeypatch.setattr("scout.agent.finish_run", _noop)
    monkeypatch.setattr("scout.agent.load_profile", _fake_load_profile)
    monkeypatch.setattr(
        "scout.agent.run_requirements_extraction", _fake_run_requirements_extraction
    )
    monkeypatch.setattr("scout.agent.record_listing_gaps", _noop)
    monkeypatch.setattr("scout.agent.record_listing_meta", _noop)
    monkeypatch.setattr("scout.agent.render_run", _fake_render_run)
    monkeypatch.setattr("scout.agent.render_history", _fake_render_history)
    monkeypatch.setattr("scout.agent.render_profile", _fake_render_profile)
    monkeypatch.setattr("scout.agent.get_adjacent_runs", _fake_get_adjacent_runs)

    texts = await _run_pipeline_agent()

    assert any(
        "1" in t and "no extracted requirements" in t.lower() for t in texts
    )


@pytest.mark.asyncio
async def test_scout_pipeline_agent_same_date_rerun_is_idempotent(
    monkeypatch, db_pool
):
    """Two runs for the same run_date collapse into one run row with upserted
    listings — the documented same-day refresh / re-run-heals contract."""
    listing = _make_listing()
    score = ListingScore(
        source="linkedin", external_id="1", score=80, reasoning="Good fit."
    )

    async with db_pool.acquire() as conn:
        await upsert_listing(conn, listing)

    async def _fake_run_scraper(settings):
        return [listing]

    async def _fake_track_listings(listings, settings=None):
        return listings

    async def _fake_run_scorer(listings, settings):
        return [score]

    async def _fake_run_briefing(matches, settings, report_path=None):
        return {}

    async def _fake_requirements(listings, settings=None):
        return []

    def _fake_render_profile(profile, settings):
        return Path("reports/profile.html")

    async def _fake_render_run(conn, run_id, settings):
        return {"dashboard": Path("reports/x/dashboard.html")}

    async def _fake_render_history(conn, settings):
        return Path("reports/history.html")

    class _UnclosablePool:
        def acquire(self):
            return db_pool.acquire()

        async def close(self):
            pass

    async def _fake_create_pool(settings):
        return _UnclosablePool()

    monkeypatch.setattr("scout.agent.run_scraper", _fake_run_scraper)
    monkeypatch.setattr("scout.agent.track_listings", _fake_track_listings)
    monkeypatch.setattr("scout.agent.run_scorer", _fake_run_scorer)
    monkeypatch.setattr("scout.agent.run_briefing", _fake_run_briefing)
    monkeypatch.setattr("scout.agent.create_pool", _fake_create_pool)
    monkeypatch.setattr("scout.agent.run_requirements_extraction", _fake_requirements)
    monkeypatch.setattr("scout.agent.render_run", _fake_render_run)
    monkeypatch.setattr("scout.agent.render_history", _fake_render_history)
    monkeypatch.setattr("scout.agent.render_profile", _fake_render_profile)

    await _run_pipeline_agent()
    await _run_pipeline_agent()

    run_date = datetime.now(ZoneInfo("Australia/Melbourne")).date()
    async with db_pool.acquire() as conn:
        runs = await conn.fetch("SELECT id FROM runs WHERE run_date = $1", run_date)
        assert len(runs) == 1  # same date collapses into one row
        run = await get_run_by_date(conn, run_date)
        run_listings = await get_run_listings(conn, run.id)
        assert len(run_listings) == 1  # upserted, not duplicated
        assert run_listings[0].score == 80


@pytest.mark.asyncio
async def test_scout_pipeline_agent_rolls_back_on_mid_persist_failure(
    monkeypatch, db_pool
):
    """If persistence fails partway through the final block, nothing from that
    block is left behind: no run_listings and finished_at stays NULL. The
    start_run row itself persists (it is the marker the next run heals)."""
    listing = _make_listing()
    score = ListingScore(
        source="linkedin", external_id="1", score=80, reasoning="Good fit."
    )

    async with db_pool.acquire() as conn:
        await upsert_listing(conn, listing)

    async def _fake_run_scraper(settings):
        return [listing]

    async def _fake_track_listings(listings, settings=None):
        return listings

    async def _fake_run_scorer(listings, settings):
        return [score]

    async def _fake_run_briefing(matches, settings, report_path=None):
        return {}

    async def _fake_requirements(listings, settings=None):
        return []

    def _fake_render_profile(profile, settings):
        return Path("reports/profile.html")

    async def _fake_render_run(conn, run_id, settings):
        return {"dashboard": Path("reports/x/dashboard.html")}

    async def _fake_render_history(conn, settings):
        return Path("reports/history.html")

    async def _boom(conn, run_id, *, listings_scraped, listings_scored):
        raise RuntimeError("simulated mid-persist failure")

    class _UnclosablePool:
        def acquire(self):
            return db_pool.acquire()

        async def close(self):
            pass

    async def _fake_create_pool(settings):
        return _UnclosablePool()

    monkeypatch.setattr("scout.agent.run_scraper", _fake_run_scraper)
    monkeypatch.setattr("scout.agent.track_listings", _fake_track_listings)
    monkeypatch.setattr("scout.agent.run_scorer", _fake_run_scorer)
    monkeypatch.setattr("scout.agent.run_briefing", _fake_run_briefing)
    monkeypatch.setattr("scout.agent.create_pool", _fake_create_pool)
    monkeypatch.setattr("scout.agent.run_requirements_extraction", _fake_requirements)
    monkeypatch.setattr("scout.agent.render_run", _fake_render_run)
    monkeypatch.setattr("scout.agent.render_history", _fake_render_history)
    monkeypatch.setattr("scout.agent.render_profile", _fake_render_profile)
    monkeypatch.setattr("scout.agent.finish_run", _boom)

    try:
        await _run_pipeline_agent()
    except Exception:
        pass

    run_date = datetime.now(ZoneInfo("Australia/Melbourne")).date()
    async with db_pool.acquire() as conn:
        run = await get_run_by_date(conn, run_date)
        assert run is not None  # start_run committed the marker row
        assert run.finished_at is None  # finish_run rolled back
        run_listings = await get_run_listings(conn, run.id)
        assert run_listings == []  # record_run_listings rolled back


@pytest.mark.asyncio
async def test_scout_pipeline_agent_records_gaps_when_profile_exists(monkeypatch):
    listing = _make_listing()
    score = ListingScore(source="linkedin", external_id="1", score=80, reasoning="Good fit.")
    profile = _make_profile()
    requirements = ListingRequirements(
        source="linkedin",
        external_id="1",
        must_have=[RequirementItem(name="Kubernetes", kind="skill")],
        nice_to_have=[],
    )

    calls = []

    async def _fake_run_scraper(settings):
        return [listing]

    async def _fake_track_listings(listings, settings=None):
        return listings

    async def _fake_run_scorer(listings, settings):
        return [score]

    async def _fake_run_briefing(matches, settings, report_path=None):
        calls.append("briefing")
        return {}

    class _FakeConn:
        def transaction(self):
            return _FakeTransaction()

    class _FakePoolAcquire:
        async def __aenter__(self):
            return _FakeConn()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _FakePool:
        def acquire(self):
            return _FakePoolAcquire()

        async def close(self):
            pass

    async def _fake_create_pool(settings):
        return _FakePool()

    async def _fake_start_run(conn, run_date):
        return 1

    async def _fake_record_run_listings(conn, run_id, matches):
        pass

    async def _fake_finish_run(conn, run_id, *, listings_scraped, listings_scored):
        pass

    def _fake_load_profile(path):
        calls.append(("load_profile", path))
        return profile

    async def _fake_run_requirements_extraction(listings, settings=None):
        calls.append(("run_requirements_extraction", listings))
        return [requirements]

    async def _fake_record_listing_gaps(conn, run_id, gaps_by_match):
        calls.append(("record_listing_gaps", run_id, gaps_by_match))

    async def _fake_record_listing_meta(conn, run_id, meta_by_match):
        calls.append(("record_listing_meta", run_id, meta_by_match))

    async def _fake_render_run(conn, run_id, settings):
        calls.append(("render_run", run_id))
        return {"dashboard": Path("reports/2026-07-21/dashboard.html")}

    async def _fake_render_history(conn, settings):
        calls.append("render_history")
        return Path("reports/history.html")

    def _fake_render_profile(profile_arg, settings):
        calls.append(("render_profile", profile_arg))
        return Path("reports/profile.html")

    async def _fake_get_adjacent_runs(conn, run_date):
        return None, None

    monkeypatch.setattr("scout.agent.run_scraper", _fake_run_scraper)
    monkeypatch.setattr("scout.agent.track_listings", _fake_track_listings)
    monkeypatch.setattr("scout.agent.run_scorer", _fake_run_scorer)
    monkeypatch.setattr("scout.agent.run_briefing", _fake_run_briefing)
    monkeypatch.setattr("scout.agent.create_pool", _fake_create_pool)
    monkeypatch.setattr("scout.agent.start_run", _fake_start_run)
    monkeypatch.setattr("scout.agent.record_run_listings", _fake_record_run_listings)
    monkeypatch.setattr("scout.agent.finish_run", _fake_finish_run)
    monkeypatch.setattr("scout.agent.load_profile", _fake_load_profile)
    monkeypatch.setattr(
        "scout.agent.run_requirements_extraction", _fake_run_requirements_extraction
    )
    monkeypatch.setattr("scout.agent.record_listing_gaps", _fake_record_listing_gaps)
    monkeypatch.setattr("scout.agent.record_listing_meta", _fake_record_listing_meta)
    monkeypatch.setattr("scout.agent.render_run", _fake_render_run)
    monkeypatch.setattr("scout.agent.render_history", _fake_render_history)
    monkeypatch.setattr("scout.agent.render_profile", _fake_render_profile)
    monkeypatch.setattr("scout.agent.get_adjacent_runs", _fake_get_adjacent_runs)

    texts = await _run_pipeline_agent()

    record_gaps_call = next(c for c in calls if c[0] == "record_listing_gaps")
    _, run_id, gaps_by_match = record_gaps_call
    assert run_id == 1
    assert len(gaps_by_match) == 1
    match, gaps = gaps_by_match[0]
    assert match.listing.external_id == "1"
    assert len(gaps) == 1
    assert gaps[0].skill == "Kubernetes"
    assert gaps[0].requirement_level == "must_have"

    assert any("Gaps detected: 1" in t for t in texts)
    assert ("render_run", 1) in calls
    assert "render_history" in calls
    assert ("render_profile", profile) in calls
    assert calls.index(("render_profile", profile)) < calls.index("briefing")
    assert calls[-1] == "briefing"
    assert any("Report rendered:" in t for t in texts)
    assert any("Run persisted:" in t for t in texts)
