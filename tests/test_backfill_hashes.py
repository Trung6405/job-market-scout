from __future__ import annotations

from scout.backfill_hashes import backfill_content_hashes
from scout.shared.db import _content_hash, upsert_listing


async def test_backfill_rewrites_stale_hashes(db_pool, listing_factory):
    listing = listing_factory()
    async with db_pool.acquire() as conn:
        await upsert_listing(conn, listing)
        await conn.execute("UPDATE listings SET content_hash = 'stale'")

        updated = await backfill_content_hashes(conn)
        assert updated == 1

        stored = await conn.fetchval("SELECT content_hash FROM listings")
        assert stored == _content_hash(listing)


async def test_backfill_is_idempotent(db_pool, listing_factory):
    async with db_pool.acquire() as conn:
        await upsert_listing(conn, listing_factory())
        await conn.execute("UPDATE listings SET content_hash = 'stale'")
        first = await backfill_content_hashes(conn)
        second = await backfill_content_hashes(conn)
        assert first == 1
        assert second == 0
