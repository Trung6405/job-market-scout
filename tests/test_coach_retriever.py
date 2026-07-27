from __future__ import annotations

import pytest

from scout.config import Settings
from scout.shared.schemas import RetrievedResource
from scout.shared.db import vector_text
from scout.shared.skills import normalize_skills
from scout.sub_agents.coach import retriever

_DIMS = 384


def _unit(index: int) -> list[float]:
    vector = [0.0] * _DIMS
    vector[index] = 1.0
    return vector


def _retrieved(url: str) -> RetrievedResource:
    return RetrievedResource(
        url=url,
        title=url.rsplit("/", 1)[-1],
        resource_type="repo",
        skills=["kubernetes"],
        summary="Seeded test resource.",
        similarity=0.9,
    )


def _test_settings(**overrides) -> Settings:
    test_db_url = Settings().database_url.rsplit("/", 1)[0] + "/scout_test"
    return Settings(database_url=test_db_url, **overrides)


def test_normalize_skills_collapses_variants():
    """Gap wording is raw as stored, so every variant has to fold to one token."""
    assert normalize_skills(
        ["K8s", "kubernetes", "React.js", "  Postgres ", "  "]
    ) == ["kubernetes", "react", "postgresql"]


@pytest.mark.asyncio
async def test_returns_results_keyed_by_original_skill_strings(monkeypatch):
    """A caller holding a SkillGap looks its resources up without re-normalizing.

    "K8s" and "kubernetes" normalize to the same token, so both keys must map
    to that token's resources — the caller never has to know they collided.
    """
    monkeypatch.setattr(retriever, "embed_many", lambda texts: [_unit(0) for _ in texts])

    async def _fake_query(conn, skills, vectors, k, max_age_days):
        return {
            "kubernetes": [_retrieved("https://example.com/k8s")],
            "react": [_retrieved("https://example.com/react")],
        }

    monkeypatch.setattr(retriever, "get_resources_for_skills", _fake_query)

    results = await retriever.retrieve_for_skills(
        None, ["K8s", "kubernetes", "React.js"], settings=_test_settings()
    )

    assert set(results) == {"K8s", "kubernetes", "React.js"}
    assert [str(r.url) for r in results["K8s"]] == ["https://example.com/k8s"]
    assert [str(r.url) for r in results["kubernetes"]] == ["https://example.com/k8s"]
    assert [str(r.url) for r in results["React.js"]] == ["https://example.com/react"]


@pytest.mark.asyncio
async def test_embeds_once_per_distinct_normalized_skill(monkeypatch):
    """A skill that is a gap on many listings must not be re-embedded per listing."""
    embedded: list[list[str]] = []

    def _fake_embed_many(texts):
        embedded.append(list(texts))
        return [_unit(0) for _ in texts]

    async def _fake_query(conn, skills, vectors, k, max_age_days):
        return {skill: [] for skill in skills}

    monkeypatch.setattr(retriever, "embed_many", _fake_embed_many)
    monkeypatch.setattr(retriever, "get_resources_for_skills", _fake_query)

    await retriever.retrieve_for_skills(
        None, ["K8s", "kubernetes", "React.js"], settings=_test_settings()
    )

    # One call, carrying every distinct skill -- not one call per skill.
    assert embedded == [["kubernetes", "react"]]


@pytest.mark.asyncio
async def test_empty_skill_list_touches_neither_embed_nor_database(monkeypatch):
    def _explode(*args, **kwargs):
        raise AssertionError("must not be called for an empty skill list")

    monkeypatch.setattr(retriever, "embed_many", _explode)
    monkeypatch.setattr(retriever, "get_resources_for_skills", _explode)

    assert await retriever.retrieve_for_skills(None, [], settings=_test_settings()) == {}


@pytest.mark.asyncio
async def test_skill_with_no_coverage_maps_to_empty_list(monkeypatch):
    monkeypatch.setattr(retriever, "embed_many", lambda texts: [_unit(0) for _ in texts])

    async def _fake_query(conn, skills, vectors, k, max_age_days):
        return {skill: [] for skill in skills}

    monkeypatch.setattr(retriever, "get_resources_for_skills", _fake_query)

    results = await retriever.retrieve_for_skills(
        None, ["Rust"], settings=_test_settings()
    )

    assert results == {"Rust": []}


@pytest.mark.asyncio
async def test_passes_configured_k_and_staleness_window(monkeypatch):
    captured: dict[str, int] = {}

    async def _fake_query(conn, skills, vectors, k, max_age_days):
        captured["k"] = k
        captured["max_age_days"] = max_age_days
        return {skill: [] for skill in skills}

    monkeypatch.setattr(retriever, "embed_many", lambda texts: [_unit(0) for _ in texts])
    monkeypatch.setattr(retriever, "get_resources_for_skills", _fake_query)

    settings = _test_settings(coach_top_k=2, coach_resource_max_age_days=30)
    await retriever.retrieve_for_skills(None, ["kubernetes"], settings=settings)

    assert captured == {"k": 2, "max_age_days": 30}


