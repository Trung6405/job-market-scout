from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path
from typing import Literal

import asyncpg

from scout.config import Settings
from scout.config import settings as default_settings
from scout.shared.schemas import (
    GroundedTip,
    LinkVerdict,
    Listing,
    ListingRequirements,
    MatchResult,
    Resource,
    RetrievedResource,
    Run,
    RunListing,
    RunListingDetail,
    RunSummary,
    SkillGap,
)

LinkCheckTransition = Literal[
    "verified", "recovered", "newly_dead", "still_dead", "failing"
]

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


def vector_text(values: list[float]) -> str:
    """Render an embedding in pgvector's text input form.

    Always passed as a bound parameter and cast with ``::vector`` in SQL, never
    interpolated into a statement, so there is no injection surface here.
    """
    return "[" + ",".join(str(value) for value in values) + "]"


async def insert_resource(
    conn: asyncpg.Connection, resource: Resource, embedding: list[float]
) -> Literal["new", "duplicate"]:
    embedding_text = vector_text(embedding)
    inserted_id = await conn.fetchval(
        """
        INSERT INTO resources (url, title, resource_type, skills, level, summary, embedding, source)
        VALUES ($1, $2, $3, $4, $5, $6, $7::vector, $8)
        ON CONFLICT (url) DO NOTHING
        RETURNING id
        """,
        str(resource.url),
        resource.title,
        resource.resource_type,
        resource.skills,
        resource.level,
        resource.summary,
        embedding_text,
        resource.source,
    )
    return "new" if inserted_id is not None else "duplicate"


async def get_resource_urls(conn: asyncpg.Connection) -> set[str]:
    rows = await conn.fetch("SELECT url FROM resources")
    return {row["url"] for row in rows}


async def get_resources_for_skills(
    conn: asyncpg.Connection,
    skills: list[str],
    vectors: list[list[float]],
    k: int,
    max_age_days: int,
) -> dict[str, list[RetrievedResource]]:
    """Retrieve the top-`k` resources for each skill, hybrid-ranked.

    ``skills`` must already be normalized, and ``vectors`` holds each one's
    query embedding at the same index. For every skill the exact ``skills[]``
    pre-filter runs first and cosine ranking only orders what survives it —
    the pre-filter is what guarantees a "java" gap can't surface JavaScript
    resources, since similarity alone cannot separate them (D-CC-3).

    The pre-filter is written as ``skills @> ARRAY[q.skill]`` rather than the
    equivalent ``q.skill = ANY(skills)`` because only the containment form can
    use a GIN index on ``skills``. No such index exists yet — the corpus is
    small enough that a scan is fine — but the predicate is kept in the shape
    that can use one, since this filter runs first and over every row.

    Every requested skill gets a key; one that matches nothing maps to an
    empty list. The dict is pre-seeded to guarantee that, because
    ``CROSS JOIN LATERAL`` emits no row at all for a skill with no matches
    rather than a null-filled one.

    Two independent staleness rules apply: ``max_age_days`` ages a resource
    out automatically once its last successful check is too old, while
    ``dead_since`` is set deliberately by the link-health checker (P5) the
    moment a resource fails verification — the same resource can be excluded
    by either without the other, and a NULL in each column means "not
    excluded on this basis" (never-checked and never-dead, respectively).
    """
    if not skills:
        return {}

    rows = await conn.fetch(
        """
        SELECT q.skill AS query_skill,
               r.url,
               r.title,
               r.resource_type,
               r.skills,
               r.level,
               r.summary,
               r.similarity
        FROM unnest($1::text[], $2::text[]) AS q(skill, vec)
        CROSS JOIN LATERAL (
            SELECT url, title, resource_type, skills, level, summary,
                   1 - (embedding <=> q.vec::vector) AS similarity
            FROM resources
            WHERE skills @> ARRAY[q.skill]
              AND embedding IS NOT NULL
              AND (last_verified IS NULL
                   OR last_verified > now() - make_interval(days => $3))
              AND dead_since IS NULL
            ORDER BY embedding <=> q.vec::vector
            LIMIT $4
        ) r
        """,
        skills,
        [vector_text(vector) for vector in vectors],
        max_age_days,
        k,
    )

    results: dict[str, list[RetrievedResource]] = {skill: [] for skill in skills}
    for row in rows:
        data = dict(row)
        results[data.pop("query_skill")].append(RetrievedResource(**data))
    return results


