from __future__ import annotations

import pytest

from scout.sub_agents.coach.grounding import (
    canonical_url,
    extract_urls,
    validate_grounding,
)


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
        # Junk appended directly after a closer is a truncation, not a wrap,
        # so the whole token is returned and the fabrication is stripped.
        (
            "See (https://github.com/a/b)fake/path) now.",
            ["https://github.com/a/b)fake/path)"],
        ),
    ],
)
def test_extract_urls_returns_the_whole_token_when_truncated(text, expected):
    assert extract_urls(text) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        # The legitimate wrapped forms must keep working: the closer is
        # followed by whitespace, sentence punctuation, or end of string.
        ("Start here (https://github.com/k/examples).", ["https://github.com/k/examples"]),
        ("[kubernetes/examples](https://github.com/k/examples)", ["https://github.com/k/examples"]),
        ("Read <https://github.com/k/examples> first.", ["https://github.com/k/examples"]),
        ('Open "https://github.com/a/b" now.', ["https://github.com/a/b"]),
        ("Open 'https://github.com/a/b' now.", ["https://github.com/a/b"]),
        # The wrap test asks what follows the closer, never what precedes the
        # URL, because a parenthetical or quotation almost always contains more
        # than the URL itself. Testing the preceding character instead read
        # each of these as a truncation, and the trailing ")" or '"' guaranteed
        # the string could not equal an allowlist entry — so a correctly-cited
        # real URL was stripped out of a tip that was fine.
        (
            "Start here (see https://github.com/k/examples).",
            ["https://github.com/k/examples"],
        ),
        ("(docs: https://github.com/a/b)", ["https://github.com/a/b"]),
        (
            'She said "start with https://github.com/a/b" and left.',
            ["https://github.com/a/b"],
        ),
        (
            "Use (https://github.com/a/b) and (see https://github.com/c/d).",
            ["https://github.com/a/b", "https://github.com/c/d"],
        ),
        # A URL that opens the string has no preceding character at all; the
        # rule must not index off the front of it.
        ("https://github.com/a/b is the one.", ["https://github.com/a/b"]),
        ("https://github.com/a/b", ["https://github.com/a/b"]),
        # Known limit of the wrap guard, pinned so it stays visible: sentence
        # punctuation after the closer reads as prose, so a fabrication glued
        # on behind it survives — the clean allowlisted URL is extracted and
        # ".fake/path" is left in the tip as text. Far weaker than the prefix
        # attack: the remainder sits outside the closing delimiter, so it is
        # not part of the link and no reader can follow it.
        (
            "See (https://github.com/a/b).fake/path now.",
            ["https://github.com/a/b"],
        ),
    ],
)
def test_extract_urls_keeps_legitimate_wraps_intact(text, expected):
    assert extract_urls(text) == expected


@pytest.mark.parametrize(
    "a,b",
    [
        ("https://github.com/k/examples", "https://github.com/k/examples/"),
        ("https://GitHub.com/k/examples", "https://github.com/k/examples"),
        ("HTTPS://github.com/k/examples", "https://github.com/k/examples"),
        ("  https://github.com/k/examples  ", "https://github.com/k/examples"),
    ],
)
def test_canonical_url_ignores_cosmetic_differences(a, b):
    assert canonical_url(a) == canonical_url(b)


@pytest.mark.parametrize(
    "a,b",
    [
        # Path case is meaningful on GitHub and everywhere else.
        ("https://github.com/k/Examples", "https://github.com/k/examples"),
        # A fabricated sibling path must never canonicalize onto a real one.
        ("https://github.com/k/examples-v2", "https://github.com/k/examples"),
        ("https://github.com/k/examples", "https://gitlab.com/k/examples"),
        ("http://github.com/k/examples", "https://github.com/k/examples"),
    ],
)
def test_canonical_url_preserves_meaningful_differences(a, b):
    assert canonical_url(a) != canonical_url(b)


@pytest.mark.parametrize(
    "a,b",
    [
        # The corpus stores GitHub repo roots, so the likeliest fabrication is a
        # real root with extra path segments glued on. Nothing may trim them.
        ("https://github.com/k/examples/docs/setup", "https://github.com/k/examples"),
        ("https://github.com/k/examples/blob/main/README.md", "https://github.com/k/examples"),
        # A trailing slash is only cosmetic on the *last* segment; it never
        # licenses dropping a segment that carries meaning.
        ("https://github.com/k/examples/docs/", "https://github.com/k/examples"),
        # A plausible near-miss host: same registrable domain, different
        # subdomain, entirely different content.
        ("https://docs.github.com/k/examples", "https://github.com/k/examples"),
        ("https://raw.githubusercontent.com/k/examples", "https://github.com/k/examples"),
        # Query and fragment are carried through, not dropped, so a deep link
        # dressed up as a repo root stays distinguishable from the root itself.
        ("https://github.com/k/examples?tab=readme", "https://github.com/k/examples"),
        ("https://github.com/k/examples#install", "https://github.com/k/examples"),
        # Host case folds, but userinfo/port do not vanish: a lookalike
        # authority must not canonicalize onto the bare host.
        ("https://github.com:8080/k/examples", "https://github.com/k/examples"),
        ("https://github.com@evil.test/k/examples", "https://github.com/k/examples"),
    ],
)
def test_canonical_url_preserves_further_near_miss_differences(a, b):
    assert canonical_url(a) != canonical_url(b)


