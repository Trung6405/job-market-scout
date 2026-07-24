from datetime import datetime, timezone

from scout.config import Settings
from scout.shared.schemas import Listing
from scout.sub_agents.briefing.filters import passes_preferences

def _make_listing(**overrides):
    defaults = dict(
        source="linkedin",
        external_id="1",
        title="Backend Engineer",
        company="Acme Corp",
        location="Sydney, AU",
        is_remote=False,
        url="https://www.linkedin.com/jobs/view/1",
        description="Build backend systems.",
        scraped_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return Listing(**defaults)

def test_passes_preferences_true_with_no_preferences():
    settings = Settings(preferred_locations=[], remote_only=False, min_salary=None)

    assert passes_preferences(_make_listing(), settings) is True

def test_passes_preferences_drops_non_remote_when_remote_only():
    settings = Settings(remote_only=True)

    assert passes_preferences(_make_listing(is_remote=True), settings) is True
    assert passes_preferences(_make_listing(is_remote=False), settings) is False

def test_passes_preferences_keeps_listing_with_no_salary_data():
    settings = Settings(min_salary=100000)

    assert (
        passes_preferences(_make_listing(salary_min=None, salary_max=None), settings)
        is True
    )

def test_passes_preferences_drops_location_mismatch():
    settings = Settings(preferred_locations=["Melbourne"])

    assert passes_preferences(_make_listing(location="Melbourne, AU"), settings) is True
    assert passes_preferences(_make_listing(location="Sydney, AU"), settings) is False

def test_passes_preferences_drops_below_min_salary_using_salary_max():
    settings = Settings(min_salary=100000)

    assert passes_preferences(_make_listing(salary_max=120000), settings) is True
    assert passes_preferences(_make_listing(salary_max=80000), settings) is False

def test_passes_preferences_falls_back_to_salary_min_when_max_missing():
    settings = Settings(min_salary=100000)

    assert (
        passes_preferences(
            _make_listing(salary_min=110000, salary_max=None), settings
        )
        is True
    )

def test_passes_preferences_remote_listing_bypasses_location_mismatch():
    settings = Settings(preferred_locations=["Melbourne"])

    assert (
        passes_preferences(
            _make_listing(location="Remote (AUS)", is_remote=True), settings
        )
        is True
    )
