from __future__ import annotations

from scout.shared.schemas import Listing, ListingScore, MatchResult


def join_match_results(
    listings: list[Listing], scores: list[ListingScore]
) -> list[MatchResult]:
    listings_by_id = {listing.external_id: listing for listing in listings}
    return [
        MatchResult(
            listing=listings_by_id[score.external_id],
            score=score.score,
            reasoning=score.reasoning,
        )
        for score in scores
        if score.external_id in listings_by_id
    ]
