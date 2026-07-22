from scout.shared.profile import render_profile_text
from scout.shared.schemas import (
    Background,
    DomainKnowledge,
    Profile,
    Project,
    TechCategory,
    TechSkill,
)


def _profile() -> Profile:
    return Profile(
        name="Test Student",
        target_role="Junior Software Engineer",
        target_locations=["Sydney"],
        tech_stack=[
            TechCategory(
                category="Languages",
                skills=[TechSkill(name="Python", proficiency=4)],
            )
        ],
        domain_knowledge=[
            DomainKnowledge(name="Web", proficiency=60, description="APIs")
        ],
        background=Background(
            education="B.Sc. CS",
            experience="0.5 yrs",
            preferred_roles=["Software Engineer"],
            locations=["Sydney"],
        ),
        projects=[Project(title="Scout", description="job agent", tags=["Python"])],
    )


def test_render_profile_text_maps_proficiency_to_words():
    text = render_profile_text(_profile())
    assert "Python (advanced)" in text
    assert "Target role: Junior Software Engineer" in text
    assert "Scout: job agent" in text
    assert "Web (Good)" in text
