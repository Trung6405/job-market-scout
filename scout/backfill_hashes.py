"""Recompute every stored ``content_hash`` under the current definition.

Run once, before the first pipeline run on code that narrowed the hash.
Without it, every listing's stored hash disagrees with its freshly computed
one, so the next run marks the entire table ``changed`` and re-analyses it
at full cost:

    python -m scout.backfill_hashes

Idempotent and re-runnable: rows already holding the correct hash are left
alone and not counted.
"""

from __future__ import annotations

import asyncio
import logging
import sys

import asyncpg

from scout.config import settings as default_settings
from scout.shared.db import _content_hash, create_pool
from scout.shared.schemas import Listing

logger = logging.getLogger("scout.backfill_hashes")


async def backfill_content_hashes(conn: asyncpg.Connection) -> int:
    """Rewrite stale hashes in place. Returns the number of rows changed."""
    rows = await conn.fetch(
        """
        SELECT source, external_id, title, company, location, url, description,
               is_remote, salary_min, salary_max, date_posted, scraped_at,
               content_hash
        FROM listings
        """
    )
    updated = 0
    for row in rows:
        data = dict(row)
        stored_hash = data.pop("content_hash")
        expected = _content_hash(Listing(**data))
        if expected == stored_hash:
            continue
        await conn.execute(
            "UPDATE listings SET content_hash = $3 WHERE source = $1 AND external_id = $2",
            data["source"],
            data["external_id"],
            expected,
        )
        updated += 1
    return updated


async def run_backfill() -> None:
    pool = await create_pool(default_settings)
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                updated = await backfill_content_hashes(conn)
        logger.info("backfilled %d listing hash(es)", updated)
    finally:
        await pool.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(run_backfill())
    except Exception:
        logger.exception("backfill failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
