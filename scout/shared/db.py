from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path
from typing import Literal

import asyncpg

from scout.config import Settings
from scout.config import settings as default_settings
from scout.shared.schemas import Listing, MatchResult, Run, RunListing

_SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


async def create_pool(settings: Settings | None = None) -> asyncpg.Pool:
    active_settings = settings or default_settings
    return await asyncpg.create_pool(dsn=active_settings.database_url)


async def apply_schema(pool: asyncpg.Pool) -> None:
    schema_sql = _SCHEMA_PATH.read_text(encoding="utf-8")
    async with pool.acquire() as conn:
        await conn.execute(schema_sql)


def _content_hash(listing: Listing) -> str:
    payload = "\x00".join(
        [
            listing.title,
            listing.company,
            listing.location,
            str(listing.is_remote),
            listing.description,
            str(listing.salary_min),
            str(listing.salary_max),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def upsert_listing(
    conn: asyncpg.Connection, listing: Listing
) -> Literal["new", "changed", "unchanged"]:
    content_hash = _content_hash(listing)
    row = await conn.fetchrow(
        """
        WITH previous AS (
            SELECT content_hash, status
            FROM listings
            WHERE source = $1 AND external_id = $2
        ), upserted AS (
            INSERT INTO listings (
                source, external_id, title, company, location, url,
                description, is_remote, salary_min, salary_max,
                date_posted, scraped_at, content_hash, status, last_seen_at
            )
            VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13,
                'open', now()
            )
            ON CONFLICT (source, external_id) DO UPDATE SET
                title = EXCLUDED.title,
                company = EXCLUDED.company,
                location = EXCLUDED.location,
                url = EXCLUDED.url,
                description = EXCLUDED.description,
                is_remote = EXCLUDED.is_remote,
                salary_min = EXCLUDED.salary_min,
                salary_max = EXCLUDED.salary_max,
                date_posted = EXCLUDED.date_posted,
                scraped_at = EXCLUDED.scraped_at,
                content_hash = EXCLUDED.content_hash,
                status = 'open',
                last_seen_at = now()
            RETURNING id
        )
        SELECT content_hash AS previous_hash, status AS previous_status
        FROM previous
        """,
        listing.source,
        listing.external_id,
        listing.title,
        listing.company,
        listing.location,
        str(listing.url),
        listing.description,
        listing.is_remote,
        listing.salary_min,
        listing.salary_max,
        listing.date_posted,
        listing.scraped_at,
        content_hash,
    )
    if row is None:
        return "new"
    if row["previous_status"] == "closed" or row["previous_hash"] != content_hash:
        return "changed"
    return "unchanged"


async def close_stale_listings(
    conn: asyncpg.Connection, seen_keys: list[tuple[str, str]]
) -> list[str]:
    sources = [key[0] for key in seen_keys]
    external_ids = [key[1] for key in seen_keys]
    rows = await conn.fetch(
        """
        UPDATE listings
        SET status = 'closed', closed_at = now()
        WHERE status = 'open'
          AND NOT (source, external_id) IN (
              SELECT * FROM unnest($1::text[], $2::text[])
          )
        RETURNING external_id
        """,
        sources,
        external_ids,
    )
    return [row["external_id"] for row in rows]


async def start_run(conn: asyncpg.Connection, run_date: date) -> int:
    return await conn.fetchval(
        """
        INSERT INTO runs (run_date)
        VALUES ($1)
        ON CONFLICT (run_date) DO UPDATE SET started_at = now()
        RETURNING id
        """,
        run_date,
    )


async def finish_run(
    conn: asyncpg.Connection,
    run_id: int,
    listings_scraped: int,
    listings_scored: int,
) -> None:
    await conn.execute(
        """
        UPDATE runs
        SET listings_scraped = $2,
            listings_scored = $3,
            finished_at = now()
        WHERE id = $1
        """,
        run_id,
        listings_scraped,
        listings_scored,
    )


async def record_run_listings(
    conn: asyncpg.Connection, run_id: int, matches: list[tuple[MatchResult, str]]
) -> None:
    sources = [match.listing.source for match, _band in matches]
    external_ids = [match.listing.external_id for match, _band in matches]
    scores = [match.score for match, _band in matches]
    reasonings = [match.reasoning for match, _band in matches]
    bands = [band for _match, band in matches]
    await conn.execute(
        """
        INSERT INTO run_listings (run_id, listing_id, score, reasoning, band)
        SELECT $1, listings.id, data.score, data.reasoning, data.band
        FROM unnest($2::text[], $3::text[], $4::int[], $5::text[], $6::text[])
            AS data(source, external_id, score, reasoning, band)
        JOIN listings
            ON listings.source = data.source AND listings.external_id = data.external_id
        ON CONFLICT (run_id, listing_id) DO UPDATE SET
            score = EXCLUDED.score,
            reasoning = EXCLUDED.reasoning,
            band = EXCLUDED.band
        """,
        run_id,
        sources,
        external_ids,
        scores,
        reasonings,
        bands,
    )


async def get_run_by_date(conn: asyncpg.Connection, run_date: date) -> Run | None:
    row = await conn.fetchrow("SELECT * FROM runs WHERE run_date = $1", run_date)
    if row is None:
        return None
    return Run(**dict(row))


async def list_runs(conn: asyncpg.Connection, limit: int) -> list[Run]:
    rows = await conn.fetch(
        "SELECT * FROM runs ORDER BY run_date DESC LIMIT $1", limit
    )
    return [Run(**dict(row)) for row in rows]


async def get_run_listings(conn: asyncpg.Connection, run_id: int) -> list[RunListing]:
    rows = await conn.fetch(
        "SELECT * FROM run_listings WHERE run_id = $1", run_id
    )
    return [RunListing(**dict(row)) for row in rows]
