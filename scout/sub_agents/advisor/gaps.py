from __future__ import annotations

import re

from scout.shared.schemas import ListingRequirements, Profile, SkillGap

# Known equivalences that a substring/punctuation strip alone can't collapse.
# Keys and values are in normalized (lowercase, alphanumeric-only) form.
_SKILL_ALIASES = {
    "js": "javascript",
    "ts": "typescript",
    "postgres": "postgresql",
    "postgre": "postgresql",
    "k8s": "kubernetes",
    "golang": "go",
}

# Framework version suffixes stripped before comparison ("React.js" -> "react").
_VERSION_SUFFIXES = (".js", ".ts")


def normalize_skill(skill: str) -> str:
    """Canonicalize a skill name so common variants compare equal.

    Lowercases, strips a framework version suffix (``.js``/``.ts``), removes
    remaining punctuation/whitespace, then folds a small set of known aliases
    (``postgres`` -> ``postgresql``). Deterministic and side-effect free — it
    is the guarantee behind gap matching; the extraction prompt's canonical
    naming is a best-effort improvement on top.
    """
    value = skill.strip().lower()
    for suffix in _VERSION_SUFFIXES:
        if value.endswith(suffix) and len(value) > len(suffix):
            value = value[: -len(suffix)]
            break
    value = re.sub(r"[^a-z0-9]", "", value)
    return _SKILL_ALIASES.get(value, value)


def evaluate_requirements(
    requirements: ListingRequirements, profile: Profile
) -> list[SkillGap]:
    """Check every stated requirement against a profile's tech stack.

    Returns one entry per requirement — met or not — so callers can render
    a full checklist (persistence) or filter to just the gaps (reporting).
    """
    profile_skills = {
        normalize_skill(skill.name)
        for category in profile.tech_stack
        for skill in category.skills
    }

    checks: list[SkillGap] = []
    for skill in requirements.must_have:
        checks.append(
            SkillGap(
                skill=skill,
                requirement_level="must_have",
                met=normalize_skill(skill) in profile_skills,
            )
        )
    for skill in requirements.nice_to_have:
        checks.append(
            SkillGap(
                skill=skill,
                requirement_level="nice_to_have",
                met=normalize_skill(skill) in profile_skills,
            )
        )
    return checks
