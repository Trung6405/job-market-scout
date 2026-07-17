from __future__ import annotations

from datetime import datetime, timezone

import pytest

from scout.shared.db import apply_schema, upsert_listing
from scout.shared.schemas import Listing


def _make_listing(**overrides) -> Listing:
    defaults = dict(
        source="linkedin",
        external_id="job-1",
        title="Backend Engineer",
        company="Acme",
        location="Remote",
        is_remote=True,
        url="https://example.com/jobs/1",
        description="Build things.",
        salary_min=100000.0,
        salary_max=150000.0,
        date_posted=datetime(2026, 7, 1, tzinfo=timezone.utc),
        scraped_at=datetime(2026, 7, 17, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return Listing(**defaults)


@pytest.mark.asyncio
async def test_apply_schema_is_idempotent(db_pool):
    await apply_schema(db_pool)
    await apply_schema(db_pool)

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT to_regclass('public.listings') AS table_name"
        )
    assert row["table_name"] == "listings"


@pytest.mark.asyncio
async def test_upsert_listing_new_returns_new(db_pool):
    async with db_pool.acquire() as conn:
        classification = await upsert_listing(conn, _make_listing())

    assert classification == "new"


@pytest.mark.asyncio
async def test_upsert_listing_unchanged_returns_unchanged(db_pool):
    listing = _make_listing()
    async with db_pool.acquire() as conn:
        await upsert_listing(conn, listing)
        classification = await upsert_listing(conn, listing)

    assert classification == "unchanged"


@pytest.mark.asyncio
async def test_upsert_listing_changed_returns_changed_and_updates_row(db_pool):
    listing = _make_listing()
    changed = _make_listing(title="Senior Backend Engineer")
    async with db_pool.acquire() as conn:
        await upsert_listing(conn, listing)
        classification = await upsert_listing(conn, changed)
        row = await conn.fetchrow(
            "SELECT title FROM listings WHERE source = $1 AND external_id = $2",
            listing.source,
            listing.external_id,
        )

    assert classification == "changed"
    assert row["title"] == "Senior Backend Engineer"


@pytest.mark.asyncio
async def test_upsert_listing_reopened_closed_listing_returns_changed(db_pool):
    listing = _make_listing()
    async with db_pool.acquire() as conn:
        await upsert_listing(conn, listing)
        await conn.execute(
            "UPDATE listings SET status = 'closed' WHERE source = $1 AND external_id = $2",
            listing.source,
            listing.external_id,
        )
        classification = await upsert_listing(conn, listing)

    assert classification == "changed"
