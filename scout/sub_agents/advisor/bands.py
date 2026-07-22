from scout.config import Settings


def classify_band(score: int, settings: Settings) -> str:
    """Classify a match score into a success band."""
    if score >= settings.strong_match_score:
        return "strong_match"
    elif score >= settings.min_match_score:
        return "competitive"
    else:
        return "reach"
