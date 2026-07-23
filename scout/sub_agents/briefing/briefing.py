from __future__ import annotations

from pathlib import Path

from scout.config import Settings
from scout.config import settings as default_settings
from scout.shared.schemas import Listing, ListingScore
from scout.sub_agents.briefing.embed_builder import build_embed
from scout.sub_agents.briefing.notification import (
    ensure_discord_configured,
    send_message,
)
from scout.sub_agents.briefing.select import select_top_matches
from scout.sub_agents.briefing.summarize import summarize_matches
from scout.sub_agents.scorer.results import join_match_results


async def run_briefing(
    listings: list[Listing],
    scores: list[ListingScore],
    settings: Settings | None = None,
    report_path: Path | None = None,
) -> dict:
    active_settings = settings or default_settings
    ensure_discord_configured(active_settings)
    matches = join_match_results(listings, scores)
    top_matches = select_top_matches(matches, active_settings)
    prose = (
        await summarize_matches(top_matches, active_settings)
        if top_matches
        else None
    )
    payload = build_embed(top_matches, prose, active_settings)
    await send_message(payload, active_settings)
    return payload
