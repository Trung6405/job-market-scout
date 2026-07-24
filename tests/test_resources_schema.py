from __future__ import annotations

import asyncpg
import pytest


@pytest.mark.asyncio
async def test_vector_extension_installed(db_pool):
    async with db_pool.acquire() as conn:
        installed = await conn.fetchval(
            "SELECT 1 FROM pg_extension WHERE extname = 'vector'"
        )
    assert installed == 1


@pytest.mark.asyncio
async def test_resources_table_exists(db_pool):
    async with db_pool.acquire() as conn:
        relname = await conn.fetchval("SELECT to_regclass('public.resources')")
    assert relname == "resources"


@pytest.mark.asyncio
async def test_resources_embedding_roundtrips(db_pool):
    # pgvector accepts a bracketed, comma-separated text form cast to ::vector.
    embedding = "[" + ",".join("0.1" for _ in range(384)) + "]"
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO resources (url, title, resource_type, skills, source, embedding)
            VALUES ($1, $2, $3, $4, $5, $6::vector)
            """,
            "https://example.com/repo",
            "Example Repo",
            "repo",
            ["python", "fastapi"],
            "test",
            embedding,
        )
        stored = await conn.fetchval(
            "SELECT embedding::text FROM resources WHERE url = $1",
            "https://example.com/repo",
        )
    assert stored is not None
    # 384 components → 383 separating commas in pgvector's text output.
    assert stored.count(",") == 383


@pytest.mark.asyncio
async def test_resources_url_is_unique(db_pool):
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO resources (url, title, resource_type, skills, source) "
            "VALUES ($1, $2, $3, $4, $5)",
            "https://example.com/dup", "One", "repo", ["python"], "test",
        )
        with pytest.raises(asyncpg.UniqueViolationError):
            await conn.execute(
                "INSERT INTO resources (url, title, resource_type, skills, source) "
                "VALUES ($1, $2, $3, $4, $5)",
                "https://example.com/dup", "Two", "repo", ["go"], "test",
            )
