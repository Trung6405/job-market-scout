from __future__ import annotations

from datetime import datetime, timezone
from typing import AsyncGenerator

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from google.genai import types as genai_types

from scout.config import settings as default_settings
from scout.shared.db import (
    create_pool,
    finish_run,
    record_listing_gaps,
    record_listing_meta,
    record_run_listings,
    start_run,
)
from scout.shared.profile import load_profile
from scout.sub_agents.advisor.bands import classify_band
from scout.sub_agents.advisor.gaps import evaluate_requirements
from scout.sub_agents.advisor.report import render_history, render_profile, render_run
from scout.sub_agents.advisor.runner import run_requirements_extraction
from scout.sub_agents.briefing.briefing import run_briefing
from scout.sub_agents.scorer.results import join_match_results
from scout.sub_agents.scorer.runner import run_scorer
from scout.sub_agents.scraper.runner import run_scraper
from scout.sub_agents.tracker.runner import track_listings


def _status_event(ctx: InvocationContext, author: str, text: str) -> Event:
    return Event(
        invocation_id=ctx.invocation_id,
        author=author,
        branch=ctx.branch,
        content=genai_types.Content(
            role="model", parts=[genai_types.Part.from_text(text=text)]
        ),
    )


class ScoutPipelineAgent(BaseAgent):
    name: str = "scout"

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        settings = default_settings

        listings = await run_scraper(settings)
        yield _status_event(
            ctx, self.name, f"Scraper: {len(listings)} listing(s) found"
        )

        relevant = await track_listings(listings, settings=settings)
        yield _status_event(
            ctx, self.name, f"Tracker: {len(relevant)} new/changed"
        )

        if not relevant:
            yield _status_event(
                ctx,
                self.name,
                "No new or changed listings — nothing to score or brief.",
            )
            return

        scores = await run_scorer(relevant, settings)
        yield _status_event(ctx, self.name, f"Scorer: {len(scores)} scored")

        matches = join_match_results(relevant, scores)
        banded_matches = [
            (match, classify_band(match.score, settings)) for match in matches
        ]
        run_date = datetime.now(timezone.utc).date()
        pool = await create_pool(settings)
        try:
            async with pool.acquire() as conn:
                run_id = await start_run(conn, run_date)
                await record_run_listings(conn, run_id, banded_matches)

                profile = load_profile(settings.profile_path)

                requirements = await run_requirements_extraction(relevant, settings)
                requirements_by_key = {
                    (r.source, r.external_id): r for r in requirements
                }
                matches_with_requirements = [
                    (
                        match,
                        requirements_by_key[
                            (match.listing.source, match.listing.external_id)
                        ],
                    )
                    for match in matches
                    if (match.listing.source, match.listing.external_id)
                    in requirements_by_key
                ]
                checks_by_match = [
                    (match, evaluate_requirements(req, profile))
                    for match, req in matches_with_requirements
                ]
                await record_listing_gaps(conn, run_id, checks_by_match)
                await record_listing_meta(conn, run_id, matches_with_requirements)
                gap_count = sum(
                    1 for _, checks in checks_by_match for c in checks if not c.met
                )
                yield _status_event(
                    ctx,
                    self.name,
                    f"Gaps detected: {gap_count} "
                    f"across {len(checks_by_match)} listing(s)",
                )

                await finish_run(
                    conn,
                    run_id,
                    listings_scraped=len(listings),
                    listings_scored=len(matches),
                )

                report_paths = await render_run(
                    conn, run_id, settings, has_profile=True
                )
                await render_history(conn, settings, has_profile=True)
                render_profile(profile, settings)
                yield _status_event(
                    ctx,
                    self.name,
                    f"Report rendered: {report_paths['dashboard']}",
                )
        finally:
            await pool.close()
        yield _status_event(ctx, self.name, f"Run persisted: {run_date}")

        if settings.gmail_address and settings.gmail_app_password:
            await run_briefing(
                relevant, scores, settings, report_path=report_paths["dashboard"]
            )
            yield _status_event(ctx, self.name, "Briefing: email sent")
        else:
            yield _status_event(
                ctx, self.name, "Briefing: skipped (GMAIL_ADDRESS/GMAIL_APP_PASSWORD not set)"
            )


root_agent = ScoutPipelineAgent()
