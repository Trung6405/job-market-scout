from __future__ import annotations

from datetime import datetime, timezone

from scout.config import Settings
from scout.config import settings as default_settings
from scout.shared.schemas import Listing
from scout.sub_agents.scraper.mcp_client import fetch_jobs
from scout.sub_agents.scraper.normalize import normalize_job

_DEFAULT_SITE_NAMES = "indeed,linkedin,zip_recruiter,glassdoor,google"


async def run_scraper(settings: Settings | None = None) -> list[Listing]:
    active_settings = settings or default_settings
    location = ", ".join(active_settings.search_locations)
    scraped_at = datetime.now(timezone.utc)

    listings: list[Listing] = []
    seen: set[tuple[str, str]] = set()
    for role in active_settings.search_roles:
        jobs = await fetch_jobs(
            active_settings.jobspy_mcp_url,
            searchTerm=role,
            location=location,
            resultsWanted=active_settings.results_wanted,
            hoursOld=active_settings.hours_old,
            siteNames=_DEFAULT_SITE_NAMES,
            format="json",
        )
        for job in jobs:
            listing = normalize_job(job, scraped_at)
            if listing is None:
                continue
            key = (listing.source, listing.external_id)
            if key in seen:
                continue
            seen.add(key)
            listings.append(listing)

    return listings
