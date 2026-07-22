"""Re-render all report HTML from data already stored in the database.

Unlike ``scout.main`` (which runs the full scrape -> score -> render pipeline),
this entrypoint does no scraping and makes no LLM calls. It reloads every run
from Postgres and rewrites its dashboard, job-detail, history and profile pages
using the current templates and filters. Use it after a template/rendering
change to refresh already-generated pages:

    python -m scout.rerender
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

from scout.config import settings as default_settings
from scout.shared.db import create_pool, list_runs
from scout.shared.profile import load_profile
from scout.sub_agents.advisor.report import render_history, render_profile, render_run

logger = logging.getLogger("scout.rerender")

# High enough to cover every run; history only ever surfaces the latest 30.
_ALL_RUNS_LIMIT = 10_000


async def rerender_all() -> None:
    settings = default_settings
    has_profile = Path(settings.profile_path).is_file()

    pool = await create_pool(settings)
    try:
        async with pool.acquire() as conn:
            runs = await list_runs(conn, _ALL_RUNS_LIMIT)
            for run in runs:
                await render_run(conn, run.id, settings, has_profile=has_profile)
                logger.info("re-rendered run %s (%s)", run.id, run.run_date)

            await render_history(conn, settings, has_profile=has_profile)
            logger.info("re-rendered history (%d run(s))", len(runs))
    finally:
        await pool.close()

    if has_profile:
        render_profile(load_profile(settings.profile_path), settings)
        logger.info("re-rendered profile page")


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(rerender_all())
    except Exception:
        logger.exception("re-render failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
