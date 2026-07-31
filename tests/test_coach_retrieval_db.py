from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from scout.shared.db import get_resources_for_skills, vector_text

# Distinct unit vectors make ranking assertions exact rather than approximate:
# a query vector equal to one of them scores 1.0 against it and 0.0 against
# every other, so "nearest first" is unambiguous.
_DIMS = 384


def _unit(index: int) -> list[float]:
    vector = [0.0] * _DIMS
    vector[index] = 1.0
    return vector


async def _seed_resource(
    conn,
    url: str,
    skills: list[str],
    embedding: list[float] | None,
    last_verified: datetime | None = None,
    title: str | None = None,
    dead_since: datetime | None = None,
) -> None:
    await conn.execute(
        """
        INSERT INTO resources
            (url, title, resource_type, skills, summary, embedding, source,
             last_verified, dead_since)
        VALUES ($1, $2, 'repo', $3, 'Seeded test resource.', $4::vector, 'test', $5, $6)
        """,
        url,
        title or url.rsplit("/", 1)[-1],
        skills,
        None if embedding is None else vector_text(embedding),
        last_verified,
        dead_since,
    )


@pytest.mark.asyncio
async def test_prefilter_excludes_other_skills_and_ranks_by_similarity(db_pool):
    """The pre-filter, not the vector distance, is what keeps wrong skills out.

    The java row is seeded with an embedding *identical* to the nearest
    kubernetes row, so if it leaks into the result the pre-filter is broken —
    similarity alone could never separate them.
    """
    async with db_pool.acquire() as conn:
        await _seed_resource(conn, "https://example.com/k8s-near", ["kubernetes"], _unit(0))
        await _seed_resource(conn, "https://example.com/k8s-far", ["kubernetes"], _unit(5))
        await _seed_resource(conn, "https://example.com/java", ["java"], _unit(0))

        results = await get_resources_for_skills(
            conn, ["kubernetes"], [_unit(0)], k=3, max_age_days=90
        )

    urls = [str(resource.url) for resource in results["kubernetes"]]
    assert urls == ["https://example.com/k8s-near", "https://example.com/k8s-far"]
    assert results["kubernetes"][0].similarity > results["kubernetes"][1].similarity


@pytest.mark.asyncio
async def test_returns_at_most_k_nearest(db_pool):
    async with db_pool.acquire() as conn:
        for index in range(4):
            await _seed_resource(
                conn, f"https://example.com/k8s-{index}", ["kubernetes"], _unit(index)
            )

        results = await get_resources_for_skills(
            conn, ["kubernetes"], [_unit(0)], k=3, max_age_days=90
        )

    assert len(results["kubernetes"]) == 3
    # unit(0) is the query, so k8s-0 scores 1.0 and the rest tie at 0.0 —
    # only the exact match's position is deterministic, which is all that
    # "the nearest survives the limit" needs.
    assert str(results["kubernetes"][0].url) == "https://example.com/k8s-0"


@pytest.mark.asyncio
async def test_maps_each_skill_to_its_own_resources(db_pool):
    """A skill with no coverage maps to [] — never to another skill's rows."""
    async with db_pool.acquire() as conn:
        await _seed_resource(conn, "https://example.com/k8s", ["kubernetes"], _unit(0))
        await _seed_resource(conn, "https://example.com/react", ["react"], _unit(1))

        results = await get_resources_for_skills(
            conn,
            ["kubernetes", "react", "rust"],
            [_unit(0), _unit(1), _unit(2)],
            k=3,
            max_age_days=90,
        )

    assert set(results) == {"kubernetes", "react", "rust"}
    assert [str(r.url) for r in results["kubernetes"]] == ["https://example.com/k8s"]
    assert [str(r.url) for r in results["react"]] == ["https://example.com/react"]
    assert results["rust"] == []


@pytest.mark.asyncio
async def test_empty_skill_list_returns_empty_mapping(db_pool):
    async with db_pool.acquire() as conn:
        assert await get_resources_for_skills(conn, [], [], k=3, max_age_days=90) == {}


