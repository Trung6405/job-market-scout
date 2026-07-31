from __future__ import annotations

import asyncio
import logging
import threading
import time
from datetime import UTC, date

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


def _mock_candidate_pipeline(monkeypatch, skills: list[str] | None = None) -> dict[str, list]:
    """Wire up fake candidate pipeline mocks and return call-tracking lists.

    The returned dict exposes "tag_readme" and "embed" lists that each mock
    appends to when invoked, so callers can assert these expensive calls are
    NOT re-spent on a subsequent run for an already-stored URL.

    ``skills`` overrides what the fake tagger returns, so a test can feed in
    non-canonical wording and assert what actually lands in the column.
    """
    tagged_skills = ["kubernetes"] if skills is None else skills
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
            skills=tagged_skills,
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
async def test_run_coach_aggregator_normalizes_tagged_skills(
    db_pool, listing_factory, match_factory, monkeypatch
):
    """Stored ``skills[]`` must be canonical (FR-CC-1), not the tagger's wording.

    The tagging prompt only *asks* for canonical names; the retriever's exact
    ``skills[]`` pre-filter needs a deterministic guarantee, so
    ``normalize_skill`` is applied on write.
    """
    await _seed_kubernetes_gap(db_pool, listing_factory, match_factory)
    _mock_candidate_pipeline(monkeypatch, skills=["K8s", "React.js", "  Postgres "])

    await runner.run_coach_aggregator(_test_settings())

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT skills FROM resources WHERE url = $1",
            "https://github.com/kubernetes/kubernetes",
        )
    assert row["skills"] == ["kubernetes", "react", "postgresql"]


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
async def test_run_coach_aggregator_isolates_a_candidate_that_fails_to_tag(
    db_pool, listing_factory, match_factory, monkeypatch
):
    """One malformed LLM response must not cost the rest of the run.

    `complete_json` validates the model's output against `ResourceTags`, so a
    response with prose where a list belongs raises `ValidationError` out of
    `tag_readme`. Unhandled, it propagated through the ingest loop and ended the
    run — which is how a run that had already worked through 920 of 1534
    candidates stopped writing anything further.

    Skipping loses nothing durable: dedup is by URL, so the next weekly run
    tries this candidate again.
    """
    await _seed_kubernetes_gap(db_pool, listing_factory, match_factory)

    urls = [
        "https://github.com/org/before",
        "https://github.com/org/malformed",
        "https://github.com/org/after",
    ]
    monkeypatch.setattr(
        "scout.sub_agents.coach.runner.search_candidates",
        lambda skill, settings: urls,
    )
    monkeypatch.setattr(
        "scout.sub_agents.coach.runner.fetch_readme",
        lambda url, settings: f"# {url}",
    )
    monkeypatch.setattr("scout.sub_agents.coach.runner.embed", lambda text: [0.1] * 384)

    async def _fake_tag_readme(readme_text, settings):
        if "malformed" in readme_text:
            # A real ValidationError, raised the way the provider's output
            # would raise it, rather than a stand-in exception.
            ResourceTags.model_validate({"skills": "kubernetes, not a list"})
        return ResourceTags(
            skills=["kubernetes"],
            resource_type="repo",
            level="intermediate",
            summary="Container orchestration platform.",
        )

    monkeypatch.setattr("scout.sub_agents.coach.runner.tag_readme", _fake_tag_readme)

    summary = await runner.run_coach_aggregator(_test_settings())

    assert summary.inserted == 2
    async with db_pool.acquire() as conn:
        stored = [
            record["url"]
            for record in await conn.fetch("SELECT url FROM resources ORDER BY url")
        ]
    # The candidate *after* the failure is the one that matters: it proves the
    # loop resumed rather than unwinding.
    assert stored == ["https://github.com/org/after", "https://github.com/org/before"]


def _mock_pipeline_failing(monkeypatch, urls: list[str], fails) -> None:
    """Wire the ingest pipeline so `fails(url)` decides which candidates raise.

    Used by the systemic-abort tests, where what varies between them is only
    *how many* of the candidates fail.
    """
    monkeypatch.setattr(
        "scout.sub_agents.coach.runner.search_candidates",
        lambda skill, settings: urls,
    )
    monkeypatch.setattr(
        "scout.sub_agents.coach.runner.fetch_readme",
        lambda url, settings: f"# {url}",
    )
    monkeypatch.setattr("scout.sub_agents.coach.runner.embed", lambda text: [0.1] * 384)

    async def _fake_tag_readme(readme_text, settings):
        if fails(readme_text.removeprefix("# ")):
            ResourceTags.model_validate({"skills": "not a list"})
        return ResourceTags(
            skills=["kubernetes"],
            resource_type="repo",
            level="intermediate",
            summary="Container orchestration platform.",
        )

    monkeypatch.setattr("scout.sub_agents.coach.runner.tag_readme", _fake_tag_readme)