ALLOWED = ["https://github.com/k/examples"]


def test_allowed_url_survives_unchanged():
    text = "Work through kubernetes/examples (https://github.com/k/examples)."
    result = validate_grounding(text, ALLOWED)
    assert result.text == text
    assert result.cited_urls == ["https://github.com/k/examples"]
    assert result.stripped_urls == []


def test_allowed_url_survives_a_trailing_slash_difference():
    text = "See https://github.com/k/examples/ for worked demos."
    result = validate_grounding(text, ALLOWED)
    assert result.cited_urls == ["https://github.com/k/examples/"]
    assert result.stripped_urls == []


def test_fabricated_url_is_stripped_and_reported():
    text = (
        "Read the guide (https://kubernetes.io/invented-guide) and then "
        "kubernetes/examples (https://github.com/k/examples)."
    )
    result = validate_grounding(text, ALLOWED)
    assert "invented-guide" not in result.text
    assert result.stripped_urls == ["https://kubernetes.io/invented-guide"]
    assert result.cited_urls == ["https://github.com/k/examples"]
    # The prose left behind reads cleanly — no orphaned "()" or double space.
    assert "()" not in result.text
    assert "  " not in result.text


def test_url_from_another_gap_is_stripped():
    """The whole point of a per-gap allowlist: every gap's resources share
    one prompt, so citing a real URL under the wrong skill is the cheapest
    hallucination available."""
    text = "Try terraform/modules (https://github.com/t/modules)."
    result = validate_grounding(text, ALLOWED)
    assert result.stripped_urls == ["https://github.com/t/modules"]
    assert result.cited_urls == []


def test_markdown_link_to_fabricated_url_keeps_its_label():
    text = "Start with [the handbook](https://example.com/handbook) today."
    result = validate_grounding(text, ALLOWED)
    assert result.text == "Start with the handbook today."
    assert result.stripped_urls == ["https://example.com/handbook"]


def test_repeated_allowed_url_is_cited_once():
    text = (
        "Clone https://github.com/k/examples, then read "
        "https://github.com/k/examples again."
    )
    result = validate_grounding(text, ALLOWED)
    assert result.cited_urls == ["https://github.com/k/examples"]


def test_tip_with_no_urls_reports_no_citations():
    result = validate_grounding("Just practise more.", ALLOWED)
    assert result.cited_urls == []
    assert result.stripped_urls == []
    assert result.text == "Just practise more."


def test_unparseable_url_is_stripped_rather_than_raising():
    """`canonical_url` calls `urlsplit`, which rejects a host that fails NFKC
    normalization — and `extract_urls` will genuinely hand one through. One
    hallucinated URL must not crash the whole grounding pass, so the failure
    resolves in the safe direction: unparseable means un-matchable, therefore
    stripped."""
    text = "Read the guide (https://git℀hub.com/k/examples) first."
    result = validate_grounding(text, ALLOWED)
    assert result.stripped_urls == ["https://git℀hub.com/k/examples"]
    assert result.cited_urls == []
    assert result.text == "Read the guide first."


def test_unparseable_allowlist_entry_does_not_raise():
    """The allowlist is canonicalized too, and it comes from a scraped corpus
    rather than a trusted constant, so the same guard has to hold on that side."""
    result = validate_grounding(
        "See https://github.com/k/examples now.",
        ["https://git℀hub.com/k/examples", "https://github.com/k/examples"],
    )
    assert result.cited_urls == ["https://github.com/k/examples"]
    assert result.stripped_urls == []


def test_truncated_token_keeping_an_allowlisted_prefix_is_stripped_whole():
    """The prefix attack Task 1's truncation guard exists to stop, checked end
    to end: `extract_urls` hands back the whole bracketed token, so it cannot
    match the allowlist, and removal takes the fabricated path out with it
    rather than leaving `(fake/path)` dangling in the tip."""
    text = "See https://github.com/k/examples(fake/path) now."
    result = validate_grounding(text, ALLOWED)
    assert result.stripped_urls == ["https://github.com/k/examples(fake/path)"]
    assert result.cited_urls == []
    assert "fake" not in result.text
    assert result.text == "See now."


