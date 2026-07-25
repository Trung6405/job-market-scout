from __future__ import annotations

from scout.config import Settings
from scout.prompts import build_coach_tagging_instruction
from scout.shared.llm import complete_json
from scout.shared.schemas import ResourceTags


async def tag_readme(readme_text: str, settings: Settings) -> ResourceTags:
    return await complete_json(
        build_coach_tagging_instruction(readme_text),
        ResourceTags,
        settings,
    )
