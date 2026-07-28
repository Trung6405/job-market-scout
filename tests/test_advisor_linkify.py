from __future__ import annotations

import re

import pytest

from scout.sub_agents.advisor.report import _env, _iter_urls, _linkify


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
        # The scheme is matched case-insensitively, exactly as the grounding
        # validator does. It stores a tip citing "HTTPS://..." because that
        # canonicalizes onto the allowlist, so failing to find it here would
        # render a validated citation as dead text.
        ("Start with HTTPS://github.com/a/b now.", ["HTTPS://github.com/a/b"]),
        ("Start with Https://github.com/a/b now.", ["Https://github.com/a/b"]),
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
    result = str(_linkify("Work through https://github.com/k/k first."))
    assert '<a href="https://github.com/k/k"' in result
    assert ">github.com/k/k</a>" in result
    assert result.startswith("Work through ")
    assert result.endswith(" first.")


def test_linkify_label_drops_www() -> None:
    result = str(_linkify("See https://www.example.com/x"))
    assert ">example.com/x</a>" in result
    assert 'href="https://www.example.com/x"' in result


def test_linkify_label_keeps_query_and_fragment_out_of_the_way() -> None:
    """A long query shouldn't become the visible label; the path is enough."""
    result = str(_linkify("See https://github.com/a/b?tab=readme#top"))
    assert ">github.com/a/b</a>" in result
    assert 'href="https://github.com/a/b?tab=readme#top"' in result


def test_linkify_escapes_markup_in_the_prose() -> None:
    result = str(_linkify("Beware <script>alert(1)</script> here."))
    assert "<script>" not in result
    assert "&lt;script&gt;" in result


def test_linkify_escapes_markup_around_a_link() -> None:
    """Escaping must survive splicing — the anchor is assembled last."""
    result = str(_linkify("<b>See</b> https://github.com/a/b now."))
    assert "<b>" not in result
    assert "&lt;b&gt;" in result
    assert '<a href="https://github.com/a/b"' in result


def test_linkify_anchors_are_safe_to_follow() -> None:
    result = str(_linkify("See https://github.com/a/b"))
    assert 'rel="noopener noreferrer"' in result
    assert 'target="_blank"' in result


def test_linkify_renders_a_markdown_citation_as_one_anchor() -> None:
    """P3 leaves this syntax intact for URLs it does not strip, so it arrives
    here as stored text and must not render as literal brackets."""
    result = str(_linkify("Try [kubernetes/examples](https://github.com/k/k) first."))
    assert '<a href="https://github.com/k/k"' in result
    assert ">kubernetes/examples</a>" in result
    assert "[" not in result
    assert "]" not in result
    assert "](" not in result
    assert result.startswith("Try ")
    assert result.endswith(" first.")


def test_linkify_markdown_and_bare_urls_coexist() -> None:
    text = "Read [the guide](https://github.com/a/b), then https://github.com/c/d."
    result = str(_linkify(text))
    assert ">the guide</a>" in result
    assert ">github.com/c/d</a>" in result
    assert result.count("<a href=") == 2
    assert "[" not in result


def test_linkify_escapes_a_markdown_label() -> None:
    result = str(_linkify("See [<b>bold</b>](https://github.com/a/b)."))
    assert "<b>" not in result
    assert "&lt;b&gt;bold&lt;/b&gt;" in result


def test_linkify_empty_markdown_label_falls_back_to_the_derived_one() -> None:
    result = str(_linkify("See [](https://github.com/a/b)."))
    assert ">github.com/a/b</a>" in result
    assert "[" not in result


_THREE_URLS = (
    "Try https://github.com/a/b, then https://github.com/c/d, "
    "then https://github.com/e/f."
)


def test_linkify_links_every_citation_in_a_tip() -> None:
    """No budget: a tip citing three resources gets three links.

    Re-rendering the real corpus is what settled this. 93% of generated tips
    cite two or three resources, so an earlier per-page budget left more than
    half of all citations as bare unclickable URLs beside linked ones.
    """
    result = str(_linkify(_THREE_URLS))
    assert result.count("<a href=") == 3
    # Nothing is left as a bare URL in the prose.
    assert not re.search(r"(?<![\"/])https?://", re.sub(r"<a [^>]*>.*?</a>", "", result))


