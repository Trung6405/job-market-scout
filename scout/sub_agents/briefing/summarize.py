from __future__ import annotations

from scout.config import Settings
from scout.config import settings as default_settings
from scout.prompts import build_briefing_instruction
from scout.shared.llm import complete_json
from scout.shared.parsing import strip_code_fence
from scout.shared.schemas import BriefingProse, MatchResult


def parse_briefing_prose(raw_text: str) -> BriefingProse:
    return BriefingProse.model_validate_json(strip_code_fence(raw_text))


async def summarize_matches(
    top_matches: list[MatchResult], settings: Settings | None = None
) -> BriefingProse:
    active_settings = settings or default_settings
    return await complete_json(
        build_briefing_instruction(active_settings, top_matches),
        BriefingProse,
        active_settings,
        temperature=0.3,
    )
