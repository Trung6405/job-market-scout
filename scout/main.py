from __future__ import annotations

import asyncio
import logging
import sys

from google.adk.runners import InMemoryRunner
from google.genai import types as genai_types

from scout.agent import ScoutPipelineAgent

logger = logging.getLogger("scout.main")

_APP_NAME = "scout"
_USER_ID = "scout"
_SESSION_ID = "scout"


async def run_once() -> None:
    runner = InMemoryRunner(agent=ScoutPipelineAgent(), app_name=_APP_NAME)
    await runner.session_service.create_session(
        app_name=_APP_NAME, user_id=_USER_ID, session_id=_SESSION_ID
    )
    message = genai_types.Content(
        role="user", parts=[genai_types.Part(text="Run the daily pipeline.")]
    )
    async for event in runner.run_async(
        user_id=_USER_ID, session_id=_SESSION_ID, new_message=message
    ):
        if event.content and event.content.parts and event.content.parts[0].text:
            logger.info(event.content.parts[0].text)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(run_once())
    except Exception:
        logger.exception("pipeline run failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
