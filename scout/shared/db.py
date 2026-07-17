from __future__ import annotations

from pathlib import Path

import asyncpg

from scout.config import Settings
from scout.config import settings as default_settings

_SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


async def create_pool(settings: Settings | None = None) -> asyncpg.Pool:
    active_settings = settings or default_settings
    return await asyncpg.create_pool(dsn=active_settings.database_url)


async def apply_schema(pool: asyncpg.Pool) -> None:
    schema_sql = _SCHEMA_PATH.read_text(encoding="utf-8")
    async with pool.acquire() as conn:
        await conn.execute(schema_sql)
