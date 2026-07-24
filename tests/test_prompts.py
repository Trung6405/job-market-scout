from datetime import datetime, timezone

from scout.config import Settings
from scout.prompts import (
    build_briefing_instruction,
    build_requirements_instruction,
    build_scorer_instruction,
)
from scout.shared.profile import render_profile_text
from scout.shared.schemas import Listing, MatchResult


def _make_match(external_id: str, title: str, score: int) -> MatchResult:
    listing = Listing(
        source="linkedin",
        external_id=external_id,
        title=title,
        company="Acme Corp",
        location="Remote",
        is_remote=True,
        url=f"https://www.linkedin.com/jobs/view/{external_id}",
        description="Build backend systems.",
        scraped_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
    )
    return MatchResult(listing=listing, score=score, reasoning="Good fit.")


def test_build_briefing_instruction_includes_profile_and_top_match_titles():
    settings = Settings()
    matches = [_make_match("1", "Platform Engineer", 88)]

    instruction = build_briefing_instruction(settings, matches)

    assert render_profile_text(settings.profile) in instruction
    assert "Platform Engineer" in instruction
    assert "88" in instruction


def test_build_briefing_instruction_excludes_listing_url_and_description():
    settings = Settings()
    matches = [_make_match("1", "Platform Engineer", 88)]

    instruction = build_briefing_instruction(settings, matches)

    assert "linkedin.com/jobs/view" not in instruction
    assert "Build backend systems." not in instruction


def test_build_requirements_instruction_asks_for_canonical_skill_names():
    settings = Settings()
    listings = [_make_match("1", "Platform Engineer", 88).listing]

    instruction = build_requirements_instruction(settings, listings)

    assert "canonical name" in instruction.lower()


def test_build_requirements_instruction_names_all_requirement_kinds():
    settings = Settings()
    listings = [_make_match("1", "Platform Engineer", 88).listing]

    instruction = build_requirements_instruction(settings, listings).lower()

    for kind in ("skill", "qualification", "experience", "soft_skill"):
        assert kind in instruction
    assert "kind" in instruction


def test_build_requirements_instruction_scopes_canonical_names_to_skills():
    settings = Settings()
    listings = [_make_match("1", "Platform Engineer", 88).listing]

    instruction = build_requirements_instruction(settings, listings).lower()

    # The canonical-short-name guidance applies to skill items; the sentence
    # that states it must mention skills so it isn't read as applying to
    # degrees/experience phrases.
    canonical_idx = instruction.find("canonical name")
    window = instruction[max(0, canonical_idx - 200) : canonical_idx + 200]
    assert "skill" in window


def test_scorer_instruction_omits_preferences(listing_factory):
    settings = Settings()
    object.__setattr__(settings, "preferred_locations", ["Melbourne"])
    object.__setattr__(settings, "remote_only", True)
    object.__setattr__(settings, "min_salary", 90000.0)

    instruction = build_scorer_instruction(settings, [listing_factory()])
    assert "Preferred locations" not in instruction
    assert "Remote only" not in instruction
    assert "Minimum salary" not in instruction


def test_scorer_instruction_keeps_profile_and_rubric(listing_factory):
    instruction = build_scorer_instruction(Settings(), [listing_factory()])
    assert "Candidate profile:" in instruction
    assert "90-100" in instruction
    assert '"scores"' in instruction


def test_scorer_and_requirements_put_listings_last(listing_factory):
    """Invariant instructions lead so the rubric+profile form a cacheable
    prefix across batches and days; the variable listings JSON trails."""
    settings = Settings()
    listings = [listing_factory()]

    scorer = build_scorer_instruction(settings, listings)
    requirements = build_requirements_instruction(settings, listings)

    for instruction in (scorer, requirements):
        assert not instruction.startswith("Listings:\n")
        # Nothing but the listings JSON follows the "Listings:" label.
        head, tail = instruction.split("Listings:\n", 1)
        assert head.strip()  # invariant content precedes the listings
        assert tail.strip()  # the JSON block is present and non-empty
    # Scorer's invariant prefix carries the rubric + profile.
    assert scorer.index("Candidate profile:") < scorer.index("Listings:\n")
    assert scorer.index("90-100") < scorer.index("Listings:\n")


def test_requirements_instruction_never_includes_the_profile(listing_factory):
    """Extraction must stay profile-blind — see the spec's Amendment.

    If the profile leaks into this prompt, a model can soften a requirement
    the student doesn't meet, and the gap silently disappears.
    """
    settings = Settings()
    instruction = build_requirements_instruction(settings, [listing_factory()])
    assert settings.profile.name not in instruction
    assert "Candidate profile:" not in instruction
