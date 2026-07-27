from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from scout.shared.db import get_resources_for_skills

# Distinct unit vectors make ranking assertions exact rather than approximate:
# a query vector equal to one of them scores 1.0 against it and 0.0 against
# every other, so "nearest first" is unambiguous.
_DIMS = 384


def _unit(index: int) -> list[float]:
    vector = [0.0] * _DIMS
    vector[index] = 1.0
    return vector


def _vec_text(values: list[float]) -> str:
    return "[" + ",".join(str(value) for value in values) + "]"


async def _seed_resource(
    conn,
    url: str,
    skills: list[str],
    embedding: list[float] | None,
    last_verified: datetime | None = None,
    title: str | None = None,
) -> None:
    await conn.execute(
        """
        INSERT INTO resources
            (url, title, resource_type, skills, summary, embedding, source, last_verified)
        VALUES ($1, $2, 'repo', $3, 'Seeded test resource.', $4::vector, 'test', $5)
        """,
        url,
        title or url.rsplit("/", 1)[-1],
        skills,
        None if embedding is None else _vec_text(embedding),
        last_verified,
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
