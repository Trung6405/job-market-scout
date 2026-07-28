from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from scout.shared.db import get_resources_to_check
from scout.shared.schemas import Resource


def _embedding() -> list[float]:
    return [0.1] * 384


async def _insert(conn, url: str, **overrides) -> int:
    resource = Resource(
        url=url,
        title=url,
        resource_type="repo",
        skills=["python"],
        summary="summary",
        source="test",
        **overrides,
    )
    return await conn.fetchval(
        """
        INSERT INTO resources (url, title, resource_type, skills, summary, source)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING id
        """,
        str(resource.url),
        resource.title,
        resource.resource_type,
        resource.skills,
        resource.summary,
        resource.source,
    )


async def _set_last_verified(conn, resource_id: int, when: datetime) -> None:
    await conn.execute(
        "UPDATE resources SET last_verified = $1 WHERE id = $2", when, resource_id
    )


@pytest.mark.asyncio
async def test_get_resources_to_check_prioritises_never_verified(db_pool):
    async with db_pool.acquire() as conn:
        old_id = await _insert(conn, "https://example.com/old")
        await _set_last_verified(
            conn, old_id, datetime.now(timezone.utc) - timedelta(days=10)
        )
        never_id = await _insert(conn, "https://example.com/never")

        rows = await get_resources_to_check(conn, limit=10)

    ids = [row["id"] for row in rows]
    assert ids.index(never_id) < ids.index(old_id)


@pytest.mark.asyncio
async def test_get_resources_to_check_orders_oldest_verified_first(db_pool):
    async with db_pool.acquire() as conn:
        now = datetime.now(timezone.utc)
        older_id = await _insert(conn, "https://example.com/older")
        await _set_last_verified(conn, older_id, now - timedelta(days=10))
        newer_id = await _insert(conn, "https://example.com/newer")
        await _set_last_verified(conn, newer_id, now - timedelta(days=1))

        rows = await get_resources_to_check(conn, limit=10)

    ids = [row["id"] for row in rows]
    assert ids.index(older_id) < ids.index(newer_id)


@pytest.mark.asyncio
async def test_get_resources_to_check_honours_limit(db_pool):
    async with db_pool.acquire() as conn:
        for i in range(5):
            await _insert(conn, f"https://example.com/limit{i}")

        rows = await get_resources_to_check(conn, limit=2)

    assert len(rows) == 2


@pytest.mark.asyncio
async def test_get_resources_to_check_breaks_ties_by_id(db_pool):
    async with db_pool.acquire() as conn:
        first_id = await _insert(conn, "https://example.com/tie1")
        second_id = await _insert(conn, "https://example.com/tie2")

        rows = await get_resources_to_check(conn, limit=10)

    ids = [row["id"] for row in rows if row["id"] in (first_id, second_id)]
    assert ids == [first_id, second_id]
