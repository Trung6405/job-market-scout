from __future__ import annotations

from scout.shared.schemas import ListingRequirements, Profile, SkillGap


def evaluate_requirements(
    requirements: ListingRequirements, profile: Profile
) -> list[SkillGap]:
    """Check every stated requirement against a profile's tech stack.

    Unlike detect_gaps, this returns one entry per requirement — met or not —
    so callers can render a full checklist, not just the missing skills.
    """
    profile_skills = {
        skill.name.lower()
        for category in profile.tech_stack
        for skill in category.skills
    }

    checks: list[SkillGap] = []
    for skill in requirements.must_have:
        checks.append(
            SkillGap(
                skill=skill,
                requirement_level="must_have",
                met=skill.lower() in profile_skills,
            )
        )
    for skill in requirements.nice_to_have:
        checks.append(
            SkillGap(
                skill=skill,
                requirement_level="nice_to_have",
                met=skill.lower() in profile_skills,
            )
        )
    return checks


def detect_gaps(requirements: ListingRequirements, profile: Profile) -> list[SkillGap]:
    """Compare listing requirements against a profile's tech stack, returning gaps."""
    return [check for check in evaluate_requirements(requirements, profile) if not check.met]
