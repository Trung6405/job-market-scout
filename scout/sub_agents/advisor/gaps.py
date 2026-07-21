from __future__ import annotations

from scout.shared.schemas import ListingRequirements, Profile, SkillGap


def detect_gaps(requirements: ListingRequirements, profile: Profile) -> list[SkillGap]:
    """Compare listing requirements against a profile's tech stack, returning gaps."""
    profile_skills = {
        skill.name.lower()
        for category in profile.tech_stack
        for skill in category.skills
    }

    gaps: list[SkillGap] = []
    for skill in requirements.must_have:
        if skill.lower() not in profile_skills:
            gaps.append(SkillGap(skill=skill, requirement_level="must_have"))
    for skill in requirements.nice_to_have:
        if skill.lower() not in profile_skills:
            gaps.append(SkillGap(skill=skill, requirement_level="nice_to_have"))
    return gaps
