from __future__ import annotations

from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner
from google.genai import types as genai_types

from scout.config import Settings
from scout.config import settings as default_settings
from scout.shared.parsing import strip_code_fence
from scout.shared.schemas import Listing, ListingScore, ListingScoreBatch
from scout.sub_agents.scorer.agent import build_scorer_agent

_APP_NAME = "scorer"
_USER_ID = "scorer"
_SESSION_ID = "scorer"


def parse_scores(raw_text: str) -> list[ListingScore]:
    return ListingScoreBatch.model_validate_json(strip_code_fence(raw_text)).scores


async def _run_scorer_agent(agent: LlmAgent) -> str:
    runner = InMemoryRunner(agent=agent, app_name=_APP_NAME)
    await runner.session_service.create_session(
        app_name=_APP_NAME, user_id=_USER_ID, session_id=_SESSION_ID
    )
    message = genai_types.Content(
        role="user", parts=[genai_types.Part(text="Score these listings.")]
    )
    final_text: str | None = None
    async for event in runner.run_async(
        user_id=_USER_ID, session_id=_SESSION_ID, new_message=message
    ):
        if event.is_final_response() and event.content and event.content.parts:
            final_text = event.content.parts[0].text
    if final_text is None:
        raise ValueError("scorer agent produced no final response")
    return final_text


async def run_scorer(
    listings: list[Listing], settings: Settings | None = None
) -> list[ListingScore]:
    active_settings = settings or default_settings
    agent = build_scorer_agent(listings, active_settings)
    raw_text = await _run_scorer_agent(agent)
    return parse_scores(raw_text)
