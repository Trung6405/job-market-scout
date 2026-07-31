"""Coach resource corpus: pgvector inserts, hybrid retrieval, link health."""

from __future__ import annotations

from typing import Literal

import asyncpg

from scout.shared.schemas import LinkVerdict, Resource, RetrievedResource

LinkCheckTransition = Literal[
    "verified", "recovered", "newly_dead", "still_dead", "failing"
]


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
