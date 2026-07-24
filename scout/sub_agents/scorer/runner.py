from __future__ import annotations

from scout.config import Settings
from scout.config import settings as default_settings
from scout.prompts import build_scorer_instruction
from scout.shared.batching import batches, run_batches
from scout.shared.llm import complete_json
from scout.shared.schemas import Listing, ListingScore, ListingScoreBatch


async def run_scorer(
    listings: list[Listing], settings: Settings | None = None
) -> list[ListingScore]:
    """Score every listing, batched.

    Batched for the same reason extraction is: one response must cover its
    whole batch, and the model caps output tokens. The Scorer previously
    issued a single call for the entire run — the shape that truncated the
    Advisor's output and aborted a run in July.
    """
    active_settings = settings or default_settings
    if not listings:
        return []

    async def _call(batch: list[Listing]) -> list[ListingScore]:
        result = await complete_json(
            build_scorer_instruction(active_settings, batch),
            ListingScoreBatch,
            active_settings,
        )
        return result.scores

    return await run_batches(
        batches(listings, active_settings.scorer_batch_size),
        _call,
        concurrency=active_settings.model_concurrency,
        label="scorer",
    )
