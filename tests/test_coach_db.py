from __future__ import annotations

from datetime import date

import pytest

from scout.shared.db import (
    get_distinct_gap_skills,
    get_resource_urls,
    insert_resource,
    record_listing_gaps,
    record_run_listings,
    start_run,
    upsert_listing,
)
from scout.shared.schemas import Resource, SkillGap


def _embedding() -> list[float]:
    return [0.1] * 384


@pytest.mark.asyncio
async def test_insert_resource_returns_new_then_duplicate(db_pool):
    resource = Resource(
        url="https://github.com/kubernetes/kubernetes",
        title="kubernetes/kubernetes",
        resource_type="repo",
        skills=["kubernetes"],
        summary="Container orchestration platform.",
        source="github",
    )
    async with db_pool.acquire() as conn:
        first = await insert_resource(conn, resource, _embedding())
        second = await insert_resource(conn, resource, _embedding())
    assert first == "new"
    assert second == "duplicate"


@pytest.mark.asyncio
async def test_insert_resource_stores_embedding(db_pool):
    resource = Resource(
        url="https://github.com/helm/helm",
        title="helm/helm",
        resource_type="repo",
        skills=["kubernetes", "helm"],
        level="intermediate",
        summary="Package manager for Kubernetes.",
        source="github",
    )
    async with db_pool.acquire() as conn:
        await insert_resource(conn, resource, _embedding())
        stored = await conn.fetchrow(
            "SELECT skills, level, embedding::text FROM resources WHERE url = $1",
            "https://github.com/helm/helm",
        )
    assert stored["skills"] == ["kubernetes", "helm"]
    assert stored["level"] == "intermediate"
    assert stored["embedding"].count(",") == 383


@pytest.mark.asyncio
async def test_get_resource_urls_returns_stored_urls(db_pool):
    resource = Resource(
        url="https://github.com/argoproj/argo-cd",
        title="argoproj/argo-cd",
        resource_type="repo",
        skills=["kubernetes", "gitops"],
        summary="Declarative GitOps CD for Kubernetes.",
        source="github",
    )
    async with db_pool.acquire() as conn:
        assert await get_resource_urls(conn) == set()
        await insert_resource(conn, resource, _embedding())
        assert await get_resource_urls(conn) == {"https://github.com/argoproj/argo-cd"}


@pytest.mark.asyncio
async def test_get_distinct_gap_skills_dedupes_across_listings(
    db_pool, match_factory, listing_factory
):
    async with db_pool.acquire() as conn:
        run_id = await start_run(conn, date(2026, 7, 25))
        listing_one = listing_factory(external_id="ext-1", url="https://example.com/1")
        listing_two = listing_factory(external_id="ext-2", url="https://example.com/2")
        await upsert_listing(conn, listing_one)
        await upsert_listing(conn, listing_two)
        match_one = match_factory(listing=listing_one)
        match_two = match_factory(listing=listing_two)
        await record_run_listings(
            conn, run_id, [(match_one, "competitive"), (match_two, "competitive")]
        )
        gap = SkillGap(skill="kubernetes", requirement_level="must_have", met=False)
        await record_listing_gaps(
            conn, run_id, [(match_one, [gap]), (match_two, [gap])]
        )
        skills = await get_distinct_gap_skills(conn)
    assert skills == ["kubernetes"]
