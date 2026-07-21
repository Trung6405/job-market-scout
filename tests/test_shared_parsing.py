from __future__ import annotations

from scout.shared.parsing import strip_code_fence


def test_strip_code_fence_returns_plain_text_unchanged():
    assert strip_code_fence('{"a": 1}') == '{"a": 1}'


def test_strip_code_fence_strips_json_fence():
    raw = '```json\n{"a": 1}\n```'
    assert strip_code_fence(raw) == '{"a": 1}'


def test_strip_code_fence_strips_bare_fence():
    raw = '```\n{"a": 1}\n```'
    assert strip_code_fence(raw) == '{"a": 1}'


def test_strip_code_fence_strips_surrounding_whitespace():
    assert strip_code_fence('  \n{"a": 1}\n  ') == '{"a": 1}'
