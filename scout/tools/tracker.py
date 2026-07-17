from __future__ import annotations

import asyncpg

from scout.config import Settings
from scout.shared.db import apply_schema, create_pool, upsert_listing
from scout.shared.schemas import Listing


async def track_listings(
    listings: list[Listing],
    pool: asyncpg.Pool | None = None,
    settings: Settings | None = None,
) -> list[Listing]:
    owns_pool = pool is None
    active_pool = pool if pool is not None else await create_pool(settings)
    if owns_pool:
        await apply_schema(active_pool)

    relevant: list[Listing] = []
    async with active_pool.acquire() as conn:
        for listing in listings:
            classification = await upsert_listing(conn, listing)
            if classification in ("new", "changed"):
                relevant.append(listing)

    if owns_pool:
        await active_pool.close()
    return relevant
