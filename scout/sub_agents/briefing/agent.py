from __future__ import annotations

from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm

from scout.config import Settings
from scout.config import settings as default_settings
from scout.prompts import build_briefing_instruction
from scout.shared.schemas import BriefingProse, MatchResult


def build_briefing_agent(
    top_matches: list[MatchResult], settings: Settings | None = None
) -> LlmAgent:
    active_settings = settings or default_settings
    return LlmAgent(
        name="briefing",
        model=LiteLlm(
            model=active_settings.deepseek_model,
            temperature=0.3,
            response_format={"type": "json_object"},
        ),
        instruction=build_briefing_instruction(active_settings, top_matches),
        output_schema=BriefingProse,
    )
