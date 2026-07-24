from __future__ import annotations

from typing import TypeVar

import litellm
from pydantic import BaseModel

from scout.config import Settings
from scout.shared.parsing import strip_code_fence

T = TypeVar("T", bound=BaseModel)


async def complete_json(
    prompt: str,
    schema: type[T],
    settings: Settings,
    *,
    temperature: float = 0.0,
) -> T:
    """Send one prompt and validate the reply into ``schema``.

    Replaces the ADK ``LlmAgent`` + ``InMemoryRunner`` pair that used to
    wrap every call. Nothing in this pipeline needs tools, delegation or a
    retained session — every call is one stateless turn returning JSON.

    ``strip_code_fence`` is kept even though ``response_format`` is set:
    it costs nothing and models occasionally fence their output anyway.
    """
    response = await litellm.acompletion(
        model=settings.deepseek_model,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        response_format={"type": "json_object"},
        api_key=settings.deepseek_api_key or None,
    )
    raw = response.choices[0].message.content
    if raw is None:
        raise ValueError("model returned no content")
    return schema.model_validate_json(strip_code_fence(raw))
