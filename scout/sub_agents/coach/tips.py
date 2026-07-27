from __future__ import annotations

import logging

import asyncpg

from scout.config import Settings
from scout.config import settings as default_settings
from scout.prompts import build_coach_tips_instruction
from scout.shared.batching import batches, run_batches
from scout.shared.llm import complete_json
from scout.shared.schemas import (
    GeneratedTips,
    GroundedTip,
    MatchResult,
    RetrievedResource,
    SkillGap,
)
from scout.sub_agents.coach.grounding import validate_grounding
from scout.sub_agents.coach.retriever import retrieve_for_skills

logger = logging.getLogger(__name__)


def _tippable_gaps(checks: list[SkillGap], limit: int) -> list[SkillGap]:
    """Unmet skill gaps only, must-haves first, capped.

    Mirrors ``get_run_details``' definition of a gap: non-skill kinds pass
    through ``evaluate_requirements`` as met by construction, and the
    corpus holds nothing for a degree or a years-of-experience bar anyway.
    """
    gaps = [check for check in checks if check.kind == "skill" and not check.met]
    gaps.sort(key=lambda gap: gap.requirement_level != "must_have")
    return gaps[:limit]


def _to_grounded_tips(
    match: MatchResult,
    resources_by_skill: dict[str, list[RetrievedResource]],
    generated: GeneratedTips,
) -> list[GroundedTip]:
    """Validate the model's reply into storable tips.

    Four ways a tip dies here, all silent to the run: it names a skill
    that was never asked about, every URL it cites is fabricated, it
    cites nothing at all, or it is a second tip for a gap already tipped.
    Uncited prose is exactly the static-template advice this stage
    replaces, so it is not worth storing.

    The contract is one row per covered gap, and ``listing_tips`` has no
    unique constraint to lean on — ``record_listing_tips`` inserts with
    ``executemany`` and no ``ON CONFLICT``, so a constraint would raise and
    fail the write rather than degrade. Deduping here keeps the first tip
    for a skill, which is the one the model led with — first *stored*, not
    first returned, so a lead tip dropped for citing nothing does not also
    cost the gap the grounded tip that followed it.
    """
    grounded: list[GroundedTip] = []
    seen_skills: set[str] = set()
    for item in generated.tips:
        if item.gap_skill in seen_skills:
            logger.warning(
                "coach tips: %s/%s returned a duplicate tip for skill %r, dropping",
                match.listing.source,
                match.listing.external_id,
                item.gap_skill,
            )
            continue

        allowed = resources_by_skill.get(item.gap_skill)
        if allowed is None:
            logger.warning(
                "coach tips: %s/%s returned a tip for unrequested skill %r, dropping",
                match.listing.source,
                match.listing.external_id,
                item.gap_skill,
            )
            continue

        result = validate_grounding(item.tip, [str(r.url) for r in allowed])
        for url in result.stripped_urls:
            logger.warning(
                "coach tips: grounding violation on %s/%s skill=%r url=%s",
                match.listing.source,
                match.listing.external_id,
                item.gap_skill,
                url,
            )
        if not result.cited_urls:
            logger.info(
                "coach tips: dropping uncited tip for %s/%s skill=%r",
                match.listing.source,
                match.listing.external_id,
                item.gap_skill,
            )
            continue

        seen_skills.add(item.gap_skill)
        grounded.append(
            GroundedTip(
                gap_skill=item.gap_skill,
                tip=result.text,
                cited_urls=result.cited_urls,
            )
        )
    return grounded


async def run_grounded_tips(
    conn: asyncpg.Connection,
    gaps_by_match: list[tuple[MatchResult, list[SkillGap]]],
    settings: Settings | None = None,
) -> list[tuple[MatchResult, list[GroundedTip]]]:
    """Generate validated coaching tips for a run's listings.

    Returns an entry for **every** supplied match, with an empty list where
    nothing was generated — a listing with no corpus coverage, a failed
    call, or a reply whose tips were all ungrounded. Callers need the empty
    entries: ``record_listing_tips`` uses them to clear stale rows from an
    earlier run on the same day.
    """
    active_settings = settings or default_settings
    work = [
        (
            match,
            _tippable_gaps(checks, active_settings.coach_tips_max_gaps_per_listing),
        )
        for match, checks in gaps_by_match
    ]
    work = [(match, gaps) for match, gaps in work if gaps]
    if not work:
        return [(match, []) for match, _checks in gaps_by_match]

    # One retrieval for the whole run: the retriever dedupes and embeds
    # each distinct skill once, so a skill that is a gap on twenty
    # listings costs one embedding, not twenty.
    all_skills = [gap.skill for _match, gaps in work for gap in gaps]
    retrieved = await retrieve_for_skills(
        conn,
        all_skills,
        active_settings,
        k=active_settings.coach_tips_resources_per_gap,
    )

    callable_work: list[tuple[MatchResult, dict[str, list[RetrievedResource]]]] = []
    for match, gaps in work:
        covered = {
            gap.skill: retrieved.get(gap.skill, [])
            for gap in gaps
            if retrieved.get(gap.skill)
        }
        if covered:
            callable_work.append((match, covered))
        else:
            logger.info(
                "coach tips: no corpus coverage for %s/%s, skipping",
                match.listing.source,
                match.listing.external_id,
            )

    async def _call(
        batch: list[tuple[MatchResult, dict[str, list[RetrievedResource]]]],
    ) -> list[tuple[MatchResult, list[GroundedTip]]]:
        match, covered = batch[0]
        generated = await complete_json(
            build_coach_tips_instruction(match.listing, covered),
            GeneratedTips,
            active_settings,
        )
        return [(match, _to_grounded_tips(match, covered, generated))]

    # Size-1 batches: one call per listing, with run_batches' existing
    # concurrency limit and skip-on-failure. A single-item batch that
    # fails is skipped directly rather than retried, which is what we
    # want — a listing's tips are not worth a second call.
    results = await run_batches(
        batches(callable_work, 1),
        _call,
        concurrency=active_settings.model_concurrency,
        label="coach tips",
    )

    tips_by_key = {
        (match.listing.source, match.listing.external_id): tips
        for match, tips in results
    }
    return [
        (
            match,
            tips_by_key.get(
                (match.listing.source, match.listing.external_id), []
            ),
        )
        for match, _checks in gaps_by_match
    ]
