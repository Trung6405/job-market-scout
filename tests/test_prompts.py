from datetime import datetime, timezone

from scout.config import Settings
from scout.prompts import build_briefing_instruction, build_scraper_instruction
from scout.shared.schemas import Listing, MatchResult


def _make_match(external_id: str, title: str, score: int) -> MatchResult:
    listing = Listing(
        source="linkedin",
        external_id=external_id,
        title=title,
        company="Acme Corp",
        location="Remote",
        is_remote=True,
        url=f"https://www.linkedin.com/jobs/view/{external_id}",
        description="Build backend systems.",
        scraped_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
    )
    return MatchResult(listing=listing, score=score, reasoning="Good fit.")


def test_build_scraper_instruction_includes_configured_roles_and_locations():
    settings = Settings(
        search_roles=["backend engineer", "platform engineer"],
        search_locations=["Sydney, AU", "Remote"],
        results_wanted=15,
        hours_old=48,
    )

    instruction = build_scraper_instruction(settings)

    assert "backend engineer, platform engineer" in instruction
    assert "Sydney, AU, Remote" in instruction
    assert "15" in instruction
    assert "48" in instruction


def test_build_scraper_instruction_uses_default_settings_values():
    instruction = build_scraper_instruction(Settings())

    assert "software engineer" in instruction
    assert "Remote" in instruction
    assert "20" in instruction
    assert "72" in instruction


def test_build_scraper_instruction_maps_every_listing_field():
    instruction = build_scraper_instruction(Settings())

    assert "`source`" in instruction and "`site`" in instruction
    assert "`external_id`" in instruction and "`id`" in instruction
    assert "`url`" in instruction and "`jobUrl`" in instruction
    assert "`description`" in instruction
    assert "`date_posted`" in instruction and "`datePosted`" in instruction
    assert "`salary_min`" in instruction and "`minAmount`" in instruction
    assert "`salary_max`" in instruction and "`maxAmount`" in instruction


def test_build_briefing_instruction_includes_resume_and_top_match_titles():
    settings = Settings()
    matches = [_make_match("1", "Platform Engineer", 88)]

    instruction = build_briefing_instruction(settings, matches)

    assert settings.resume_text in instruction
    assert "Platform Engineer" in instruction
    assert "88" in instruction


def test_build_briefing_instruction_excludes_listing_url_and_description():
    settings = Settings()
    matches = [_make_match("1", "Platform Engineer", 88)]

    instruction = build_briefing_instruction(settings, matches)

    assert "linkedin.com/jobs/view" not in instruction
    assert "Build backend systems." not in instruction
