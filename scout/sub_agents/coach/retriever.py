from __future__ import annotations

import asyncpg

from scout.config import Settings
from scout.config import settings as default_settings
from scout.shared.db import get_resources_for_skills
from scout.shared.schemas import RetrievedResource
from scout.shared.skills import normalize_skill
from scout.sub_agents.coach.embeddings import embed


def _distinct_normalized(skills: list[str]) -> list[str]:
    """Canonicalize gap skill names and drop duplicates, preserving order.

    ``listing_gaps.skill`` stores the raw extracted wording ("K8s",
    "React.js"), while ``resources.skills`` is normalized on write, so the
    read side has to canonicalize before the exact pre-filter can match.
    Deduping is what keeps a skill that is a gap on twenty listings from being
    embedded and queried twenty times.
    """
    distinct: list[str] = []
    seen: set[str] = set()
    for skill in skills:
        normalized = normalize_skill(skill)
        if normalized and normalized not in seen:
            seen.add(normalized)
            distinct.append(normalized)
    return distinct


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
    as keys, mapping to the same resources.

    A skill whose exact ``skills[]`` pre-filter matches nothing maps to an
    empty list. There is deliberately no relaxed fallback: it would fire
    precisely when a skill has no genuine coverage, turning "no resource" into
    "a resource for something else" (D-CC-3).

    ``k`` overrides the configured default for one call, for a caller that
    wants fewer resources than the global setting allows.
    """
    active_settings = settings or default_settings
    normalized = _distinct_normalized(skills)
    if not normalized:
        return {}

    vectors = [embed(skill) for skill in normalized]
    by_normalized = await get_resources_for_skills(
        conn,
        normalized,
        vectors,
        k=active_settings.coach_top_k if k is None else k,
        max_age_days=active_settings.coach_resource_max_age_days,
    )

    results: dict[str, list[RetrievedResource]] = {}
    for skill in skills:
        key = normalize_skill(skill)
        if key:
            results[skill] = by_normalized.get(key, [])
    return results
