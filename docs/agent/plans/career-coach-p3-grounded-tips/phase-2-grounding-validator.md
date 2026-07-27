# Phase 2: Grounding Validator

> **Parent plan:** [plan.md](plan.md)
> **Status:** Complete
> **Depends on:** nothing — this phase is pure string logic and shares no code
> with Phase 1. Sequenced second only because Phase 3 consumes it.

---

## Goal

Build the deterministic enforcement FR-CC-9 and NFR-CC-3 require: given a tip's
text and the URLs retrieved for that gap, return the text with every
un-allowlisted URL removed, plus the lists of what survived and what was
stripped. Done when the module is exhaustively tested on plain strings, with no
LLM, no database, and no network anywhere in it.

## Safety Checklist

- **Touches user input, auth, secrets, or external calls?**
  Yes, indirectly — this module's input is untrusted LLM output, and it *is*
  the validation boundary for it. It performs no network call of its own; it
  never fetches a URL, only compares it against the allowlist.
- **Contains a one-way door (schema, public API shape, new dependency)?**
  No. New module, no dependency (`re` and `urllib.parse` are stdlib).

---

## Tasks

### Task 1: URL extraction *(spike — resolves the extractor risk in plan.md)*

The risk this settles: an extractor that mis-handles trailing punctuation or
Markdown syntax either loses a legitimate citation or lets a fabricated URL
through. Pin the behaviour against the real shapes an LLM emits **before** any
stripping logic exists. Both possible outcomes are complete answers — if a
shape proves unparseable by regex, record it in Notes and constrain the prompt
in Phase 3 to avoid emitting it.

- **Files:** `scout/sub_agents/coach/grounding.py`, `tests/test_coach_grounding.py`
- **Gate:** none
- **Steps:**
  - [x] Write failing test: one parametrized case per URL shape, covering bare
        URLs, sentence-final URLs, parenthesised URLs, Markdown links, two
        URLs in one sentence, and text with no URL at all.

    ```python
    # tests/test_coach_grounding.py
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
    ```

  - [x] Verify it fails (`pytest tests/test_coach_grounding.py -v`) — expected:
        `ModuleNotFoundError: No module named 'scout.sub_agents.coach.grounding'`
  - [x] Implement `extract_urls` in a new
        `scout/sub_agents/coach/grounding.py`.

    ```python
    from __future__ import annotations

    import re
    from urllib.parse import urlsplit, urlunsplit

    from pydantic import BaseModel

    # LLM prose wraps URLs in parentheses and Markdown link syntax and ends
    # sentences with them, so the pattern stops at whitespace and at the
    # bracket characters that are prose in practice. The cost is a URL that
    # genuinely contains a bracket (rare outside wiki links) being truncated —
    # accepted, because the alternative is swallowing the closing paren of
    # every parenthesised citation into the URL and failing every comparison.
    _URL_PATTERN = re.compile(r"https?://[^\s<>\"'()\[\]]+")

    # Trailing sentence punctuation is prose, never part of the URL. A path
    # genuinely ending in one of these would be mis-trimmed; no such URL exists
    # in the corpus, which stores GitHub repo roots.
    _TRAILING_PUNCTUATION = ".,;:!?"


    def extract_urls(text: str) -> list[str]:
        """Every URL appearing in a tip, in order, duplicates included."""
        return [
            match.group(0).rstrip(_TRAILING_PUNCTUATION)
            for match in _URL_PATTERN.finditer(text)
        ]
    ```

  - [x] Verify it passes (`pytest tests/test_coach_grounding.py -v`)
  - [x] Record in Notes / Learnings: any shape that could not be handled, and
        whether Phase 3's prompt must avoid it.
  - [x] Commit: `feat(coach): add URL extraction for grounding validation`

### Task 2: URL canonicalization for comparison

