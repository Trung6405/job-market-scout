from __future__ import annotations

from datetime import date, datetime, timezone

import asyncpg
import pytest

from scout.shared.db import (
    apply_schema,
    close_stale_listings,
    finish_run,
    get_listing_gaps,
    get_run_by_date,
    get_run_details,
    get_run_listings,
    list_runs,
    record_listing_gaps,
    record_run_listings,
    start_run,
    upsert_listing,
)
from scout.shared.schemas import Listing, MatchResult, SkillGap


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


def test_content_hash_ignores_description(listing_factory):
    from scout.shared.db import _content_hash

    original = listing_factory(description="We need Python.")
    reworded = listing_factory(description="We are looking for Python skills!")
    assert _content_hash(original) == _content_hash(reworded)


def test_content_hash_still_tracks_substantive_fields(listing_factory):
    from scout.shared.db import _content_hash

    base = listing_factory()
    assert _content_hash(base) != _content_hash(listing_factory(title="Staff Engineer"))
    assert _content_hash(base) != _content_hash(listing_factory(company="Other Ltd"))
    assert _content_hash(base) != _content_hash(listing_factory(location="Sydney NSW"))
    assert _content_hash(base) != _content_hash(listing_factory(is_remote=True))
    assert _content_hash(base) != _content_hash(listing_factory(salary_min=90000.0))
    assert _content_hash(base) != _content_hash(listing_factory(salary_max=120000.0))


@pytest.mark.asyncio
async def test_close_stale_listings_keeps_recently_seen(db_pool, listing_factory):
    async with db_pool.acquire() as conn:
        await upsert_listing(conn, listing_factory(external_id="fresh"))
        closed = await close_stale_listings(conn, stale_days=7)
        assert closed == []
        status = await conn.fetchval("SELECT status FROM listings")
        assert status == "open"


@pytest.mark.asyncio
async def test_close_stale_listings_closes_long_unseen(db_pool, listing_factory):
    async with db_pool.acquire() as conn:
        await upsert_listing(conn, listing_factory(external_id="old"))
        await conn.execute("UPDATE listings SET last_seen_at = now() - interval '30 days'")
        closed = await close_stale_listings(conn, stale_days=7)
        assert closed == ["old"]
        status = await conn.fetchval("SELECT status FROM listings")
        assert status == "closed"


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


@pytest.mark.asyncio
async def test_start_run_creates_row(db_pool):
    async with db_pool.acquire() as conn:
        run_id = await start_run(conn, date(2026, 7, 21))
        row = await conn.fetchrow("SELECT id, run_date FROM runs WHERE id = $1", run_id)

    assert row["id"] == run_id
    assert row["run_date"] == date(2026, 7, 21)


@pytest.mark.asyncio
async def test_start_run_is_idempotent_per_run_date(db_pool):
    run_date = date(2026, 7, 21)
    async with db_pool.acquire() as conn:
        first_id = await start_run(conn, run_date)
        second_id = await start_run(conn, run_date)
        count = await conn.fetchval(
            "SELECT count(*) FROM runs WHERE run_date = $1", run_date
        )

    assert first_id == second_id
    assert count == 1


@pytest.mark.asyncio
async def test_start_run_refreshes_started_at_on_conflict(db_pool):
    run_date = date(2026, 7, 21)
    async with db_pool.acquire() as conn:
        run_id = await start_run(conn, run_date)
        await conn.execute(
            "UPDATE runs SET started_at = started_at - interval '1 day' WHERE id = $1",
            run_id,
        )
        before = await conn.fetchval("SELECT started_at FROM runs WHERE id = $1", run_id)

        await start_run(conn, run_date)
        after = await conn.fetchval("SELECT started_at FROM runs WHERE id = $1", run_id)

    assert after > before


@pytest.mark.asyncio
async def test_finish_run_updates_counts_and_finished_at(db_pool):
    async with db_pool.acquire() as conn:
        run_id = await start_run(conn, date(2026, 7, 21))
        # listings_scored is derived from run_listings, not the argument; no
        # rows exist for this run_id, so it comes back 0. See
        # test_finish_run_derives_scored_from_stored_rows for the derived case.
        await finish_run(conn, run_id, listings_scraped=42, listings_scored=10)
        row = await conn.fetchrow(
            "SELECT listings_scraped, listings_scored, finished_at FROM runs WHERE id = $1",
            run_id,
        )

    assert row["listings_scraped"] == 42
    assert row["listings_scored"] == 0
    assert row["finished_at"] is not None


