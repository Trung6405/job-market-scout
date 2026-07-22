from __future__ import annotations

import dataclasses

import asyncpg
import pytest

from scout.config import Settings
from scout.shared.db import upsert_listing
from scout.sub_agents.tracker.runner import track_listings
from tests.conftest import _test_database_url
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


@pytest.mark.asyncio
async def test_track_listings_closes_self_managed_pool(db_pool, monkeypatch):
    from scout.shared.db import create_pool as real_create_pool

    created_pools = []

    async def _tracking_create_pool(settings=None):
        created_pool = await real_create_pool(settings)
        created_pools.append(created_pool)
        return created_pool

    monkeypatch.setattr(
        "scout.sub_agents.tracker.runner.create_pool", _tracking_create_pool
    )

    # Must point at the isolated scout_test database, not the real
    # dev/prod one that create_pool(None) would otherwise resolve to.
    test_settings = dataclasses.replace(
        Settings(), database_url=_test_database_url(Settings().database_url)
    )

    await track_listings(
        [_make_listing(source="linkedin", external_id="job-self-managed")],
        settings=test_settings,
    )

    assert len(created_pools) == 1
    with pytest.raises(asyncpg.InterfaceError):
        await created_pools[0].acquire()


@pytest.mark.asyncio
async def test_track_listings_does_not_close_caller_supplied_pool(db_pool):
    await track_listings(
        [_make_listing(source="linkedin", external_id="job-caller-pool")],
        pool=db_pool,
    )

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT 1 AS ok")

    assert row["ok"] == 1


@pytest.mark.asyncio
async def test_track_listings_empty_batch_does_not_close_open_listings(db_pool):
    open_listing = _make_listing(source="linkedin", external_id="job-open")
    async with db_pool.acquire() as conn:
        await upsert_listing(conn, open_listing)

    result = await track_listings([], pool=db_pool)

    assert result == []

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT status FROM listings WHERE external_id = $1", "job-open"
        )
    assert row["status"] == "open"


@pytest.mark.asyncio
async def test_track_listings_rerun_after_partial_failure_is_safe(db_pool):
    listing_a = _make_listing(source="linkedin", external_id="job-a")
    listing_b = _make_listing(source="linkedin", external_id="job-b")

    async with db_pool.acquire() as conn:
        await upsert_listing(conn, listing_a)

    result = await track_listings([listing_a, listing_b], pool=db_pool)

    assert result == [listing_b]
