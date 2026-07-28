from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from scout.config import Settings
from scout.shared.db import (
    finish_run,
    record_listing_gaps,
    record_listing_meta,
    record_listing_tips,
    record_run_listings,
    start_run,
    upsert_listing,
)
from scout.shared.schemas import (
    Background,
    DomainKnowledge,
    GroundedTip,
    Listing,
    ListingRequirements,
    MatchResult,
    Profile,
    RequirementItem,
    Project,
    SkillGap,
    TechCategory,
    TechSkill,
)
from scout.sub_agents.advisor.report import render_history, render_profile, render_run
from scout import rerender


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
        paths = await render_run(conn, run_id, settings)

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
async def test_render_run_shows_today_badge_only_on_actual_today(db_pool, tmp_path):
    listing = _make_listing()
    async with db_pool.acquire() as conn:
        await upsert_listing(conn, listing)
        match = MatchResult(listing=listing, score=88, reasoning="Great fit")

        past_run_id = await start_run(conn, date(2026, 7, 21))
        await record_run_listings(conn, past_run_id, [(match, "strong_match")])
        await finish_run(conn, past_run_id, listings_scraped=1, listings_scored=1)

        today_run_id = await start_run(conn, date.today())
        await record_run_listings(conn, today_run_id, [(match, "strong_match")])
        await finish_run(conn, today_run_id, listings_scraped=1, listings_scored=1)

        settings = Settings(report_output_dir=str(tmp_path))
        past_paths = await render_run(conn, past_run_id, settings)
        today_paths = await render_run(conn, today_run_id, settings)

    past_html = past_paths["dashboard"].read_text(encoding="utf-8")
    today_html = today_paths["dashboard"].read_text(encoding="utf-8")

    assert '<span class="tag-today">' not in past_html
    assert '<span class="tag-today">' in today_html


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
            must_have=[
                RequirementItem(name="Python", kind="skill"),
                RequirementItem(name="PostgreSQL", kind="skill"),
            ],
            nice_to_have=[RequirementItem(name="Docker", kind="skill")],
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
        paths = await render_run(conn, run_id, settings)

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
async def test_render_run_job_detail_coverage_counts_skills_only(db_pool, tmp_path):
    listing = _make_listing()
    async with db_pool.acquire() as conn:
        await upsert_listing(conn, listing)
        run_id = await start_run(conn, date(2026, 7, 21))
        match = MatchResult(listing=listing, score=88, reasoning="Great fit")
        await record_run_listings(conn, run_id, [(match, "strong_match")])
        # Two skill must-haves (one met) + one qualification must-have. The
        # qualification must not dilute the must-have coverage denominator.
        await record_listing_gaps(
            conn,
            run_id,
            [
                (
                    match,
                    [
                        SkillGap(skill="Python", requirement_level="must_have", met=True, kind="skill"),
                        SkillGap(skill="PostgreSQL", requirement_level="must_have", met=False, kind="skill"),
                        SkillGap(
                            skill="A STEM degree in CS",
                            requirement_level="must_have",
                            met=True,
                            kind="qualification",
                        ),
                    ],
                )
            ],
        )
        await finish_run(conn, run_id, listings_scraped=1, listings_scored=1)
        run_listing_id = await conn.fetchval(
            "SELECT id FROM run_listings WHERE run_id = $1", run_id
        )
        settings = Settings(report_output_dir=str(tmp_path))
        paths = await render_run(conn, run_id, settings)

    html = paths[f"job_detail_{run_listing_id}"].read_text(encoding="utf-8")

    assert "1 / 2" in html  # skill must-have coverage, qualification excluded
    assert "/ 3" not in html
    assert "/3" not in html
    # The qualification is not a pass/fail row: no ✕ gap mark is emitted for it.
    # The pass/fail checklist ends where the non-skill context section begins.
    checklist = html.split("Requirements vs your profile", 1)[1].split(
        "Role also asks for", 1
    )[0]
    assert "A STEM degree in CS" not in checklist


