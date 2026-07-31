from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import NamedTuple

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
from scout.sub_agents.coach.github_search import (
    fetch_readme,
    fetch_repo_metadata,
    passes_quality_bar,
    search_candidates,
)
from scout.sub_agents.coach.tagging import tag_readme

logger = logging.getLogger("scout.coach.runner")

# GitHub's Search API caps authenticated requests at 30/minute — far
# stricter than the 5000/hr core REST limit. A weekly run's skill list can
# run into the hundreds, so calls are throttled to stay under that cap
# rather than bursting through it (see plan.md's Risks & Unknowns).
_SEARCH_THROTTLE_SECONDS = 2.5

# Skipping a failed candidate is right for one bad response and wrong for a bad
# run: a revoked token, a provider outage or a broken prompt fails every
# candidate alike, and a run that skipped all of them would report success
# having written nothing. Both parts of the threshold earn their place — the
# floor stops a run aborting on its first few candidates, when any failure is
# 100% of what has been processed, and the rate is what actually catches a
# systemic fault in a long run.
#
# Tuned against a single observation (one malformed response in ~920), so it is
# a starting point, not a measurement. The failed count is in the run summary
# precisely so the next few runs characterise it; both values are module
# constants because changing them should be a one-line edit.
_MIN_FAILURES_BEFORE_ABORT = 10
_ABORT_FAILURE_RATE = 0.2


def _is_rate_limited(exc: BaseException) -> bool:
    """Whether an exception is GitHub saying "you are out of quota".

    Deliberately narrow. A 403 *without* an exhausted quota is a private,
    blocked or DMCA'd repo — one bad candidate, which the ingest loop skips.
    A 403 *with* one means every candidate after it fails identically, so
    skipping would leave the corpus quietly short by however long the limit
    lasted and look exactly like "those repos didn't qualify".

    Mirrors the check `fetch_repo_metadata` already makes, so both layers agree
    on what a 403 means. The duplication is the cost of leaving
    `github_search.py` untouched by this phase; a shared predicate would be
    better and is noted as follow-up work.
    """
    response = getattr(exc, "response", None)
    return (
        response is not None
        and response.status_code == 403
        and response.headers.get("X-RateLimit-Remaining") == "0"
    )


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
    harvested: list[str] = []
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
        before = len(harvested)
        for url in harvest_awesome_list(list_url, settings):
            if url not in seen:
                seen.add(url)
                harvested.append(url)
        logger.info(
            "Harvested %s: +%d new candidate(s) (%d total).",
            list_url,
            len(harvested) - before,
            len(harvested),
        )
    # Filter the bootstrap pool to FR-CC-2's bar before anything is tagged.
    # The per-skill searches push those filters into the query and get them for
    # free; a harvested README link has had no filtering at all, so each one
    # costs a core-REST metadata call here. That is the cheap side of the trade:
    # a rejected candidate would otherwise cost an LLM tagging call (~1.5s) and
    # then sit in the corpus permanently, popular and maintained or not.
    #
    # Deliberately after the cross-list dedup above, so a repo linked from two
    # awesome-lists is asked about once.
    bootstrap: list[str] = []
    dropped = 0
    unavailable = 0
    filter_started = time.monotonic()
    # Threads rather than asyncio: `fetch_repo_metadata` is blocking `requests`
    # IO and this whole function already runs inside a worker thread, so there
    # is no event loop here to await on.
    #
    # `executor.map` yields in submission order, which is what keeps the
    # kept-order stable — the ingest loop walks that order, so shuffling it
    # would undo phase 1's ordering work. An exception surfaces when its result
    # is read, so a rate-limited filter still propagates rather than silently
    # dropping every remaining candidate.
    filter_width = max(1, settings.coach_ingest_concurrency)
    executor = ThreadPoolExecutor(max_workers=filter_width)
    try:
        metadata_results = executor.map(
            lambda url: fetch_repo_metadata(url, settings), harvested
        )
        for position, (url, metadata) in enumerate(
            zip(harvested, metadata_results), start=1
        ):
            if metadata is None:
                unavailable += 1
                continue
            if not passes_quality_bar(metadata):
                dropped += 1
                continue
            bootstrap.append(url)
            if position % 100 == 0 or position == len(harvested):
                logger.info(
                    "Bootstrap filter: %d/%d checked, %d kept, %d below the bar, "
                    "%d gone or inaccessible, %.1f min elapsed.",
                    position,
                    len(harvested),
                    len(bootstrap),
                    dropped,
                    unavailable,
                    (time.monotonic() - filter_started) / 60,
                )
    finally:
        # `cancel_futures=True` matters: `map` submits every URL up front, so
        # without it a rate limit raised on the first result would still let the
        # remaining hundreds of requests run — hammering an API that has already
        # said stop. A plain `with` block cannot do this; it waits instead.
        executor.shutdown(wait=False, cancel_futures=True)
    logger.info(
        "Bootstrap filter done in %.1f min: %d of %d harvested links kept "
        "(%d below the bar — that many LLM tagging calls avoided — and "
        "%d gone or inaccessible, which would have died at the README fetch).",
        (time.monotonic() - filter_started) / 60,
        len(bootstrap),
        len(harvested),
        dropped,
        unavailable,
    )

    # Accumulated separately from the bootstrap pool, because the *returned*
    # order decides what a truncated ingest gets through. See the return below.
    searched: list[str] = []
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
                searched.append(url)
        # Periodic, not per-skill: hundreds of skills would bury the log.
        if index % 25 == 0 or index == len(skills):
            elapsed = time.monotonic() - started
            remaining = (len(skills) - index) * _SEARCH_THROTTLE_SECONDS
            logger.info(
                "Gather progress: %d/%d skills searched, %d candidate(s) so far, "
                "%.1f min elapsed, ~%.1f min of throttle left.",
                index,
                len(skills),
                len(bootstrap) + len(searched),
                elapsed / 60,
                remaining / 60,
            )
    logger.info(
        "Gather phase done in %.1f min: %d candidate(s) — %d from skill search "
        "(ingested first) then %d from awesome lists.",
        (time.monotonic() - started) / 60,
        len(searched) + len(bootstrap),
        len(searched),
        len(bootstrap),
    )
    # Search-derived first, deliberately. Ingest walks this list serially and
    # may not finish: it can time out, be cancelled, or abort. Whatever it got
    # through is the corpus, so the candidates found by searching a real unmet
    # gap skill have to come before general awesome-list material. The run that
    # produced 957 rows and zero cloud tips died at 920/1534 — entirely inside
    # the bootstrap pool, having never reached a single gap-matched repo.
    #
    # Only the order changes. Both pools are still filtered and deduplicated
    # exactly as before, and `seen` still spans both, so a repo that is both
    # harvested and searched is tagged once.
    return searched + bootstrap


