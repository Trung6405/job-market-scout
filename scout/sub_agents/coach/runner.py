from __future__ import annotations

import asyncio
import logging
import time

import requests

from scout.config import Settings
from scout.config import settings as default_settings
from scout.shared.db import (
    create_pool,
    get_distinct_gap_skills,
    get_resource_urls,
    insert_resource,
)
from scout.shared.schemas import CoachSummary, Resource
from scout.shared.skills import normalize_skills
from scout.sub_agents.coach.bootstrap import harvest_awesome_list
from scout.sub_agents.coach.embeddings import embed
from scout.sub_agents.coach.github_search import fetch_readme, search_candidates
from scout.sub_agents.coach.tagging import tag_readme

logger = logging.getLogger("scout.coach.runner")

# GitHub's Search API caps authenticated requests at 30/minute — far
# stricter than the 5000/hr core REST limit. A weekly run's skill list can
# run into the hundreds, so calls are throttled to stay under that cap
# rather than bursting through it (see plan.md's Risks & Unknowns).
_SEARCH_THROTTLE_SECONDS = 2.5


def _title_from_url(url: str) -> str:
    return url.removeprefix("https://github.com/").rstrip("/")


def _canonical_skills(skills: list[str]) -> list[str]:
    """Normalize tagged skill names, dropping empties and duplicates.

    The tagging prompt only *asks* for canonical names, which is best-effort.
    ``resources.skills`` is the column the retriever pre-filters on by exact
    match (FR-CC-1/FR-CC-7), so the guarantee has to be deterministic. Two
    variants that normalize to the same token ("K8s", "kubernetes") collapse
    into one entry; order is preserved so the tagger's primary skill stays first.

    Delegates to the shared helper the retriever also uses on read — the two
    sides of the exact-match guarantee must not be able to drift apart.
    """
    return normalize_skills(skills)


