from __future__ import annotations

from datetime import datetime, timezone

import asyncpg
import pytest
import pytest_asyncio

from scout.config import Settings
from scout.shared.db import apply_schema
from scout.shared.schemas import Listing, MatchResult

# Tests must never run against the dev/prod database (Settings().database_url) —
# a TRUNCATE here would wipe real run history. Use a dedicated database on the
# same Postgres server instead.
_TEST_DB_NAME = "scout_test"


def _test_database_url(dev_database_url: str) -> str:
    base = dev_database_url.rsplit("/", 1)[0]
    return f"{base}/{_TEST_DB_NAME}"


async def _ensure_test_database(dev_database_url: str) -> None:
    conn = await asyncpg.connect(dsn=dev_database_url, timeout=2)
    try:
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", _TEST_DB_NAME
        )
        if not exists:
            await conn.execute(f'CREATE DATABASE "{_TEST_DB_NAME}"')
    finally:
        await conn.close()


@pytest_asyncio.fixture
async def db_pool():
    dev_database_url = Settings().database_url
    try:
        await _ensure_test_database(dev_database_url)
        pool = await asyncpg.create_pool(
            dsn=_test_database_url(dev_database_url), timeout=2
        )
    except (OSError, asyncpg.PostgresError) as exc:
        pytest.skip(f"Postgres unreachable: {exc}")
    await apply_schema(pool)
    async with pool.acquire() as conn:
        await conn.execute("TRUNCATE TABLE run_listings, runs, listings CASCADE")
    yield pool
    await pool.close()


@pytest.fixture
def listing_factory():
    def _make(**overrides) -> Listing:
        defaults = dict(
            source="indeed",
            external_id="ext-1",
            title="Backend Engineer",
            company="Acme Corp",
            location="Melbourne VIC",
            is_remote=False,
            url="https://example.com/job/1",
            description="We need Python and PostgreSQL.",
            salary_min=None,
            salary_max=None,
            date_posted=None,
            scraped_at=datetime(2026, 7, 24, tzinfo=timezone.utc),
        )
        return Listing(**{**defaults, **overrides})

    return _make


@pytest.fixture
def match_factory(listing_factory):
    def _make(
        listing: Listing | None = None, score: int = 70, reasoning: str = "ok"
    ) -> MatchResult:
        return MatchResult(
            listing=listing if listing is not None else listing_factory(),
            score=score,
            reasoning=reasoning,
        )

    return _make
