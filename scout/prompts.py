from __future__ import annotations

from scout.config import Settings

SCRAPER_INSTRUCTION_TEMPLATE = """\
You are the job-listing scraper for Job Market Scout.

Call the `search_jobs` tool once for each of these search roles: {roles}.
For each call, use these locations: {locations}, request up to
{results_wanted} results, and restrict results to postings from the last
{hours_old} hours. Do not invent listings or call any other tool.

Normalize every result the tool returns into the Listing schema:
- Keep `title`, `company`, `location`, and `url` exactly as provided.
- Set `is_remote` to true only if the listing is explicitly remote.
- Leave `salary_min`/`salary_max`/`date_posted` unset when the source does
  not provide them.
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
