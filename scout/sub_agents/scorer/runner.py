from __future__ import annotations

from google.adk.agents import LlmAgent

from scout.config import Settings
from scout.config import settings as default_settings
from scout.shared.adk_runner import run_single_turn
from scout.shared.parsing import strip_code_fence
from scout.shared.schemas import Listing, ListingScore, ListingScoreBatch
from scout.sub_agents.scorer.agent import build_scorer_agent

_APP_NAME = "scorer"


def parse_scores(raw_text: str) -> list[ListingScore]:
    return ListingScoreBatch.model_validate_json(strip_code_fence(raw_text)).scores


async def _run_scorer_agent(agent: LlmAgent) -> str:
    final_text = await run_single_turn(agent, _APP_NAME, "Score these listings.")
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