@pytest.mark.asyncio
async def test_render_run_job_detail_shows_non_skill_requirements_as_context(
    db_pool, tmp_path
):
    listing = _make_listing()
    async with db_pool.acquire() as conn:
        await upsert_listing(conn, listing)
        run_id = await start_run(conn, date(2026, 7, 21))
        match = MatchResult(listing=listing, score=88, reasoning="Great fit")
        await record_run_listings(conn, run_id, [(match, "strong_match")])
        await record_listing_gaps(
            conn,
            run_id,
            [
                (
                    match,
                    [
                        SkillGap(skill="Python", requirement_level="must_have", met=True, kind="skill"),
                        SkillGap(
                            skill="A STEM degree in CS",
                            requirement_level="must_have",
                            met=True,
                            kind="qualification",
                        ),
                        SkillGap(
                            skill="3+ years experience",
                            requirement_level="must_have",
                            met=True,
                            kind="experience",
                        ),
                        SkillGap(
                            skill="Strong communication",
                            requirement_level="nice_to_have",
                            met=True,
                            kind="soft_skill",
                        ),
                    ],
                )
            ],
        )
        await finish_run(conn, run_id, listings_scraped=1, listings_scored=1)
        run_listing_id = await conn.fetchval(
            "SELECT id FROM run_listings WHERE run_id = $1", run_id
        )
        settings = Settings(report_output_dir=str(tmp_path))
        paths = await render_run(conn, run_id, settings)

    html = paths[f"job_detail_{run_listing_id}"].read_text(encoding="utf-8")

    assert "Role also asks for" in html
    context = html.split("Role also asks for", 1)[1]
    assert "A STEM degree in CS" in context
    assert "3+ years experience" in context
    assert "Strong communication" in context
    # Context items carry no pass/fail mark.
    context_section = context.split("</section>", 1)[0]
    assert "✓" not in context_section
    assert "✕" not in context_section


@pytest.mark.asyncio
async def test_render_run_job_detail_omits_context_when_all_skills(db_pool, tmp_path):
    listing = _make_listing()
    async with db_pool.acquire() as conn:
        await upsert_listing(conn, listing)
        run_id = await start_run(conn, date(2026, 7, 21))
        match = MatchResult(listing=listing, score=88, reasoning="Great fit")
        await record_run_listings(conn, run_id, [(match, "strong_match")])
        await record_listing_gaps(
            conn,
            run_id,
            [
                (
                    match,
                    [SkillGap(skill="Python", requirement_level="must_have", met=True, kind="skill")],
                )
            ],
        )
        await finish_run(conn, run_id, listings_scraped=1, listings_scored=1)
        run_listing_id = await conn.fetchval(
            "SELECT id FROM run_listings WHERE run_id = $1", run_id
        )
        settings = Settings(report_output_dir=str(tmp_path))
        paths = await render_run(conn, run_id, settings)

    html = paths[f"job_detail_{run_listing_id}"].read_text(encoding="utf-8")

    assert "Role also asks for" not in html


@pytest.mark.asyncio
async def test_render_run_job_detail_renders_markdown_description(db_pool, tmp_path):
    # JobSpy returns descriptions as Markdown with backslash escapes such as
    # ``C\+\+`` and ``\-`` — the advisor page must render, not display, them.
    description = (
        "**Backend Engineer** \\| Java / Go / Rust / C\\+\\+\n\n"
        "Responsibilities:\n\n"
        "\\-Design and build backend services.\n\n"
        "<script>alert('xss')</script>"
    )
    listing = _make_listing(description=description)
    async with db_pool.acquire() as conn:
        await upsert_listing(conn, listing)
        run_id = await start_run(conn, date(2026, 7, 21))
        match = MatchResult(listing=listing, score=88, reasoning="Great fit")
        await record_run_listings(conn, run_id, [(match, "strong_match")])
        await finish_run(conn, run_id, listings_scraped=1, listings_scored=1)

        run_listing_id = await conn.fetchval(
            "SELECT id FROM run_listings WHERE run_id = $1", run_id
        )

        settings = Settings(report_output_dir=str(tmp_path))
        paths = await render_run(conn, run_id, settings)

    html = paths[f"job_detail_{run_listing_id}"].read_text(encoding="utf-8")

    # Markdown is rendered to HTML, backslash escapes are resolved.
    assert "<strong>Backend Engineer</strong>" in html
    assert "C++" in html
    assert "C\\+\\+" not in html
    # Raw HTML in the source is neutralised, not injected.
    assert "<script>alert" not in html


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
    # The profile page is always rendered (settings hard-requires profile.json
    # at import), so the nav link is always clickable.
    assert 'href="profile.html"' in html


@pytest.mark.asyncio
async def test_rerender_all_regenerates_pages_from_db(db_pool, tmp_path, monkeypatch):
    # A run whose stored description is raw Markdown, plus a stale HTML page on
    # disk from a hypothetical older renderer. rerender must overwrite it.
    listing = _make_listing(description="**Backend** \\| Go / C\\+\\+")
    async with db_pool.acquire() as conn:
        await upsert_listing(conn, listing)
        run_id = await start_run(conn, date(2026, 7, 21))
        match = MatchResult(listing=listing, score=88, reasoning="Great fit")
        await record_run_listings(conn, run_id, [(match, "strong_match")])
        await finish_run(conn, run_id, listings_scraped=1, listings_scored=1)
        run_listing_id = await conn.fetchval(
            "SELECT id FROM run_listings WHERE run_id = $1", run_id
        )

    stale = tmp_path / "2026-07-21" / f"job-detail-{run_listing_id}.html"
    stale.parent.mkdir(parents=True)
    stale.write_text("STALE", encoding="utf-8")

    settings = Settings(report_output_dir=str(tmp_path))
    monkeypatch.setattr(rerender, "default_settings", settings)

    class _NonClosingPool:
        def acquire(self):
            return db_pool.acquire()

        async def close(self):  # rerender_all closes its own pool; keep fixture alive
            pass

    async def _fake_create_pool(_settings):
        return _NonClosingPool()

    monkeypatch.setattr(rerender, "create_pool", _fake_create_pool)

    await rerender.rerender_all()

    html = stale.read_text(encoding="utf-8")
    assert "STALE" not in html
    assert "<strong>Backend</strong>" in html
    assert "C++" in html
    assert (tmp_path / "history.html").exists()


