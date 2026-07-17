from __future__ import annotations

import pytest

from scout.shared.db import apply_schema


@pytest.mark.asyncio
async def test_apply_schema_is_idempotent(db_pool):
    await apply_schema(db_pool)
    await apply_schema(db_pool)

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT to_regclass('public.listings') AS table_name"
        )
    assert row["table_name"] == "listings"
