from __future__ import annotations

from scout.config import Settings
from scout.shared.schemas import Listing


def passes_preferences(listing: Listing, settings: Settings) -> bool:
    """Whether a listing matches the student's stated preferences.

    Applied at brief selection, deliberately *not* before scoring: every
    listing is scored so the dashboard shows the day's full market, and
    preferences narrow only what reaches Discord.
    """
    if settings.remote_only and not listing.is_remote:
        return False
    if (
        settings.preferred_locations
        and not listing.is_remote
        and not any(
            preferred.lower() in listing.location.lower()
            for preferred in settings.preferred_locations
        )
    ):
        return False
    if settings.min_salary is not None:
        salary = (
            listing.salary_max
            if listing.salary_max is not None
            else listing.salary_min
        )
        if salary is not None and salary < settings.min_salary:
            return False
    return True