@pytest.mark.asyncio
async def test_run_coach_aggregator_aborts_when_failures_look_systemic(
    db_pool, listing_factory, match_factory, monkeypatch
):
    """Skipping is right for a bad candidate and wrong for a bad *run*.

    A revoked token, a provider outage or a broken prompt fails every candidate
    alike. Left to skip, the run would report success having written nothing —
    the silent-degradation mode this whole area exists to close.
    """
    await _seed_kubernetes_gap(db_pool, listing_factory, match_factory)
    urls = [f"https://github.com/org/repo-{index}" for index in range(15)]
    _mock_pipeline_failing(monkeypatch, urls, fails=lambda url: True)

    with pytest.raises(RuntimeError) as excinfo:
        await runner.run_coach_aggregator(_test_settings())

    # The threshold is max(10, 20% of processed), so with everything failing
    # the 11th failure is the one that trips it. The count belongs in the
    # message: the workflow step surfaces only this string.
    assert "11" in str(excinfo.value)


@pytest.mark.asyncio
async def test_run_coach_aggregator_does_not_abort_on_a_few_systemic_lookalikes(
    db_pool, listing_factory, match_factory, monkeypatch
):
    """The companion to the abort test, and the one that stops the threshold
    being tuned into uselessness. Occasional malformed output is expected — if
    a handful of failures aborted the run, this change would be a regression on
    the skip-and-continue behaviour it just added."""
    await _seed_kubernetes_gap(db_pool, listing_factory, match_factory)
    urls = [f"https://github.com/org/repo-{index}" for index in range(20)]
    _mock_pipeline_failing(
        monkeypatch, urls, fails=lambda url: url.endswith(("-3", "-7", "-11"))
    )

    summary = await runner.run_coach_aggregator(_test_settings())

    assert summary.inserted == 17


def _http_error(status: int, **headers: str) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status
    response.headers.update(headers)
    return requests.HTTPError(f"{status} error", response=response)


@pytest.mark.asyncio
async def test_run_coach_aggregator_lets_a_rate_limit_end_the_run(
    db_pool, listing_factory, match_factory, monkeypatch
):
    """Isolation must not absorb a rate limit.

    Every candidate after the limit is hit would fail identically, so skipping
    turns one recoverable condition into a corpus that is quietly short by
    however long the limit lasted — indistinguishable from "those repos didn't
    qualify". `fetch_repo_metadata` already fails loudly on this exact case;
    the ingest loop has to agree with it, or the two layers disagree about what
    a 403 means depending on which one sees it.
    """
    await _seed_kubernetes_gap(db_pool, listing_factory, match_factory)
    monkeypatch.setattr(
        "scout.sub_agents.coach.runner.search_candidates",
        lambda skill, settings: ["https://github.com/org/repo"],
    )

    def _rate_limited(url, settings):
        raise _http_error(403, **{"X-RateLimit-Remaining": "0"})

    monkeypatch.setattr("scout.sub_agents.coach.runner.fetch_readme", _rate_limited)

    with pytest.raises(requests.HTTPError):
        await runner.run_coach_aggregator(_test_settings())


@pytest.mark.asyncio
async def test_run_coach_aggregator_still_skips_a_plain_403(
    db_pool, listing_factory, match_factory, monkeypatch
):
    """The contrast that stops the escalation being "any HTTPError is fatal".

    A 403 without an exhausted quota is a private, blocked or DMCA'd repo —
    one bad candidate. A predicate matching every HTTPError would pass the
    rate-limit test above and silently undo the isolation this phase added.
    """
    await _seed_kubernetes_gap(db_pool, listing_factory, match_factory)
    monkeypatch.setattr(
        "scout.sub_agents.coach.runner.search_candidates",
        lambda skill, settings: ["https://github.com/org/blocked"],
    )

    def _forbidden(url, settings):
        raise _http_error(403, **{"X-RateLimit-Remaining": "4999"})

    monkeypatch.setattr("scout.sub_agents.coach.runner.fetch_readme", _forbidden)

    summary = await runner.run_coach_aggregator(_test_settings())

    assert summary.inserted == 0


