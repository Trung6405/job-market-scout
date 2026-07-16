from datetime import datetime, timezone

from scout.config import Settings
from scout.shared.schemas import Listing
from scout.sub_agents.scorer.filters import filter_listings

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

def test_filter_listings_pass_through_with_no_preferences():
    settings = Settings(preferred_locations=[], remote_only=False, min_salary=None)
    listings = [_make_listing()]
    
    result = filter_listings(listings, settings)

    assert result == listings

def test_filter_listings_drops_non_remote_when_remote_only():
    settings = Settings(remote_only=True)
    listings = [
        _make_listing(external_id = '1', is_remote = True),
        _make_listing(external_id = '2', is_remote = False),
    ]

    result = filter_listings(listings, settings)

    assert [listing.external_id for listing in result] == ["1"]

def test_filter_listings_keeps_listing_with_no_salary_data():
    settings = Settings(min_salary=100000)
    listings = [_make_listing(external_id="1", salary_min=None, salary_max=None)]

    result = filter_listings(listings, settings)

    assert [listing.external_id for listing in result] == ["1"]