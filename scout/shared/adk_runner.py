from __future__ import annotations

from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner
from google.genai import types as genai_types


async def run_single_turn(
    agent: LlmAgent, app_name: str, message_text: str
) -> str | None:
    """Run one message through an ADK agent and return its final response text."""
    session_id = user_id = app_name
    runner = InMemoryRunner(agent=agent, app_name=app_name)
    await runner.session_service.create_session(
        app_name=app_name, user_id=user_id, session_id=session_id
    )
    message = genai_types.Content(
        role="user", parts=[genai_types.Part(text=message_text)]
    )
    final_text: str | None = None
    async for event in runner.run_async(
        user_id=user_id, session_id=session_id, new_message=message
    ):
        if event.is_final_response() and event.content and event.content.parts:
            final_text = event.content.parts[0].text
    return final_text