class PreparedCandidate(NamedTuple):
    """One candidate fetched, tagged and embedded — everything but the write."""

    url: str
    resource: Resource
    embedding: list[float]


async def _prepare_candidate(
    url: str, settings: Settings
) -> PreparedCandidate | None:
    """Fetch, tag and embed one candidate. Returns None if it has no README.

    Deliberately touches no database. This is the seam concurrency needs: the
    expensive part of a candidate is IO-bound and independent per URL, while
    the insert is neither, so this can overlap while writes stay serial on the
    single open connection.

    Failures propagate rather than being caught here. The caller owns the
    isolation policy — skip a bad candidate, escalate a rate limit, abort on a
    systemic rate — and that policy has to stay in one place.
    """
    readme = await asyncio.to_thread(fetch_readme, url, settings)
    if readme is None:
        # Doubles as the "has a README" filter, and it comes first so a bare
        # repo costs neither a tagging call nor an embedding.
        return None
    tags = await tag_readme(readme, settings)
    resource = Resource(
        url=url,
        title=_title_from_url(url),
        resource_type=tags.resource_type,
        skills=_canonical_skills(tags.skills),
        level=tags.level,
        summary=tags.summary,
        source="github",
    )
    # Off the event loop, for the reason the fetch above already is: embedding
    # is CPU-bound local inference (D-CC-4), and the first call also loads the
    # model. Called inline it blocked the loop while the asyncpg pool was open.
    embedding = await asyncio.to_thread(embed, tags.summary)
    return PreparedCandidate(url=url, resource=resource, embedding=embedding)


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
        failed = 0
        ingest_started = time.monotonic()
        # One connection for the whole ingest loop rather than one
        # acquire/release per row; the blocking README fetch goes through a
        # worker thread so the loop's awaits stay serviceable.
        width = max(1, active_settings.coach_ingest_concurrency)
        async with pool.acquire() as conn:
            position = 0
            for start in range(0, len(new_urls), width):
                chunk = new_urls[start : start + width]
                # Prepare the chunk concurrently, then write it serially. The
                # split is the whole design: fetch/tag/embed are IO-bound and
                # independent per URL, while inserts share this one connection.
                #
                # `return_exceptions=True` so one bad candidate does not cancel
                # its chunk-mates — without it, `gather` propagates the first
                # exception and the sibling coroutines' work is thrown away,
                # which would reintroduce phase 1's bug at chunk granularity.
                outcomes = await asyncio.gather(
                    *(_prepare_candidate(url, active_settings) for url in chunk),
                    return_exceptions=True,
                )
                for url, outcome in zip(chunk, outcomes):
                    position += 1
                    # Unconditional, before any `continue`: a run whose
                    # candidates are mostly failing or README-less is precisely
                    # the one whose progress must stay visible.
                    if position % 20 == 0 or position == len(new_urls):
                        elapsed = time.monotonic() - ingest_started
                        # Effective seconds per candidate, not per serial call:
                        # this is the figure that shows whether concurrency is
                        # actually working. A width that is silently ineffective
                        # leaves it unchanged.
                        per_item = elapsed / position
                        logger.info(
                            "Ingest progress: %d/%d candidates, %d inserted, "
                            "%d duplicate(s), %d without a README, %d failed, "
                            "%.1f min elapsed (%.1fs each, ~%.1f min left).",
                            position,
                            len(new_urls),
                            inserted,
                            duplicates,
                            no_readme,
                            failed,
                            elapsed / 60,
                            per_item,
                            per_item * (len(new_urls) - position) / 60,
                        )
                    if isinstance(outcome, BaseException):
                        # `return_exceptions=True` turns a raise into a value,
                        # so every escalation phase 1 established has to be
                        # re-applied by hand here. Order matters and mirrors
                        # the serial version exactly.
                        if not isinstance(outcome, Exception):
                            # CancelledError and friends. A cancelled step must
                            # not be recorded as one skipped candidate per
                            # remaining URL.
                            raise outcome
                        if _is_rate_limited(outcome):
                            # Not a failed candidate — the end of the run. Every
                            # candidate after it would fail identically.
                            raise outcome
                        failed += 1
                        # WARNING with the URL and the exception type: a skipped
                        # candidate has to be legible in the run log, or
                        # "silently thinner corpus" becomes indistinguishable
                        # from "nothing matched".
                        logger.warning(
                            "Skipping candidate %s — %s: %s",
                            url,
                            type(outcome).__name__,
                            outcome,
                        )
                        # Chained, so the abort says how many failed and the
                        # cause says what they looked like.
                        if failed > max(
                            _MIN_FAILURES_BEFORE_ABORT, position * _ABORT_FAILURE_RATE
                        ):
                            raise RuntimeError(
                                f"Aborting aggregation: {failed} of {position} "
                                f"candidates processed have failed, which looks "
                                f"systemic rather than incidental. "
                                f"{inserted} resource(s) were inserted before this."
                            ) from outcome
                        continue
                    if outcome is None:
                        no_readme += 1
                        continue
                    result = await insert_resource(
                        conn, outcome.resource, outcome.embedding
                    )
                    if result == "new":
                        inserted += 1
                    else:
                        duplicates += 1
        # Every candidate lands in exactly one of these buckets, so the four
        # counts plus the already-stored ones account for the whole run. That
        # is what makes a degraded run legible without opening the code.
        logger.info(
            "Aggregation complete in %.1f min: %d inserted, %d duplicate(s), "
            "%d without a README, %d failed, out of %d seen.",
            (time.monotonic() - ingest_started) / 60,
            inserted,
            duplicates,
            no_readme,
            failed,
            len(candidate_urls),
        )
        return CoachSummary(
            candidates_seen=len(candidate_urls),
            inserted=inserted,
            duplicates=duplicates,
            failed=failed,
        )
    finally:
        await pool.close()
