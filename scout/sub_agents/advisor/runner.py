from __future__ import annotations

from scout.config import Settings
from scout.config import settings as default_settings
from scout.prompts import build_requirements_instruction
from scout.shared.batching import batches, run_batches
from scout.shared.llm import complete_json
from scout.shared.schemas import (
    Listing,
    ListingRequirements,
    ListingRequirementsBatch,
)


async def run_requirements_extraction(
    listings: list[Listing], settings: Settings | None = None
) -> list[ListingRequirements]:
    """Extract stated requirements for every listing, batched.

    Deliberately profile-blind: ``build_requirements_instruction`` never
    renders the profile, so a requirement can't be softened or dropped
    because the student doesn't meet it. See the spec's Amendment.
    """
    active_settings = settings or default_settings
    if not listings:
        return []

    async def _call(batch: list[Listing]) -> list[ListingRequirements]:
        result = await complete_json(
            build_requirements_instruction(active_settings, batch),
            ListingRequirementsBatch,
            active_settings,
        )
        return result.requirements

    return await run_batches(
        batches(listings, active_settings.requirements_batch_size),
        _call,
        concurrency=active_settings.model_concurrency,
        label="requirements",
    )
