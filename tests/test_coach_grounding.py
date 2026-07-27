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
        # A URL that genuinely contains parentheses is still not parsed as
        # such, but the truncation guard returns the whole token rather than
        # the prefix, so the loss is a stripped real link — never a kept
        # fabricated one.
        (
            "See https://en.wikipedia.org/wiki/Deployment_(computing).",
            ["https://en.wikipedia.org/wiki/Deployment_(computing)"],
        ),
        # A schemeless mention is not a URL to this extractor, so nothing
        # downstream can strip it. Phase 3's prompt must demand full https://
        # URLs for exactly this reason.
        ("Browse github.com/k/examples for demos.", []),
        # An uppercase scheme must still be extracted. An un-extracted string
        # is invisible to the allowlist comparison and so cannot be stripped —
        # the unsafe direction, the same class as the schemeless mention.
        ("Open HTTPS://github.com/a/b now.", ["HTTPS://github.com/a/b"]),
        ("Open Https://GitHub.com/a/b now.", ["Https://GitHub.com/a/b"]),
    ],
)
def test_extract_urls_handles_additional_llm_shapes(text, expected):
    assert extract_urls(text) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        # The failure the guard exists to prevent: the corpus stores GitHub
        # repo roots, so a fabricated deep link truncated at "(" would be
        # *exactly* an allowlist entry, compare equal, and survive whole. The
        # full token is returned instead, so it can never match and is
        # stripped entirely — no dangling "(fake/path)" left in the prose.
        (
            "See https://github.com/a/b(fake/path) now.",
            ["https://github.com/a/b(fake/path)"],
        ),
        # Same mechanism with any other stop character.
        ("Read https://github.com/a/b'sfake now.", ["https://github.com/a/b'sfake"]),
        ('Read https://github.com/a/b"sfake now.', ['https://github.com/a/b"sfake']),
        ("Read https://github.com/a/b[fake] now.", ["https://github.com/a/b[fake]"]),
        # A closing bracket with no matching opener before the URL is not a
        # wrap either — it is a truncation.
        ("Read https://github.com/a/b)fake now.", ["https://github.com/a/b)fake"]),
        ("Read https://github.com/a/b]fake now.", ["https://github.com/a/b]fake"]),
    ],
)
def test_extract_urls_returns_the_whole_token_when_truncated(text, expected):
    assert extract_urls(text) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        # The legitimate wrapped forms must keep working: the character before
        # the URL opens the pair the character after it closes.
        ("Start here (https://github.com/k/examples).", ["https://github.com/k/examples"]),
        ("[kubernetes/examples](https://github.com/k/examples)", ["https://github.com/k/examples"]),
        ("Read <https://github.com/k/examples> first.", ["https://github.com/k/examples"]),
        ('Open "https://github.com/a/b" now.', ["https://github.com/a/b"]),
        ("Open 'https://github.com/a/b' now.", ["https://github.com/a/b"]),
    ],
)
def test_extract_urls_keeps_legitimate_wraps_intact(text, expected):
    assert extract_urls(text) == expected