async def get_distinct_gap_skills(conn: asyncpg.Connection) -> list[str]:
    rows = await conn.fetch(
        "SELECT DISTINCT skill FROM listing_gaps WHERE kind = 'skill' AND NOT met"
    )
    return [row["skill"] for row in rows]


async def get_resources_to_check(
    conn: asyncpg.Connection, limit: int
) -> list[asyncpg.Record]:
    """Return the next `limit` resources due a link-health check.

    Ordered oldest-checked first, with never-checked (`last_verified` NULL)
    rows first of all — a freshly aggregated resource is exactly as overdue
    as one nobody has looked at in months. Every row starts NULL, so the
    ordering among them is otherwise unspecified; the `id` tiebreak makes
    consecutive runs advance through the corpus deterministically instead of
    repeatedly revisiting the same subset.
    """
    return await conn.fetch(
        "SELECT id, url FROM resources ORDER BY last_verified ASC NULLS FIRST, id LIMIT $1",
        limit,
    )


async def record_link_check(
    conn: asyncpg.Connection,
    resource_id: int,
    verdict: LinkVerdict,
    reason: str | None,
    max_failures: int,
) -> LinkCheckTransition:
    """Apply one link-check verdict to a resource and report the transition.

    A `healthy` verdict always wins: it stamps `last_verified` and clears
    every failure signal, whether the resource was previously clean
    (`"verified"`) or already excluded (`"recovered"`) — a resource returns
    to retrieval on its own, with no manual reinstatement.
    """
    if verdict == "healthy":
        was_dead = await conn.fetchval(
            "SELECT dead_since IS NOT NULL FROM resources WHERE id = $1", resource_id
        )
        await conn.execute(
            """
            UPDATE resources
            SET last_verified = now(),
                consecutive_failures = 0,
                dead_since = NULL,
                last_check_error = NULL
            WHERE id = $1
            """,
            resource_id,
        )
        return "recovered" if was_dead else "verified"

    if verdict == "gone":
        # COALESCE preserves the first dead_since across repeat checks, so
        # the record of *when* a resource died survives being re-observed
        # dead — only a healthy check ever clears it.
        was_dead = await conn.fetchval(
            "SELECT dead_since IS NOT NULL FROM resources WHERE id = $1", resource_id
        )
        await conn.execute(
            """
            UPDATE resources
            SET consecutive_failures = consecutive_failures + 1,
                dead_since = COALESCE(dead_since, now()),
                last_check_error = $2
            WHERE id = $1
            """,
            resource_id,
            reason,
        )
        return "still_dead" if was_dead else "newly_dead"

    # verdict == "transient": increment and mark dead only once the
    # incremented count reaches the threshold. The comparison runs in SQL
    # against the stored count (not a value read back into Python first) so
    # two concurrent runs checking the same resource can't disagree about
    # whether this observation was the one that crossed the line.
    was_dead = await conn.fetchval(
        "SELECT dead_since IS NOT NULL FROM resources WHERE id = $1", resource_id
    )
    row = await conn.fetchrow(
        """
        UPDATE resources
        SET consecutive_failures = consecutive_failures + 1,
            dead_since = CASE
                WHEN consecutive_failures + 1 >= $3 THEN COALESCE(dead_since, now())
                ELSE dead_since
            END,
            last_check_error = $2
        WHERE id = $1
        RETURNING dead_since
        """,
        resource_id,
        reason,
        max_failures,
    )
    if row["dead_since"] is None:
        return "failing"
    return "still_dead" if was_dead else "newly_dead"