async def test_finish_run_derives_scored_from_stored_rows(
    db_pool, listing_factory, match_factory
):
    async with db_pool.acquire() as conn:
        listing = listing_factory()
        await upsert_listing(conn, listing)
        run_id = await start_run(conn, date(2026, 7, 24))
        await record_run_listings(
            conn, run_id, [(match_factory(listing=listing), "competitive")]
        )

        # Report a wrong count; the stored rows are the source of truth.
        await finish_run(conn, run_id, listings_scraped=40, listings_scored=999)
        scored = await conn.fetchval(
            "SELECT listings_scored FROM runs WHERE id = $1", run_id
        )
        assert scored == 1


async def test_finish_run_never_lowers_scraped_count(db_pool):
    async with db_pool.acquire() as conn:
        run_id = await start_run(conn, date(2026, 7, 24))
        await finish_run(conn, run_id, listings_scraped=81, listings_scored=0)
        # A quieter same-day re-run must not shrink the day's snapshot.
        await finish_run(conn, run_id, listings_scraped=3, listings_scored=0)
        scraped = await conn.fetchval(
            "SELECT listings_scraped FROM runs WHERE id = $1", run_id
        )
        assert scraped == 81


@pytest.mark.asyncio
async def test_record_run_listings_inserts_scored_listings(db_pool):
    listing = _make_listing()
    async with db_pool.acquire() as conn:
        await upsert_listing(conn, listing)
        run_id = await start_run(conn, date(2026, 7, 21))

        await record_run_listings(
            conn,
            run_id,
            [
                (
                    MatchResult(listing=listing, score=87, reasoning="Great fit"),
                    "strong_match",
                )
            ],
        )

        row = await conn.fetchrow(
            "SELECT score, reasoning, band FROM run_listings WHERE run_id = $1", run_id
        )

    assert row["score"] == 87
    assert row["reasoning"] == "Great fit"
    assert row["band"] == "strong_match"


@pytest.mark.asyncio
async def test_record_run_listings_upserts_on_conflict(db_pool):
    listing = _make_listing()
    async with db_pool.acquire() as conn:
        await upsert_listing(conn, listing)
        run_id = await start_run(conn, date(2026, 7, 21))

        await record_run_listings(
            conn,
            run_id,
            [
                (
                    MatchResult(listing=listing, score=50, reasoning="Ok fit"),
                    "reach",
                )
            ],
        )
        await record_run_listings(
            conn,
            run_id,
            [
                (
                    MatchResult(listing=listing, score=90, reasoning="Better fit"),
                    "strong_match",
                )
            ],
        )

        rows = await conn.fetch(
            "SELECT score, reasoning, band FROM run_listings WHERE run_id = $1", run_id
        )

    assert len(rows) == 1
    assert rows[0]["score"] == 90
    assert rows[0]["reasoning"] == "Better fit"
    assert rows[0]["band"] == "strong_match"


@pytest.mark.asyncio
async def test_get_run_by_date_returns_run(db_pool):
    run_date = date(2026, 7, 21)
    async with db_pool.acquire() as conn:
        run_id = await start_run(conn, run_date)
        run = await get_run_by_date(conn, run_date)

    assert run is not None
    assert run.id == run_id
    assert run.run_date == run_date


@pytest.mark.asyncio
async def test_get_run_by_date_returns_none_when_missing(db_pool):
    async with db_pool.acquire() as conn:
        run = await get_run_by_date(conn, date(2099, 1, 1))

    assert run is None


@pytest.mark.asyncio
async def test_list_runs_returns_most_recent_first(db_pool):
    async with db_pool.acquire() as conn:
        await start_run(conn, date(2026, 7, 19))
        await start_run(conn, date(2026, 7, 21))
        await start_run(conn, date(2026, 7, 20))

        runs = await list_runs(conn, limit=2)

    assert [run.run_date for run in runs] == [date(2026, 7, 21), date(2026, 7, 20)]


