# Phase 1: Shared data layer

> **Parent plan:** [plan.md](plan.md)
> **Status:** Not started
> **Depends on:** nothing (builds directly on P0's `resources` table)

---

## Goal

Give every later phase a typed `Resource`/`ResourceTags` model and three DB
helpers (`insert_resource`, `get_distinct_gap_skills`, `get_resource_urls`)
that round-trip against the real `resources` table, plus the three new
`Settings` fields the aggregator needs. No GitHub/LLM/embedding code yet —
this phase is pure data layer, independently testable against Postgres.

## Safety Checklist

- **Touches user input, auth, secrets, or external calls?**
  No external calls. `github_pat` is introduced as a new `Settings` field
  (a secret string) but nothing in this phase reads or transmits it yet.
- **Contains a one-way door (schema, public API shape, new dependency)?**
  No. No schema change (P0's DDL is untouched), no new dependency, and the
  three new `db.py`/`schemas.py` additions are pure additions with no
  existing caller to break.

---

## Pre-execution (docs commit)

Per the repo's doc-gating rule, the approved docs are committed **once,
right before this phase's code changes**:

- [ ] Commit the approved planning docs:

```bash
git add docs/agent/specs/career-coach-p1-aggregator/spec.md \
        docs/agent/plans/career-coach-p1-aggregator/plan.md \
        docs/agent/plans/career-coach-p1-aggregator/phase-1-shared-data-layer.md \
        docs/agent/plans/career-coach-p1-aggregator/phase-2-candidate-gathering-and-tagging.md \
        docs/agent/plans/career-coach-p1-aggregator/phase-3-runner-entrypoint-and-ci.md
git commit -m "docs: Career Coach P1 aggregator spec & plan

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Tasks

### Task 1: `Resource` and `ResourceTags` schemas

- **Files:**
  - Modify: `scout/shared/schemas.py`
  - Test: `tests/test_coach_schemas.py`
- **Gate:** none.
- **Interfaces:**
  - Produces: `Resource` (fields: `url: HttpUrl`, `title: str`,
    `resource_type: Literal["doc", "course", "repo", "note"]`,
    `skills: list[str]`,
    `level: Literal["beginner", "intermediate", "advanced"] | None = None`,
    `summary: str | None = None`, `source: str`) and `ResourceTags`
    (fields: `skills: list[str]`, `resource_type: Literal["doc", "course",
    "repo", "note"]`, `level: Literal["beginner", "intermediate",
    "advanced"] | None = None`, `summary: str`). `Resource` carries the
    fields a caller constructs before insert (matches the `resources`
    table minus `id`/`embedding`/`last_verified`/`created_at`, which are
    set at insert time — mirrors P0's phase doc note that those aren't
    part of a caller-constructed model). `ResourceTags` is exactly what
    Phase 2's LLM tagging call returns, separate from `Resource` because
    the tagging call never sees `url`/`title`/`source` (those come from
    the candidate metadata, not the README).

- [ ] **Step 1: Write the failing test**

Create `tests/test_coach_schemas.py`:

```python
from __future__ import annotations

import pytest
from pydantic import ValidationError

from scout.shared.schemas import Resource, ResourceTags


def test_resource_accepts_minimal_fields():
    resource = Resource(
        url="https://github.com/kubernetes/kubernetes",
        title="kubernetes/kubernetes",
        resource_type="repo",
        skills=["kubernetes"],
        source="github",
    )
    assert resource.level is None
    assert resource.summary is None
    assert str(resource.url) == "https://github.com/kubernetes/kubernetes"


def test_resource_rejects_invalid_resource_type():
    with pytest.raises(ValidationError):
        Resource(
            url="https://github.com/kubernetes/kubernetes",
            title="kubernetes/kubernetes",
            resource_type="video",
            skills=["kubernetes"],
            source="github",
        )


def test_resource_tags_accepts_minimal_fields():
    tags = ResourceTags(
        skills=["kubernetes", "helm"],
        resource_type="repo",
        summary="A Helm chart repository for Kubernetes deployments.",
    )
    assert tags.level is None


def test_resource_tags_rejects_invalid_level():
    with pytest.raises(ValidationError):
        ResourceTags(
            skills=["kubernetes"],
            resource_type="repo",
            level="guru",
            summary="A Helm chart repository.",
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_coach_schemas.py -v`
Expected: FAIL — `ImportError: cannot import name 'Resource' from
'scout.shared.schemas'`.

- [ ] **Step 3: Write minimal implementation**

In `scout/shared/schemas.py`, append after `SkillGap` (after line 108):

```python
ResourceType = Literal["doc", "course", "repo", "note"]
ResourceLevel = Literal["beginner", "intermediate", "advanced"]


class Resource(BaseModel):
    """A caller-constructed candidate row for the `resources` table.

    Excludes `id`, `embedding`, `last_verified`, and `created_at` — those
    are set at insert time by `scout.shared.db.insert_resource`, not part
    of what an aggregator builds before writing.
    """

    url: HttpUrl
    title: str
    resource_type: ResourceType
    skills: list[str]
    level: ResourceLevel | None = None
    summary: str | None = None
    source: str


class ResourceTags(BaseModel):
    """The LLM tagging pass's output for one README (P1's tagging.py)."""

    skills: list[str]
    resource_type: ResourceType
    level: ResourceLevel | None = None
    summary: str
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_coach_schemas.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add scout/shared/schemas.py tests/test_coach_schemas.py
git commit -m "feat(coach): add Resource and ResourceTags schemas

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task 2: `Settings` fields for the aggregator

- **Files:**
  - Modify: `scout/config.py`
  - Test: `tests/test_coach_config.py`
- **Gate:** none.
- **Interfaces:**
  - Produces: `Settings.github_pat: str` (default `""`),
    `Settings.coach_top_n_per_skill: int` (default `5`),
    `Settings.coach_awesome_lists: list[str]` (default: the six URLs below).
    Phase 2's `github_search.py`/`bootstrap.py` and Phase 3's `runner.py`
    read all three.

- [ ] **Step 1: Write the failing test**

Create `tests/test_coach_config.py`:

```python
from __future__ import annotations

import os

import pytest

from scout.config import Settings


@pytest.fixture(autouse=True)
def _clear_coach_env(monkeypatch):
    for name in ("GITHUB_PAT", "COACH_TOP_N_PER_SKILL", "COACH_AWESOME_LISTS"):
        monkeypatch.delenv(name, raising=False)


def test_github_pat_defaults_empty():
    assert Settings().github_pat == ""


def test_github_pat_reads_env(monkeypatch):
    monkeypatch.setenv("GITHUB_PAT", "ghp_test123")
    assert Settings().github_pat == "ghp_test123"


def test_coach_top_n_per_skill_defaults_to_five():
    assert Settings().coach_top_n_per_skill == 5


def test_coach_awesome_lists_has_six_defaults():
    lists = Settings().coach_awesome_lists
    assert len(lists) == 6
    assert "https://github.com/vinta/awesome-python" in lists


def test_coach_awesome_lists_reads_csv_env(monkeypatch):
    monkeypatch.setenv("COACH_AWESOME_LISTS", "https://github.com/a/b,https://github.com/c/d")
    assert Settings().coach_awesome_lists == [
        "https://github.com/a/b",
        "https://github.com/c/d",
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_coach_config.py -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute
'github_pat'`.

- [ ] **Step 3: Write minimal implementation**

In `scout/config.py`, add after `discord_channel_id` (after line 148, before
`profile: Profile = field(init=False)`):

```python
    github_pat: str = field(
        default_factory=partial(_env_str, "GITHUB_PAT", "")
    )
    # Candidates kept per skill after GitHub search filtering (stars,
    # pushed-within, archived, README) — bounds both API and LLM-tagging
    # spend per skill per run.
    coach_top_n_per_skill: int = field(
        default_factory=partial(_env_int, "COACH_TOP_N_PER_SKILL", 5)
    )
    # Seed coverage before per-skill search has run enough cycles to find
    # everything on its own. Default set covers the profile's current
    # domains (umbrella PRS Q1) — refinable via env, no code change needed.
    coach_awesome_lists: list[str] = field(
        default_factory=partial(
            _env_csv,
            "COACH_AWESOME_LISTS",
            "https://github.com/vinta/awesome-python,"
            "https://github.com/mjhea0/awesome-fastapi,"
            "https://github.com/enaqx/awesome-react,"
            "https://github.com/dzharii/awesome-typescript,"
            "https://github.com/veggiemonk/awesome-docker,"
            "https://github.com/kristofferandreasen/awesome-azure",
        )
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_coach_config.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add scout/config.py tests/test_coach_config.py
git commit -m "feat(coach): add github_pat/coach_top_n_per_skill/coach_awesome_lists settings

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task 3: `insert_resource`, `get_distinct_gap_skills`, `get_resource_urls`

- **Files:**
  - Modify: `scout/shared/db.py`
  - Test: `tests/test_coach_db.py`
- **Gate:** none.
- **Interfaces:**
  - Consumes: `Resource` (Task 1), the existing `db_pool` fixture
    (`tests/conftest.py`) and `listing_gaps`/`resources` tables (P0/existing
    schema — unchanged).
  - Produces: `insert_resource(conn: asyncpg.Connection, resource: Resource,
    embedding: list[float]) -> Literal["new", "duplicate"]`,
    `get_distinct_gap_skills(conn: asyncpg.Connection) -> list[str]`,
    `get_resource_urls(conn: asyncpg.Connection) -> set[str]`. Phase 3's
    `runner.py` relies on exactly these three names and signatures.

- [ ] **Step 1: Write the failing test**

Create `tests/test_coach_db.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_coach_db.py -v`
Expected: FAIL — `ImportError: cannot import name 'insert_resource' from
'scout.shared.db'`.

- [ ] **Step 3: Write minimal implementation**

In `scout/shared/db.py`, add:

```python
async def insert_resource(
    conn: asyncpg.Connection, resource: Resource, embedding: list[float]
) -> Literal["new", "duplicate"]:
    embedding_text = "[" + ",".join(str(x) for x in embedding) + "]"
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


async def get_distinct_gap_skills(conn: asyncpg.Connection) -> list[str]:
    rows = await conn.fetch(
        "SELECT DISTINCT skill FROM listing_gaps WHERE kind = 'skill' AND NOT met"
    )
    return [row["skill"] for row in rows]
```

Add `Resource` to the existing `from scout.shared.schemas import (...)`
import block at the top of `db.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_coach_db.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add scout/shared/db.py tests/test_coach_db.py
git commit -m "feat(coach): add insert_resource, get_resource_urls, get_distinct_gap_skills

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Verification

- [ ] All phase tests pass: `pytest tests/test_coach_schemas.py tests/test_coach_config.py tests/test_coach_db.py -v`
- [ ] Full regression: `pytest` (no existing test regresses).

## Rollback

Revert the three feat commits (or `git revert` them in order). All three are
pure additions with no existing caller, so reverting is safe at any point —
nothing else in the codebase imports `Resource`, `ResourceTags`,
`insert_resource`, `get_resource_urls`, `get_distinct_gap_skills`, or the
three new `Settings` fields until Phase 2/3 land.

---

## Notes / Learnings

<Filled in during execution.>
