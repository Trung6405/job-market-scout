from datetime import datetime, timezone

from scout.config import Settings
from scout.shared.schemas import Listing, MatchResult
from scout.sub_agents.briefing.select import select_top_matches


def _make_match(external_id: str, score: int) -> MatchResult:
    listing = Listing(
        source="linkedin",
        external_id=external_id,
        title="Backend Engineer",
        company="Acme Corp",
        location="Remote",
        is_remote=True,
        url=f"https://www.linkedin.com/jobs/view/{external_id}",
        description="Build backend systems.",
        scraped_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
    )
    return MatchResult(listing=listing, score=score, reasoning="Good fit.")


def test_select_top_matches_drops_below_threshold():
    settings = Settings(min_match_score=60, briefing_max_matches=5)
    matches = [_make_match("1", 80), _make_match("2", 40)]

    result = select_top_matches(matches, settings)

    assert [m.listing.external_id for m in result] == ["1"]


def test_select_top_matches_sorts_descending():
    settings = Settings(min_match_score=0, briefing_max_matches=5)
    matches = [_make_match("1", 50), _make_match("2", 90), _make_match("3", 70)]

    result = select_top_matches(matches, settings)

    assert [m.listing.external_id for m in result] == ["2", "3", "1"]


def test_select_top_matches_caps_to_max():
    settings = Settings(min_match_score=0, briefing_max_matches=2)
    matches = [_make_match("1", 90), _make_match("2", 80), _make_match("3", 70)]

    result = select_top_matches(matches, settings)

    assert [m.listing.external_id for m in result] == ["1", "2"]


def test_select_top_matches_returns_empty_when_none_qualify():
    settings = Settings(min_match_score=90, briefing_max_matches=5)
    matches = [_make_match("1", 50)]

    result = select_top_matches(matches, settings)

    assert result == []


def test_select_top_matches_excludes_preference_failures(match_factory, listing_factory):
    settings = Settings()
    object.__setattr__(settings, "min_match_score", 50)
    object.__setattr__(settings, "remote_only", True)

    remote = match_factory(listing=listing_factory(external_id="r", is_remote=True), score=80)
    onsite = match_factory(listing=listing_factory(external_id="o", is_remote=False), score=90)

    selected = select_top_matches([remote, onsite], settings)
    assert [m.listing.external_id for m in selected] == ["r"]


def test_select_top_matches_still_applies_score_floor(match_factory):
    settings = Settings()
    object.__setattr__(settings, "min_match_score", 60)
    object.__setattr__(settings, "remote_only", False)
    object.__setattr__(settings, "preferred_locations", [])
    object.__setattr__(settings, "min_salary", None)

    assert select_top_matches([match_factory(score=59)], settings) == []
