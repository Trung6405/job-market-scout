from __future__ import annotations

import json

from scout.config import Settings
from scout.shared.schemas import Listing, MatchResult

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

For each listing below, first identify the required skills and
qualifications stated in its description — not nice-to-haves, the ones
described as required, must-have, or similar. Check each one against the
resume. A skill only counts as met if the resume states it or something
clearly equivalent; do not assume a candidate has a skill just because it
is adjacent to something they do have.

Score from 0 to 100 using this rubric:
- 90-100: the resume meets essentially all stated required skills, with
  no missing skill category.
- 70-89: the resume meets most required skills, missing at most one
  minor one.
- 40-69: the resume meets the core experience level and role type, but
  is missing multiple required skills, or an entire required skill
  category (e.g. the listing requires cloud/DevOps tooling and the
  resume has none).
- 0-39: fundamental mismatch in role, seniority, or most required
  skills.

Matching on job title, seniority, or general domain alone is not enough
to score high if specific required skills are missing — a partial skill
match is a partial score, not a full one.

Give one short sentence of reasoning per listing that names the most
significant missing required skill, if any. Do not invent listings
beyond the ones provided, and do not call any tool.

Resume:
{settings.resume_text}

Preferred locations: {settings.preferred_locations or "no preference"}
Remote only: {settings.remote_only}
Minimum salary: {settings.min_salary if settings.min_salary is not None else "no floor"}

Listings to score:
{listings_json}

Return a JSON object with a single key "scores" containing a list of
objects, each with "source" and "external_id" (copied exactly from the
listing — together they identify it, since external_id alone may repeat
across sources), "score" (integer 0-100), and "reasoning" (one short
sentence). Return only the JSON object, no commentary.
"""


def _project_match_for_briefing(match: MatchResult) -> dict:
    return {
        "source": match.listing.source,
        "external_id": match.listing.external_id,
        "title": match.listing.title,
        "company": match.listing.company,
        "score": match.score,
    }


def build_briefing_instruction(
    settings: Settings, top_matches: list[MatchResult]
) -> str:
    matches_json = json.dumps(
        [_project_match_for_briefing(match) for match in top_matches], indent=2
    )
    return f"""\
You are the briefing writer for Job Market Scout. Write a short, upbeat
intro paragraph (2-3 sentences) for today's job matches, then one
one-line takeaway per listing explaining why it's worth a look, based
only on the title, company, and score given. Do not invent facts about
any listing beyond what is given, and do not call any tool.

Resume:
{settings.resume_text}

Today's top matches:
{matches_json}

Return a single JSON object with two keys: "intro" (string) and
"takeaways" (a list of objects, each with "source" and "external_id"
copied exactly from the match, and "takeaway", one short sentence).
Return only the JSON object, no commentary.
"""
