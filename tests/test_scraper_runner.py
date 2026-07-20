from __future__ import annotations

import pytest

from scout.config import Settings
from scout.sub_agents.scraper.runner import run_scraper


def _job(**overrides):
    defaults = dict(
        id="1",
        site="indeed",
        jobUrl="https://www.indeed.com/viewjob?jk=1",
        title="Backend Engineer",
        company="Acme Corp",
        location="Remote",
        isRemote=True,
        description="Build backend systems.",
    )
    defaults.update(overrides)
    return defaults


@pytest.mark.asyncio
async def test_run_scraper_calls_fetch_jobs_once_per_role(monkeypatch):
    calls = []

    async def _fake_fetch_jobs(url, **params):
        calls.append(params)
        return []

    monkeypatch.setattr(
        "scout.sub_agents.scraper.runner.fetch_jobs", _fake_fetch_jobs
    )

    settings = Settings(
        search_roles=["backend engineer", "platform engineer"],
        search_locations=["Remote", "Sydney, AU"],
        results_wanted=15,
        hours_old=48,
    )

    await run_scraper(settings)

    assert len(calls) == 2
    for params in calls:
        assert params["location"] == "Remote, Sydney, AU"
        assert params["resultsWanted"] == 15
        assert params["hoursOld"] == 48


@pytest.mark.asyncio
async def test_run_scraper_normalizes_and_returns_listings(monkeypatch):
    async def _fake_fetch_jobs(url, **params):
        return [_job()]

    monkeypatch.setattr(
        "scout.sub_agents.scraper.runner.fetch_jobs", _fake_fetch_jobs
    )

    listings = await run_scraper(Settings(search_roles=["backend engineer"]))

    assert len(listings) == 1
    assert listings[0].external_id == "1"


@pytest.mark.asyncio
async def test_run_scraper_drops_rows_that_fail_normalization(monkeypatch):
    async def _fake_fetch_jobs(url, **params):
        return [_job(company=None)]

    monkeypatch.setattr(
        "scout.sub_agents.scraper.runner.fetch_jobs", _fake_fetch_jobs
    )

    listings = await run_scraper(Settings(search_roles=["backend engineer"]))

    assert listings == []


@pytest.mark.asyncio
async def test_run_scraper_deduplicates_across_roles(monkeypatch):
    async def _fake_fetch_jobs(url, **params):
        return [_job()]

    monkeypatch.setattr(
        "scout.sub_agents.scraper.runner.fetch_jobs", _fake_fetch_jobs
    )

    settings = Settings(search_roles=["backend engineer", "platform engineer"])
    listings = await run_scraper(settings)

    assert len(listings) == 1
