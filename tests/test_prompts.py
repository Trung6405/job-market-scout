from scout.config import Settings
from scout.prompts import build_scraper_instruction


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