@pytest.mark.asyncio
async def test_run_coach_aggregator_summary_reports_every_disposition(
    db_pool, listing_factory, match_factory, monkeypatch, caplog
):
    """Every candidate ends up in exactly one bucket, and the run says so.

    Without the failed count, a thin corpus and a working one produce the same
    log line, and the systemic threshold has nothing to be tuned against — it
    is currently set from a single observation.
    """
    await _seed_kubernetes_gap(db_pool, listing_factory, match_factory)
    urls = [
        "https://github.com/org/before",
        "https://github.com/org/malformed",
        "https://github.com/org/after",
    ]
    _mock_pipeline_failing(
        monkeypatch, urls, fails=lambda url: url.endswith("malformed")
    )

    with caplog.at_level(logging.INFO, logger="scout.coach.runner"):
        summary = await runner.run_coach_aggregator(_test_settings())

    assert summary.failed == 1
    completion = next(
        record.getMessage()
        for record in caplog.records
        if record.getMessage().startswith("Aggregation complete")
    )
    for expected in ("2 inserted", "0 duplicate(s)", "0 without a README", "1 failed"):
        assert expected in completion


@pytest.mark.asyncio
async def test_run_coach_aggregator_skips_when_github_pat_unset(db_pool):
    summary = await runner.run_coach_aggregator(_test_settings(github_pat=""))
    assert summary == type(summary)(candidates_seen=0, inserted=0, duplicates=0)


def test_canonical_skills_collapses_variants_and_drops_empties():
    assert runner._canonical_skills(["K8s", "Kubernetes", "React.js", "!!", "  "]) == [
        "kubernetes",
        "react",
    ]


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
    # 30 requests/minute search API limit. The sleep absorbs elapsed
    # request time, so each value is at most (and here, with an instant
    # fake search, approximately) the full throttle window.
    assert sleep_calls == pytest.approx(
        [runner._SEARCH_THROTTLE_SECONDS] * 2, abs=0.25
    )


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


@pytest.mark.asyncio
async def test_candidate_pipeline_prepares_everything_but_the_write(monkeypatch):
    """The seam concurrency needs: fetch, tag and embed one URL, no database.

    Splitting here is what lets the expensive, independent, IO-bound part of a
    candidate overlap while inserts stay serial on the one open connection.
    """
    monkeypatch.setattr(
        "scout.sub_agents.coach.runner.fetch_readme",
        lambda url, settings: "# Kubernetes\n\nContainer orchestration.",
    )
    monkeypatch.setattr("scout.sub_agents.coach.runner.embed", lambda text: [0.5] * 384)

    async def _fake_tag_readme(readme_text, settings):
        return ResourceTags(
            skills=["K8s", "  Postgres "],
            resource_type="repo",
            level="intermediate",
            summary="Container orchestration platform.",
        )

    monkeypatch.setattr("scout.sub_agents.coach.runner.tag_readme", _fake_tag_readme)

    prepared = await runner._prepare_candidate(
        "https://github.com/kubernetes/kubernetes", _test_settings()
    )

    assert prepared.url == "https://github.com/kubernetes/kubernetes"
    assert prepared.resource.title == "kubernetes/kubernetes"
    # Normalisation belongs to the prepared resource, not the insert, or moving
    # the work concurrent would quietly change what lands in the column.
    assert prepared.resource.skills == ["kubernetes", "postgresql"]
    assert prepared.embedding == [0.5] * 384


@pytest.mark.asyncio
async def test_candidate_pipeline_returns_nothing_for_a_repo_without_a_readme(
    monkeypatch,
):
    """No README is a skip, and it must cost neither a tagging call nor an
    embedding — that ordering is the reason `fetch_readme` doubles as the
    filter."""
    monkeypatch.setattr(
        "scout.sub_agents.coach.runner.fetch_readme", lambda url, settings: None
    )
    spent: list[str] = []

    async def _unexpected_tag(readme_text, settings):
        spent.append("tag")
        raise AssertionError("tagging a candidate with no README")

    monkeypatch.setattr("scout.sub_agents.coach.runner.tag_readme", _unexpected_tag)
    monkeypatch.setattr(
        "scout.sub_agents.coach.runner.embed",
        lambda text: spent.append("embed"),
    )

    prepared = await runner._prepare_candidate(
        "https://github.com/org/bare", _test_settings()
    )

    assert prepared is None
    assert spent == []


