from __future__ import annotations

from typing import AsyncGenerator

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from google.genai import types as genai_types

from scout.config import settings as default_settings
from scout.sub_agents.briefing.briefing import run_briefing
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

        await run_briefing(relevant, scores, settings)
        yield _status_event(ctx, self.name, "Briefing: email sent")


root_agent = ScoutPipelineAgent()
