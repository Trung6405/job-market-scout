from __future__ import annotations

from scout.shared.schemas import (
    Background,
    ListingRequirements,
    Profile,
    SkillGap,
    TechCategory,
    TechSkill,
)
from scout.sub_agents.advisor.gaps import detect_gaps


def _make_profile(skills: list[str]) -> Profile:
    return Profile(
        name="Test Student",
        target_role="Backend Engineer",
        target_locations=["Remote"],
        tech_stack=[
            TechCategory(
                category="Languages",
                skills=[TechSkill(name=skill, proficiency=3) for skill in skills],
            )
        ],
        domain_knowledge=[],
        background=Background(
            education="BS CS",
            experience="1 year",
            preferred_roles=["Backend Engineer"],
            locations=["Remote"],
        ),
        projects=[],
    )


def _make_requirements(
    must_have: list[str], nice_to_have: list[str]
) -> ListingRequirements:
    return ListingRequirements(
        source="linkedin",
        external_id="job-1",
        must_have=must_have,
        nice_to_have=nice_to_have,
    )


def test_detect_gaps_returns_empty_when_fully_covered():
    requirements = _make_requirements(["Python", "SQL"], ["Docker"])
    profile = _make_profile(["Python", "SQL", "Docker"])

    gaps = detect_gaps(requirements, profile)

    assert gaps == []


def test_detect_gaps_flags_missing_must_have():
    requirements = _make_requirements(["Python", "Go"], [])
    profile = _make_profile(["Python"])

    gaps = detect_gaps(requirements, profile)

    assert gaps == [SkillGap(skill="Go", requirement_level="must_have")]


def test_detect_gaps_flags_missing_nice_to_have():
    requirements = _make_requirements([], ["Docker", "Kubernetes"])
    profile = _make_profile(["Docker"])

    gaps = detect_gaps(requirements, profile)

    assert gaps == [SkillGap(skill="Kubernetes", requirement_level="nice_to_have")]


def test_detect_gaps_case_insensitive_match():
    requirements = _make_requirements(["Python"], [])
    profile = _make_profile(["python"])

    gaps = detect_gaps(requirements, profile)

    assert gaps == []


def test_detect_gaps_mixed_must_have_and_nice_to_have_ordering():
    requirements = _make_requirements(
        ["Python", "Go"], ["Docker", "Kubernetes"]
    )
    profile = _make_profile(["python", "Docker"])

    gaps = detect_gaps(requirements, profile)

    assert gaps == [
        SkillGap(skill="Go", requirement_level="must_have"),
        SkillGap(skill="Kubernetes", requirement_level="nice_to_have"),
    ]
