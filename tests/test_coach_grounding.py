from __future__ import annotations

import pytest

from scout.sub_agents.coach.grounding import extract_urls


@pytest.mark.parametrize(
    "text,expected",
    [
        ("See https://github.com/k/examples", ["https://github.com/k/examples"]),
        # Sentence-final: the period is prose, not part of the URL.
        ("See https://github.com/k/examples.", ["https://github.com/k/examples"]),
        ("See https://github.com/k/examples, then start.", ["https://github.com/k/examples"]),
        ("Start here (https://github.com/k/examples).", ["https://github.com/k/examples"]),
        ("[kubernetes/examples](https://github.com/k/examples)", ["https://github.com/k/examples"]),
        (
            "Compare https://github.com/a/b and https://github.com/c/d.",
            ["https://github.com/a/b", "https://github.com/c/d"],
        ),
        ("http://example.org/docs/", ["http://example.org/docs/"]),
        ("No links here at all.", []),
        ("", []),
    ],
)
def test_extract_urls_handles_llm_prose_shapes(text, expected):
    assert extract_urls(text) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        # Autolink syntax: angle brackets are prose too.
        ("Read <https://github.com/k/examples> first.", ["https://github.com/k/examples"]),
        # Bullet lists are the most common tip layout, so a URL ending a line
        # must not absorb the newline or the next line's text.
        (
            "- Docs: https://github.com/a/b\n- Demos: https://github.com/c/d\n",
            ["https://github.com/a/b", "https://github.com/c/d"],
        ),
        # Query strings and fragments are part of the URL, not prose.
        (
            "Filter it: https://github.com/k/examples?tab=readme#setup.",
            ["https://github.com/k/examples?tab=readme#setup"],
        ),
        # Duplicates are kept: the caller de-duplicates, so it can also count
        # how often a fabricated URL was repeated.
        (
            "Clone https://github.com/a/b, then re-read https://github.com/a/b.",
            ["https://github.com/a/b", "https://github.com/a/b"],
        ),
        # Multiple trailing marks (ellipsis, "!?") are all prose.
        ("Just look at https://github.com/a/b!", ["https://github.com/a/b"]),
        ("Just look at https://github.com/a/b...", ["https://github.com/a/b"]),
        # A quoted URL: the quote characters are excluded by the pattern.
        ('Open "https://github.com/a/b" now.', ["https://github.com/a/b"]),
        # Accepted cost of excluding brackets: a URL that genuinely contains
        # parentheses is truncated at the first one. Pinned so the loss is a
        # known, deliberate trade-off rather than a surprise.
        (
            "See https://en.wikipedia.org/wiki/Deployment_(computing).",
            ["https://en.wikipedia.org/wiki/Deployment_"],
        ),
        # A schemeless mention is not a URL to this extractor, so nothing
        # downstream can strip it. Phase 3's prompt must demand full https://
        # URLs for exactly this reason.
        ("Browse github.com/k/examples for demos.", []),
    ],
)
def test_extract_urls_handles_additional_llm_shapes(text, expected):
    assert extract_urls(text) == expected
