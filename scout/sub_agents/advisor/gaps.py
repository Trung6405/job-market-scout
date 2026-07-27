from __future__ import annotations

from scout.shared.schemas import ListingRequirements, Profile, SkillGap
from scout.shared.skills import normalize_skill

__all__ = ["evaluate_requirements", "normalize_skill"]


def evaluate_requirements(
    requirements: ListingRequirements, profile: Profile
) -> list[SkillGap]:
    """Check every stated requirement against a profile's tech stack.

    Returns one entry per requirement — met or not — so callers can render
    a full checklist (persistence) or filter to just the gaps (reporting).

    Only ``skill``-kind requirements are normalized and matched against the
    profile's tech stack. Non-skill requirements (degrees, experience, soft
    skills) can't be matched against a tech-stack token, so they pass through
    with ``met=True`` — never a gap — carrying their kind for display. Callers
    that compute gaps must also exclude non-skill kinds so this sentinel can't
    silently flip; see ``get_run_details``.
    """
    profile_skills = {
        normalize_skill(skill.name)
        for category in profile.tech_stack
        for skill in category.skills
    }

    def _check(item, requirement_level: str) -> SkillGap:
        if item.kind == "skill":
            met = normalize_skill(item.name) in profile_skills
        else:
            met = True
        return SkillGap(
            skill=item.name,
            requirement_level=requirement_level,
            met=met,
            kind=item.kind,
        )

    checks: list[SkillGap] = []
    for item in requirements.must_have:
        checks.append(_check(item, "must_have"))
    for item in requirements.nice_to_have:
        checks.append(_check(item, "nice_to_have"))
    return checks
