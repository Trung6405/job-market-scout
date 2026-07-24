from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")
R = TypeVar("R")


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
    """Run ``call`` over each batch concurrently, tolerating failure.

    On a batch's first failure the batch is split in half and each half is
    retried once; a half that still fails is skipped with a warning. A
    single-item batch that fails is skipped directly — retrying it
    unchanged at temperature 0 would just reproduce the same truncation.
    A skipped batch costs its listings, not the whole day's run — and
    because the Scorer and Extractor are separate stages, a skipped
    extraction batch costs gaps while the listing keeps its score.
    """
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def _guarded(batch: list[T]) -> list[R]:
        async with semaphore:
            return await call(batch)

    async def _one(batch: list[T]) -> list[R]:
        try:
            return await _guarded(batch)
        except Exception as first_exc:
            if len(batch) <= 1:
                logger.warning(
                    "%s batch of %d item(s) failed, skipping: %s",
                    label,
                    len(batch),
                    first_exc,
                )
                return []
            mid = len(batch) // 2
            logger.info(
                "%s batch of %d failed, splitting and retrying each half: %s",
                label,
                len(batch),
                first_exc,
            )
            results: list[R] = []
            for half in (batch[:mid], batch[mid:]):
                try:
                    results.extend(await _guarded(half))
                except Exception as exc:
                    logger.warning(
                        "%s retry half of %d item(s) failed, skipping: %s",
                        label,
                        len(half),
                        exc,
                    )
            return results

    results = await asyncio.gather(*(_one(batch) for batch in batch_list))
    return [item for batch_result in results for item in batch_result]
