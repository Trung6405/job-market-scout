from __future__ import annotations

from datetime import datetime, timezone

import pytest

from scout.shared.schemas import GroundedTip, Listing, RunListingDetail, SkillGap
from scout.sub_agents.advisor.report import (
    _citation_cap,
    _env,
    _iter_urls,
    _linkify,
)


def _detail(gap_skills: list[str], tip_skills: list[str]) -> RunListingDetail:
    """A detail carrying the given gaps, and tips answering the given skills."""
    return RunListingDetail(
        run_listing_id=1,
        listing=Listing(
            source="linkedin",
            external_id="job-1",
            title="Graduate Software Engineer",
            company="Atlassian",
            location="Sydney",
            is_remote=False,
            url="https://example.com/jobs/1",
            description="Build things.",
            scraped_at=datetime(2026, 7, 21, tzinfo=timezone.utc),
        ),
        score=70,
        reasoning="Solid overlap.",
        band="competitive",
        gaps=[
            SkillGap(skill=skill, requirement_level="must_have") for skill in gap_skills
        ],
        tips=[
            GroundedTip(gap_skill=skill, tip=f"Learn {skill}.", cited_urls=[])
            for skill in tip_skills
        ],
    )


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


def test_linkify_renders_a_markdown_citation_as_one_anchor() -> None:
    """P3 leaves this syntax intact for URLs it does not strip, so it arrives
    here as stored text and must not render as literal brackets."""
    result = str(_linkify("Try [kubernetes/examples](https://github.com/k/k) first.", 3))
    assert '<a href="https://github.com/k/k"' in result
    assert ">kubernetes/examples</a>" in result
    assert "[" not in result
    assert "]" not in result
    assert "](" not in result
    assert result.startswith("Try ")
    assert result.endswith(" first.")


def test_linkify_markdown_and_bare_urls_coexist() -> None:
    text = "Read [the guide](https://github.com/a/b), then https://github.com/c/d."
    result = str(_linkify(text, 3))
    assert ">the guide</a>" in result
    assert ">github.com/c/d</a>" in result
    assert result.count("<a href=") == 2
    assert "[" not in result


def test_linkify_escapes_a_markdown_label() -> None:
    result = str(_linkify("See [<b>bold</b>](https://github.com/a/b).", 3))
    assert "<b>" not in result
    assert "&lt;b&gt;bold&lt;/b&gt;" in result


def test_linkify_empty_markdown_label_falls_back_to_the_derived_one() -> None:
    result = str(_linkify("See [](https://github.com/a/b).", 3))
    assert ">github.com/a/b</a>" in result
    assert "[" not in result


_THREE_URLS = (
    "Try https://github.com/a/b, then https://github.com/c/d, "
    "then https://github.com/e/f."
)


def test_linkify_links_up_to_the_limit() -> None:
    result = str(_linkify(_THREE_URLS, 1))
    assert result.count("<a href=") == 1
    # The unlinked ones stay visible rather than vanishing from the advice.
    assert "https://github.com/c/d" in result
    assert "https://github.com/e/f" in result


def test_linkify_links_all_when_the_limit_allows() -> None:
    assert str(_linkify(_THREE_URLS, 3)).count("<a href=") == 3


def test_linkify_with_a_zero_limit_links_nothing_and_loses_nothing() -> None:
    result = str(_linkify(_THREE_URLS, 0))
    assert "<a href=" not in result
    assert result == _THREE_URLS


def test_linkify_counts_distinct_urls_against_the_limit() -> None:
    """P3 dedupes cited_urls but never the prose, so one resource can appear
    twice. Counting occurrences would let it consume the whole budget."""
    text = (
        "Clone https://github.com/a/b, read https://github.com/a/b again, "
        "then try https://github.com/c/d."
    )
    result = str(_linkify(text, 2))
    # Both mentions of the repeated URL link, and the second distinct URL
    # still gets its link — three anchors from two units of budget.
    assert result.count("<a href=") == 3
    assert result.count('href="https://github.com/a/b"') == 2
    assert 'href="https://github.com/c/d"' in result


def test_linkify_repeat_beyond_the_limit_is_still_not_linked() -> None:
    text = "Clone https://github.com/a/b, then try https://github.com/c/d twice: https://github.com/c/d."
    result = str(_linkify(text, 1))
    assert result.count("<a href=") == 1
    assert result.count('href="https://github.com/a/b"') == 1
    assert "<a href=\"https://github.com/c/d\"" not in result


