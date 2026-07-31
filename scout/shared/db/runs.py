"""Run and report persistence: runs, run_listings, listing_gaps, listing_tips."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

import asyncpg

from scout.shared.schemas import (
    GroundedTip,
    Listing,
    ListingRequirements,
    MatchResult,
    Run,
    RunListing,
    RunListingDetail,
    RunSummary,
    SkillGap,
)


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
    conn: asyncpg.Connection,
    run_id: int,
    # Sequence, not list: the caller's tuples carry the band as a Literal,
    # and list's invariance would reject list[tuple[..., Literal]] here.
    matches: Sequence[tuple[MatchResult, str]],
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
               -- Gaps come from a correlated subquery, NOT a join: joining
               -- listing_gaps fans out each run_listings row once per gap,
               -- which would multiply every band count by that listing's
               -- gap-row count (the history/dashboard mismatch bug).
               (
                   SELECT count(*)
                   FROM listing_gaps
                   JOIN run_listings AS rl
                       ON rl.id = listing_gaps.run_listing_id
                   WHERE rl.run_id = run_listings.run_id
                     AND listing_gaps.kind = 'skill'
                     AND NOT listing_gaps.met
               ) AS gaps
        FROM run_listings
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


async def record_listing_tips(
    conn: asyncpg.Connection,
    run_id: int,
    tips_by_match: list[tuple[MatchResult, list[GroundedTip]]],
) -> None:
    """Replace the stored tips for the supplied listings in one run.

    Scoped to the listings supplied, not the whole run, for the same
    reason ``record_listing_gaps`` is: a same-day re-run that only
    re-analyses some listings must not wipe the rest of the run's tips.
    """
    if not tips_by_match:
        return

    # Inner transaction keeps delete-then-insert self-atomic when called on
    # its own; nested inside the pipeline's run transaction asyncpg makes
    # it a harmless savepoint.
    async with conn.transaction():
        rows = await conn.fetch(
            """
            SELECT run_listings.id, listings.source, listings.external_id
            FROM run_listings
            JOIN listings ON listings.id = run_listings.listing_id
            WHERE run_listings.run_id = $1
            """,
            run_id,
        )
        id_by_key = {
            (row["source"], row["external_id"]): row["id"] for row in rows
        }

        # Built from every match supplied — not just those with tips — so a
        # listing whose tips are now all ungrounded has its stale rows
        # cleared rather than left behind.
        target_ids = [
            id_by_key[(match.listing.source, match.listing.external_id)]
            for match, _tips in tips_by_match
            if (match.listing.source, match.listing.external_id) in id_by_key
        ]
        if not target_ids:
            return

        await conn.execute(
            "DELETE FROM listing_tips WHERE run_listing_id = ANY($1::bigint[])",
            target_ids,
        )

        records = [
            (
                id_by_key[(match.listing.source, match.listing.external_id)],
                tip.gap_skill,
                tip.tip,
                tip.cited_urls,
            )
            for match, tips in tips_by_match
            if (match.listing.source, match.listing.external_id) in id_by_key
            for tip in tips
        ]
        if not records:
            return

        # executemany rather than record_listing_gaps' set-based unnest INSERT:
        # cited_urls is TEXT[], and an array-of-arrays doesn't pass through
        # unnest the way flat text columns do, whereas asyncpg binds a Python
        # list[str] straight to TEXT[] here.
        await conn.executemany(
            """
            INSERT INTO listing_tips (run_listing_id, gap_skill, tip, cited_urls)
            VALUES ($1, $2, $3, $4)
            """,
            records,
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

    tip_rows = await conn.fetch(
        """
        SELECT run_listing_id, gap_skill, tip, cited_urls
        FROM listing_tips
        WHERE run_listing_id = ANY($1::bigint[])
        ORDER BY id
        """,
        run_listing_ids,
    )
    tips_by_id: dict[int, list[GroundedTip]] = {}
    for tip_row in tip_rows:
        tips_by_id.setdefault(tip_row["run_listing_id"], []).append(
            GroundedTip(
                gap_skill=tip_row["gap_skill"],
                tip=tip_row["tip"],
                cited_urls=list(tip_row["cited_urls"]),
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
                tips=tips_by_id.get(run_listing_id, []),
                seniority=seniority,
                work_type=work_type,
                team=team,
            )
        )
    return details


async def get_distinct_gap_skills(conn: asyncpg.Connection) -> list[str]:
    rows = await conn.fetch(
        "SELECT DISTINCT skill FROM listing_gaps WHERE kind = 'skill' AND NOT met"
    )
    return [row["skill"] for row in rows]
