from __future__ import annotations

import json

from scout.config import Settings
from scout.shared.profile import render_profile_text
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


def _listings_block(settings: Settings, listings: list[Listing]) -> str:
    """The listings JSON for one batch — the variable trailing suffix of
    both the Scorer and Extractor prompts.

    Placed last, after each prompt's own (invariant) instructions and, for
    the Scorer, the candidate profile. That invariant text is identical
    across every batch of a stage and across every day's run, so putting it
    first makes it the shared leading prefix DeepSeek's automatic cache can
    key on — see scripts/spike_prefix_cache.py and
    docs/agent/specs/llm-call-efficiency/spec.md. The listings JSON itself
    varies per batch and per stage (different batch sizes), so it can never
    be part of that shared prefix and belongs at the end instead.
    """
    listings_json = json.dumps(
        [
            _project_listing_for_scoring(listing, settings.description_char_limit)
            for listing in listings
        ],
        indent=2,
    )
    return f"Listings:\n{listings_json}"


# Preferences (location, remote, salary) are deliberately NOT given to the
# scorer. They gate the brief instead — see briefing/filters.py. Scoring
# them here too would count them twice: a strong role in the wrong city
# would reach the dashboard already marked down, when the dashboard is
# meant to show the day's full market.
def build_scorer_instruction(settings: Settings, listings: list[Listing]) -> str:
    return f"""\
You are the job-match scorer for Job Market Scout.

For each listing in the Listings block below, first identify the required skills and
qualifications stated in its description — not nice-to-haves, the ones
described as required, must-have, or similar. Check each one against the
resume. A skill only counts as met if the resume states it or something
clearly equivalent; do not assume a candidate has a skill just because it
is adjacent to something they do have.

Then compare seniority level: the years of experience, scope, and
language of the listing (e.g. "1+ years," "entry-level," "associate,"
"will receive guidance") against what the resume shows. A resume whose
experience clearly exceeds what the listing asks for is overqualified —
this is a real mismatch, not a bonus, because it raises the risk of
being screened out or of a scope/pay mismatch, even when every required
skill is met.

Score from 0 to 100 using this rubric:
- 90-100: the resume meets essentially all stated required skills, with
  no missing skill category, and the seniority level is a good match
  (neither overqualified nor underqualified).
- 70-89: the resume meets most required skills, missing at most one
  minor one, and seniority is a reasonable match.
- 40-69: the resume meets most required skills, but is significantly
  overqualified or underqualified for the listing's stated seniority
  level, or is missing multiple required skills or an entire required
  skill category (e.g. the listing requires cloud/DevOps tooling and
  the resume has none).
- 0-39: fundamental mismatch in role, seniority, or most required
  skills.

Matching on job title, seniority, or general domain alone is not enough
to score high if specific required skills are missing — a partial skill
match is a partial score, not a full one. Likewise, meeting every
required skill is not enough to score high if the resume is
overqualified for the listing's stated seniority level.

Give one short sentence of reasoning per listing that names the most
significant missing required skill or seniority mismatch, if any. Do
not invent listings beyond the ones provided, and do not call any tool.

Candidate profile:
{render_profile_text(settings.profile)}

Return a JSON object with a single key "scores" containing a list of
objects, each with "source" and "external_id" (copied exactly from the
listing — together they identify it, since external_id alone may repeat
across sources), "score" (integer 0-100), and "reasoning" (one short
sentence). Return only the JSON object, no commentary.

{_listings_block(settings, listings)}
"""


def build_requirements_instruction(settings: Settings, listings: list[Listing]) -> str:
    return f"""\
You are the requirements extractor for Job Market Scout.

For each listing in the Listings block below, read its description and identify two separate
lists of requirements:
- "must_have": requirements explicitly stated as required, must-have,
  mandatory, or similar.
- "nice_to_have": requirements explicitly marked as preferred,
  nice-to-have, bonus, a plus, or similar.

Each requirement is an object with a "name" and a "kind". Classify the
kind as exactly one of:
- "skill": a concrete technical skill, tool, framework, or language
  (e.g. PostgreSQL, React, Docker).
- "qualification": a degree, certification, or credential
  (e.g. "A STEM degree in computer science").
- "experience": a years-of-experience or seniority threshold
  (e.g. "3+ years of backend experience").
- "soft_skill": a non-technical trait
  (e.g. "strong communication", "teamwork").

Also extract three short facts, only if the listing states them:
- "seniority": the stated experience level (e.g. "Graduate / Entry",
  "Mid-level", "Senior"), in the listing's own words or a short
  paraphrase.
- "work_type": the stated work arrangement (e.g. "Remote", "Hybrid — 3
  days in office", "On-site"), if the listing says more than the plain
  remote/on-site flag already tracked separately.
- "team": the specific team or group mentioned (e.g. "Platform team",
  "Payments engineering"), if named.
Set any of these to null if the listing does not clearly state it — do
not guess or infer one from general context.

For "skill"-kind requirements only, write each skill as a single
canonical name: use the common full name without version numbers or
punctuation decoration (e.g. "React" not "React.js" or "React 18",
"JavaScript" not "JS", "PostgreSQL" not "Postgres"). This keeps a skill
comparable across listings. Qualification, experience, and soft_skill
names may stay as short natural phrases.

Only extract what the listing's description actually states. Do not
invent requirements that aren't stated in the text, and do not infer or
assume requirements that are merely implied. Do not merge the two
skill categories — a skill belongs in exactly one list, based on how
the listing describes it. If a listing does not clearly state any
requirements in a category, return an empty list for that category. Do
not invent listings beyond the ones provided, and do not call any tool.

Return a JSON object with a single key "requirements" containing a list
of objects, each with "source" and "external_id" (copied exactly from
the listing — together they identify it, since external_id alone may
repeat across sources), "must_have" (a list of {"name", "kind"}
objects), "nice_to_have" (a list of {"name", "kind"} objects),
"seniority" (short string or
null), "work_type" (short string or null), and "team" (short string or
null). Return only the JSON object, no commentary.

{_listings_block(settings, listings)}
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

Candidate profile:
{render_profile_text(settings.profile)}

Today's top matches:
{matches_json}

Return a single JSON object with two keys: "intro" (string) and
"takeaways" (a list of objects, each with "source" and "external_id"
copied exactly from the match, and "takeaway", one short sentence).
Return only the JSON object, no commentary.
"""
