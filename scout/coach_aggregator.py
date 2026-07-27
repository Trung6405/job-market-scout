from __future__ import annotations

import asyncio
import logging
import sys

from scout.sub_agents.coach.runner import run_coach_aggregator

logger = logging.getLogger("scout.coach_aggregator")


async def run_once() -> None:
    summary = await run_coach_aggregator()
    logger.info(
        "Coach aggregator: %s candidate(s) seen, %s inserted, %s duplicate(s)",
        summary.candidates_seen,
        summary.inserted,
        summary.duplicates,
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(run_once())
    except Exception:
        logger.exception("coach aggregator run failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
