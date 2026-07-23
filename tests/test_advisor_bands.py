from typing import get_args

import pytest
from pydantic import ValidationError

from scout.config import Settings
from scout.shared.schemas import Band, RunListing
from scout.sub_agents.advisor.bands import classify_band


def test_band_is_a_closed_vocabulary():
    assert set(get_args(Band)) == {"strong_match", "competitive", "reach"}


def test_classify_band_returns_a_member_of_the_band_vocabulary():
    settings = Settings(strong_match_score=85, min_match_score=60)
    assert classify_band(90, settings) in get_args(Band)
    assert classify_band(70, settings) in get_args(Band)
    assert classify_band(10, settings) in get_args(Band)


def test_run_listing_rejects_unknown_band():
    with pytest.raises(ValidationError):
        RunListing(
            id=1,
            run_id=1,
            listing_id=1,
            score=50,
            reasoning="ok",
            band="banana",
        )


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
