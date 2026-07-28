from __future__ import annotations

import asyncio
import logging
import sys

from scout.sub_agents.coach.link_health import run_link_health

logger = logging.getLogger("scout.coach_link_health")


async def run_once() -> None:
    summary = await run_link_health()
    logger.info(
        "Coach link health: %s checked, %s verified, %s recovered, "
        "%s newly dead, %s still dead, %s failing",
        summary.checked,
        summary.verified,
        summary.recovered,
        summary.newly_dead,
        summary.still_dead,
        summary.failing,
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(run_once())
    except Exception:
        logger.exception("coach link-health run failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
