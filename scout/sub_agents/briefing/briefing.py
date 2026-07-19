from __future__ import annotations

from email.message import EmailMessage

from scout.config import Settings
from scout.config import settings as default_settings
from scout.shared.schemas import Listing, ListingScore
from scout.sub_agents.briefing.email_builder import build_email
from scout.sub_agents.briefing.notification import send_email
from scout.sub_agents.briefing.select import select_top_matches
from scout.sub_agents.briefing.summarize import summarize_matches
from scout.sub_agents.scorer.results import join_match_results


async def run_briefing(
    listings: list[Listing],
    scores: list[ListingScore],
    settings: Settings | None = None,
) -> EmailMessage:
    active_settings = settings or default_settings
    matches = join_match_results(listings, scores)
    top_matches = select_top_matches(matches, active_settings)
    prose = (
        await summarize_matches(top_matches, active_settings)
        if top_matches
        else None
    )
    message = build_email(top_matches, prose, active_settings)
    send_email(message, active_settings)
    return message
