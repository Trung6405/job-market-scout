from __future__ import annotations

import asyncpg

from scout.config import Settings
from scout.config import settings as default_settings
from scout.shared.db import get_resources_for_skills
from scout.shared.schemas import RetrievedResource
from scout.shared.skills import normalize_skill, normalize_skills
from scout.sub_agents.coach.embeddings import embed_many


async def retrieve_for_skills(
    conn: asyncpg.Connection,
    skills: list[str],
    settings: Settings | None = None,
    k: int | None = None,
) -> dict[str, list[RetrievedResource]]:
    """Return the top resources for each gap skill, hybrid-ranked.

    Takes raw gap skill names as stored — variants and duplicates included —
    and returns a dict keyed by the **caller's original strings**, so a caller
    holding a ``SkillGap`` can look up its resources without knowing anything
    about normalization. Two spellings of the same skill therefore both appear
    as keys, mapping to equal (but not shared) lists.

    **Every skill passed in gets a key**, including one that normalizes to
    nothing at all. Such a skill has no coverage by definition, so an empty
    list is not merely safe but correct: a caller must be able to tell "no
    resource for this" apart from a missing entry, and indexing the result by
    a gap's own skill string must never raise.

    A skill whose exact ``skills[]`` pre-filter matches nothing likewise maps
    to an empty list. There is deliberately no relaxed fallback: it would fire
    precisely when a skill has no genuine coverage, turning "no resource" into
    "a resource for something else" (D-CC-3).

    ``k`` overrides the configured default for one call, for a caller that
    wants fewer resources than the global setting allows.
    """
    active_settings = settings or default_settings
    normalized = normalize_skills(skills)
    if not normalized:
        return {skill: [] for skill in skills}

    vectors = embed_many(normalized)
    by_normalized = await get_resources_for_skills(
        conn,
        normalized,
        vectors,
        k=active_settings.coach_top_k if k is None else k,
        max_age_days=active_settings.coach_resource_max_age_days,
    )

    # A fresh list per key: two spellings of one skill share a normalized
    # entry, and a caller sorting or trimming one must not mutate the other.
    return {
        skill: list(by_normalized.get(normalize_skill(skill), [])) for skill in skills
    }
