from datetime import datetime, timezone

from scout.shared.schemas import Listing, ListingScore
from scout.sub_agents.scorer.results import join_match_results

def _make_listing(**overrides):
    defaults = dict(
        source="linkedin",
        external_id="1",
        title="Backend Engineer",
        company="Acme Corp",
        location="Sydney, AU",
        is_remote=False,
        url="https://www.linkedin.com/jobs/view/1",
        description="Build backend systems.",
        scraped_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return Listing(**defaults)

def test_join_match_results_pairs_listing_with_its_score():
    listings = [_make_listing(external_id="1")]
    scores = [
        ListingScore(
            source="linkedin", external_id="1", score=82, reasoning="Strong overlap."
        )
    ]

    result = join_match_results(listings, scores)

    assert len(result) == 1
    assert result[0].listing.external_id == "1"
    assert result[0].score == 82
    assert result[0].reasoning == "Strong overlap."

def test_join_match_results_drops_unscored_listings():
    listings = [
        _make_listing(external_id="1"),
        _make_listing(external_id="2"),
    ]
    scores = [
        ListingScore(
            source="linkedin", external_id="1", score=82, reasoning="Strong overlap."
        )
    ]

    result = join_match_results(listings, scores)

    assert [match.listing.external_id for match in result] == ["1"]

def test_join_match_results_ignores_hallucinated_external_ids():
    listings = [_make_listing(external_id="1")]
    scores = [
        ListingScore(
            source="linkedin", external_id="1", score=82, reasoning="Strong overlap."
        ),
        ListingScore(
            source="linkedin",
            external_id="does-not-exist",
            score=50,
            reasoning="Invented.",
        ),
    ]

    result = join_match_results(listings, scores)

    assert [match.listing.external_id for match in result] == ["1"]

def test_join_match_results_distinguishes_same_external_id_across_sources():
    listings = [
        _make_listing(source="linkedin", external_id="1", title="Backend Engineer"),
        _make_listing(source="indeed", external_id="1", title="Data Engineer"),
    ]
    scores = [
        ListingScore(
            source="linkedin", external_id="1", score=90, reasoning="Great fit."
        ),
        ListingScore(
            source="indeed", external_id="1", score=40, reasoning="Weak fit."
        ),
    ]

    result = join_match_results(listings, scores)

    scores_by_title = {match.listing.title: match.score for match in result}
    assert scores_by_title == {"Backend Engineer": 90, "Data Engineer": 40}
