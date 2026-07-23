from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from scout.shared.schemas import (
    BriefingProse,
    BriefingTakeaway,
    Listing,
    ListingScore,
    MatchResult,
    RequirementItem,
    SkillGap,
)


def test_listing_accepts_valid_data():
    listing = Listing(
        source="linkedin",
        external_id="123",
        title="Backend Engineer",
        company="Acme Corp",
        location="Remote",
        is_remote=True,
        url="https://www.linkedin.com/jobs/view/123",
        description="Build backend systems.",
        salary_min=100000.0,
        salary_max=140000.0,
        date_posted=datetime(2026, 7, 10, tzinfo=timezone.utc),
        scraped_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
    )
    assert listing.title == "Backend Engineer"
    assert listing.is_remote is True


def test_listing_allows_missing_optional_salary_and_date():
    listing = Listing(
        source="linkedin",
        external_id="124",
        title="Frontend Engineer",
        company="Acme Corp",
        location="Sydney, AU",
        is_remote=False,
        url="https://www.linkedin.com/jobs/view/124",
        description="Build frontend systems.",
        scraped_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
    )
    assert listing.salary_min is None
    assert listing.date_posted is None


def test_listing_requires_title():
    with pytest.raises(ValidationError):
        Listing(
            source="linkedin",
            external_id="125",
            company="Acme Corp",
            location="Remote",
            is_remote=True,
            url="https://www.linkedin.com/jobs/view/125",
            description="Missing title.",
            scraped_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
        )

def _make_listing(**overrides):
    defaults = dict(
        source="linkedin",
        external_id="123",
        title="Backend Engineer",
        company="Acme Corp",
        location="Remote",
        is_remote=True,
        url="https://www.linkedin.com/jobs/view/123",
        description="Build backend systems.",
        scraped_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return Listing(**defaults)

def test_match_result_accepts_valid_data():
    result = MatchResult(
        listing=_make_listing(),
        score=82,
        reasoning="Strong backend overlap with resume experience",
    )
    assert result.score == 82
    assert result.listing.title == "Backend Engineer"

def test_match_result_require_score():
    with pytest.raises(ValidationError):
        MatchResult(listing=_make_listing(), reasoning="Missing score.")

def test_listing_score_accepts_valid_data():
    score = ListingScore(
        source="linkedin", external_id="123", score=82, reasoning="Strong overlap."
    )
    assert score.external_id == "123"
    assert score.score == 82

def test_listing_score_rejects_score_above_100():
    with pytest.raises(ValidationError):
        ListingScore(
            source="linkedin", external_id="123", score=101, reasoning="Too high."
        )

def test_listing_score_rejects_score_below_0():
    with pytest.raises(ValidationError):
        ListingScore(
            source="linkedin", external_id="123", score=-1, reasoning="Too low."
        )


def test_briefing_takeaway_accepts_valid_data():
    takeaway = BriefingTakeaway(
        source="linkedin", external_id="123", takeaway="Strong Python overlap."
    )
    assert takeaway.external_id == "123"


def test_briefing_prose_accepts_valid_data():
    prose = BriefingProse(
        intro="Here are today's top matches.",
        takeaways=[
            BriefingTakeaway(
                source="linkedin", external_id="123", takeaway="Strong overlap."
            )
        ],
    )
    assert prose.intro == "Here are today's top matches."
    assert len(prose.takeaways) == 1


def test_briefing_prose_allows_empty_takeaways():
    prose = BriefingProse(intro="No matches today.", takeaways=[])
    assert prose.takeaways == []


@pytest.mark.parametrize(
    "kind", ["skill", "qualification", "experience", "soft_skill"]
)
def test_requirement_item_accepts_each_kind(kind):
    item = RequirementItem(name="PostgreSQL", kind=kind)
    assert item.name == "PostgreSQL"
    assert item.kind == kind


def test_requirement_item_defaults_kind_to_skill():
    item = RequirementItem(name="React")
    assert item.kind == "skill"


def test_requirement_item_rejects_unknown_kind():
    with pytest.raises(ValidationError):
        RequirementItem(name="React", kind="framework")


def test_skill_gap_defaults_kind_to_skill():
    gap = SkillGap(skill="Go", requirement_level="must_have")
    assert gap.kind == "skill"


def test_skill_gap_rejects_unknown_kind():
    with pytest.raises(ValidationError):
        SkillGap(skill="Go", requirement_level="must_have", kind="framework")
