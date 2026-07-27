from __future__ import annotations

from datetime import date

import pytest

from scout.shared.db import record_listing_tips, record_run_listings, start_run, upsert_listing
from scout.shared.schemas import GroundedTip

pytestmark = pytest.mark.asyncio


async def _seed_run(conn, matches) -> int:
    """Create one run holding the given matches. Returns the run id.

    Goes through ``upsert_listing`` / ``record_run_listings`` rather than
    raw INSERTs so these tests don't hard-code the run_listings column
    list — note ``upsert_listing`` returns a 'new'/'changed'/'unchanged'
    status, not an id.
    """
    run_id = await start_run(conn, date(2026, 7, 27))
    for match in matches:
        await upsert_listing(conn, match.listing)
    await record_run_listings(conn, run_id, [(m, "competitive") for m in matches])
    return run_id


async def _run_listing_id(conn, run_id: int, external_id: str) -> int:
    return await conn.fetchval(
        """
        SELECT run_listings.id
        FROM run_listings
        JOIN listings ON listings.id = run_listings.listing_id
        WHERE run_listings.run_id = $1 AND listings.external_id = $2
        """,
        run_id,
        external_id,
    )


async def test_listing_tips_row_round_trips(db_pool, match_factory, listing_factory):
    async with db_pool.acquire() as conn:
        match = match_factory(listing=listing_factory(external_id="tips-1"))
        run_id = await _seed_run(conn, [match])
        run_listing_id = await _run_listing_id(conn, run_id, "tips-1")
        await conn.execute(
            """
            INSERT INTO listing_tips (run_listing_id, gap_skill, tip, cited_urls)
            VALUES ($1, $2, $3, $4)
            """,
            run_listing_id,
            "Kubernetes",
            "Work through kubernetes/examples.",
            ["https://github.com/k/examples"],
        )
        row = await conn.fetchrow(
            "SELECT gap_skill, tip, cited_urls FROM listing_tips WHERE run_listing_id = $1",
            run_listing_id,
        )
        assert row["gap_skill"] == "Kubernetes"
        assert list(row["cited_urls"]) == ["https://github.com/k/examples"]


async def test_listing_tips_cascade_with_run_listing(
    db_pool, match_factory, listing_factory
):
    async with db_pool.acquire() as conn:
        match = match_factory(listing=listing_factory(external_id="tips-1"))
        run_id = await _seed_run(conn, [match])
        run_listing_id = await _run_listing_id(conn, run_id, "tips-1")
        await conn.execute(
            """
            INSERT INTO listing_tips (run_listing_id, gap_skill, tip, cited_urls)
            VALUES ($1, 'Kubernetes', 'tip', ARRAY['https://github.com/k/examples'])
            """,
            run_listing_id,
        )
        await conn.execute("DELETE FROM run_listings WHERE id = $1", run_listing_id)
        remaining = await conn.fetchval(
            "SELECT count(*) FROM listing_tips WHERE run_listing_id = $1",
            run_listing_id,
        )
        assert remaining == 0


async def test_record_listing_tips_writes_one_row_per_tip(
    db_pool, listing_factory, match_factory
):
    async with db_pool.acquire() as conn:
        match = match_factory(listing=listing_factory(external_id="tips-1"))
        run_id = await _seed_run(conn, [match])

        await record_listing_tips(
            conn,
            run_id,
            [
                (
                    match,
                    [
                        GroundedTip(
                            gap_skill="Kubernetes",
                            tip="Start with kubernetes/examples.",
                            cited_urls=["https://github.com/k/examples"],
                        ),
                        GroundedTip(
                            gap_skill="Terraform",
                            tip="Read the module registry docs.",
                            cited_urls=["https://github.com/t/modules"],
                        ),
                    ],
                )
            ],
        )

        rows = await conn.fetch(
            "SELECT gap_skill, cited_urls FROM listing_tips ORDER BY gap_skill"
        )
        assert [row["gap_skill"] for row in rows] == ["Kubernetes", "Terraform"]
        assert list(rows[0]["cited_urls"]) == ["https://github.com/k/examples"]


async def test_record_listing_tips_replaces_previous_tips(
    db_pool, listing_factory, match_factory
):
    async with db_pool.acquire() as conn:
        match = match_factory(listing=listing_factory(external_id="tips-1"))
        run_id = await _seed_run(conn, [match])
        first = [
            GroundedTip(gap_skill="Kubernetes", tip="old", cited_urls=["https://a/b"])
        ]
        second = [
            GroundedTip(gap_skill="Kubernetes", tip="new", cited_urls=["https://a/b"])
        ]

        await record_listing_tips(conn, run_id, [(match, first)])
        await record_listing_tips(conn, run_id, [(match, second)])

        rows = await conn.fetch("SELECT tip FROM listing_tips")
        assert [row["tip"] for row in rows] == ["new"]
