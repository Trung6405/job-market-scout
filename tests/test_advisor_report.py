from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from scout.config import Settings
from scout.shared.db import (
    finish_run,
    record_listing_gaps,
    record_listing_meta,
    record_run_listings,
    start_run,
    upsert_listing,
)
from scout.shared.schemas import (
    Background,
    DomainKnowledge,
    Listing,
    ListingRequirements,
    MatchResult,
    Profile,
    Project,
    SkillGap,
    TechCategory,
    TechSkill,
)
from scout.sub_agents.advisor.report import render_history, render_profile, render_run


def _make_listing(**overrides) -> Listing:
    defaults = dict(
        source="linkedin",
        external_id="job-1",
        title="Graduate Software Engineer",
        company="Atlassian",
        location="Sydney",
        is_remote=False,
        url="https://example.com/jobs/1",
        description="Build things.",
        salary_min=95000.0,
        salary_max=110000.0,
        date_posted=datetime(2026, 7, 19, tzinfo=timezone.utc),
        scraped_at=datetime(2026, 7, 21, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return Listing(**defaults)


def _make_profile() -> Profile:
    return Profile(
        name="Minh Nguyen",
        target_role="Junior / Graduate Software Engineer",
        target_locations=["Sydney", "Remote (AU)"],
        tech_stack=[
            TechCategory(
                category="Languages",
                skills=[
                    TechSkill(name="Python", proficiency=4, note="2 yrs"),
                    TechSkill(name="TypeScript", proficiency=1, note="learning"),
                ],
            )
        ],
        domain_knowledge=[
            DomainKnowledge(
                name="Web application development",
                proficiency=75,
                description="Full request-to-DB-to-UI loop across 2 projects.",
            )
        ],
        background=Background(
            education="B.Sc. Computer Science",
            experience="0.5 yrs",
            preferred_roles=["Software Engineer"],
            locations=["Sydney"],
        ),
        projects=[
            Project(
                title="Recipe-sharing web app",
                description="React + Flask + REST API.",
                tags=["React", "Flask"],
            )
        ],
    )


@pytest.mark.asyncio
async def test_render_run_writes_dashboard_and_job_detail_files(db_pool, tmp_path):
    listing = _make_listing()
    async with db_pool.acquire() as conn:
        await upsert_listing(conn, listing)
        run_id = await start_run(conn, date(2026, 7, 21))
        match = MatchResult(listing=listing, score=88, reasoning="Great fit")
        await record_run_listings(conn, run_id, [(match, "strong_match")])
        await record_listing_gaps(
            conn, run_id, [(match, [SkillGap(skill="PostgreSQL", requirement_level="must_have")])]
        )
        await finish_run(conn, run_id, listings_scraped=24, listings_scored=1)

        run_listing_id = await conn.fetchval(
            "SELECT id FROM run_listings WHERE run_id = $1", run_id
        )

        settings = Settings(report_output_dir=str(tmp_path))
        paths = await render_run(conn, run_id, settings, has_profile=True)

    run_dir = tmp_path / "2026-07-21"
    dashboard_path = run_dir / "dashboard.html"
    job_detail_path = run_dir / f"job-detail-{run_listing_id}.html"

    assert dashboard_path.exists()
    assert job_detail_path.exists()
    assert paths["dashboard"] == dashboard_path
    assert paths[f"job_detail_{run_listing_id}"] == job_detail_path

    dashboard_html = dashboard_path.read_text(encoding="utf-8")
    assert "Graduate Software Engineer" in dashboard_html
    assert "88" in dashboard_html
    assert "Strong-match" in dashboard_html

    job_detail_html = job_detail_path.read_text(encoding="utf-8")
    assert "Graduate Software Engineer" in job_detail_html
    assert "PostgreSQL" in job_detail_html
    assert '../history.html' in job_detail_html
    assert 'href="../profile.html"' in job_detail_html


@pytest.mark.asyncio
async def test_render_run_profile_nav_link_is_inert_when_no_profile(db_pool, tmp_path):
    listing = _make_listing()
    async with db_pool.acquire() as conn:
        await upsert_listing(conn, listing)
        run_id = await start_run(conn, date(2026, 7, 21))
        match = MatchResult(listing=listing, score=88, reasoning="Great fit")
        await record_run_listings(conn, run_id, [(match, "strong_match")])
        await finish_run(conn, run_id, listings_scraped=24, listings_scored=1)

        settings = Settings(report_output_dir=str(tmp_path))
        # has_profile defaults to False — no profile.json exists in this scenario.
        paths = await render_run(conn, run_id, settings)

    dashboard_html = paths["dashboard"].read_text(encoding="utf-8")
    assert 'href="../profile.html"' not in dashboard_html
    assert "My Profile" in dashboard_html  # nav item still shown, just inert

    job_detail_paths = [p for key, p in paths.items() if key.startswith("job_detail_")]
    assert job_detail_paths
    job_detail_html = job_detail_paths[0].read_text(encoding="utf-8")
    assert 'href="../profile.html"' not in job_detail_html
    assert "My Profile" in job_detail_html


@pytest.mark.asyncio
async def test_render_run_job_detail_shows_snapshot_breakdown_and_checklist(
    db_pool, tmp_path
):
    listing = _make_listing()
    async with db_pool.acquire() as conn:
        await upsert_listing(conn, listing)
        run_id = await start_run(conn, date(2026, 7, 21))
        match = MatchResult(listing=listing, score=88, reasoning="Great fit overall")
        await record_run_listings(conn, run_id, [(match, "strong_match")])
        await record_listing_gaps(
            conn,
            run_id,
            [
                (
                    match,
                    [
                        SkillGap(skill="Python", requirement_level="must_have", met=True),
                        SkillGap(skill="PostgreSQL", requirement_level="must_have", met=False),
                        SkillGap(skill="Docker", requirement_level="nice_to_have", met=False),
                    ],
                )
            ],
        )
        requirements = ListingRequirements(
            source=listing.source,
            external_id=listing.external_id,
            must_have=["Python", "PostgreSQL"],
            nice_to_have=["Docker"],
            seniority="Graduate / Entry",
            work_type="Hybrid — 3 days",
            team="Platform",
        )
        await record_listing_meta(conn, run_id, [(match, requirements)])
        await finish_run(conn, run_id, listings_scraped=1, listings_scored=1)

        run_listing_id = await conn.fetchval(
            "SELECT id FROM run_listings WHERE run_id = $1", run_id
        )

        settings = Settings(report_output_dir=str(tmp_path))
        paths = await render_run(conn, run_id, settings, has_profile=True)

    job_detail_html = paths[f"job_detail_{run_listing_id}"].read_text(encoding="utf-8")

    assert "Graduate / Entry" in job_detail_html
    assert "Hybrid — 3 days" in job_detail_html
    assert "Platform" in job_detail_html
    assert "Why this band" in job_detail_html
    assert "1 / 2" in job_detail_html  # must-have tech stack fit
    assert "Requirements vs your profile" in job_detail_html
    assert "How to position your application" in job_detail_html
    assert "PostgreSQL" in job_detail_html


@pytest.mark.asyncio
async def test_render_run_links_to_adjacent_day_dashboards(db_pool, tmp_path):
    listing = _make_listing()
    async with db_pool.acquire() as conn:
        await upsert_listing(conn, listing)
        match = MatchResult(listing=listing, score=88, reasoning="Great fit")

        prev_run_id = await start_run(conn, date(2026, 7, 20))
        await record_run_listings(conn, prev_run_id, [(match, "strong_match")])
        await finish_run(conn, prev_run_id, listings_scraped=1, listings_scored=1)

        run_id = await start_run(conn, date(2026, 7, 21))
        await record_run_listings(conn, run_id, [(match, "strong_match")])
        await finish_run(conn, run_id, listings_scraped=1, listings_scored=1)

        settings = Settings(report_output_dir=str(tmp_path))
        paths = await render_run(conn, run_id, settings)

    dashboard_html = paths["dashboard"].read_text(encoding="utf-8")
    assert 'href="../2026-07-20/dashboard.html"' in dashboard_html
    assert "No later run" in dashboard_html
    assert "No earlier run" not in dashboard_html


@pytest.mark.asyncio
async def test_render_history_reflects_runs_including_empty_day(db_pool, tmp_path):
    listing = _make_listing()
    async with db_pool.acquire() as conn:
        await upsert_listing(conn, listing)

        scored_run_id = await start_run(conn, date(2026, 7, 21))
        match = MatchResult(listing=listing, score=88, reasoning="Great fit")
        await record_run_listings(conn, scored_run_id, [(match, "strong_match")])
        await finish_run(conn, scored_run_id, listings_scraped=24, listings_scored=1)

        empty_run_id = await start_run(conn, date(2026, 7, 20))
        await finish_run(conn, empty_run_id, listings_scraped=12, listings_scored=0)

        settings = Settings(report_output_dir=str(tmp_path))
        history_path = await render_history(conn, settings)

    assert history_path == tmp_path / "history.html"
    html = history_path.read_text(encoding="utf-8")
    assert "Graduate Software Engineer" not in html  # history is summary-only
    assert "day empty" in html
    assert "2026-07-21/dashboard.html" in html
    # has_profile defaults to False — nav link must not point at a 404.
    assert 'href="profile.html"' not in html
    assert "My Profile" in html


@pytest.mark.asyncio
async def test_render_history_profile_nav_link_is_clickable_when_profile_exists(
    db_pool, tmp_path
):
    listing = _make_listing()
    async with db_pool.acquire() as conn:
        await upsert_listing(conn, listing)
        run_id = await start_run(conn, date(2026, 7, 21))
        match = MatchResult(listing=listing, score=88, reasoning="Great fit")
        await record_run_listings(conn, run_id, [(match, "strong_match")])
        await finish_run(conn, run_id, listings_scraped=24, listings_scored=1)

        settings = Settings(report_output_dir=str(tmp_path))
        history_path = await render_history(conn, settings, has_profile=True)

    html = history_path.read_text(encoding="utf-8")
    assert 'href="profile.html"' in html


def test_render_profile_writes_profile_html(tmp_path):
    profile = _make_profile()
    settings = Settings(report_output_dir=str(tmp_path))

    path = render_profile(profile, settings)

    assert path == tmp_path / "profile.html"
    html = path.read_text(encoding="utf-8")
    assert "Minh Nguyen" in html
    assert "Recipe-sharing web app" in html
    assert "Python" in html