def test_bare_fabricated_url_ending_a_sentence_leaves_clean_prose():
    """The most common shape after the parenthetical: no brackets to tidy, so
    the risk is a stranded space before the full stop."""
    text = "Then read https://example.com/handbook."
    result = validate_grounding(text, ALLOWED)
    assert result.stripped_urls == ["https://example.com/handbook"]
    assert result.text == "Then read."


# --- Removal is positional, not substring-based -----------------------------
#
# Removing a URL by `str.replace` reached inside *other* URLs' occurrences:
# every allowlisted GitHub URL has "https://github.com" and
# "https://github.com/<org>" as literal prefixes, so stripping a fabricated
# prefix mangled the legitimate citation standing next to it. The prose damage
# was the visible half; the dangerous half was that `cited_urls` went on naming
# a URL the returned text no longer contained, and the caller drops a tip only
# when `cited_urls` is empty — so a citationless tip was stored as grounded.
#
# Sorting removals longest-first would not have fixed it: allowed URLs are
# never removed, so a short fabricated URL's substring replace still reaches
# into a long allowed one. Every case below therefore asserts `cited_urls`
# against the URLs *actually present* in the returned text, not merely that it
# is non-empty.


@pytest.mark.parametrize(
    "text,expected_text,expected_stripped",
    [
        # The ordinary-prose trigger: a model mentions the bare domain in
        # passing and cites a real deep link in the same sentence.
        (
            "Search GitHub (https://github.com) then clone "
            "https://github.com/k/examples.",
            "Search GitHub then clone https://github.com/k/examples.",
            ["https://github.com"],
        ),
        (
            "Browse https://github.com for repos, then clone "
            "https://github.com/k/examples.",
            "Browse for repos, then clone https://github.com/k/examples.",
            ["https://github.com"],
        ),
        # A fabricated near-miss that is a strict *prefix* of the allowed URL,
        # in both orders — order never mattered to the substring bug.
        (
            "Read https://github.com/k/examples then https://github.com/k/example.",
            "Read https://github.com/k/examples then.",
            ["https://github.com/k/example"],
        ),
        (
            "Read https://github.com/k/example then https://github.com/k/examples.",
            "Read then https://github.com/k/examples.",
            ["https://github.com/k/example"],
        ),
        # The reverse containment: the allowed URL is a prefix of the
        # fabricated one (a real repo root with extra path glued on).
        (
            "Start at https://github.com/k/examples then see "
            "https://github.com/k/examples/docs.",
            "Start at https://github.com/k/examples then see.",
            ["https://github.com/k/examples/docs"],
        ),
    ],
)
def test_removal_never_damages_a_neighbouring_url(
    text, expected_text, expected_stripped
):
    result = validate_grounding(text, ALLOWED)
    assert result.text == expected_text
    assert result.stripped_urls == expected_stripped
    # cited_urls must describe the text that was actually returned.
    assert result.cited_urls == ["https://github.com/k/examples"]
    assert result.cited_urls == extract_urls(result.text)


@pytest.mark.parametrize(
    "text",
    [
        "Search GitHub (https://github.com) then clone https://github.com/k/examples.",
        "Read https://github.com/k/examples then https://github.com/k/example.",
        "Read https://github.com/k/example then https://github.com/k/examples.",
        "Start at https://github.com/k/examples then see https://github.com/k/examples/docs.",
        "Try https://github.com/t/modules and https://github.com/k/examples.",
        "Only https://github.com/t/modules here.",
        "Work through kubernetes/examples (https://github.com/k/examples).",
    ],
)
def test_cited_urls_always_matches_the_returned_text(text):
    """The invariant the caller's "drop tips citing nothing" rule depends on:
    `cited_urls` is derived from the returned text, so it can never claim a
    citation the reader will not find."""
    result = validate_grounding(text, ALLOWED)
    assert result.cited_urls == extract_urls(result.text)


def test_stripping_a_line_final_url_leaves_no_trailing_space():
    """A bullet list is the commonest tip layout, so a citation ending a line
    is the commonest strip. `[ \\t]{2,}` needs two spaces and `\\s+([.,;:!?])`
    needs punctuation, so neither tidy rule fired on the one space left
    behind."""
    result = validate_grounding("Read https://x.test/a\nThen continue.", ALLOWED)
    assert result.text == "Read\nThen continue."
    assert result.stripped_urls == ["https://x.test/a"]
    assert result.cited_urls == []


def test_stripping_one_bullet_leaves_the_other_bullet_intact():
    text = "- Docs: https://bad.test/a\n- Real: https://github.com/k/examples\n"
    result = validate_grounding(text, ALLOWED)
    assert result.text == "- Docs:\n- Real: https://github.com/k/examples"
    assert result.cited_urls == extract_urls(result.text)
    assert result.stripped_urls == ["https://bad.test/a"]
