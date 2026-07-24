from __future__ import annotations

from scout.config import Settings
from scout.shared.schemas import MatchResult
from scout.sub_agents.briefing.filters import passes_preferences


def select_top_matches(
    matches: list[MatchResult], settings: Settings
) -> list[MatchResult]:
    qualifying = [
        match
        for match in matches
        if match.score >= settings.min_match_score
        and passes_preferences(match.listing, settings)
    ]
    qualifying.sort(key=lambda m: m.score, reverse=True)
    return qualifying[: settings.briefing_max_matches]