- **Files:** `scout/sub_agents/coach/grounding.py`, `tests/test_coach_grounding.py`
- **Gate:** none
- **Steps:**
  - [x] Write failing test: cosmetic differences compare equal, meaningful
        differences do not.

    ```python
    # append to tests/test_coach_grounding.py
    from scout.sub_agents.coach.grounding import canonical_url


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
    ```

  - [x] Verify it fails (`pytest tests/test_coach_grounding.py -v`) — expected:
        `ImportError: cannot import name 'canonical_url'`
  - [x] Implement in `grounding.py`.

    ```python
    def canonical_url(url: str) -> str:
        """Normalize only what is cosmetic, so comparison is neither too
        strict nor too loose.

        Scheme and host are case-insensitive per RFC 3986 and a trailing
        slash on a path names the same resource, so normalizing those stops a
        real citation being stripped over formatting. Everything else is left
        alone deliberately: path case is significant, and folding it would let
        a fabricated near-miss path canonicalize onto a real one — which is
        exactly the failure this validator exists to catch. The scheme is
        compared, not normalized away, so http:// and https:// stay distinct.
        """
        parts = urlsplit(url.strip())
        return urlunsplit(
            (
                parts.scheme.lower(),
                parts.netloc.lower(),
                parts.path.rstrip("/"),
                parts.query,
                parts.fragment,
            )
        )
    ```

  - [x] Verify it passes (`pytest tests/test_coach_grounding.py -v`)
  - [x] Commit: `feat(coach): add URL canonicalization for allowlist comparison`

### Task 3: `validate_grounding`

- **Files:** `scout/sub_agents/coach/grounding.py`, `tests/test_coach_grounding.py`
- **Gate:** none
- **Steps:**
  - [x] Write failing test: allowed URLs survive untouched; a fabricated URL is
        removed from the text and reported as stripped; a URL from a *different*
        gap's resources is stripped even though it is real; the leftover prose
        reads cleanly; a tip citing nothing valid reports no citations; **and a
        URL that `canonical_url` cannot parse is stripped rather than raising**
        (e.g. a host containing `℀`, which `extract_urls` will hand
        through and `urlsplit` rejects under NFKC — added after Task 2's
        review found the unguarded call).

    ```python
    # append to tests/test_coach_grounding.py
    from scout.sub_agents.coach.grounding import validate_grounding

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
    ```

  - [x] Verify it fails (`pytest tests/test_coach_grounding.py -v`) — expected:
        `ImportError: cannot import name 'validate_grounding'`
  - [x] Implement in `grounding.py`.

    ```python
    class GroundingResult(BaseModel):
        """The outcome of validating one tip against one gap's allowlist.

        `stripped_urls` is returned rather than only logged so the caller can
        count violations per run and store the surviving citations.
        """

        text: str
        cited_urls: list[str] = []
        stripped_urls: list[str] = []


    def _remove_url(text: str, url: str) -> str:
        """Take one URL out of the prose without leaving debris behind."""
        escaped = re.escape(url)
        # [label](url) -> label: the sentence still reads, minus the link.
        text = re.sub(rf"\[([^\]]*)\]\(\s*{escaped}/?\s*\)", r"\1", text)
        # " (url)" -> "": a parenthesised citation goes with its parentheses.
        text = re.sub(rf"\s*\(\s*{escaped}/?\s*\)", "", text)
        return text.replace(url, "")


    def _tidy(text: str) -> str:
        text = re.sub(r"\(\s*\)", "", text)
        text = re.sub(r"[ \t]{2,}", " ", text)
        text = re.sub(r"\s+([.,;:!?])", r"\1", text)
        return text.strip()


    def _safe_canonical(url: str) -> str:
        """`canonical_url`, but never raising on untrusted input.

        `urlsplit` rejects some strings the extractor will genuinely hand us —
        a host that fails NFKC normalization, for one — and this function's
        whole job is absorbing model output, so a crash here would take down
        the grounding pass instead of stripping one bad URL. Falling back to
        the raw string is safe in the direction that matters: an unparseable
        URL cannot equal a canonicalized allowlist entry, so it stays
        un-matchable and gets stripped.
        """
        try:
            return canonical_url(url)
        except ValueError:
            return url


    def validate_grounding(text: str, allowed_urls: list[str]) -> GroundingResult:
        """Strip every URL in `text` that is not in `allowed_urls`.

        `allowed_urls` is the resource set retrieved for **one gap**, not for
        the whole listing. Enforcement is deterministic on purpose: the
        generation prompt also instructs the model to cite only these, but per
        D-CC-5 that instruction is not what makes it true.
        """
        allowed = {_safe_canonical(url) for url in allowed_urls}
        cited: list[str] = []
        stripped: list[str] = []
        cleaned = text

        for url in extract_urls(text):
            if _safe_canonical(url) in allowed:
                if url not in cited:
                    cited.append(url)
            elif url not in stripped:
                stripped.append(url)
                cleaned = _remove_url(cleaned, url)

        return GroundingResult(
            text=_tidy(cleaned), cited_urls=cited, stripped_urls=stripped
        )
    ```

  - [x] Verify it passes (`pytest tests/test_coach_grounding.py -v`)
  - [x] Commit: `feat(coach): add deterministic grounding validator`