@pytest.mark.asyncio
async def test_get_run_summaries_returns_band_counts(
    db_pool, listing_factory, match_factory
):
    from scout.shared.db import get_run_summaries

    async with db_pool.acquire() as conn:
        strong = listing_factory(external_id="strong")
        reach = listing_factory(external_id="reach")
        for listing in (strong, reach):
            await upsert_listing(conn, listing)
        run_id = await start_run(conn, date(2026, 7, 24))
        await record_run_listings(
            conn,
            run_id,
            [
                (match_factory(listing=strong, score=90), "strong_match"),
                (match_factory(listing=reach, score=30), "reach"),
            ],
        )

        summaries = await get_run_summaries(conn, limit=30)
        assert len(summaries) == 1
        summary = summaries[0]
        assert summary.run.id == run_id
        assert summary.stats["scored"] == 2
        assert summary.stats["strong"] == 1
        assert summary.stats["reach"] == 1
        assert summary.stats["avg_score"] == 60


@pytest.mark.asyncio
async def test_get_run_summaries_returns_zeroed_stats_for_empty_run(db_pool):
    from scout.shared.db import get_run_summaries

    async with db_pool.acquire() as conn:
        run_id = await start_run(conn, date(2026, 7, 24))
        summaries = await get_run_summaries(conn, limit=30)

    assert len(summaries) == 1
    assert summaries[0].run.id == run_id
    assert summaries[0].stats == {
        "scored": 0,
        "strong": 0,
        "competitive": 0,
        "reach": 0,
        "avg_score": 0,
        "gaps": 0,
    }


@pytest.mark.asyncio
async def test_get_run_listings_returns_scored_listings_for_run(db_pool):
    listing_a = _make_listing(source="linkedin", external_id="job-a")
    listing_b = _make_listing(source="linkedin", external_id="job-b")
    async with db_pool.acquire() as conn:
        await upsert_listing(conn, listing_a)
        await upsert_listing(conn, listing_b)
        run_id = await start_run(conn, date(2026, 7, 21))
        await record_run_listings(
            conn,
            run_id,
            [
                (MatchResult(listing=listing_a, score=80, reasoning="Good"), "competitive"),
                (MatchResult(listing=listing_b, score=60, reasoning="Ok"), "reach"),
            ],
        )

        run_listings = await get_run_listings(conn, run_id)

    assert len(run_listings) == 2
    assert {rl.score for rl in run_listings} == {80, 60}
    assert {rl.band for rl in run_listings} == {"competitive", "reach"}
    assert all(rl.run_id == run_id for rl in run_listings)


@pytest.mark.asyncio
async def test_record_listing_gaps_inserts_and_get_listing_gaps_returns_them(db_pool):
    listing = _make_listing()
    async with db_pool.acquire() as conn:
        await upsert_listing(conn, listing)
        run_id = await start_run(conn, date(2026, 7, 21))
        match = MatchResult(listing=listing, score=70, reasoning="Decent fit")
        await record_run_listings(conn, run_id, [(match, "competitive")])

        gaps = [
            SkillGap(skill="Go", requirement_level="must_have"),
            SkillGap(skill="Kubernetes", requirement_level="nice_to_have"),
        ]
        await record_listing_gaps(conn, run_id, [(match, gaps)])

        run_listing_id = await conn.fetchval(
            "SELECT id FROM run_listings WHERE run_id = $1", run_id
        )
        stored_gaps = await get_listing_gaps(conn, run_listing_id)

    assert {(g.skill, g.requirement_level) for g in stored_gaps} == {
        ("Go", "must_have"),
        ("Kubernetes", "nice_to_have"),
    }


@pytest.mark.asyncio
async def test_record_listing_gaps_skips_matches_with_no_gaps(db_pool):
    listing = _make_listing()
    async with db_pool.acquire() as conn:
        await upsert_listing(conn, listing)
        run_id = await start_run(conn, date(2026, 7, 21))
        match = MatchResult(listing=listing, score=95, reasoning="Great fit")
        await record_run_listings(conn, run_id, [(match, "strong_match")])

        await record_listing_gaps(conn, run_id, [(match, [])])

        run_listing_id = await conn.fetchval(
            "SELECT id FROM run_listings WHERE run_id = $1", run_id
        )
        stored_gaps = await get_listing_gaps(conn, run_listing_id)

    assert stored_gaps == []