def test_render_profile_writes_profile_html(tmp_path):
    profile = _make_profile()
    settings = Settings(report_output_dir=str(tmp_path))

    path = render_profile(profile, settings)

    assert path == tmp_path / "profile.html"
    html = path.read_text(encoding="utf-8")
    assert "Minh Nguyen" in html
    assert "Recipe-sharing web app" in html
    assert "Python" in html


async def _render_with_tips(
    conn,
    tmp_path,
    gaps: list[SkillGap],
    tips: list[GroundedTip],
) -> str:
    """Seed one run with the given gaps and stored tips, return its detail page."""
    listing = _make_listing()
    await upsert_listing(conn, listing)
    run_id = await start_run(conn, date(2026, 7, 21))
    match = MatchResult(listing=listing, score=72, reasoning="Decent overlap")
    await record_run_listings(conn, run_id, [(match, "competitive")])
    await record_listing_gaps(conn, run_id, [(match, gaps)])
    await record_listing_tips(conn, run_id, [(match, tips)])
    await finish_run(conn, run_id, listings_scraped=1, listings_scored=1)

    run_listing_id = await conn.fetchval(
        "SELECT id FROM run_listings WHERE run_id = $1", run_id
    )
    paths = await render_run(conn, run_id, Settings(report_output_dir=str(tmp_path)))
    return paths[f"job_detail_{run_listing_id}"].read_text(encoding="utf-8")


def _gap_block(html: str, skill: str) -> str:
    """The one gap block naming `skill`, so assertions are about placement.

    Each segment is cut at the end of the gaps section as well as at the next
    block: the last block would otherwise run on into the rest of the page,
    which until phase 3 still names the top must-have gap in its static
    positioning advice.
    """
    blocks = [
        block.split("</section>")[0] for block in html.split('class="gapblock"')[1:]
    ]
    matching = [block for block in blocks if skill in block]
    assert len(matching) == 1, f"expected exactly one gap block for {skill!r}"
    return matching[0]


_K8S_GAP = SkillGap(skill="Kubernetes", requirement_level="must_have")
_TERRAFORM_GAP = SkillGap(skill="Terraform", requirement_level="nice_to_have")


@pytest.mark.asyncio
async def test_job_detail_renders_each_tip_inside_its_own_gap_block(db_pool, tmp_path):
    """The whole point of the placement: advice sits with the gap it answers,
    and a gap the corpus did not cover is not given someone else's advice."""
    async with db_pool.acquire() as conn:
        html = await _render_with_tips(
            conn,
            tmp_path,
            [_K8S_GAP, _TERRAFORM_GAP],
            [
                GroundedTip(
                    gap_skill="Kubernetes",
                    tip="Work through the worked examples, then ship one manifest.",
                    cited_urls=[],
                )
            ],
        )

    assert "Work through the worked examples" in _gap_block(html, "Kubernetes")
    assert "Work through the worked examples" not in _gap_block(html, "Terraform")


@pytest.mark.asyncio
async def test_job_detail_renders_no_tip_for_a_skill_that_is_not_a_gap(
    db_pool, tmp_path
):
    """Pins that the template iterates gaps, not tips. The coach stage already
    drops tips for unrequested skills, so this guards the direction of
    iteration rather than a live failure — reversing it would surface advice
    for a skill the listing never asked about."""
    async with db_pool.acquire() as conn:
        html = await _render_with_tips(
            conn,
            tmp_path,
            [_K8S_GAP],
            [
                GroundedTip(gap_skill="Kubernetes", tip="Ship one manifest.", cited_urls=[]),
                GroundedTip(gap_skill="Rust", tip="Read the ownership chapter.", cited_urls=[]),
            ],
        )

    assert "Ship one manifest." in html
    assert "Read the ownership chapter." not in html
    assert "Rust" not in html


