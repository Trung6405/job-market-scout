from __future__ import annotations

from google.adk.agents import LlmAgent

from scout.config import Settings
from scout.config import settings as default_settings
from scout.shared.adk_runner import run_single_turn
from scout.shared.parsing import strip_code_fence
from scout.shared.schemas import Listing, ListingRequirements, ListingRequirementsBatch
from scout.sub_agents.advisor.agent import build_requirements_agent

_APP_NAME = "advisor"


def parse_requirements(raw_text: str) -> list[ListingRequirements]:
    return ListingRequirementsBatch.model_validate_json(
        strip_code_fence(raw_text)
    ).requirements


async def _run_requirements_agent(agent: LlmAgent) -> str:
    final_text = await run_single_turn(
        agent, _APP_NAME, "Extract requirements from these listings."
    )
    if final_text is None:
        raise ValueError("advisor agent produced no final response")
    return final_text


def _batches(
    listings: list[Listing], batch_size: int
) -> list[list[Listing]]:
    size = max(1, batch_size)
    return [listings[i : i + size] for i in range(0, len(listings), size)]


async def run_requirements_extraction(
    listings: list[Listing], settings: Settings | None = None
) -> list[ListingRequirements]:
    """Extract requirements for every listing, one LLM call per batch.

    A single call must emit requirements for each listing it was given, and
    the model caps its output tokens. Asking for the whole day's listings at
    once overruns that cap and truncates the JSON mid-value, so the listings
    are split into batches small enough for each response to parse.
    """
    active_settings = settings or default_settings
    requirements: list[ListingRequirements] = []
    for batch in _batches(listings, active_settings.requirements_batch_size):
        agent = build_requirements_agent(batch, active_settings)
        raw_text = await _run_requirements_agent(agent)
        requirements.extend(parse_requirements(raw_text))
    return requirements
