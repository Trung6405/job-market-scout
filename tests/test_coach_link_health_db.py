from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from scout.shared.db import (
    get_resources_for_skills,
    get_resources_to_check,
    record_link_check,
    vector_text,
)
from scout.shared.schemas import Resource

_DIMS = 384


def _unit(index: int) -> list[float]:
    vector = [0.0] * _DIMS
    vector[index] = 1.0
    return vector


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


async def _row(conn, resource_id: int):
    return await conn.fetchrow(
        "SELECT last_verified, consecutive_failures, dead_since, last_check_error "
        "FROM resources WHERE id = $1",
        resource_id,
    )


@pytest.mark.asyncio
async def test_record_link_check_healthy_verifies_a_clean_row(db_pool):
    async with db_pool.acquire() as conn:
        resource_id = await _insert(conn, "https://example.com/clean")

        transition = await record_link_check(
            conn, resource_id, verdict="healthy", reason=None, max_failures=3
        )
        row = await _row(conn, resource_id)

    assert transition == "verified"
    assert row["last_verified"] is not None
    assert row["consecutive_failures"] == 0
    assert row["dead_since"] is None
    assert row["last_check_error"] is None


@pytest.mark.asyncio
async def test_record_link_check_healthy_recovers_a_dead_row(db_pool):
    async with db_pool.acquire() as conn:
        resource_id = await _insert(conn, "https://example.com/recovering")
        await conn.execute(
            "UPDATE resources SET dead_since = now(), consecutive_failures = 3, "
            "last_check_error = 'HTTP 404' WHERE id = $1",
            resource_id,
        )

        transition = await record_link_check(
            conn, resource_id, verdict="healthy", reason=None, max_failures=3
        )
        row = await _row(conn, resource_id)

    assert transition == "recovered"
    assert row["consecutive_failures"] == 0
    assert row["dead_since"] is None
    assert row["last_check_error"] is None


@pytest.mark.asyncio
async def test_record_link_check_gone_kills_on_first_observation(db_pool):
    async with db_pool.acquire() as conn:
        resource_id = await _insert(conn, "https://example.com/gone")

        transition = await record_link_check(
            conn, resource_id, verdict="gone", reason="HTTP 404", max_failures=3
        )
        row = await _row(conn, resource_id)

    assert transition == "newly_dead"
    assert row["dead_since"] is not None
    assert row["consecutive_failures"] == 1
    assert row["last_check_error"] == "HTTP 404"
    assert row["last_verified"] is None


@pytest.mark.asyncio
async def test_record_link_check_gone_twice_keeps_original_dead_since(db_pool):
    async with db_pool.acquire() as conn:
        resource_id = await _insert(conn, "https://example.com/stillgone")

        await record_link_check(
            conn, resource_id, verdict="gone", reason="HTTP 404", max_failures=3
        )
        first_dead_since = (await _row(conn, resource_id))["dead_since"]

        transition = await record_link_check(
            conn, resource_id, verdict="gone", reason="HTTP 404", max_failures=3
        )
        row = await _row(conn, resource_id)

    assert transition == "still_dead"
    assert row["dead_since"] == first_dead_since
    assert row["consecutive_failures"] == 2


@pytest.mark.asyncio
async def test_record_link_check_transient_failing_until_threshold(db_pool):
    async with db_pool.acquire() as conn:
        resource_id = await _insert(conn, "https://example.com/flaky")

        first = await record_link_check(
            conn, resource_id, verdict="transient", reason="Timeout", max_failures=3
        )
        second = await record_link_check(
            conn, resource_id, verdict="transient", reason="Timeout", max_failures=3
        )
        third = await record_link_check(
            conn, resource_id, verdict="transient", reason="Timeout", max_failures=3
        )
        row = await _row(conn, resource_id)

    assert [first, second, third] == ["failing", "failing", "newly_dead"]
    assert row["dead_since"] is not None
    assert row["consecutive_failures"] == 3


@pytest.mark.asyncio
async def test_record_link_check_healthy_check_resets_transient_streak(db_pool):
    """One blip must not combine with an unrelated later one to kill a resource."""
    async with db_pool.acquire() as conn:
        resource_id = await _insert(conn, "https://example.com/blip")

        await record_link_check(
            conn, resource_id, verdict="transient", reason="Timeout", max_failures=3
        )
        await record_link_check(
            conn, resource_id, verdict="healthy", reason=None, max_failures=3
        )
        transition = await record_link_check(
            conn, resource_id, verdict="transient", reason="Timeout", max_failures=3
        )
        row = await _row(conn, resource_id)

    assert transition == "failing"
    assert row["dead_since"] is None
    assert row["consecutive_failures"] == 1


@pytest.mark.asyncio
async def test_dead_resource_is_absent_from_retrieval_and_reappears_on_recovery(
    db_pool,
):
    """Wires Phase 3's writer to Phase 4's reader: a verdict recorded here
    must actually change what retrieval returns, not just what's stored."""
    async with db_pool.acquire() as conn:
        resource_id = await conn.fetchval(
            """
            INSERT INTO resources (url, title, resource_type, skills, summary, embedding, source)
            VALUES ($1, $2, 'repo', $3, 'Seeded test resource.', $4::vector, 'test')
            RETURNING id
            """,
            "https://example.com/roundtrip",
            "roundtrip",
            ["kubernetes"],
            vector_text(_unit(0)),
        )

        before = await get_resources_for_skills(
            conn, ["kubernetes"], [_unit(0)], k=10, max_age_days=90
        )
        assert len(before["kubernetes"]) == 1

        await record_link_check(
            conn, resource_id, verdict="gone", reason="HTTP 404", max_failures=3
        )
        after_death = await get_resources_for_skills(
            conn, ["kubernetes"], [_unit(0)], k=10, max_age_days=90
        )
        assert after_death["kubernetes"] == []

        await record_link_check(
            conn, resource_id, verdict="healthy", reason=None, max_failures=3
        )
        after_recovery = await get_resources_for_skills(
            conn, ["kubernetes"], [_unit(0)], k=10, max_age_days=90
        )

    assert len(after_recovery["kubernetes"]) == 1