def test_linkify_over_limit_markdown_citation_stays_as_written() -> None:
    """Over budget, the construct is left exactly as stored — the URL stays
    visible rather than being deleted from advice written around it, and its
    brackets come along, since rewriting unlinked prose is not this filter's
    job."""
    text = "Try https://github.com/a/b or [the guide](https://github.com/c/d)."
    result = str(_linkify(text, 1))
    assert result.count("<a href=") == 1
    assert "[the guide](https://github.com/c/d)" in result


@pytest.mark.parametrize(
    "hostile",
    [
        "javascript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "file:///etc/passwd",
        "vbscript:msgbox(1)",
    ],
)
def test_linkify_never_links_a_non_http_scheme(hostile: str) -> None:
    """The corpus should never contain these, but tip text arrives from an LLM
    and the filter is the last thing between it and the page."""
    result = str(_linkify(f"Open {hostile} now.", 3))
    assert "<a " not in result
    assert "href=" not in result
    assert "<script>" not in result


def test_linkify_never_links_a_markdown_wrapped_hostile_scheme() -> None:
    result = str(_linkify("Read [the guide](javascript:alert(1)) now.", 3))
    assert "<a " not in result
    assert "href=" not in result


def test_linkify_leaves_text_without_urls_alone() -> None:
    assert str(_linkify("Just practise more.", 3)) == "Just practise more."


def test_linkify_handles_empty_text() -> None:
    assert str(_linkify("", 3)) == ""


@pytest.mark.parametrize(
    "tipped_gaps,expected",
    [
        (1, 3),
        (2, 1),
        (3, 1),
        (5, 1),
    ],
)
def test_citation_cap_divides_the_budget_across_tipped_gaps(
    tipped_gaps: int, expected: int
) -> None:
    """One gap with advice may show the full budget; several share it, and the
    cap floors at one so no tip cites a resource the reader cannot open."""
    skills = [f"skill-{i}" for i in range(tipped_gaps)]
    assert _citation_cap(_detail(skills, skills)) == expected


def test_citation_cap_is_zero_without_tips() -> None:
    assert _citation_cap(_detail(["Kubernetes", "Terraform"], [])) == 0


def test_citation_cap_counts_only_gaps_that_have_a_tip() -> None:
    """Four gaps but one tip is still one gap's worth of budget."""
    detail = _detail(["Kubernetes", "Terraform", "Go", "Rust"], ["Kubernetes"])
    assert _citation_cap(detail) == 3


def test_citation_cap_ignores_tips_matching_no_gap() -> None:
    """An orphan tip renders nowhere, so it must not shrink the budget of the
    gaps that do have advice."""
    detail = _detail(["Kubernetes"], ["Kubernetes", "Rust", "Go", "Elixir", "Nix"])
    assert _citation_cap(detail) == 3


def test_citation_cap_counts_a_duplicated_tip_once() -> None:
    """Two tips stored for one gap is one gap's worth of advice — only the
    first renders — so it must not halve the budget."""
    detail = _detail(["Kubernetes"], ["Kubernetes", "Kubernetes"])
    assert _citation_cap(detail) == 3


def test_linkify_is_registered_under_the_name_the_template_uses() -> None:
    rendered = _env.from_string("{{ text|linkify(1) }}").render(
        text="See https://github.com/a/b now."
    )
    assert '<a href="https://github.com/a/b"' in rendered


def test_citation_cap_is_registered_under_the_name_the_template_uses() -> None:
    rendered = _env.from_string("{{ detail|citation_cap }}").render(
        detail=_detail(["Kubernetes"], ["Kubernetes"])
    )
    assert rendered == "3"


def test_registered_linkify_output_is_not_double_escaped() -> None:
    """Jinja autoescape must leave the filter's Markup alone — otherwise the
    anchors would render as visible tags."""
    rendered = _env.from_string("{{ text|linkify(1) }}").render(
        text="Beware <b>this</b> https://github.com/a/b"
    )
    assert "&lt;a href" not in rendered
    assert "&lt;b&gt;" in rendered


def test_linkify_links_an_uppercase_scheme() -> None:
    """Regression: the validator matches the scheme case-insensitively, so a
    tip citing HTTPS:// is stored with that spelling intact. Missing it here
    left a grounded citation rendering as unclickable text."""
    result = str(_linkify("Start with HTTPS://github.com/k/k now.", 3))
    assert '<a href="HTTPS://github.com/k/k"' in result
    assert result.count("<a href=") == 1


def test_link_label_lowercases_the_host_but_not_the_path() -> None:
    """A shouty host is a spelling accident; path case is significant."""
    result = str(_linkify("See HTTPS://GitHub.com/k/Examples now.", 3))
    assert ">github.com/k/Examples</a>" in result
