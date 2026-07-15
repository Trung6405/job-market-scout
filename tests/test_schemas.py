from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from scout.shared.schemas import Listing


def test_listing_accepts_valid_data():
    listing = Listing(
        source="linkedin",
        external_id="123",
        title="Backend Engineer",
        company="Acme Corp",
        location="Remote",
        is_remote=True,
        url="https://www.linkedin.com/jobs/view/123",
        description="Build backend systems.",
        salary_min=100000.0,
        salary_max=140000.0,
        date_posted=datetime(2026, 7, 10, tzinfo=timezone.utc),
        scraped_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
    )
    assert listing.title == "Backend Engineer"
    assert listing.is_remote is True


def test_listing_allows_missing_optional_salary_and_date():
    listing = Listing(
        source="linkedin",
        external_id="124",
        title="Frontend Engineer",
        company="Acme Corp",
        location="Sydney, AU",
        is_remote=False,
        url="https://www.linkedin.com/jobs/view/124",
        description="Build frontend systems.",
        scraped_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
    )
    assert listing.salary_min is None
    assert listing.date_posted is None


def test_listing_requires_title():
    with pytest.raises(ValidationError):
        Listing(
            source="linkedin",
            external_id="125",
            company="Acme Corp",
            location="Remote",
            is_remote=True,
            url="https://www.linkedin.com/jobs/view/125",
            description="Missing title.",
            scraped_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
        )
