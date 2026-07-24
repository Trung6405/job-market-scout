from __future__ import annotations

import asyncio
import logging
import sys

from scout.agent import ScoutPipelineAgent

logger = logging.getLogger("scout.main")


async def run_once() -> None:
    agent = ScoutPipelineAgent()
    async for event in agent.run():
        logger.info(event.text)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(run_once())
    except Exception:
        logger.exception("pipeline run failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