def _gather_candidate_urls(settings: Settings, skills: list[str]) -> list[str]:
    seen: set[str] = set()
    candidates: list[str] = []
    started = time.monotonic()
    # Throttled at _SEARCH_THROTTLE_SECONDS per skill, serially, so this phase
    # costs roughly len(skills) * the throttle before anything is written.
    # Logged up front because that figure is the difference between "working"
    # and "hung", and there is no way to tell from the outside otherwise.
    logger.info(
        "Gather phase starting: %d awesome list(s) + %d distinct gap skill(s); "
        "search throttle %.1fs/skill implies >= %.0f min in this phase alone.",
        len(settings.coach_awesome_lists),
        len(skills),
        _SEARCH_THROTTLE_SECONDS,
        len(skills) * _SEARCH_THROTTLE_SECONDS / 60,
    )
    for list_url in settings.coach_awesome_lists:
        before = len(candidates)
        for url in harvest_awesome_list(list_url, settings):
            if url not in seen:
                seen.add(url)
                candidates.append(url)
        logger.info(
            "Harvested %s: +%d new candidate(s) (%d total).",
            list_url,
            len(candidates) - before,
            len(candidates),
        )
    bootstrap_total = len(candidates)
    last_search_at: float | None = None
    for index, skill in enumerate(skills, start=1):
        if last_search_at is not None:
            # Sleep only for what's left of the throttle window: request
            # latency already spent counts toward the 30/min pacing.
            elapsed = time.monotonic() - last_search_at
            time.sleep(max(0.0, _SEARCH_THROTTLE_SECONDS - elapsed))
        last_search_at = time.monotonic()
        try:
            skill_urls = search_candidates(skill, settings)
        except requests.HTTPError as exc:
            # A single skill hitting the search rate limit (or any other
            # HTTP error) must not lose candidates already gathered for
            # every other skill — log and move on.
            logger.warning("GitHub search failed for skill %r — skipping: %s", skill, exc)
            continue
        for url in skill_urls:
            if url not in seen:
                seen.add(url)
                candidates.append(url)
        # Periodic, not per-skill: hundreds of skills would bury the log.
        if index % 25 == 0 or index == len(skills):
            elapsed = time.monotonic() - started
            remaining = (len(skills) - index) * _SEARCH_THROTTLE_SECONDS
            logger.info(
                "Gather progress: %d/%d skills searched, %d candidate(s) so far, "
                "%.1f min elapsed, ~%.1f min of throttle left.",
                index,
                len(skills),
                len(candidates),
                elapsed / 60,
                remaining / 60,
            )
    logger.info(
        "Gather phase done in %.1f min: %d candidate(s) (%d from awesome lists, "
        "%d from skill search).",
        (time.monotonic() - started) / 60,
        len(candidates),
        bootstrap_total,
        len(candidates) - bootstrap_total,
    )
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

        # Runs in a worker thread: the gather loop is throttled requests +
        # time.sleep, which must not block the event loop while the asyncpg
        # pool is open.
        candidate_urls = await asyncio.to_thread(
            _gather_candidate_urls, active_settings, skills
        )
        # Dedup happens once, up front, against a single snapshot of stored
        # URLs — an already-stored candidate is skipped before any
        # README fetch, LLM tagging, or embedding call (spec requirement).
        new_urls = [url for url in candidate_urls if url not in existing_urls]
        # This is the phase that dominates a first run, not the throttled
        # gather above: one README fetch plus one LLM tagging call plus one
        # embedding per candidate, serially. Stating the count before starting
        # is what makes the duration predictable instead of alarming.
        logger.info(
            "Ingest phase starting: %d new candidate(s) to tag "
            "(%d of %d already stored).",
            len(new_urls),
            len(candidate_urls) - len(new_urls),
            len(candidate_urls),
        )

        inserted = 0
        duplicates = 0
        no_readme = 0
        ingest_started = time.monotonic()
        # One connection for the whole ingest loop rather than one
        # acquire/release per row; the blocking README fetch goes through a
        # worker thread so the loop's awaits stay serviceable.
        async with pool.acquire() as conn:
            for position, url in enumerate(new_urls, start=1):
                if position % 20 == 0 or position == len(new_urls):
                    elapsed = time.monotonic() - ingest_started
                    per_item = elapsed / position
                    logger.info(
                        "Ingest progress: %d/%d candidates, %d inserted, "
                        "%d duplicate(s), %d without a README, %.1f min elapsed "
                        "(%.1fs each, ~%.1f min left).",
                        position,
                        len(new_urls),
                        inserted,
                        duplicates,
                        no_readme,
                        elapsed / 60,
                        per_item,
                        per_item * (len(new_urls) - position) / 60,
                    )
                readme = await asyncio.to_thread(
                    fetch_readme, url, active_settings
                )
                if readme is None:
                    no_readme += 1
                    continue
                tags = await tag_readme(readme, active_settings)
                resource = Resource(
                    url=url,
                    title=_title_from_url(url),
                    resource_type=tags.resource_type,
                    skills=_canonical_skills(tags.skills),
                    level=tags.level,
                    summary=tags.summary,
                    source="github",
                )
                # Off the event loop, for the reason the fetch above already is:
                # embedding is CPU-bound local inference (D-CC-4), and the first
                # call also loads the model. Called inline it blocked the loop
                # while the asyncpg pool was open.
                embedding = await asyncio.to_thread(embed, tags.summary)
                result = await insert_resource(conn, resource, embedding)
                if result == "new":
                    inserted += 1
                else:
                    duplicates += 1
        logger.info(
            "Aggregation complete in %.1f min: %d inserted, %d duplicate(s), "
            "%d candidate(s) without a README, out of %d seen.",
            (time.monotonic() - ingest_started) / 60,
            inserted,
            duplicates,
            no_readme,
            len(candidate_urls),
        )
        return CoachSummary(
            candidates_seen=len(candidate_urls),
            inserted=inserted,
            duplicates=duplicates,
        )
    finally:
        await pool.close()
