from __future__ import annotations

from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm

from scout.config import Settings
from scout.config import settings as default_settings
from scout.prompts import build_scorer_instruction
from scout.shared.schemas import Listing, ListingScore
from scout.sub_agents.scorer.filters import filter_listings


def build_scorer_agent(
    listings: list[Listing], settings: Settings | None = None
) -> LlmAgent:
    active_settings = settings or default_settings
    survivors = filter_listings(listings, active_settings)
    return LlmAgent(
        name="scorer",
        model=LiteLlm(model=active_settings.deepseek_model, temperature=0),
        instruction=build_scorer_instruction(active_settings, survivors),
        output_schema=list[ListingScore],
    )
