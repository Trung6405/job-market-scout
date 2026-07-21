from __future__ import annotations

from datetime import datetime, timezone

import pytest

from scout.shared.db import apply_schema, close_stale_listings, upsert_listing
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


@pytest.mark.asyncio
async def test_close_stale_listings_closes_unseen_and_keeps_seen_open(db_pool):
    seen = _make_listing(source="linkedin", external_id="job-seen")
    stale = _make_listing(source="linkedin", external_id="job-stale")
    async with db_pool.acquire() as conn:
        await upsert_listing(conn, seen)
        await upsert_listing(conn, stale)

        closed_ids = await close_stale_listings(conn, [(seen.source, seen.external_id)])

        seen_row = await conn.fetchrow(
            "SELECT status FROM listings WHERE external_id = $1", seen.external_id
        )
        stale_row = await conn.fetchrow(
            "SELECT status, closed_at FROM listings WHERE external_id = $1",
            stale.external_id,
        )

    assert closed_ids == ["job-stale"]
    assert seen_row["status"] == "open"
    assert stale_row["status"] == "closed"
    assert stale_row["closed_at"] is not None


@pytest.mark.asyncio
async def test_apply_schema_creates_runs_table(db_pool):
    """Verify that apply_schema creates the runs table with expected columns and constraints."""
    async with db_pool.acquire() as conn:
        # Verify table exists
        row = await conn.fetchrow(
            "SELECT to_regclass('public.runs') AS table_name"
        )
        assert row["table_name"] == "runs"

        # Verify columns exist with correct types
        columns = await conn.fetch(
            """
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_name = 'runs'
            ORDER BY column_name
            """
        )
        column_map = {col["column_name"]: col for col in columns}

        assert "id" in column_map
        assert column_map["id"]["data_type"] == "bigint"
        assert column_map["id"]["is_nullable"] == "NO"

        assert "run_date" in column_map
        assert column_map["run_date"]["data_type"] == "date"
        assert column_map["run_date"]["is_nullable"] == "NO"

        assert "started_at" in column_map
        assert column_map["started_at"]["data_type"] == "timestamp with time zone"
        assert column_map["started_at"]["is_nullable"] == "NO"

        assert "finished_at" in column_map
        assert column_map["finished_at"]["is_nullable"] == "YES"

        assert "listings_scraped" in column_map
        assert column_map["listings_scraped"]["data_type"] == "integer"
        assert column_map["listings_scraped"]["is_nullable"] == "NO"

        assert "listings_scored" in column_map
        assert column_map["listings_scored"]["data_type"] == "integer"
        assert column_map["listings_scored"]["is_nullable"] == "NO"

        # Verify UNIQUE constraint on run_date
        constraints = await conn.fetch(
            """
            SELECT constraint_name, constraint_type
            FROM information_schema.table_constraints
            WHERE table_name = 'runs' AND constraint_type = 'UNIQUE'
            """
        )
        constraint_names = [c["constraint_name"] for c in constraints]
        assert any("run_date" in name for name in constraint_names)


@pytest.mark.asyncio
async def test_apply_schema_creates_run_listings_table(db_pool):
    """Verify that apply_schema creates the run_listings table with expected columns and constraints."""
    async with db_pool.acquire() as conn:
        # Verify table exists
        row = await conn.fetchrow(
            "SELECT to_regclass('public.run_listings') AS table_name"
        )
        assert row["table_name"] == "run_listings"

        # Verify columns exist with correct types
        columns = await conn.fetch(
            """
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_name = 'run_listings'
            ORDER BY column_name
            """
        )
        column_map = {col["column_name"]: col for col in columns}

        assert "id" in column_map
        assert column_map["id"]["data_type"] == "bigint"

        assert "run_id" in column_map
        assert column_map["run_id"]["data_type"] == "bigint"
        assert column_map["run_id"]["is_nullable"] == "NO"

        assert "listing_id" in column_map
        assert column_map["listing_id"]["data_type"] == "bigint"
        assert column_map["listing_id"]["is_nullable"] == "NO"

        assert "score" in column_map
        assert column_map["score"]["data_type"] == "integer"
        assert column_map["score"]["is_nullable"] == "NO"

        assert "reasoning" in column_map
        assert column_map["reasoning"]["is_nullable"] == "NO"

        # Verify CHECK constraint on score (0-100)
        constraints = await conn.fetch(
            """
            SELECT constraint_name, constraint_type
            FROM information_schema.table_constraints
            WHERE table_name = 'run_listings' AND constraint_type = 'CHECK'
            """
        )
        assert len(constraints) > 0

        # Verify UNIQUE constraint on (run_id, listing_id)
        unique_constraints = await conn.fetch(
            """
            SELECT constraint_name
            FROM information_schema.table_constraints
            WHERE table_name = 'run_listings' AND constraint_type = 'UNIQUE'
            """
        )
        assert len(unique_constraints) > 0

        # Verify FOREIGN KEY constraints
        fk_constraints = await conn.fetch(
            """
            SELECT constraint_name
            FROM information_schema.table_constraints
            WHERE table_name = 'run_listings' AND constraint_type = 'FOREIGN KEY'
            """
        )
        assert len(fk_constraints) >= 2  # Should have FK to runs and listings


@pytest.mark.asyncio
async def test_run_listings_score_constraint_enforced(db_pool):
    """Verify that score CHECK constraint is enforced."""
    listing = _make_listing()
    async with db_pool.acquire() as conn:
        # Insert a listing first
        await upsert_listing(conn, listing)

        # Insert a run
        run_id = await conn.fetchval(
            """
            INSERT INTO runs (run_date)
            VALUES ($1)
            RETURNING id
            """,
            datetime.now().date(),
        )

        # Try to insert a score outside 0-100 range (should fail)
        with pytest.raises(Exception):  # Should raise constraint violation
            await conn.execute(
                """
                INSERT INTO run_listings (run_id, listing_id, score, reasoning)
                VALUES ($1, $2, $3, $4)
                """,
                run_id,
                (await conn.fetchval("SELECT id FROM listings LIMIT 1")),
                101,  # Invalid score > 100
                "Test reasoning",
            )
