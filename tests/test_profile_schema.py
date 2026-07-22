from __future__ import annotations

import pytest
from pydantic import ValidationError

from scout.shared.schemas import (
    Background,
    DomainKnowledge,
    Profile,
    Project,
    TechCategory,
    TechSkill,
)


def _make_profile(**overrides):
    defaults = dict(
        name="Minh Nguyen",
        target_role="Junior / Graduate Software Engineer",
        target_locations=["Sydney", "Melbourne", "Remote (AU)"],
        tech_stack=[
            TechCategory(
                category="Languages",
                skills=[TechSkill(name="Python", proficiency=4, note="2 yrs")],
            )
        ],
        domain_knowledge=[
            DomainKnowledge(
                name="Web application development",
                proficiency=75,
                description="Full request-to-DB-to-UI loop across 2 projects.",
            )
        ],
        background=Background(
            education="B.Sc. Computer Science",
            experience="0.5 yrs",
            preferred_roles=["Software Engineer"],
            locations=["Sydney"],
        ),
        projects=[
            Project(
                title="Recipe-sharing web app",
                description="React + Flask + REST API.",
                tags=["React", "Flask"],
            )
        ],
    )
    defaults.update(overrides)
    return Profile(**defaults)


def test_tech_skill_accepts_valid_data():
    skill = TechSkill(name="Python", proficiency=4, note="2 yrs")
    assert skill.proficiency == 4
    assert skill.note == "2 yrs"


def test_tech_skill_note_is_optional():
    skill = TechSkill(name="React", proficiency=3)
    assert skill.note is None


def test_tech_skill_rejects_proficiency_above_5():
    with pytest.raises(ValidationError):
        TechSkill(name="Python", proficiency=6)


def test_tech_skill_rejects_proficiency_below_1():
    with pytest.raises(ValidationError):
        TechSkill(name="Python", proficiency=0)


def test_tech_category_accepts_freeform_category_name():
    category = TechCategory(
        category="Machine Learning",
        skills=[TechSkill(name="PyTorch", proficiency=2)],
    )
    assert category.category == "Machine Learning"
    assert len(category.skills) == 1


@pytest.mark.parametrize(
    "proficiency,expected_level",
    [
        (100, "Solid"),
        (75, "Solid"),
        (70, "Solid"),
        (69, "Good"),
        (65, "Good"),
        (50, "Good"),
        (49, "Developing"),
        (35, "Developing"),
        (30, "Developing"),
        (29, "Emerging"),
        (20, "Emerging"),
        (0, "Emerging"),
    ],
)
def test_domain_knowledge_level_derived_from_proficiency(proficiency, expected_level):
    domain = DomainKnowledge(
        name="Cloud & distributed systems",
        proficiency=proficiency,
        description="Conceptual only.",
    )
    assert domain.level == expected_level


def test_domain_knowledge_rejects_proficiency_above_100():
    with pytest.raises(ValidationError):
        DomainKnowledge(name="Cloud", proficiency=101, description="Too high.")


def test_domain_knowledge_rejects_proficiency_below_0():
    with pytest.raises(ValidationError):
        DomainKnowledge(name="Cloud", proficiency=-1, description="Too low.")


def test_background_accepts_valid_data():
    background = Background(
        education="B.Sc. Computer Science — Univ. of Melbourne (2026)",
        experience="0.5 yrs — 1 internship + coursework",
        preferred_roles=["Software Engineer", "Backend Developer"],
        locations=["Sydney", "Melbourne", "Remote (AU)"],
    )
    assert background.preferred_roles == ["Software Engineer", "Backend Developer"]


def test_project_accepts_valid_data():
    project = Project(
        title="Discord study-group bot",
        description="Python; scheduling, reminders, ~200 users on campus.",
        tags=["Python", "async"],
    )
    assert project.tags == ["Python", "async"]


def test_profile_accepts_valid_data():
    profile = _make_profile()
    assert profile.name == "Minh Nguyen"
    assert profile.tech_stack[0].category == "Languages"
    assert profile.domain_knowledge[0].level == "Solid"


def test_profile_requires_name():
    with pytest.raises(ValidationError):
        _make_profile(name=None)
