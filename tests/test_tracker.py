from __future__ import annotations

import pytest

from scout.shared.db import upsert_listing
from scout.tools.tracker import track_listings
from tests.test_db import _make_listing


@pytest.mark.asyncio
async def test_track_listings_returns_only_new_and_changed(db_pool):
    existing = _make_listing(source="linkedin", external_id="job-existing")
    async with db_pool.acquire() as conn:
        await upsert_listing(conn, existing)

    changed = _make_listing(
        source="linkedin", external_id="job-existing", title="Updated Title"
    )
    unchanged = _make_listing(source="linkedin", external_id="job-unchanged-src")
    async with db_pool.acquire() as conn:
        await upsert_listing(conn, unchanged)
    new = _make_listing(source="linkedin", external_id="job-new")

    result = await track_listings([changed, unchanged, new], pool=db_pool)

    assert result == [changed, new]

    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT external_id, title FROM listings ORDER BY external_id"
        )
    stored = {row["external_id"]: row["title"] for row in rows}
    assert stored["job-existing"] == "Updated Title"
    assert stored["job-new"] == new.title


@pytest.mark.asyncio
async def test_track_listings_closes_previously_open_listings_absent_from_batch(
    db_pool,
):
    stale = _make_listing(source="linkedin", external_id="job-stale")
    async with db_pool.acquire() as conn:
        await upsert_listing(conn, stale)

    current = _make_listing(source="linkedin", external_id="job-current")

    await track_listings([current], pool=db_pool)

    async with db_pool.acquire() as conn:
        stale_row = await conn.fetchrow(
            "SELECT status FROM listings WHERE external_id = $1", "job-stale"
        )
        current_row = await conn.fetchrow(
            "SELECT status FROM listings WHERE external_id = $1", "job-current"
        )

    assert stale_row["status"] == "closed"
    assert current_row["status"] == "open"
