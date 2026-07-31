"""Listing lifecycle: upsert on scrape, staleness-based closure."""

from __future__ import annotations

import hashlib
from typing import Literal

import asyncpg

from scout.shared.schemas import Listing


def _content_hash(listing: Listing) -> str:
    """Fingerprint the fields that change a listing's substance.

    ``description`` is deliberately excluded: job boards re-word and
    re-timestamp descriptions constantly, and including it meant any
    cosmetic edit marked the listing ``changed`` and bought a full
    re-analysis. The trade-off is accepted — a materially rewritten
    description goes unnoticed until some other tracked field moves.
    """
    payload = "\x00".join(
        [
            listing.title,
            listing.company,
            listing.location,
            str(listing.is_remote),
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
    conn: asyncpg.Connection, stale_days: int
) -> list[str]:
    """Close listings unseen for longer than ``stale_days``.

    Closure is deliberately time-based rather than "absent from this run":
    a run only sees RESULTS_WANTED listings per role within HOURS_OLD, so a
    still-open listing drops out of the results routinely. Closing on first
    absence made it reopen as ``changed`` on its return, buying a second
    full analysis of a listing that never changed.

    ``last_seen_at`` is stamped by ``upsert_listing``, so this needs no
    seen-key arrays.
    """
    rows = await conn.fetch(
        """
        UPDATE listings
        SET status = 'closed', closed_at = now()
        WHERE status = 'open'
          AND last_seen_at < now() - make_interval(days => $1)
        RETURNING external_id
        """,
        stale_days,
    )
    return [row["external_id"] for row in rows]
