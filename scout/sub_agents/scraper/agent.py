from __future__ import annotations

from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm

from scout.config import Settings
from scout.config import settings as default_settings
from scout.prompts import build_scraper_instruction
from scout.shared.schemas import Listing
from scout.sub_agents.scraper.tools import build_scraper_toolset


def build_scraper_agent(settings: Settings | None = None) -> LlmAgent:
    active_settings = settings or default_settings
    return LlmAgent(
        name="scraper",
        model=LiteLlm(model=active_settings.deepseek_model),
        instruction=build_scraper_instruction(active_settings),
        tools=[build_scraper_toolset(active_settings)],
        output_schema=list[Listing],
    )


root_agent = build_scraper_agent()
