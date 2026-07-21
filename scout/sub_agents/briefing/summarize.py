from __future__ import annotations

from google.adk.agents import LlmAgent

from scout.config import Settings
from scout.config import settings as default_settings
from scout.shared.adk_runner import run_single_turn
from scout.shared.parsing import strip_code_fence
from scout.shared.schemas import BriefingProse, MatchResult
from scout.sub_agents.briefing.agent import build_briefing_agent

_APP_NAME = "briefing"


def parse_briefing_prose(raw_text: str) -> BriefingProse:
    return BriefingProse.model_validate_json(strip_code_fence(raw_text))


async def _run_briefing_agent(agent: LlmAgent) -> str:
    final_text = await run_single_turn(agent, _APP_NAME, "Generate the briefing.")
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
