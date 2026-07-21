from __future__ import annotations

from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm

from scout.config import Settings
from scout.config import settings as default_settings
from scout.prompts import build_requirements_instruction
from scout.shared.schemas import Listing, ListingRequirementsBatch


def build_requirements_agent(
    listings: list[Listing], settings: Settings | None = None
) -> LlmAgent:
    active_settings = settings or default_settings
    return LlmAgent(
        name="advisor",
        model=LiteLlm(
            model=active_settings.deepseek_model,
            temperature=0,
            response_format={"type": "json_object"},
        ),
        instruction=build_requirements_instruction(active_settings, listings),
        output_schema=ListingRequirementsBatch,
    )
