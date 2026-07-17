from __future__ import annotations

import asyncpg
import pytest
import pytest_asyncio

from scout.shared.db import apply_schema


@pytest_asyncio.fixture
async def db_pool():
    try:
        pool = await asyncpg.create_pool(
            dsn="postgresql://scout:scout@localhost:5433/scout", timeout=2
        )
    except (OSError, asyncpg.PostgresError) as exc:
        pytest.skip(f"Postgres unreachable: {exc}")
    await apply_schema(pool)
    async with pool.acquire() as conn:
        await conn.execute("TRUNCATE TABLE listings")
    yield pool
    await pool.close()
