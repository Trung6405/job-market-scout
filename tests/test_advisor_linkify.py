from __future__ import annotations

import pytest

from scout.sub_agents.advisor.report import _iter_urls, _linkify


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


def test_linkify_wraps_a_bare_url_with_a_shortened_label() -> None:
    result = str(_linkify("Work through https://github.com/k/k first.", 3))
    assert '<a href="https://github.com/k/k"' in result
    assert ">github.com/k/k</a>" in result
    assert result.startswith("Work through ")
    assert result.endswith(" first.")


def test_linkify_label_drops_www() -> None:
    result = str(_linkify("See https://www.example.com/x", 3))
    assert ">example.com/x</a>" in result
    assert 'href="https://www.example.com/x"' in result


def test_linkify_label_keeps_query_and_fragment_out_of_the_way() -> None:
    """A long query shouldn't become the visible label; the path is enough."""
    result = str(_linkify("See https://github.com/a/b?tab=readme#top", 3))
    assert ">github.com/a/b</a>" in result
    assert 'href="https://github.com/a/b?tab=readme#top"' in result


def test_linkify_escapes_markup_in_the_prose() -> None:
    result = str(_linkify("Beware <script>alert(1)</script> here.", 3))
    assert "<script>" not in result
    assert "&lt;script&gt;" in result


def test_linkify_escapes_markup_around_a_link() -> None:
    """Escaping must survive splicing — the anchor is assembled last."""
    result = str(_linkify("<b>See</b> https://github.com/a/b now.", 3))
    assert "<b>" not in result
    assert "&lt;b&gt;" in result
    assert '<a href="https://github.com/a/b"' in result


def test_linkify_anchors_are_safe_to_follow() -> None:
    result = str(_linkify("See https://github.com/a/b", 3))
    assert 'rel="noopener noreferrer"' in result
    assert 'target="_blank"' in result


def test_linkify_leaves_text_without_urls_alone() -> None:
    assert str(_linkify("Just practise more.", 3)) == "Just practise more."


def test_linkify_handles_empty_text() -> None:
    assert str(_linkify("", 3)) == ""