def test_linkify_links_every_occurrence_of_a_repeated_url() -> None:
    """Each mention is a link; there is no budget for a repeat to spend."""
    text = "Clone https://github.com/a/b, then read https://github.com/a/b again."
    result = str(_linkify(text))
    assert result.count('href="https://github.com/a/b"') == 2


def test_linkify_leaves_text_without_urls_alone() -> None:
    assert str(_linkify("Just practise more.")) == "Just practise more."


def test_linkify_handles_empty_text() -> None:
    assert str(_linkify("")) == ""


def test_linkify_is_registered_under_the_name_the_template_uses() -> None:
    rendered = _env.from_string("{{ text|linkify }}").render(
        text="See https://github.com/a/b now."
    )
    assert '<a href="https://github.com/a/b"' in rendered


def test_registered_linkify_output_is_not_double_escaped() -> None:
    """Jinja autoescape must leave the filter's Markup alone — otherwise the
    anchors would render as visible tags."""
    rendered = _env.from_string("{{ text|linkify }}").render(
        text="Beware <b>this</b> https://github.com/a/b"
    )
    assert "&lt;a href" not in rendered
    assert "&lt;b&gt;" in rendered


def test_linkify_links_an_uppercase_scheme() -> None:
    """Regression: the validator matches the scheme case-insensitively, so a
    tip citing HTTPS:// is stored with that spelling intact. Missing it here
    left a grounded citation rendering as unclickable text."""
    result = str(_linkify("Start with HTTPS://github.com/k/k now."))
    assert '<a href="HTTPS://github.com/k/k"' in result
    assert result.count("<a href=") == 1


def test_link_label_lowercases_the_host_but_not_the_path() -> None:
    """A shouty host is a spelling accident; path case is significant."""
    result = str(_linkify("See HTTPS://GitHub.com/k/Examples now."))
    assert ">github.com/k/Examples</a>" in result


def test_url_lexing_stays_in_step_with_the_grounding_validator() -> None:
    """The renderer must find exactly the URLs the validator approved.

    These two stay independent in policy — the validator decides what may be
    stored, this decides what is clickable — but a divergence in *lexing* means
    a stored, grounded citation renders as dead text. That is not theoretical:
    the renderer's copy of this pattern was case-sensitive while the
    validator's was not, so a tip citing "HTTPS://..." passed grounding and
    rendered unclickable. Asserting on the pattern itself is what turns the
    next such drift into a failing test rather than a review finding.
    """
    from scout.sub_agents.coach import grounding
    from scout.sub_agents.advisor import report

    assert report._URL_PATTERN.pattern == grounding._URL_PATTERN.pattern
    assert report._URL_PATTERN.flags == grounding._URL_PATTERN.flags
    assert report._TRAILING_PUNCTUATION == grounding._TRAILING_PUNCTUATION


@pytest.mark.parametrize(
    "text",
    [
        "Start with https://github.com/k/examples for demos.",
        "Start with HTTPS://github.com/k/examples for demos.",
        "Start with https://GitHub.com/k/examples for demos.",
        "Read (https://github.com/k/examples) then build one.",
        "Read [the demos](https://github.com/k/examples) then build one.",
        "Clone https://github.com/k/examples/ and read the README.",
    ],
)
def test_renderer_finds_every_url_the_validator_leaves_behind(text: str) -> None:
    """End-to-end on the contract: whatever survives grounding must linkify."""
    from scout.sub_agents.coach.grounding import extract_urls, validate_grounding

    stored = validate_grounding(text, ["https://github.com/k/examples"])
    assert stored.cited_urls, "fixture should survive grounding"
    rendered = str(_linkify(stored.text))
    assert rendered.count("<a href=") == len(extract_urls(stored.text))
