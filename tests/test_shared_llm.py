from __future__ import annotations

import pytest
from pydantic import BaseModel

from scout.config import Settings
from scout.shared import llm


class _Toy(BaseModel):
    value: int


def _fake_response(content: str | None):
    class _Message:
        def __init__(self, c):
            self.content = c

    class _Choice:
        def __init__(self, c):
            self.message = _Message(c)

    class _Response:
        def __init__(self, c):
            self.choices = [_Choice(c)]

    return _Response(content)


async def test_complete_json_validates_into_schema(monkeypatch):
    async def _fake_acompletion(**kwargs):
        return _fake_response('{"value": 7}')

    monkeypatch.setattr(llm.litellm, "acompletion", _fake_acompletion)
    result = await llm.complete_json("prompt", _Toy, Settings())
    assert result.value == 7


async def test_complete_json_strips_code_fence(monkeypatch):
    async def _fake_acompletion(**kwargs):
        return _fake_response('```json\n{"value": 3}\n```')

    monkeypatch.setattr(llm.litellm, "acompletion", _fake_acompletion)
    result = await llm.complete_json("prompt", _Toy, Settings())
    assert result.value == 3


async def test_complete_json_raises_on_empty_content(monkeypatch):
    async def _fake_acompletion(**kwargs):
        return _fake_response(None)

    monkeypatch.setattr(llm.litellm, "acompletion", _fake_acompletion)
    with pytest.raises(ValueError, match="no content"):
        await llm.complete_json("prompt", _Toy, Settings())


async def test_complete_json_passes_model_and_json_mode(monkeypatch):
    seen: dict = {}

    async def _fake_acompletion(**kwargs):
        seen.update(kwargs)
        return _fake_response('{"value": 1}')

    monkeypatch.setattr(llm.litellm, "acompletion", _fake_acompletion)
    settings = Settings()
    await llm.complete_json("prompt", _Toy, settings, temperature=0.3)
    assert seen["model"] == settings.deepseek_model
    assert seen["response_format"] == {"type": "json_object"}
    assert seen["temperature"] == 0.3
    assert seen["messages"] == [{"role": "user", "content": "prompt"}]


async def test_complete_json_forwards_max_tokens_and_timeout(monkeypatch):
    seen: dict = {}

    async def _fake_acompletion(**kwargs):
        seen.update(kwargs)
        return _fake_response('{"value": 1}')

    monkeypatch.setattr(llm.litellm, "acompletion", _fake_acompletion)
    settings = Settings()
    await llm.complete_json("prompt", _Toy, settings)
    assert seen["max_tokens"] == settings.model_max_tokens
    assert seen["timeout"] == settings.model_timeout_seconds
