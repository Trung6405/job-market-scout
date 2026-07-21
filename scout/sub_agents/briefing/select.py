from __future__ import annotations

from scout.config import Settings
from scout.shared.schemas import MatchResult


def select_top_matches(
    matches: list[MatchResult], settings: Settings
) -> list[MatchResult]:
    qualifying = [m for m in matches if m.score >= settings.min_match_score]
    qualifying.sort(key=lambda m: m.score, reverse=True)
    return qualifying[: settings.briefing_max_matches]