@pytest.mark.asyncio
async def test_record_listing_gaps_is_idempotent_on_rerun(db_pool):
    listing = _make_listing()
    async with db_pool.acquire() as conn:
        await upsert_listing(conn, listing)
        run_id = await start_run(conn, date(2026, 7, 21))
        match = MatchResult(listing=listing, score=70, reasoning="Decent fit")
        await record_run_listings(conn, run_id, [(match, "competitive")])

        first_gaps = [
            SkillGap(skill="Go", requirement_level="must_have"),
            SkillGap(skill="Kubernetes", requirement_level="nice_to_have"),
            SkillGap(skill="Rust", requirement_level="nice_to_have"),
        ]
        await record_listing_gaps(conn, run_id, [(match, first_gaps)])

        second_gaps = [SkillGap(skill="Go", requirement_level="must_have")]
        await record_listing_gaps(conn, run_id, [(match, second_gaps)])

        run_listing_id = await conn.fetchval(
            "SELECT id FROM run_listings WHERE run_id = $1", run_id
        )
        stored_gaps = await get_listing_gaps(conn, run_listing_id)

    assert [(g.skill, g.requirement_level) for g in stored_gaps] == [
        ("Go", "must_have")
    ]


@pytest.mark.asyncio
async def test_record_listing_gaps_delete_scoped_to_run_id(db_pool):
    listing_a = _make_listing(source="linkedin", external_id="job-a")
    listing_b = _make_listing(source="linkedin", external_id="job-b")
    async with db_pool.acquire() as conn:
        await upsert_listing(conn, listing_a)
        await upsert_listing(conn, listing_b)

        run_id_1 = await start_run(conn, date(2026, 7, 20))
        match_1 = MatchResult(listing=listing_a, score=70, reasoning="Decent fit")
        await record_run_listings(conn, run_id_1, [(match_1, "competitive")])
        await record_listing_gaps(
            conn, run_id_1, [(match_1, [SkillGap(skill="Go", requirement_level="must_have")])]
        )

        run_id_2 = await start_run(conn, date(2026, 7, 21))
        match_2 = MatchResult(listing=listing_b, score=60, reasoning="Ok fit")
        await record_run_listings(conn, run_id_2, [(match_2, "reach")])
        await record_listing_gaps(
            conn,
            run_id_2,
            [(match_2, [SkillGap(skill="Rust", requirement_level="nice_to_have")])],
        )

        run_listing_id_1 = await conn.fetchval(
            "SELECT id FROM run_listings WHERE run_id = $1", run_id_1
        )
        run_listing_id_2 = await conn.fetchval(
            "SELECT id FROM run_listings WHERE run_id = $1", run_id_2
        )
        gaps_1 = await get_listing_gaps(conn, run_listing_id_1)
        gaps_2 = await get_listing_gaps(conn, run_listing_id_2)

    assert [(g.skill, g.requirement_level) for g in gaps_1] == [("Go", "must_have")]
    assert [(g.skill, g.requirement_level) for g in gaps_2] == [
        ("Rust", "nice_to_have")
    ]


@pytest.mark.asyncio
async def test_record_listing_gaps_only_replaces_supplied_listings(
    db_pool, listing_factory, match_factory
):
    """Recording one listing's gaps must not wipe another listing's gaps
    from the same run -- a same-day re-run that only re-analyses some
    listings should leave the rest of that run's gaps intact."""
    first = listing_factory(external_id="first")
    second = listing_factory(external_id="second")
    async with db_pool.acquire() as conn:
        for listing in (first, second):
            await upsert_listing(conn, listing)
        run_id = await start_run(conn, date(2026, 7, 24))
        await record_run_listings(
            conn,
            run_id,
            [
                (match_factory(listing=first), "competitive"),
                (match_factory(listing=second), "competitive"),
            ],
        )

        gap = SkillGap(skill="Go", requirement_level="must_have", met=False, kind="skill")
        await record_listing_gaps(conn, run_id, [(match_factory(listing=first), [gap])])
        await record_listing_gaps(conn, run_id, [(match_factory(listing=second), [gap])])

        # Recording the second listing's gaps must not have wiped the first's.
        total = await conn.fetchval("SELECT count(*) FROM listing_gaps")
    assert total == 2