@pytest.mark.asyncio
async def test_ingest_runs_a_chunk_concurrently_and_still_inserts_in_order(
    db_pool, listing_factory, match_factory, monkeypatch
):
    """Overlap where it is safe, sequence where it is not.

    Tagging and embedding are independent per candidate and dominate the run;
    inserts share one connection and must stay serial. The peak in-flight count
    is what proves overlap — a timing assertion would prove the same thing
    less reliably, since a loaded machine can make a concurrent run look
    serial.
    """
    await _seed_kubernetes_gap(db_pool, listing_factory, match_factory)
    urls = [f"https://github.com/org/repo-{index}" for index in range(4)]
    monkeypatch.setattr(
        "scout.sub_agents.coach.runner.search_candidates",
        lambda skill, settings: urls,
    )
    monkeypatch.setattr(
        "scout.sub_agents.coach.runner.fetch_readme",
        lambda url, settings: f"# {url}",
    )
    monkeypatch.setattr("scout.sub_agents.coach.runner.embed", lambda text: [0.1] * 384)

    in_flight = 0
    peak = 0

    async def _fake_tag_readme(readme_text, settings):
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.05)
        in_flight -= 1
        return ResourceTags(
            skills=["kubernetes"],
            resource_type="repo",
            level="intermediate",
            summary=f"Summary of {readme_text}.",
        )

    monkeypatch.setattr("scout.sub_agents.coach.runner.tag_readme", _fake_tag_readme)

    summary = await runner.run_coach_aggregator(
        _test_settings(coach_ingest_concurrency=4)
    )

    assert summary.inserted == 4
    assert peak == 4, "candidates were tagged one at a time, not concurrently"
    async with db_pool.acquire() as conn:
        stored = [
            record["url"]
            for record in await conn.fetch("SELECT url FROM resources ORDER BY id")
        ]
    # Ascending id is insertion order: the writes happened one at a time, and
    # in the order the candidate list was assembled — which is what makes the
    # phase-1 ordering guarantee survive concurrency.
    assert stored == urls


@pytest.mark.asyncio
async def test_chunk_failure_leaves_its_chunk_mates_inserted(
    db_pool, listing_factory, match_factory, monkeypatch
):
    """Isolation has to survive the move to `gather`, and it does not for free.

    A plain `gather` propagates the first exception and discards its siblings'
    completed work — phase 1's bug back again, one chunk wide instead of one
    run wide. `return_exceptions=True` prevents that, which is why this test
    exists at chunk granularity rather than trusting the serial-path test.
    """
    await _seed_kubernetes_gap(db_pool, listing_factory, match_factory)
    urls = [
        "https://github.com/org/mate-a",
        "https://github.com/org/malformed",
        "https://github.com/org/mate-b",
    ]
    _mock_pipeline_failing(
        monkeypatch, urls, fails=lambda url: url.endswith("malformed")
    )

    summary = await runner.run_coach_aggregator(
        _test_settings(coach_ingest_concurrency=3)
    )

    assert summary.inserted == 2
    assert summary.failed == 1
    async with db_pool.acquire() as conn:
        stored = [
            record["url"]
            for record in await conn.fetch("SELECT url FROM resources ORDER BY id")
        ]
    assert stored == ["https://github.com/org/mate-a", "https://github.com/org/mate-b"]


@pytest.mark.asyncio
async def test_chunk_failure_from_a_rate_limit_still_ends_the_run(
    db_pool, listing_factory, match_factory, monkeypatch
):
    """The escalation that `return_exceptions=True` silently disables.

    It turns a raise into a *value*, so nothing propagates on its own any more
    — every guarantee phase 1 established has to be re-applied by hand when the
    gathered results are inspected. A rate limit reaching this point as a value
    and being counted as one skipped candidate would look exactly like the bug
    phase 1 task 4 fixed, while all its tests still passed.
    """
    await _seed_kubernetes_gap(db_pool, listing_factory, match_factory)
    urls = [
        "https://github.com/org/fine",
        "https://github.com/org/limited",
        "https://github.com/org/also-fine",
    ]
    monkeypatch.setattr(
        "scout.sub_agents.coach.runner.search_candidates",
        lambda skill, settings: urls,
    )
    monkeypatch.setattr("scout.sub_agents.coach.runner.embed", lambda text: [0.1] * 384)

    def _fetch(url, settings):
        if url.endswith("limited"):
            raise _http_error(403, **{"X-RateLimit-Remaining": "0"})
        return f"# {url}"

    monkeypatch.setattr("scout.sub_agents.coach.runner.fetch_readme", _fetch)

    async def _fake_tag_readme(readme_text, settings):
        return ResourceTags(
            skills=["kubernetes"],
            resource_type="repo",
            level="intermediate",
            summary=f"Summary of {readme_text}.",
        )

    monkeypatch.setattr("scout.sub_agents.coach.runner.tag_readme", _fake_tag_readme)

    with pytest.raises(requests.HTTPError):
        await runner.run_coach_aggregator(_test_settings(coach_ingest_concurrency=3))


