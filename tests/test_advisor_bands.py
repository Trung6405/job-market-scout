from scout.config import Settings
from scout.sub_agents.advisor.bands import classify_band


def test_classify_band_strong_match_at_threshold():
    settings = Settings(strong_match_score=85, min_match_score=60)
    result = classify_band(85, settings)
    assert result == "strong_match"


def test_classify_band_strong_match_above_threshold():
    settings = Settings(strong_match_score=85, min_match_score=60)
    result = classify_band(100, settings)
    assert result == "strong_match"


def test_classify_band_competitive_at_min_threshold():
    settings = Settings(strong_match_score=85, min_match_score=60)
    result = classify_band(60, settings)
    assert result == "competitive"


def test_classify_band_competitive_between_thresholds():
    settings = Settings(strong_match_score=85, min_match_score=60)
    result = classify_band(84, settings)
    assert result == "competitive"


def test_classify_band_reach_below_min_threshold():
    settings = Settings(strong_match_score=85, min_match_score=60)
    result = classify_band(59, settings)
    assert result == "reach"


def test_classify_band_reach_zero():
    settings = Settings(strong_match_score=85, min_match_score=60)
    result = classify_band(0, settings)
    assert result == "reach"