@pytest.mark.asyncio
async def test_record_listing_gaps_rolls_back_delete_when_insert_fails(db_pool):
    listing = _make_listing()
    async with db_pool.acquire() as conn:
        await upsert_listing(conn, listing)
        run_id = await start_run(conn, date(2026, 7, 21))
        match = MatchResult(listing=listing, score=70, reasoning="Decent fit")
        await record_run_listings(conn, run_id, [(match, "competitive")])

        existing_gaps = [SkillGap(skill="Go", requirement_level="must_have")]
        await record_listing_gaps(conn, run_id, [(match, existing_gaps)])

        invalid_gaps = [SkillGap(skill="Rust", requirement_level="invalid_level")]
        with pytest.raises(asyncpg.CheckViolationError):
            await record_listing_gaps(conn, run_id, [(match, invalid_gaps)])

        run_listing_id = await conn.fetchval(
            "SELECT id FROM run_listings WHERE run_id = $1", run_id
        )
        stored_gaps = await get_listing_gaps(conn, run_listing_id)

    assert [(g.skill, g.requirement_level) for g in stored_gaps] == [
        ("Go", "must_have")
    ]


@pytest.mark.asyncio
async def test_record_listing_gaps_round_trips_kind(db_pool):
    listing = _make_listing()
    async with db_pool.acquire() as conn:
        await upsert_listing(conn, listing)
        run_id = await start_run(conn, date(2026, 7, 21))
        match = MatchResult(listing=listing, score=70, reasoning="Decent fit")
        await record_run_listings(conn, run_id, [(match, "competitive")])

        checks = [
            SkillGap(skill="Go", requirement_level="must_have", met=False, kind="skill"),
            SkillGap(
                skill="A STEM degree in CS",
                requirement_level="must_have",
                met=True,
                kind="qualification",
            ),
            SkillGap(
                skill="3+ years experience",
                requirement_level="nice_to_have",
                met=True,
                kind="experience",
            ),
        ]
        await record_listing_gaps(conn, run_id, [(match, checks)])

        run_listing_id = await conn.fetchval(
            "SELECT id FROM run_listings WHERE run_id = $1", run_id
        )
        stored = await get_listing_gaps(conn, run_listing_id)

    assert {(g.skill, g.kind) for g in stored} == {
        ("Go", "skill"),
        ("A STEM degree in CS", "qualification"),
        ("3+ years experience", "experience"),
    }


@pytest.mark.asyncio
async def test_get_run_details_excludes_non_skill_kinds_from_gaps(db_pool):
    listing = _make_listing()
    async with db_pool.acquire() as conn:
        await upsert_listing(conn, listing)
        run_id = await start_run(conn, date(2026, 7, 21))
        match = MatchResult(listing=listing, score=70, reasoning="Decent fit")
        await record_run_listings(conn, run_id, [(match, "competitive")])

        # A non-skill check with met=False must still be kept out of gaps by
        # kind, so the sentinel can't silently flip a qualification into a gap.
        checks = [
            SkillGap(skill="Rust", requirement_level="must_have", met=False, kind="skill"),
            SkillGap(
                skill="A STEM degree in CS",
                requirement_level="must_have",
                met=False,
                kind="qualification",
            ),
        ]
        await record_listing_gaps(conn, run_id, [(match, checks)])

        [detail] = await get_run_details(conn, run_id)

    assert [g.skill for g in detail.gaps] == ["Rust"]
    # Every check, skill or not, is still available for display.
    assert {r.skill for r in detail.requirements} == {"Rust", "A STEM degree in CS"}


@pytest.mark.asyncio
async def test_get_listing_gaps_defaults_kind_to_skill_for_legacy_rows(db_pool):
    listing = _make_listing()
    async with db_pool.acquire() as conn:
        await upsert_listing(conn, listing)
        run_id = await start_run(conn, date(2026, 7, 21))
        match = MatchResult(listing=listing, score=70, reasoning="Decent fit")
        await record_run_listings(conn, run_id, [(match, "competitive")])
        run_listing_id = await conn.fetchval(
            "SELECT id FROM run_listings WHERE run_id = $1", run_id
        )
        # A row written without kind (as legacy rows were) relies on the column
        # DEFAULT and must read back as the skill kind.
        await conn.execute(
            "INSERT INTO listing_gaps (run_listing_id, skill, requirement_level, met) "
            "VALUES ($1, 'Go', 'must_have', false)",
            run_listing_id,
        )
        stored = await get_listing_gaps(conn, run_listing_id)

    assert stored == [
        SkillGap(skill="Go", requirement_level="must_have", met=False, kind="skill")
    ]
