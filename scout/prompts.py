from __future__ import annotations

import json

from scout.config import Settings
from scout.shared.schemas import Listing

SCRAPER_INSTRUCTION_TEMPLATE = """\
You are the job-listing scraper for Job Market Scout.

Call the `search_jobs` tool once for each of these search roles: {roles}.
For each call, use these locations: {locations}, request up to
{results_wanted} results, and restrict results to postings from the last
{hours_old} hours. Do not invent listings or call any other tool.

Normalize every result the tool returns into the Listing schema:
- Set `source` from the result's `site` field.
- Set `external_id` from the result's `id` field.
- Keep `title`, `company`, and `location` exactly as provided, and set
  `url` from the result's `jobUrl` field.
- Set `description` from the result's `description` field.
- Set `is_remote` to true only if the listing is explicitly remote.
- Set `date_posted` from the result's `datePosted` field when the source
  provides one; otherwise leave it unset.
- Set `salary_min`/`salary_max` from the result's `minAmount`/`maxAmount`
  fields; leave them unset when the source does not provide them.
- Set `scraped_at` to the current UTC time.

Drop any result missing a `title`, `company`, or `url` instead of guessing
values. Return only the normalized list of listings, no commentary.
"""


def build_scraper_instruction(settings: Settings) -> str:
    return SCRAPER_INSTRUCTION_TEMPLATE.format(
        roles=", ".join(settings.search_roles),
        locations=", ".join(settings.search_locations),
        results_wanted=settings.results_wanted,
        hours_old=settings.hours_old,
    )


def _project_listing_for_scoring(listing: Listing, description_char_limit: int) -> dict:
    return {
        "source": listing.source,
        "external_id": listing.external_id,
        "title": listing.title,
        "company": listing.company,
        "location": listing.location,
        "is_remote": listing.is_remote,
        "salary_min": listing.salary_min,
        "salary_max": listing.salary_max,
        "description": listing.description[:description_char_limit],
    }


def build_scorer_instruction(settings: Settings, listings: list[Listing]) -> str:
    listings_json = json.dumps(
        [
            _project_listing_for_scoring(listing, settings.description_char_limit)
            for listing in listings
        ],
        indent=2,
    )
    return f"""\
You are the job-match scorer for Job Market Scout.

Score each listing below from 0 to 100 on how well it fits the resume and
preferences, and give one short sentence of reasoning per listing. Do not
invent listings beyond the ones provided, and do not call any tool.

Resume:
{settings.resume_text}

Preferred locations: {settings.preferred_locations or "no preference"}
Remote only: {settings.remote_only}
Minimum salary: {settings.min_salary if settings.min_salary is not None else "no floor"}

Listings to score:
{listings_json}

Return a JSON list of objects, each with "source" and "external_id"
(copied exactly from the listing — together they identify it, since
external_id alone may repeat across sources), "score" (integer 0-100),
and "reasoning" (one short sentence). Return only the JSON list, no
commentary.
"""
