from __future__ import annotations

from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner
from google.genai import types as genai_types
from pydantic import TypeAdapter

from scout.config import Settings
from scout.config import settings as default_settings
from scout.shared.parsing import strip_code_fence
from scout.shared.schemas import Listing
from scout.sub_agents.scraper.agent import build_scraper_agent

_LISTING_LIST_ADAPTER = TypeAdapter(list[Listing])
_APP_NAME = "scraper"
_USER_ID = "scraper"
_SESSION_ID = "scraper"


def parse_listings(raw_text: str) -> list[Listing]:
    return _LISTING_LIST_ADAPTER.validate_json(strip_code_fence(raw_text))


async def _run_scraper_agent(agent: LlmAgent) -> str:
    runner = InMemoryRunner(agent=agent, app_name=_APP_NAME)
    await runner.session_service.create_session(
        app_name=_APP_NAME, user_id=_USER_ID, session_id=_SESSION_ID
    )
    message = genai_types.Content(
        role="user", parts=[genai_types.Part(text="Find matching listings.")]
    )
    final_text: str | None = None
    async for event in runner.run_async(
        user_id=_USER_ID, session_id=_SESSION_ID, new_message=message
    ):
        if event.is_final_response() and event.content and event.content.parts:
            final_text = event.content.parts[0].text
    if final_text is None:
        raise ValueError("scraper agent produced no final response")
    return final_text


async def run_scraper(settings: Settings | None = None) -> list[Listing]:
    active_settings = settings or default_settings
    agent = build_scraper_agent(active_settings)
    raw_text = await _run_scraper_agent(agent)
    return parse_listings(raw_text)
