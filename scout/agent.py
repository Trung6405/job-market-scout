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
    record_run_listings,
    start_run,
)
from scout.shared.profile import load_profile
from scout.sub_agents.advisor.bands import classify_band
from scout.sub_agents.advisor.gaps import detect_gaps
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

                try:
                    profile = load_profile(settings.profile_path)
                except FileNotFoundError:
                    profile = None

                if profile is None:
                    yield _status_event(
                        ctx,
                        self.name,
                        f"Gap detection: skipped (no profile at {settings.profile_path})",
                    )
                else:
                    requirements = await run_requirements_extraction(
                        relevant, settings
                    )
                    requirements_by_key = {
                        (r.source, r.external_id): r for r in requirements
                    }
                    gaps_by_match = [
                        (
                            match,
                            detect_gaps(
                                requirements_by_key[
                                    (match.listing.source, match.listing.external_id)
                                ],
                                profile,
                            ),
                        )
                        for match in matches
                        if (match.listing.source, match.listing.external_id)
                        in requirements_by_key
                    ]
                    await record_listing_gaps(conn, run_id, gaps_by_match)
                    yield _status_event(
                        ctx,
                        self.name,
                        f"Gaps detected: {sum(len(g) for _, g in gaps_by_match)} "
                        f"across {len(gaps_by_match)} listing(s)",
                    )

                await finish_run(
                    conn,
                    run_id,
                    listings_scraped=len(listings),
                    listings_scored=len(scores),
                )

                report_paths = await render_run(conn, run_id, settings)
                await render_history(conn, settings)
                if profile is not None:
                    render_profile(profile, settings)
                yield _status_event(
                    ctx,
                    self.name,
                    f"Report rendered: {report_paths['dashboard']}",
                )
        finally:
            await pool.close()
        yield _status_event(ctx, self.name, f"Run persisted: {run_date}")

        await run_briefing(relevant, scores, settings)
        yield _status_event(ctx, self.name, "Briefing: email sent")


root_agent = ScoutPipelineAgent()
