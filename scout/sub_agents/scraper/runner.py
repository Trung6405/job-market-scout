from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from scout.config import Settings
from scout.config import settings as default_settings
from scout.shared.schemas import Listing
from scout.sub_agents.scraper.mcp_client import fetch_jobs
from scout.sub_agents.scraper.normalize import normalize_job

logger = logging.getLogger(__name__)


async def _fetch_role(
    jobspy_mcp_url: str,
    role: str,
    location: str,
    results_wanted: int,
    hours_old: int,
    site_names: str,
):
    logger.info("Scraping role=%r location=%r sites=%r ...", role, location, site_names)
    jobs = await fetch_jobs(
        jobspy_mcp_url,
        searchTerm=role,
        location=location,
        resultsWanted=results_wanted,
        hoursOld=hours_old,
        siteNames=site_names,
        format="json",
    )
    logger.info("Scraped role=%r: %d raw jobs", role, len(jobs))
    return jobs


async def run_scraper(settings: Settings | None = None) -> list[Listing]:
    active_settings = settings or default_settings
    location = ", ".join(active_settings.search_locations)
    site_names = ",".join(active_settings.search_site_names)
    scraped_at = datetime.now(timezone.utc)

    logger.info(
        "Starting scrape: %d role(s) across sites=%r",
        len(active_settings.search_roles),
        site_names,
    )

    # jobspy-mcp-server used to share one MCP `Server` instance across all
    # SSE connections, which crashed on a second concurrent connection. The
    # server now creates a fresh `Server` per SSE connection (see
    # docker/jobspy-mcp/index.js), so role searches can run concurrently.
    jobs_by_role = await asyncio.gather(
        *(
            _fetch_role(
                active_settings.jobspy_mcp_url,
                role,
                location,
                active_settings.results_wanted,
                active_settings.hours_old,
                site_names,
            )
            for role in active_settings.search_roles
        )
    )

    listings: list[Listing] = []
    seen: set[tuple[str, str]] = set()
    for jobs in jobs_by_role:
        for job in jobs:
            listing = normalize_job(job, scraped_at)
            if listing is None:
                continue
            key = (listing.source, listing.external_id)
            if key in seen:
                continue
            seen.add(key)
            listings.append(listing)

    logger.info(
        "Finished scrape: %d unique listing(s) after dedup (from %d raw)",
        len(listings),
        sum(len(jobs) for jobs in jobs_by_role),
    )

    return listings
