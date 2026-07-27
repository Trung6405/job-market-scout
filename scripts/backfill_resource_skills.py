"""One-off backfill: canonicalize resources.skills[] for existing rows.

fix(coach) 6338556 started normalizing resources.skills[] on write
(scout.sub_agents.coach.runner._canonical_skills), but the aggregator's
per-URL dedup means an already-stored row is never re-tagged, so rows
inserted before that fix keep their raw, non-canonical skill strings
forever unless backfilled once. normalize_skill is a pure, local,
deterministic string transform (no LLM/network call), so this reprocesses
stored data directly rather than re-running the aggregator.

Usage: python -m scripts.backfill_resource_skills
"""

from __future__ import annotations

import asyncio
import logging

from scout.shared.db import create_pool
from scout.sub_agents.coach.runner import _canonical_skills

logger = logging.getLogger("scripts.backfill_resource_skills")


async def backfill() -> None:
    pool = await create_pool()
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT id, skills FROM resources")
            examined = len(rows)
            updated = 0
            for row in rows:
                canonical = _canonical_skills(row["skills"])
                if canonical != row["skills"]:
                    await conn.execute(
                        "UPDATE resources SET skills = $1 WHERE id = $2",
                        canonical,
                        row["id"],
                    )
                    updated += 1
        logger.info(
            "Backfill complete: %s row(s) examined, %s row(s) updated.",
            examined,
            updated,
        )
    finally:
        await pool.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(backfill())


if __name__ == "__main__":
    main()
