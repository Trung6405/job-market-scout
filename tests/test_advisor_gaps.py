from __future__ import annotations

from scout.shared.schemas import (
    Background,
    ListingRequirements,
    Profile,
    SkillGap,
    TechCategory,
    TechSkill,
)
from scout.sub_agents.advisor.gaps import evaluate_requirements, normalize_skill


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


def test_normalize_skill_collapses_common_variants():
    assert normalize_skill("React.js") == normalize_skill("React")
    assert normalize_skill("Node.js") == normalize_skill("node")
    assert normalize_skill("  Python 3 ") == normalize_skill("python3")


def test_normalize_skill_collapses_known_aliases():
    assert normalize_skill("Postgres") == normalize_skill("PostgreSQL")
    assert normalize_skill("JS") == normalize_skill("JavaScript")
    assert normalize_skill("TS") == normalize_skill("TypeScript")
    assert normalize_skill("k8s") == normalize_skill("Kubernetes")


def test_normalize_skill_does_not_collapse_unrelated_skills():
    assert normalize_skill("React") != normalize_skill("Angular")
    assert normalize_skill("Java") != normalize_skill("JavaScript")


def test_evaluate_requirements_returns_no_gaps_when_fully_covered():
    requirements = _make_requirements(["Python", "SQL"], ["Docker"])
    profile = _make_profile(["Python", "SQL", "Docker"])

    checks = evaluate_requirements(requirements, profile)

    assert [check for check in checks if not check.met] == []


def test_evaluate_requirements_flags_missing_must_have():
    requirements = _make_requirements(["Python", "Go"], [])
    profile = _make_profile(["Python"])

    checks = evaluate_requirements(requirements, profile)

    assert [check for check in checks if not check.met] == [
        SkillGap(skill="Go", requirement_level="must_have", met=False)
    ]


def test_evaluate_requirements_flags_missing_nice_to_have():
    requirements = _make_requirements([], ["Docker", "Kubernetes"])
    profile = _make_profile(["Docker"])

    checks = evaluate_requirements(requirements, profile)

    assert [check for check in checks if not check.met] == [
        SkillGap(skill="Kubernetes", requirement_level="nice_to_have", met=False)
    ]


def test_evaluate_requirements_case_insensitive_match():
    requirements = _make_requirements(["Python"], [])
    profile = _make_profile(["python"])

    checks = evaluate_requirements(requirements, profile)

    assert [check for check in checks if not check.met] == []


def test_evaluate_requirements_mixed_must_have_and_nice_to_have_ordering():
    requirements = _make_requirements(
        ["Python", "Go"], ["Docker", "Kubernetes"]
    )
    profile = _make_profile(["python", "Docker"])

    checks = evaluate_requirements(requirements, profile)

    assert [check for check in checks if not check.met] == [
        SkillGap(skill="Go", requirement_level="must_have", met=False),
        SkillGap(skill="Kubernetes", requirement_level="nice_to_have", met=False),
    ]


def test_evaluate_requirements_includes_met_and_unmet():
    requirements = _make_requirements(["Python", "Go"], ["Docker"])
    profile = _make_profile(["python", "Docker"])

    checks = evaluate_requirements(requirements, profile)

    assert checks == [
        SkillGap(skill="Python", requirement_level="must_have", met=True),
        SkillGap(skill="Go", requirement_level="must_have", met=False),
        SkillGap(skill="Docker", requirement_level="nice_to_have", met=True),
    ]
