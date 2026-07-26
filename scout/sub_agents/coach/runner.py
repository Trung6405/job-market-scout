from __future__ import annotations

import logging

from scout.config import Settings
from scout.config import settings as default_settings
from scout.shared.db import (
    create_pool,
    get_distinct_gap_skills,
    get_resource_urls,
    insert_resource,
)
from scout.shared.schemas import CoachSummary, Resource
from scout.sub_agents.coach.bootstrap import harvest_awesome_list
from scout.sub_agents.coach.embeddings import embed
from scout.sub_agents.coach.github_search import fetch_readme, search_candidates
from scout.sub_agents.coach.tagging import tag_readme

logger = logging.getLogger("scout.coach.runner")


def _title_from_url(url: str) -> str:
    return url.removeprefix("https://github.com/").rstrip("/")


def _gather_candidate_urls(settings: Settings, skills: list[str]) -> list[str]:
    seen: set[str] = set()
    candidates: list[str] = []
    for list_url in settings.coach_awesome_lists:
        for url in harvest_awesome_list(list_url, settings):
            if url not in seen:
                seen.add(url)
                candidates.append(url)
    for skill in skills:
        for url in search_candidates(skill, settings):
            if url not in seen:
                seen.add(url)
                candidates.append(url)
    return candidates


async def run_coach_aggregator(settings: Settings | None = None) -> CoachSummary:
    active_settings = settings or default_settings
    if not active_settings.github_pat:
        logger.info("GITHUB_PAT not set — skipping coach aggregator run.")
        return CoachSummary(candidates_seen=0, inserted=0, duplicates=0)

    pool = await create_pool(active_settings)
    try:
        async with pool.acquire() as conn:
            skills = await get_distinct_gap_skills(conn)
            existing_urls = await get_resource_urls(conn)

        candidate_urls = _gather_candidate_urls(active_settings, skills)
        # Dedup happens once, up front, against a single snapshot of stored
        # URLs — an already-stored candidate is skipped before any
        # README fetch, LLM tagging, or embedding call (spec requirement).
        new_urls = [url for url in candidate_urls if url not in existing_urls]

        inserted = 0
        duplicates = 0
        for url in new_urls:
            readme = fetch_readme(url, active_settings)
            if readme is None:
                continue
            tags = await tag_readme(readme, active_settings)
            resource = Resource(
                url=url,
                title=_title_from_url(url),
                resource_type=tags.resource_type,
                skills=tags.skills,
                level=tags.level,
                summary=tags.summary,
                source="github",
            )
            embedding = embed(tags.summary)
            async with pool.acquire() as conn:
                result = await insert_resource(conn, resource, embedding)
            if result == "new":
                inserted += 1
            else:
                duplicates += 1
        return CoachSummary(
            candidates_seen=len(candidate_urls),
            inserted=inserted,
            duplicates=duplicates,
        )
    finally:
        await pool.close()