---

## Verification

- [x] All phase tests pass: `pytest tests/test_coach_grounding.py -v`
- [x] The module imports nothing from `asyncpg`, `litellm`, or `requests` —
      confirm with
      `grep -nE "asyncpg|litellm|requests|httpx" scout/sub_agents/coach/grounding.py`
      returning nothing. This is the integrity boundary; it must stay testable
      without a database or a model.
- [x] Manual: none — nothing calls this until Phase 3.

## Rollback

Revert the phase's three commits. `grounding.py` is a new file with no
consumers until Phase 3; deleting it affects nothing else.

---

## Notes / Learnings

### Task 1 spike outcome — the regex extractor is sufficient

The named risk (some real LLM output shape is unparseable by regex) did **not**
materialise for the shapes the corpus and prompt will produce. What it takes is
a pattern, a trailing-punctuation trim, **and the truncation guard described
below** — the guard is load-bearing, not a refinement: without it a fabricated
deep link truncates onto an allowlisted prefix and survives. Together they
cover every shape in the task's table and several more, all pinned in
`tests/test_coach_grounding.py`:

- bare URL, sentence-final URL (`.`, `!`, `...`), comma-followed URL
- parenthesised citation `(url).`
- Markdown link `[label](url)`, and autolink `<url>`
- two URLs in one sentence; URLs at end of bullet lines (newline-delimited)
- quoted URL `"url"`, and uppercase or mixed-case schemes (`HTTPS://…`)
- query string and fragment retained (`?tab=readme#setup`)
- duplicates returned in order, as the docstring promises
- text with no URL, and the empty string

**Bracket truncation is NOT safe on its own — it needs the truncation guard.**
The original spike recorded truncation as the safe direction of error. That was
wrong for this corpus. The corpus stores GitHub **repo roots**, so a fabricated
deep link written as `https://github.com/a/b(fake/path)` truncates to exactly
`https://github.com/a/b` — an allowlist entry. Comparison passes, nothing is
stripped, and the entire fabricated string stays in the tip verbatim. The same
holds for any stop character, e.g. `https://github.com/a/b'sfake`.

`extract_urls` therefore detects truncation and returns the **full
non-whitespace token** instead of the prefix. A token containing a bracket or
quote can never equal an allowlist entry, so it is always stripped — the safe
direction — and Task 3's removal step takes the whole fabricated string out
rather than leaving a dangling `(fake/path)`. The rule, for a match that stops
at one of `<>"'()[]`, is two halves, each guarding one failure direction:

- An **opening** bracket right after the URL (`url(fake/path)`) is always
  truncation — nothing it could close came before it. Guards against a
  fabricated link keeping an allowlisted prefix.
- A **closer** (`)]>"'`) is a wrap when whitespace, sentence punctuation or the
  end of the string follows it, and a truncation when more non-whitespace does
  (`url)fake`). Guards against a real citation being stripped because the prose
  said more than the URL.

The wrap half deliberately asks what *follows the closer*, never what precedes
the URL. An earlier version required the opener to touch the URL, which read
every ordinary parenthetical or quotation containing more than the bare URL —
`(see url)`, `(docs: url)`, `said "start with url"` — as a truncation and
stripped a correctly-cited real link out of a fine tip.

Consequence for a URL whose path genuinely contains brackets (e.g.
`…/Deployment_(computing)`): it is extracted whole, fails comparison, and is
stripped. A real link is lost; a fabricated one is never kept. Note also that
`_full_token` swallows a wrapper's own closer, so
`[label](https://en.wikipedia.org/wiki/Deployment_(computing))` yields a token
with one paren too many; the outcome is safe (stripped), but Task 3's removal
step will leave a dangling `[label](` in the prose.

**Limit of the wrap guard**, pinned as a test: once a wrap is recognised,
anything after the closer stays in the prose. `(https://github.com/a/b).fake/path`
extracts the clean allowlisted URL — the `.` after the `)` reads as prose — and
leaves `.fake/path` behind as text. This is far weaker than the prefix attack:
the fabricated remainder sits outside the closing delimiter, so it is not part
of the link and no reader can follow it. Junk glued directly to the closer
(`(url)fake/path`) *is* caught, as truncation.

