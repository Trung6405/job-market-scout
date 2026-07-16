from __future__ import annotations

from scout.config import Settings
from scout.shared.schemas import Listing

def filter_listings(listings: list[Listing], settings: Settings) -> list[Listing]:
    filtered = []
    for listing in listings:
        if settings.remote_only and not listing.is_remote:
            continue
        if settings.preferred_locations and not any(
            preferred.lower() in listings.location.lower()
            for preferred in settings.preferred_locations
        ):
            continue
        if settings.min_salary is not None:
            salary = (
                listing.salary_max
                if listing.salary_max is not None
                else listing.salary_min
            )
            if salary is not None and salary < settings.min_salary:
                continue
        filtered.append(listing)
    return filtered