@pytest.mark.asyncio
async def test_explicit_k_overrides_the_configured_default(monkeypatch):
    """P3 may want fewer resources for one tip than the global default."""
    captured: dict[str, int] = {}

    async def _fake_query(conn, skills, vectors, k, max_age_days):
        captured["k"] = k
        return {skill: [] for skill in skills}

    monkeypatch.setattr(retriever, "embed_many", lambda texts: [_unit(0) for _ in texts])
    monkeypatch.setattr(retriever, "get_resources_for_skills", _fake_query)

    await retriever.retrieve_for_skills(
        None, ["kubernetes"], settings=_test_settings(coach_top_k=3), k=1
    )

    assert captured["k"] == 1


@pytest.mark.asyncio
async def test_end_to_end_against_seeded_rows(db_pool, monkeypatch):
    """The module and the SQL compose: real connection, real rows, real query.

    Only `embed_many` is stubbed — a deterministic query vector is what makes
    the ranking assertion exact. Everything else is the production path, so this
    is what proves normalization on the read side actually reaches the
    pre-filter: the caller asks for "K8s" and gets rows tagged "kubernetes".
    """
    monkeypatch.setattr(retriever, "embed_many", lambda texts: [_unit(0) for _ in texts])

    async with db_pool.acquire() as conn:
        for url, skills, vector in [
            ("https://example.com/k8s-near", ["kubernetes"], _unit(0)),
            ("https://example.com/k8s-far", ["kubernetes"], _unit(7)),
            ("https://example.com/java", ["java"], _unit(0)),
        ]:
            await conn.execute(
                """
                INSERT INTO resources
                    (url, title, resource_type, skills, summary, embedding, source)
                VALUES ($1, $2, 'repo', $3, 'Seeded.', $4::vector, 'test')
                """,
                url,
                url.rsplit("/", 1)[-1],
                skills,
                vector_text(vector),
            )

        results = await retriever.retrieve_for_skills(
            conn, ["K8s"], settings=_test_settings()
        )

    assert list(results) == ["K8s"]
    assert [str(r.url) for r in results["K8s"]] == [
        "https://example.com/k8s-near",
        "https://example.com/k8s-far",
    ]


@pytest.mark.asyncio
async def test_unnormalizable_skill_still_gets_a_key(monkeypatch):
    """Indexing the result by a gap's own skill string must never raise.

    A skill that normalizes to nothing has no coverage by definition, so [] is
    the correct answer rather than an absent key -- the db layer guarantees
    every requested skill gets a key, and the public API must not weaken it.
    """
    monkeypatch.setattr(
        retriever, "embed_many", lambda texts: [_unit(0) for _ in texts]
    )

    async def _fake_query(conn, skills, vectors, k, max_age_days):
        return {skill: [] for skill in skills}

    monkeypatch.setattr(retriever, "get_resources_for_skills", _fake_query)

    results = await retriever.retrieve_for_skills(
        None, ["kubernetes", "!!!", "   "], settings=_test_settings()
    )

    assert results == {"kubernetes": [], "!!!": [], "   ": []}


@pytest.mark.asyncio
async def test_all_skills_unnormalizable_still_returns_a_key_each(monkeypatch):
    def _explode(*args, **kwargs):
        raise AssertionError("nothing to embed or query")

    monkeypatch.setattr(retriever, "embed_many", _explode)
    monkeypatch.setattr(retriever, "get_resources_for_skills", _explode)

    results = await retriever.retrieve_for_skills(
        None, ["!!!", "  "], settings=_test_settings()
    )

    assert results == {"!!!": [], "  ": []}


@pytest.mark.asyncio
async def test_aliased_keys_do_not_share_a_list_object(monkeypatch):
    """Two spellings of one skill map to equal but independent lists.

    A caller trimming or sorting one key's results must not mutate the other's,
    nor the helper's internal dict.
    """
    monkeypatch.setattr(
        retriever, "embed_many", lambda texts: [_unit(0) for _ in texts]
    )

    async def _fake_query(conn, skills, vectors, k, max_age_days):
        return {"kubernetes": [_retrieved("https://example.com/k8s")]}

    monkeypatch.setattr(retriever, "get_resources_for_skills", _fake_query)

    results = await retriever.retrieve_for_skills(
        None, ["K8s", "kubernetes"], settings=_test_settings()
    )

    assert results["K8s"] == results["kubernetes"]
    assert results["K8s"] is not results["kubernetes"]
    results["K8s"].clear()
    assert len(results["kubernetes"]) == 1