@pytest.mark.asyncio
async def test_excludes_stale_and_unrankable_resources(db_pool):
    """Only live, rankable rows come back.

    A NULL `last_verified` means "never checked" — trusted, since a freshly
    aggregated resource must be retrievable before its first link-health
    check. A resource whose last successful check has aged past
    `max_age_days` is excluded independently of link health (FR-CC-10).
    """
    now = datetime.now(UTC)
    async with db_pool.acquire() as conn:
        await _seed_resource(conn, "https://example.com/never", ["kubernetes"], _unit(0))
        await _seed_resource(
            conn,
            "https://example.com/fresh",
            ["kubernetes"],
            _unit(1),
            last_verified=now - timedelta(days=1),
        )
        await _seed_resource(
            conn,
            "https://example.com/stale",
            ["kubernetes"],
            _unit(2),
            last_verified=now - timedelta(days=200),
        )
        await _seed_resource(
            conn, "https://example.com/unrankable", ["kubernetes"], None
        )

        results = await get_resources_for_skills(
            conn, ["kubernetes"], [_unit(0)], k=10, max_age_days=90
        )

    assert {str(r.url) for r in results["kubernetes"]} == {
        "https://example.com/never",
        "https://example.com/fresh",
    }


@pytest.mark.asyncio
async def test_excludes_dead_resources(db_pool):
    """A resource marked dead by the link-health checker (P5) is never
    returned, even though it is otherwise a perfect, freshly-embedded match."""
    now = datetime.now(UTC)
    async with db_pool.acquire() as conn:
        await _seed_resource(conn, "https://example.com/alive", ["kubernetes"], _unit(0))
        await _seed_resource(
            conn,
            "https://example.com/dead",
            ["kubernetes"],
            _unit(0),
            dead_since=now,
        )

        results = await get_resources_for_skills(
            conn, ["kubernetes"], [_unit(0)], k=10, max_age_days=90
        )

    assert {str(r.url) for r in results["kubernetes"]} == {
        "https://example.com/alive",
    }


@pytest.mark.asyncio
async def test_skill_with_only_a_dead_resource_maps_to_empty_list(db_pool):
    async with db_pool.acquire() as conn:
        await _seed_resource(
            conn,
            "https://example.com/onlydead",
            ["rust"],
            _unit(0),
            dead_since=datetime.now(UTC),
        )

        results = await get_resources_for_skills(
            conn, ["rust"], [_unit(0)], k=10, max_age_days=90
        )

    assert results["rust"] == []


@pytest.mark.asyncio
async def test_never_checked_resource_stays_retrievable(db_pool):
    """A freshly aggregated resource — last_verified, dead_since, and
    consecutive_failures all at their defaults — must be usable before its
    first link-health check."""
    async with db_pool.acquire() as conn:
        await _seed_resource(conn, "https://example.com/fresh-agg", ["go"], _unit(0))

        results = await get_resources_for_skills(
            conn, ["go"], [_unit(0)], k=10, max_age_days=90
        )

    assert {str(r.url) for r in results["go"]} == {"https://example.com/fresh-agg"}


@pytest.mark.asyncio
async def test_resource_below_failure_threshold_stays_retrievable(db_pool):
    """Failing, but not yet dead, is not the same as dead."""
    async with db_pool.acquire() as conn:
        await _seed_resource(conn, "https://example.com/failing", ["ruby"], _unit(0))
        await conn.execute(
            "UPDATE resources SET consecutive_failures = 2 WHERE url = $1",
            "https://example.com/failing",
        )

        results = await get_resources_for_skills(
            conn, ["ruby"], [_unit(0)], k=10, max_age_days=90
        )

    assert {str(r.url) for r in results["ruby"]} == {"https://example.com/failing"}


@pytest.mark.asyncio
async def test_each_skill_is_ranked_by_its_own_query_vector(db_pool):
    """Pins the skills/vectors pairing in the parallel-array unnest.

    Two skills, two rows each, with each skill's query vector favouring a
    *different* position — so an off-by-one in the `q(skill, vec)` pairing
    flips both orderings. Every other test in this file uses either one skill
    or one row per skill, where a misalignment would go unnoticed.
    """
    async with db_pool.acquire() as conn:
        await _seed_resource(conn, "https://example.com/a-first", ["alpha"], _unit(0))
        await _seed_resource(conn, "https://example.com/a-second", ["alpha"], _unit(1))
        await _seed_resource(conn, "https://example.com/b-first", ["beta"], _unit(2))
        await _seed_resource(conn, "https://example.com/b-second", ["beta"], _unit(3))

        results = await get_resources_for_skills(
            conn,
            ["alpha", "beta"],
            [_unit(1), _unit(2)],  # alpha favours a-second, beta favours b-first
            k=2,
            max_age_days=90,
        )

    assert [str(r.url) for r in results["alpha"]] == [
        "https://example.com/a-second",
        "https://example.com/a-first",
    ]
    assert [str(r.url) for r in results["beta"]] == [
        "https://example.com/b-first",
        "https://example.com/b-second",
    ]
