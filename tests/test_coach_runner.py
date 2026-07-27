from __future__ import annotations

from datetime import date

import pytest
import requests

from scout.config import Settings
from scout.shared.db import (
    record_listing_gaps,
    record_run_listings,
    start_run,
    upsert_listing,
)
from scout.shared.schemas import ResourceTags, SkillGap
from scout.sub_agents.coach import runner


def _test_settings(**overrides) -> Settings:
    test_db_url = Settings().database_url.rsplit("/", 1)[0] + "/scout_test"
    defaults = dict(
        database_url=test_db_url,
        github_pat="test-pat",
        coach_awesome_lists=[],
    )
    defaults.update(overrides)
    return Settings(**defaults)


async def _seed_kubernetes_gap(db_pool, listing_factory, match_factory) -> None:
    async with db_pool.acquire() as conn:
        run_id = await start_run(conn, date(2026, 7, 25))
        listing = listing_factory(external_id="ext-1", url="https://example.com/1")
        await upsert_listing(conn, listing)
        match = match_factory(listing=listing)
        await record_run_listings(conn, run_id, [(match, "competitive")])
        gap = SkillGap(skill="kubernetes", requirement_level="must_have", met=False)
        await record_listing_gaps(conn, run_id, [(match, [gap])])


def _mock_candidate_pipeline(monkeypatch) -> dict[str, list]:
    """Wire up fake candidate pipeline mocks and return call-tracking lists.

    The returned dict exposes "tag_readme" and "embed" lists that each mock
    appends to when invoked, so callers can assert these expensive calls are
    NOT re-spent on a subsequent run for an already-stored URL.
    """
    calls: dict[str, list] = {"tag_readme": [], "embed": []}

    monkeypatch.setattr(
        "scout.sub_agents.coach.runner.search_candidates",
        lambda skill, settings: ["https://github.com/kubernetes/kubernetes"],
    )
    monkeypatch.setattr(
        "scout.sub_agents.coach.runner.fetch_readme",
        lambda url, settings: "# Kubernetes\n\nContainer orchestration.",
    )

    async def _fake_tag_readme(readme_text, settings):
        calls["tag_readme"].append((readme_text, settings))
        return ResourceTags(
            skills=["kubernetes"],
            resource_type="repo",
            level="intermediate",
            summary="Container orchestration platform.",
        )

    def _fake_embed(text):
        calls["embed"].append(text)
        return [0.1] * 384

    monkeypatch.setattr("scout.sub_agents.coach.runner.tag_readme", _fake_tag_readme)
    monkeypatch.setattr("scout.sub_agents.coach.runner.embed", _fake_embed)

    return calls


@pytest.mark.asyncio
async def test_run_coach_aggregator_inserts_new_resource(
    db_pool, listing_factory, match_factory, monkeypatch
):
    await _seed_kubernetes_gap(db_pool, listing_factory, match_factory)
    _mock_candidate_pipeline(monkeypatch)

    summary = await runner.run_coach_aggregator(_test_settings())

    assert summary.inserted == 1
    assert summary.duplicates == 0
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT skills FROM resources WHERE url = $1",
            "https://github.com/kubernetes/kubernetes",
        )
    assert row["skills"] == ["kubernetes"]


@pytest.mark.asyncio
async def test_run_coach_aggregator_second_run_inserts_nothing_new(
    db_pool, listing_factory, match_factory, monkeypatch
):
    await _seed_kubernetes_gap(db_pool, listing_factory, match_factory)
    calls = _mock_candidate_pipeline(monkeypatch)

    await runner.run_coach_aggregator(_test_settings())
    second_summary = await runner.run_coach_aggregator(_test_settings())

    assert second_summary.inserted == 0
    async with db_pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT count(*) FROM resources WHERE url = $1",
            "https://github.com/kubernetes/kubernetes",
        )
    assert count == 1
    # The already-stored URL must be skipped entirely on the second run, not
    # re-fetched or re-tagged: no additional LLM/embedding cost should be
    # spent. Both counts should reflect only the first run's single call.
    assert len(calls["tag_readme"]) == 1
    assert len(calls["embed"]) == 1


@pytest.mark.asyncio
async def test_run_coach_aggregator_skips_when_github_pat_unset(db_pool):
    summary = await runner.run_coach_aggregator(_test_settings(github_pat=""))
    assert summary == type(summary)(candidates_seen=0, inserted=0, duplicates=0)


def test_gather_candidate_urls_throttles_between_skill_searches(monkeypatch):
    sleep_calls: list[float] = []
    monkeypatch.setattr(runner.time, "sleep", lambda seconds: sleep_calls.append(seconds))
    monkeypatch.setattr(
        "scout.sub_agents.coach.runner.search_candidates",
        lambda skill, settings: [f"https://github.com/org/{skill}"],
    )

    candidates = runner._gather_candidate_urls(
        _test_settings(), ["kubernetes", "helm", "docker"]
    )

    assert candidates == [
        "https://github.com/org/kubernetes",
        "https://github.com/org/helm",
        "https://github.com/org/docker",
    ]
    # One skill needs no throttle before its own (first) call; every
    # subsequent search call is preceded by a sleep to stay under GitHub's
    # 30 requests/minute search API limit.
    assert sleep_calls == [runner._SEARCH_THROTTLE_SECONDS] * 2


def test_gather_candidate_urls_skips_skill_on_rate_limit_and_continues(monkeypatch):
    monkeypatch.setattr(runner.time, "sleep", lambda seconds: None)

    def _fake_search_candidates(skill, settings):
        if skill == "rate-limited-skill":
            response = requests.Response()
            response.status_code = 403
            raise requests.HTTPError("403 rate limited", response=response)
        return [f"https://github.com/org/{skill}"]

    monkeypatch.setattr(
        "scout.sub_agents.coach.runner.search_candidates", _fake_search_candidates
    )

    candidates = runner._gather_candidate_urls(
        _test_settings(), ["kubernetes", "rate-limited-skill", "docker"]
    )

    # The rate-limited skill is skipped, not fatal — candidates from every
    # other skill are still gathered and the run doesn't abort.
    assert candidates == [
        "https://github.com/org/kubernetes",
        "https://github.com/org/docker",
    ]