def _repo_payload(stars: int = 5_000, archived: bool = False) -> dict:
    """A metadata payload that clears the quality bar unless a test says not."""
    from datetime import datetime, timedelta

    fresh = (datetime.now(UTC) - timedelta(days=30)).isoformat()
    return {
        "stargazers_count": stars,
        "archived": archived,
        "pushed_at": fresh.replace("+00:00", "Z"),
    }


def test_gather_filters_bootstrap_candidates_through_the_quality_bar(monkeypatch):
    """Every existing gather test runs with coach_awesome_lists=[], which
    bypasses the bootstrap filter entirely — the whole suite stayed green while
    the filter was unwired. This drives the harvested path: links below the bar
    or gone from GitHub must not survive to the (expensive) ingest phase."""
    monkeypatch.setattr(runner.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(
        "scout.sub_agents.coach.runner.harvest_awesome_list",
        lambda list_url, settings: [
            "https://github.com/org/popular",
            "https://github.com/org/obscure",
            "https://github.com/org/deleted",
            "https://github.com/org/archived",
        ],
    )
    metadata = {
        "https://github.com/org/popular": _repo_payload(),
        "https://github.com/org/obscure": _repo_payload(stars=12),
        "https://github.com/org/deleted": None,
        "https://github.com/org/archived": _repo_payload(archived=True),
    }
    metadata_calls: list[str] = []

    def _fake_metadata(url, settings):
        metadata_calls.append(url)
        return metadata[url]

    monkeypatch.setattr(
        "scout.sub_agents.coach.runner.fetch_repo_metadata", _fake_metadata
    )
    search_urls: list[str] = []

    def _fake_search(skill, settings):
        search_urls.append(skill)
        return [f"https://github.com/search/{skill}"]

    monkeypatch.setattr(
        "scout.sub_agents.coach.runner.search_candidates", _fake_search
    )

    candidates = runner._gather_candidate_urls(
        _test_settings(coach_awesome_lists=["https://github.com/org/awesome-x"]),
        ["kubernetes"],
    )

    # Search-derived first — see the ordering test above. What this test pins
    # is which links *survive*, not the order they survive in.
    assert candidates == [
        "https://github.com/search/kubernetes",
        "https://github.com/org/popular",
    ]
    # The bar is asked about harvested links only. Search results already
    # passed the same filters server-side (stars/archived in the query,
    # freshness client-side) — metadata calls for them would be pure waste.
    assert metadata_calls == list(metadata)


def test_gather_returns_search_derived_candidates_before_bootstrap_ones(monkeypatch):
    """Ordering is what makes a *partial* run useful.

    Ingest walks this list serially and can run out of time, be cancelled, or
    abort. When it does, whatever it got through is the corpus. A run killed at
    920 of 1534 candidates produced 957 rows and zero tips for cloud gaps,
    because every one of those 920 came from the awesome-lists — general
    Python-ecosystem material nobody's gap asked for.

    Search-derived candidates were found *by searching a real unmet gap skill*,
    so they are the ones a truncated run must reach first.
    """
    monkeypatch.setattr(runner.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(
        "scout.sub_agents.coach.runner.harvest_awesome_list",
        lambda list_url, settings: [
            "https://github.com/org/bootstrap-a",
            "https://github.com/org/bootstrap-b",
        ],
    )
    monkeypatch.setattr(
        "scout.sub_agents.coach.runner.fetch_repo_metadata",
        lambda url, settings: _repo_payload(),
    )
    monkeypatch.setattr(
        "scout.sub_agents.coach.runner.search_candidates",
        lambda skill, settings: [f"https://github.com/search/{skill}"],
    )

    candidates = runner._gather_candidate_urls(
        _test_settings(coach_awesome_lists=["https://github.com/org/awesome-x"]),
        ["terraform", "snowflake"],
    )

    assert candidates == [
        "https://github.com/search/terraform",
        "https://github.com/search/snowflake",
        "https://github.com/org/bootstrap-a",
        "https://github.com/org/bootstrap-b",
    ]


def test_filter_concurrency_asks_once_per_url_and_keeps_kept_order(monkeypatch):
    """The bootstrap filter is one blocking metadata call per harvested link,
    serially — the slowest part of the gather phase after the search throttle.

    Making it concurrent must not change what it produces: still exactly one
    call per unique URL, and still the same kept-order, because that order is
    what the ingest loop walks.

    No `time.sleep` patch here on purpose. `runner.time` *is* the `time` module,
    so patching it would also silence this test's own delay and leave nothing
    to overlap. Passing no skills means the throttle never runs anyway.
    """
    urls = [f"https://github.com/org/repo-{index}" for index in range(6)]
    monkeypatch.setattr(
        "scout.sub_agents.coach.runner.harvest_awesome_list",
        lambda list_url, settings: urls,
    )
    lock = threading.Lock()
    in_flight = 0
    peak = 0
    calls: list[str] = []

    def _fake_metadata(url, settings):
        nonlocal in_flight, peak
        with lock:
            in_flight += 1
            peak = max(peak, in_flight)
            calls.append(url)
        time.sleep(0.05)
        with lock:
            in_flight -= 1
        # One link gone from GitHub, to prove a dropped candidate doesn't
        # shift the survivors' order.
        return None if url.endswith("-3") else _repo_payload()

    monkeypatch.setattr(
        "scout.sub_agents.coach.runner.fetch_repo_metadata", _fake_metadata
    )

    candidates = runner._gather_candidate_urls(
        _test_settings(
            coach_awesome_lists=["https://github.com/org/awesome-x"],
            coach_ingest_concurrency=3,
        ),
        [],
    )

    # >= 2 rather than == 3: overlap is the property under test, and pinning an
    # exact peak would make thread start-up jitter look like a regression.
    assert peak >= 2, "metadata lookups ran one at a time"
    assert sorted(calls) == sorted(urls)
    assert len(calls) == len(urls), "a URL was asked about more than once"
    assert candidates == [url for url in urls if not url.endswith("-3")]


def test_gather_asks_github_once_per_unique_harvested_url(monkeypatch):
    """The filter must run on the deduped pool: a repo linked from two
    awesome-lists costs one metadata call, not two."""
    monkeypatch.setattr(runner.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(
        "scout.sub_agents.coach.runner.harvest_awesome_list",
        lambda list_url, settings: ["https://github.com/org/shared"],
    )
    metadata_calls: list[str] = []

    def _fake_metadata(url, settings):
        metadata_calls.append(url)
        return _repo_payload()

    monkeypatch.setattr(
        "scout.sub_agents.coach.runner.fetch_repo_metadata", _fake_metadata
    )

    candidates = runner._gather_candidate_urls(
        _test_settings(
            coach_awesome_lists=[
                "https://github.com/org/awesome-a",
                "https://github.com/org/awesome-b",
            ]
        ),
        [],
    )

    assert candidates == ["https://github.com/org/shared"]
    assert metadata_calls == ["https://github.com/org/shared"]


def test_gather_fails_loudly_when_the_metadata_filter_is_rate_limited(monkeypatch):
    """Deliberate contrast with the per-skill search loop above, which skips a
    rate-limited skill and continues. A rate-limited *filter* pass would
    silently drop every remaining bootstrap candidate — the corpus would come
    out thin and nothing would say so. fetch_repo_metadata raises on that
    case, and the gather loop must let it propagate, not swallow it."""
    monkeypatch.setattr(runner.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(
        "scout.sub_agents.coach.runner.harvest_awesome_list",
        lambda list_url, settings: ["https://github.com/org/first"],
    )

    def _rate_limited(url, settings):
        response = requests.Response()
        response.status_code = 403
        raise requests.HTTPError("403 rate limit exhausted", response=response)

    monkeypatch.setattr(
        "scout.sub_agents.coach.runner.fetch_repo_metadata", _rate_limited
    )

    with pytest.raises(requests.HTTPError):
        runner._gather_candidate_urls(
            _test_settings(coach_awesome_lists=["https://github.com/org/awesome-x"]),
            [],
        )
