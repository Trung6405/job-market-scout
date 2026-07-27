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
