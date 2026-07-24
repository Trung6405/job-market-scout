"""Spike: does litellm.acompletion honour response_format=json_object for
DeepSeek when called directly, without ADK's LiteLlm wrapper in between?

Throwaway — not part of the shipped pipeline. See
docs/agent/plans/pipeline-efficiency/phase-1-model-layer.md Task 1.
"""

from __future__ import annotations

import asyncio

import litellm

from scout.config import settings


async def main() -> None:
    response = await litellm.acompletion(
        model=settings.deepseek_model,
        messages=[
            {
                "role": "user",
                "content": 'Reply with only this exact JSON object, no commentary: {"ok": true}',
            }
        ],
        temperature=0,
        response_format={"type": "json_object"},
        api_key=settings.deepseek_api_key or None,
    )
    raw = response.choices[0].message.content
    print("raw content repr:", repr(raw))


if __name__ == "__main__":
    asyncio.run(main())
