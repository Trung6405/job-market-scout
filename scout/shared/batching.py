from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")
R = TypeVar("R")

_MAX_ATTEMPTS = 2


def batches(items: list[T], size: int) -> list[list[T]]:
    """Split items into consecutive chunks of at most ``size``."""
    step = max(1, size)
    return [items[i : i + step] for i in range(0, len(items), step)]


async def run_batches(
    batch_list: list[list[T]],
    call: Callable[[list[T]], Awaitable[list[R]]],
    *,
    concurrency: int,
    label: str,
) -> list[R]:
    """Run ``call`` over each batch concurrently, tolerating batch failure.

    A batch is retried once, then skipped with a warning. One truncated or
    malformed response should cost that batch's listings, not the whole
    day's run — and because the Scorer and Extractor are separate stages, a
    skipped extraction batch costs gaps while the listing keeps its score.
    """
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def _one(batch: list[T]) -> list[R]:
        async with semaphore:
            for attempt in range(1, _MAX_ATTEMPTS + 1):
                try:
                    return await call(batch)
                except Exception as exc:
                    if attempt == _MAX_ATTEMPTS:
                        logger.warning(
                            "%s batch failed after %d attempt(s), skipping %d item(s): %s",
                            label,
                            attempt,
                            len(batch),
                            exc,
                        )
                        return []
                    logger.info(
                        "%s batch attempt %d failed, retrying: %s", label, attempt, exc
                    )
            return []

    results = await asyncio.gather(*(_one(batch) for batch in batch_list))
    return [item for batch_result in results for item in batch_result]
