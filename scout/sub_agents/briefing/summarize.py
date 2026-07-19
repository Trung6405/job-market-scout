from __future__ import annotations

import json

from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner
from google.genai import types as genai_types

from scout.config import Settings
from scout.config import settings as default_settings
from scout.shared.schemas import BriefingProse, MatchResult
from scout.sub_agents.briefing.agent import build_briefing_agent

_APP_NAME = "briefing"
_USER_ID = "briefing"
_SESSION_ID = "briefing"


def parse_briefing_prose(raw_text: str) -> BriefingProse:
    return BriefingProse.model_validate(json.loads(raw_text))


async def _run_briefing_agent(agent: LlmAgent) -> str:
    runner = InMemoryRunner(agent=agent, app_name=_APP_NAME)
    await runner.session_service.create_session(
        app_name=_APP_NAME, user_id=_USER_ID, session_id=_SESSION_ID
    )
    message = genai_types.Content(
        role="user", parts=[genai_types.Part(text="Generate the briefing.")]
    )
    final_text: str | None = None
    async for event in runner.run_async(
        user_id=_USER_ID, session_id=_SESSION_ID, new_message=message
    ):
        if event.is_final_response() and event.content and event.content.parts:
            final_text = event.content.parts[0].text
    if final_text is None:
        raise ValueError("briefing agent produced no final response")
    return final_text


async def summarize_matches(
    top_matches: list[MatchResult], settings: Settings | None = None
) -> BriefingProse:
    active_settings = settings or default_settings
    agent = build_briefing_agent(top_matches, active_settings)
    raw_text = await _run_briefing_agent(agent)
    return parse_briefing_prose(raw_text)
