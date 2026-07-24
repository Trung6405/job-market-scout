from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path
from typing import Literal

import asyncpg

from scout.config import Settings
from scout.config import settings as default_settings
from scout.shared.schemas import (
    Listing,
    ListingRequirements,
    MatchResult,
    Run,
    RunListing,
    RunListingDetail,
    RunSummary,
    SkillGap,
)

_SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


async def create_pool(settings: Settings | None = None) -> asyncpg.Pool:
    active_settings = settings or default_settings
    return await asyncpg.create_pool(dsn=active_settings.database_url)


async def apply_schema(pool: asyncpg.Pool) -> None:
    schema_sql = _SCHEMA_PATH.read_text(encoding="utf-8")
    async with pool.acquire() as conn:
        await conn.execute(schema_sql)


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
    """Mark a run finished without letting a re-run degrade it.

    Two runs on one date share a row (``runs.run_date`` is unique, kept
    deliberately — see the pipeline-hardening spec). The second is usually
    quieter than the first, so reporting its numbers verbatim used to zero
    the morning's ``listings_scored`` while its ``run_listings`` rows stayed
    in the table. Instead: ``listings_scored`` is derived from those rows,
    and ``listings_scraped`` keeps the larger of the two snapshots.

    ``listings_scored`` is passed but unused; it stays in the signature so
    callers read symmetrically and so the derived value is obviously
    authoritative.
    """
    await conn.execute(
        """
        UPDATE runs
        SET listings_scraped = GREATEST(runs.listings_scraped, $2),
            listings_scored = (
                SELECT count(*) FROM run_listings WHERE run_listings.run_id = $1
            ),
            finished_at = now()
        WHERE id = $1
        """,
        run_id,
        listings_scraped,
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


async def record_listing_meta(
    conn: asyncpg.Connection,
    run_id: int,
    meta_by_match: list[tuple[MatchResult, ListingRequirements]],
) -> None:
    if not meta_by_match:
        return
    sources = [match.listing.source for match, _req in meta_by_match]
    external_ids = [match.listing.external_id for match, _req in meta_by_match]
    seniorities = [req.seniority for _match, req in meta_by_match]
    work_types = [req.work_type for _match, req in meta_by_match]
    teams = [req.team for _match, req in meta_by_match]
    await conn.execute(
        """
        UPDATE run_listings
        SET seniority = data.seniority,
            work_type = data.work_type,
            team = data.team
        FROM unnest($2::text[], $3::text[], $4::text[], $5::text[], $6::text[])
            AS data(source, external_id, seniority, work_type, team)
        JOIN listings
            ON listings.source = data.source AND listings.external_id = data.external_id
        WHERE run_listings.run_id = $1
            AND run_listings.listing_id = listings.id
        """,
        run_id,
        sources,
        external_ids,
        seniorities,
        work_types,
        teams,
    )


async def get_run_by_date(conn: asyncpg.Connection, run_date: date) -> Run | None:
    """Fetch a run by date. Used only by tests.

    No production caller: the pipeline holds the run id from ``start_run``.
    Kept as an assertion probe for ``tests/test_agent.py`` and
    ``tests/test_db.py`` — not dead code, do not remove.
    """
    row = await conn.fetchrow("SELECT * FROM runs WHERE run_date = $1", run_date)
    if row is None:
        return None
    return Run(**dict(row))


async def list_runs(conn: asyncpg.Connection, limit: int) -> list[Run]:
    rows = await conn.fetch(
        "SELECT * FROM runs ORDER BY run_date DESC LIMIT $1", limit
    )
    return [Run(**dict(row)) for row in rows]


async def get_run_summaries(
    conn: asyncpg.Connection, limit: int
) -> list[RunSummary]:
    """Per-run aggregates for the history page, in two queries total."""
    runs = await list_runs(conn, limit)
    if not runs:
        return []
    rows = await conn.fetch(
        """
        SELECT run_listings.run_id,
               count(*) AS scored,
               count(*) FILTER (WHERE run_listings.band = 'strong_match') AS strong,
               count(*) FILTER (WHERE run_listings.band = 'competitive') AS competitive,
               count(*) FILTER (WHERE run_listings.band = 'reach') AS reach,
               coalesce(round(avg(run_listings.score)), 0) AS avg_score,
               count(listing_gaps.id) FILTER (
                   WHERE listing_gaps.kind = 'skill' AND NOT listing_gaps.met
               ) AS gaps
        FROM run_listings
        LEFT JOIN listing_gaps ON listing_gaps.run_listing_id = run_listings.id
        WHERE run_listings.run_id = ANY($1::bigint[])
        GROUP BY run_listings.run_id
        """,
        [run.id for run in runs],
    )
    stats_by_run = {row["run_id"]: dict(row) for row in rows}
    summaries: list[RunSummary] = []
    for run in runs:
        row = stats_by_run.get(run.id, {})
        summaries.append(
            RunSummary(
                run=run,
                stats={
                    "scored": int(row.get("scored", 0)),
                    "strong": int(row.get("strong", 0)),
                    "competitive": int(row.get("competitive", 0)),
                    "reach": int(row.get("reach", 0)),
                    "avg_score": int(row.get("avg_score", 0)),
                    "gaps": int(row.get("gaps", 0)),
                },
            )
        )
    return summaries


async def get_adjacent_runs(
    conn: asyncpg.Connection, run_date: date
) -> tuple[Run | None, Run | None]:
    prev_row = await conn.fetchrow(
        "SELECT * FROM runs WHERE run_date < $1 ORDER BY run_date DESC LIMIT 1",
        run_date,
    )
    next_row = await conn.fetchrow(
        "SELECT * FROM runs WHERE run_date > $1 ORDER BY run_date ASC LIMIT 1",
        run_date,
    )
    prev_run = Run(**dict(prev_row)) if prev_row else None
    next_run = Run(**dict(next_row)) if next_row else None
    return prev_run, next_run


async def get_run_listings(conn: asyncpg.Connection, run_id: int) -> list[RunListing]:
    """Fetch every run_listings row for a run. Used only by tests.

    No production caller: ``get_run_details`` is what the report layer
    reads from. Kept as an assertion probe for ``tests/test_agent.py`` and
    ``tests/test_db.py`` — not dead code, do not remove.
    """
    rows = await conn.fetch(
        "SELECT * FROM run_listings WHERE run_id = $1", run_id
    )
    return [RunListing(**dict(row)) for row in rows]


async def record_listing_gaps(
    conn: asyncpg.Connection,
    run_id: int,
    gaps_by_match: list[tuple[MatchResult, list[SkillGap]]],
) -> None:
    # Inner transaction keeps the delete-then-insert self-atomic even when
    # called on its own; when the caller (ScoutPipelineAgent) already holds a
    # run-scoped transaction, asyncpg nests this as a harmless savepoint.
    async with conn.transaction():
        # Listings being (re)recorded, built from every match supplied —
        # not just those with checks — so a listing whose requirements are
        # now all met still has its stale gap rows cleared below.
        listing_sources = [match.listing.source for match, _checks in gaps_by_match]
        listing_external_ids = [
            match.listing.external_id for match, _checks in gaps_by_match
        ]

        # Scoped to the listings supplied, not the whole run: recording one
        # listing's gaps must not wipe another listing's gaps from the same
        # run, which a whole-run delete did whenever a same-day re-run only
        # re-analysed some of the run's listings.
        await conn.execute(
            """
            DELETE FROM listing_gaps
            WHERE run_listing_id IN (
                SELECT run_listings.id
                FROM run_listings
                JOIN listings ON listings.id = run_listings.listing_id
                JOIN unnest($2::text[], $3::text[]) AS data(source, external_id)
                    ON listings.source = data.source
                   AND listings.external_id = data.external_id
                WHERE run_listings.run_id = $1
            )
            """,
            run_id,
            listing_sources,
            listing_external_ids,
        )

        sources: list[str] = []
        external_ids: list[str] = []
        skills: list[str] = []
        requirement_levels: list[str] = []
        mets: list[bool] = []
        kinds: list[str] = []
        for match, checks in gaps_by_match:
            for check in checks:
                sources.append(match.listing.source)
                external_ids.append(match.listing.external_id)
                skills.append(check.skill)
                requirement_levels.append(check.requirement_level)
                mets.append(check.met)
                kinds.append(check.kind)

        if not skills:
            return

        await conn.execute(
            """
            INSERT INTO listing_gaps (run_listing_id, skill, requirement_level, met, kind)
            SELECT run_listings.id, data.skill, data.requirement_level, data.met, data.kind
            FROM unnest($2::text[], $3::text[], $4::text[], $5::text[], $6::boolean[], $7::text[])
                AS data(source, external_id, skill, requirement_level, met, kind)
            JOIN listings
                ON listings.source = data.source AND listings.external_id = data.external_id
            JOIN run_listings
                ON run_listings.listing_id = listings.id AND run_listings.run_id = $1
            """,
            run_id,
            sources,
            external_ids,
            skills,
            requirement_levels,
            mets,
            kinds,
        )


async def get_listing_gaps(conn: asyncpg.Connection, run_listing_id: int) -> list[SkillGap]:
    rows = await conn.fetch(
        "SELECT skill, requirement_level, met, kind FROM listing_gaps WHERE run_listing_id = $1",
        run_listing_id,
    )
    return [SkillGap(**dict(row)) for row in rows]


async def get_run(conn: asyncpg.Connection, run_id: int) -> Run:
    """Fetch a run by id.

    Non-optional on purpose: every caller dereferences the result
    immediately, so an Optional return only moved the failure to a less
    informative ``AttributeError`` further down.
    """
    row = await conn.fetchrow("SELECT * FROM runs WHERE id = $1", run_id)
    if row is None:
        raise LookupError(f"no run with id {run_id}")
    return Run(**dict(row))


async def get_run_details(conn: asyncpg.Connection, run_id: int) -> list[RunListingDetail]:
    rows = await conn.fetch(
        """
        SELECT run_listings.id AS run_listing_id, run_listings.score, run_listings.reasoning, run_listings.band,
               run_listings.seniority, run_listings.work_type, run_listings.team,
               listings.source, listings.external_id, listings.title, listings.company, listings.location,
               listings.is_remote, listings.url, listings.description, listings.salary_min, listings.salary_max,
               listings.date_posted, listings.scraped_at
        FROM run_listings
        JOIN listings ON listings.id = run_listings.listing_id
        WHERE run_listings.run_id = $1
        ORDER BY run_listings.score DESC
        """,
        run_id,
    )

    run_listing_ids = [row["run_listing_id"] for row in rows]
    gap_rows = await conn.fetch(
        """
        SELECT run_listing_id, skill, requirement_level, met, kind
        FROM listing_gaps
        WHERE run_listing_id = ANY($1::bigint[])
        """,
        run_listing_ids,
    )
    requirements_by_id: dict[int, list[SkillGap]] = {}
    for gap_row in gap_rows:
        requirements_by_id.setdefault(gap_row["run_listing_id"], []).append(
            SkillGap(
                skill=gap_row["skill"],
                requirement_level=gap_row["requirement_level"],
                met=gap_row["met"],
                kind=gap_row["kind"],
            )
        )

    details: list[RunListingDetail] = []
    for row in rows:
        data = dict(row)
        run_listing_id = data.pop("run_listing_id")
        score = data.pop("score")
        reasoning = data.pop("reasoning")
        band = data.pop("band")
        seniority = data.pop("seniority")
        work_type = data.pop("work_type")
        team = data.pop("team")
        requirements = requirements_by_id.get(run_listing_id, [])
        details.append(
            RunListingDetail(
                run_listing_id=run_listing_id,
                listing=Listing(**data),
                score=score,
                reasoning=reasoning,
                band=band,
                gaps=[
                    check
                    for check in requirements
                    if check.kind == "skill" and not check.met
                ],
                requirements=requirements,
                seniority=seniority,
                work_type=work_type,
                team=team,
            )
        )
    return details
