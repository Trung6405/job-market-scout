from __future__ import annotations

from pathlib import Path

from scout.shared.schemas import Profile


def load_profile(path: str | Path) -> Profile:
    profile_path = Path(path)
    if not profile_path.is_file():
        raise FileNotFoundError(f"profile file not found: {profile_path}")
    return Profile.model_validate_json(profile_path.read_text(encoding="utf-8"))


_SKILL_LEVELS = {1: "beginner", 2: "basic", 3: "intermediate", 4: "advanced", 5: "expert"}


def render_profile_text(profile: Profile) -> str:
    """Render a Profile into a readable resume-like block for LLM prompts."""
    lines: list[str] = [
        f"Name: {profile.name}",
        f"Target role: {profile.target_role}",
    ]
    if profile.target_locations:
        lines.append(f"Target locations: {', '.join(profile.target_locations)}")
    lines.append(f"Education: {profile.background.education}")
    lines.append(f"Experience: {profile.background.experience}")

    lines += ["", "Skills:"]
    for category in profile.tech_stack:
        skills = ", ".join(
            f"{s.name} ({_SKILL_LEVELS[s.proficiency]})" for s in category.skills
        )
        lines.append(f"- {category.category}: {skills}")

    if profile.domain_knowledge:
        lines += ["", "Domain knowledge:"]
        for dk in profile.domain_knowledge:
            lines.append(f"- {dk.name} ({dk.level}): {dk.description}")

    if profile.projects:
        lines += ["", "Projects:"]
        for project in profile.projects:
            tags = f" [{', '.join(project.tags)}]" if project.tags else ""
            lines.append(f"- {project.title}: {project.description}{tags}")

    return "\n".join(lines)
