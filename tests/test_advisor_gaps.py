from __future__ import annotations

from scout.shared.schemas import (
    Background,
    ListingRequirements,
    Profile,
    RequirementItem,
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


def _item(spec) -> RequirementItem:
    """Bare strings are skill-kind; ``(name, kind)`` tuples set the kind."""
    if isinstance(spec, tuple):
        name, kind = spec
        return RequirementItem(name=name, kind=kind)
    return RequirementItem(name=spec, kind="skill")


def _make_requirements(must_have, nice_to_have) -> ListingRequirements:
    return ListingRequirements(
        source="linkedin",
        external_id="job-1",
        must_have=[_item(s) for s in must_have],
        nice_to_have=[_item(s) for s in nice_to_have],
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


def test_evaluate_requirements_matches_skill_name_variants():
    requirements = _make_requirements(["React.js", "Postgres"], ["JS"])
    profile = _make_profile(["React", "PostgreSQL", "JavaScript"])

    checks = evaluate_requirements(requirements, profile)

    assert [check for check in checks if not check.met] == []


def test_evaluate_requirements_still_flags_genuinely_absent_skill():
    requirements = _make_requirements(["React.js", "Rust"], [])
    profile = _make_profile(["React"])

    checks = evaluate_requirements(requirements, profile)

    assert [check for check in checks if not check.met] == [
        SkillGap(skill="Rust", requirement_level="must_have", met=False)
    ]


def test_evaluate_requirements_preserves_original_skill_string():
    requirements = _make_requirements(["React.js"], [])
    profile = _make_profile(["React"])

    checks = evaluate_requirements(requirements, profile)

    assert checks[0].skill == "React.js"
    assert checks[0].met is True


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


def test_evaluate_requirements_does_not_gap_non_skill_requirements():
    # A STEM degree the profile's tech_stack can never contain must not be a
    # gap; non-skill items pass through with their kind and a met=True sentinel.
    requirements = _make_requirements(
        [("A STEM degree in CS", "qualification"), "Rust"],
        [("3+ years experience", "experience")],
    )
    profile = _make_profile(["Python"])

    checks = evaluate_requirements(requirements, profile)

    # Only the genuinely-absent technical skill is a gap.
    assert [check for check in checks if not check.met] == [
        SkillGap(skill="Rust", requirement_level="must_have", met=False)
    ]
    by_name = {c.skill: c for c in checks}
    assert by_name["A STEM degree in CS"].kind == "qualification"
    assert by_name["A STEM degree in CS"].met is True
    assert by_name["3+ years experience"].kind == "experience"
    assert by_name["3+ years experience"].met is True
    assert by_name["Rust"].kind == "skill"


def test_evaluate_requirements_includes_met_and_unmet():
    requirements = _make_requirements(["Python", "Go"], ["Docker"])
    profile = _make_profile(["python", "Docker"])

    checks = evaluate_requirements(requirements, profile)

    assert checks == [
        SkillGap(skill="Python", requirement_level="must_have", met=True),
        SkillGap(skill="Go", requirement_level="must_have", met=False),
        SkillGap(skill="Docker", requirement_level="nice_to_have", met=True),
    ]