@pytest.mark.asyncio
async def test_job_detail_renders_only_the_first_tip_stored_for_a_gap(
    db_pool, tmp_path
):
    """listing_tips has no unique constraint, so a duplicate is possible in
    principle even though the coach stage drops them."""
    async with db_pool.acquire() as conn:
        html = await _render_with_tips(
            conn,
            tmp_path,
            [_K8S_GAP],
            [
                GroundedTip(gap_skill="Kubernetes", tip="First stored advice.", cited_urls=[]),
                GroundedTip(gap_skill="Kubernetes", tip="Second stored advice.", cited_urls=[]),
            ],
        )

    assert "First stored advice." in html
    assert "Second stored advice." not in html


@pytest.mark.asyncio
async def test_job_detail_gives_a_lone_tipped_gap_the_whole_citation_budget(
    db_pool, tmp_path
):
    async with db_pool.acquire() as conn:
        html = await _render_with_tips(
            conn,
            tmp_path,
            [_K8S_GAP, _TERRAFORM_GAP],
            [
                GroundedTip(
                    gap_skill="Kubernetes",
                    tip=(
                        "Start at https://github.com/k/examples, then "
                        "https://github.com/k/website, then https://github.com/k/kops."
                    ),
                    cited_urls=[],
                )
            ],
        )

    block = _gap_block(html, "Kubernetes")
    assert block.count("<a href=") == 3
    assert 'href="https://github.com/k/examples"' in block
    assert ">github.com/k/examples</a>" in block


@pytest.mark.asyncio
async def test_job_detail_splits_the_citation_budget_across_tipped_gaps(
    db_pool, tmp_path
):
    """Three tipped gaps get one link each — the budget divides, it does not
    multiply."""
    gaps = [
        SkillGap(skill=skill, requirement_level="must_have")
        for skill in ("Kubernetes", "Terraform", "Go")
    ]
    tips = [
        GroundedTip(
            gap_skill=skill,
            tip=f"Start at https://github.com/x/{skill.lower()} and then https://github.com/y/{skill.lower()}.",
            cited_urls=[],
        )
        for skill in ("Kubernetes", "Terraform", "Go")
    ]
    async with db_pool.acquire() as conn:
        html = await _render_with_tips(conn, tmp_path, gaps, tips)

    for skill in ("Kubernetes", "Terraform", "Go"):
        assert _gap_block(html, skill).count("<a href=") == 1
    # The second URL in each tip stays readable, just not clickable.
    assert "https://github.com/y/kubernetes" in html


@pytest.mark.asyncio
async def test_job_detail_renders_a_markdown_citation_without_bracket_debris(
    db_pool, tmp_path
):
    """The validator leaves this syntax intact for URLs it does not strip."""
    async with db_pool.acquire() as conn:
        html = await _render_with_tips(
            conn,
            tmp_path,
            [_K8S_GAP],
            [
                GroundedTip(
                    gap_skill="Kubernetes",
                    tip="Work through [kubernetes/examples](https://github.com/k/examples) first.",
                    cited_urls=[],
                )
            ],
        )

    block = _gap_block(html, "Kubernetes")
    assert block.count("<a href=") == 1
    assert ">kubernetes/examples</a>" in block
    assert "[" not in block
    assert "](" not in block


@pytest.mark.asyncio
async def test_job_detail_escapes_markup_in_tip_text(db_pool, tmp_path):
    """Tip text is LLM output reaching the page through a filter that opts out
    of Jinja's autoescape, so assert it at the layer that ships HTML."""
    async with db_pool.acquire() as conn:
        html = await _render_with_tips(
            conn,
            tmp_path,
            [_K8S_GAP],
            [
                GroundedTip(
                    gap_skill="Kubernetes",
                    tip="Beware <script>alert(1)</script> and javascript:alert(2) too.",
                    cited_urls=[],
                )
            ],
        )

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
    assert 'href="javascript:' not in html


@pytest.mark.asyncio
async def test_job_detail_orders_must_have_gaps_before_nice_to_have(db_pool, tmp_path):
    """Priority is carried by position and pill, which is what replaced the
    deleted static advice that used to name the top must-have in prose."""
    async with db_pool.acquire() as conn:
        html = await _render_with_tips(
            conn,
            tmp_path,
            [
                SkillGap(skill="Terraform", requirement_level="nice_to_have"),
                SkillGap(skill="Ansible", requirement_level="nice_to_have"),
                SkillGap(skill="Kubernetes", requirement_level="must_have"),
            ],
            [],
        )

    gaps_section = html.split("Skill gaps to close")[1].split("</section>")[0]
    assert gaps_section.index("Kubernetes") < gaps_section.index("Terraform")
    assert gaps_section.index("Kubernetes") < gaps_section.index("Ansible")
    # Nothing is asserted about order *within* a level: `get_run_details`
    # selects listing_gaps with no ORDER BY, so the database never promised
    # one. Adding an ORDER BY belongs to whoever owns that read path, not to a
    # rendering change.
