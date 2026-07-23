from __future__ import annotations

from scout.config import Settings
from scout.shared.schemas import BriefingProse, MatchResult

_FALLBACK_TAKEAWAY_TEMPLATE = "Worth a look — scored {score}/100 against your resume."

# Discord embed limits (https://discord.com/developers/docs/resources/message).
_TITLE_LIMIT = 256
_FIELD_NAME_LIMIT = 256
_FIELD_VALUE_LIMIT = 1024
_DESCRIPTION_LIMIT = 4096


def _clamp(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _index_takeaways(prose: BriefingProse | None) -> dict[tuple[str, str], str]:
    if prose is None:
        return {}
    return {
        (takeaway.source, takeaway.external_id): takeaway.takeaway
        for takeaway in prose.takeaways
    }


def _takeaway_for(
    match: MatchResult, takeaways_by_key: dict[tuple[str, str], str]
) -> str:
    key = (match.listing.source, match.listing.external_id)
    if key in takeaways_by_key:
        return takeaways_by_key[key]
    return _FALLBACK_TAKEAWAY_TEMPLATE.format(score=match.score)


def build_embed(
    top_matches: list[MatchResult],
    prose: BriefingProse | None,
    settings: Settings,
) -> dict:
    """Build a Discord message payload (``{"embeds": [...]}``) for the briefing."""
    if not top_matches:
        embed = {
            "title": "Job Market Scout: no strong matches today",
            "description": "No listings met your match-score threshold today.",
        }
        return {"embeds": [embed]}

    count = len(top_matches)
    title = f"Job Market Scout: {count} match{'es' if count != 1 else ''} today"

    intro = prose.intro if prose is not None else ""
    takeaways_by_key = _index_takeaways(prose)

    fields = []
    for match in top_matches:
        listing = match.listing
        takeaway = _takeaway_for(match, takeaways_by_key)
        name = f"{listing.title} at {listing.company} — {match.score}/100"
        value = f"[View listing]({listing.url})\n{takeaway}"
        fields.append(
            {
                "name": _clamp(name, _FIELD_NAME_LIMIT),
                "value": _clamp(value, _FIELD_VALUE_LIMIT),
            }
        )

    embed = {
        "title": _clamp(title, _TITLE_LIMIT),
        "description": _clamp(intro, _DESCRIPTION_LIMIT),
        "fields": fields,
    }
    return {"embeds": [embed]}