**One shape remains deliberately not handled**, pinned as a test so it stays
visible, and it constrains Phase 3:

- **A schemeless mention** (`github.com/k/examples`) is not extracted, so
  nothing downstream can strip it. This *is* the unsafe direction: a
  fabricated schemeless reference would survive untouched. Phase 3's
  generation prompt must therefore require citations as full `https://` URLs
  and forbid bare-domain references; the prompt cannot be trusted for
  correctness (D-CC-5), but it can be used to keep output inside the shape
  the deterministic validator can police.

An uppercase scheme (`HTTPS://github.com/a/b`) used to fall in that same unsafe
class — un-extracted, therefore un-strippable. Scheme matching is now
case-insensitive, so it is extracted and policed like any other URL, and Task
2's `canonical_url` lowercases the scheme for comparison.

No fragile pattern was added to chase any of these.

### Task 3 defect — substring removal was the wrong primitive

Shipped in `15b6d68`, fixed after review. `_remove_url` ended in
`text.replace(url, "")`. A URL is not a token to `str.replace`; it is a
substring, and these substrings nest. Every allowlisted GitHub URL has
`https://github.com` and `https://github.com/<org>` as literal prefixes, so
removing a fabricated URL reached *inside* a legitimate citation's occurrence:

```
allowlist = ["https://github.com/k/examples"]

"Search GitHub (https://github.com) then clone https://github.com/k/examples."
  -> "Search GitHub then clone /k/examples."   cited: ["https://github.com/k/examples"]
"Read https://github.com/k/examples then https://github.com/k/example."
  -> "Read s then."                            cited: ["https://github.com/k/examples"]
```

The mangled prose was the visible half. The dangerous half was `cited_urls`:
it was accumulated from `extract_urls(text)` on the *original* text, alongside
the removals rather than from their result, so it kept naming a citation the
returned text no longer contained. That is exactly the signal Phase 3's caller
uses to drop tips citing nothing — so a tip whose only citation had been
destroyed was stored as properly grounded. Order was irrelevant; the fabrication
mangled the citation whether it came before or after it. Sorting removals
longest-first would **not** have fixed it either: allowed URLs are never removed
at all, so a short fabricated URL's substring replace still reaches into a long
allowed URL's occurrence. Only position fixes it.

The fix, and the two rules worth carrying into Phase 3:

- **Remove by span.** An internal `_iter_urls` generator yields
  `(url, start, end)`; `extract_urls` is now a thin wrapper over it, unchanged
  in behaviour and signature. The span is of the token actually *returned* —
  widened by the truncation guard, trimmed of trailing punctuation — not of the
  bare regex match, or removal would leave the widened remainder behind.
  `validate_grounding` rebuilds the text in one pass, copying between spans
  verbatim and dropping spans that fail the allowlist. Wrapper cleanup
  (`[label](url)` → `label`, `(url)` → nothing) is matched *relative to the
  span* — `\Z`-anchored opener patterns on the slice before it, a closer
  pattern at its end — so a wrapper cannot be found across a neighbouring URL.
  Spans starting before the rebuild cursor are skipped: a widened token can
  contain a later regex match, and cutting it twice would corrupt the text.
- **Derive the report from the result, never alongside it.** `cited_urls` is
  now read back out of the rebuilt, tidied text via `extract_urls`. Any
  bookkeeping computed in parallel with a transformation can disagree with it;
  when the disagreement is what a caller's drop/keep decision rests on, it must
  be derived instead. Pinned as a `cited_urls == extract_urls(result.text)`
  assertion across the removal cases.

Also fixed in the same pass (minor): `_tidy` left a space stranded before a
newline. `[ \t]{2,}` needs two spaces and `\s+([.,;:!?])` needs punctuation, so
neither rule fired on the single space a line-final citation leaves behind —
and a bullet list is the commonest tip layout, so line-final citations are the
commonest strip.

Deliberately left alone: a fabricated URL nested *inside* an allowed URL's
widened token (only reachable via `https://a/b(https://c/d)` with the outer
token allowlisted) is skipped rather than cut, so it survives. Cutting it would
corrupt a citation the allowlist approved, and the shape requires an allowlist
entry containing a bracket, which the corpus of GitHub repo roots does not have.
