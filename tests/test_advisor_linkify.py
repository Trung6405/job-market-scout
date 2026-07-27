from __future__ import annotations

import pytest

from scout.sub_agents.advisor.report import _iter_urls


def _urls(text: str) -> list[str]:
    return [url for _start, _end, url in _iter_urls(text)]


@pytest.mark.parametrize(
    "text,expected",
    [
        ("See https://github.com/a/b", ["https://github.com/a/b"]),
        # Sentence-final: the period is prose, not part of the URL.
        ("See https://github.com/a/b.", ["https://github.com/a/b"]),
        ("See https://github.com/a/b, then start.", ["https://github.com/a/b"]),
        ("Start here (https://github.com/a/b).", ["https://github.com/a/b"]),
        # P3 leaves Markdown syntax intact for URLs it does not strip, so this
        # shape reaches the renderer as stored text.
        ("[label](https://github.com/a/b)", ["https://github.com/a/b"]),
        ("https://github.com/a/b#readme", ["https://github.com/a/b#readme"]),
        ("https://github.com/a/b?tab=readme", ["https://github.com/a/b?tab=readme"]),
        # A trailing slash names the same resource but is part of the URL.
        ("https://github.com/a/b/", ["https://github.com/a/b/"]),
        ("http://example.org/docs/", ["http://example.org/docs/"]),
        # No scheme: prose naming a repo, not a link.
        ("Look at github.com/a/b for examples.", []),
        (
            "Compare https://github.com/a/b and https://github.com/c/d.",
            ["https://github.com/a/b", "https://github.com/c/d"],
        ),
        ("No links here at all.", []),
        ("", []),
    ],
)
def test_iter_urls_handles_llm_prose_shapes(text: str, expected: list[str]) -> None:
    assert _urls(text) == expected


def test_iter_urls_spans_index_the_original_text() -> None:
    """The spans must slice the source exactly, since linkify splices on them."""
    text = "Start with (https://github.com/a/b), then practise."
    spans = _iter_urls(text)
    assert len(spans) == 1
    start, end, url = spans[0]
    assert text[start:end] == url
