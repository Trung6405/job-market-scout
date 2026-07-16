from __future__ import annotations

from scout.config import Settings

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
