from __future__ import annotations

import re
from collections.abc import Iterator
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel

# LLM prose wraps URLs in parentheses, Markdown link syntax, angle brackets
# and quotes, and ends sentences with them, so the pattern stops at whitespace
# and at the bracket and quote characters — <, >, ", ', (, ), [, ] — that are
# prose in practice. The alternative is swallowing the closing paren of every
# parenthesised citation into the URL and failing every comparison. The cost is
# a URL that genuinely contains one of them (rare outside wiki links): the
# truncation guard below returns it whole, so it fails comparison and is
# stripped — a real link lost, never a fabricated one kept. The scheme is
# matched case-insensitively: an un-extracted string is invisible to the
# allowlist comparison and so can never be stripped, and HTTPS:// is a real
# thing models write, so it must not be the one shape that slips past unseen.
_URL_PATTERN = re.compile(r"https?://[^\s<>\"'()\[\]]+", re.IGNORECASE)

# Trailing sentence punctuation is prose, never part of the URL. A path
# genuinely ending in one of these would be mis-trimmed; no such URL exists
# in the corpus, which stores GitHub repo roots.
_TRAILING_PUNCTUATION = ".,;:!?"

# The characters the pattern stops at, and the half of them that can *close*
# something the prose opened. Whether stopping at a closer is a legitimate wrap
# or a truncation is decided by what follows the closer, not by what precedes
# the URL: requiring the opener to touch the URL would misread every ordinary
# parenthetical — "(see url)", "(docs: url)", 'said "start with url"' — as a
# truncation and strip a correctly-cited real link.
_CLOSERS = frozenset(")]>\"'")
_STOP_CHARACTERS = frozenset("<>\"'()[]")


def _is_truncated(text: str, match: re.Match[str]) -> bool:
    """Did this match stop at a stop character that was not closing a wrap?

    Truncation matters because the prefix left behind can itself be a valid
    allowlist entry. The corpus stores GitHub repo roots, so a fabricated deep
    link written as `https://github.com/a/b(fake/path)` truncates to exactly
    the allowlisted `https://github.com/a/b`, compares equal, and the whole
    fabricated string — parenthesised part included — survives in the tip.
    Same mechanism for any other stop character, e.g. `https://a/b'sfake`.

    The rule, in two halves, each guarding one failure direction:

    - An *opening* bracket right after the URL (`url(fake/path)`) is always
      truncation — nothing it could close came before it. This half guards
      against a fabricated link keeping an allowlisted prefix.
    - A *closer* is a wrap when whitespace, sentence punctuation or the end of
      the string follows it, and a truncation when more non-whitespace does
      (`url)fake`). This half guards against a real citation being stripped
      because the prose around it said more than the URL.
    """
    end = match.end()
    if end >= len(text):
        return False
    following = text[end]
    if following not in _STOP_CHARACTERS:
        return False
    if following not in _CLOSERS:
        # An *opening* bracket immediately after a URL never wraps it.
        return True
    after_closer = text[end + 1 : end + 2]
    if after_closer == "" or after_closer.isspace():
        return False
    return after_closer not in _TRAILING_PUNCTUATION


def _full_token(text: str, start: int) -> str:
    """The whole non-whitespace run beginning at `start`."""
    end = start
    while end < len(text) and not text[end].isspace():
        end += 1
    return text[start:end]


def _iter_urls(text: str) -> Iterator[tuple[str, int, int]]:
    """Every URL in `text` paired with the span it actually occupies.

    The span belongs to the token *returned*, not to the bare regex match:
    `_is_truncated` can widen a match to the whole non-whitespace run, and
    trailing sentence punctuation is trimmed back off the end. Removal works
    from these spans rather than by substring search, which is the difference
    between taking one URL out and reaching inside another one's occurrence.
    Every allowlisted GitHub URL has `https://github.com` and
    `https://github.com/<org>` as literal prefixes, so a substring removal of a
    fabricated bare-domain mention also ate the front of the legitimate
    citation standing next to it — leaving `/k/examples` in the prose while
    `cited_urls` still claimed the whole URL was cited. Sorting removals
    longest-first does not help: allowed URLs are never removed at all, so a
    short fabricated URL's substring replace still reaches into a long allowed
    one. Only position does.
    """
    for match in _URL_PATTERN.finditer(text):
        start = match.start()
        raw = (
            _full_token(text, start)
            if _is_truncated(text, match)
            else match.group(0)
        )
        url = raw.rstrip(_TRAILING_PUNCTUATION)
        yield url, start, start + len(url)


def extract_urls(text: str) -> list[str]:
    """Every URL appearing in a tip, in order, duplicates included.

    When a match was truncated by a stop character rather than closed by a
    legitimate wrap, the full non-whitespace token is returned instead of the
    prefix. A token containing a bracket or quote can never equal an allowlist
    entry, so it is always stripped — the safe direction of error — and the
    removal step takes the fabricated string out whole rather than leaving a
    dangling `(fake/path)` behind.

    Known limit: when a wrap *is* recognised, anything after the closer stays
    in the prose. `(https://github.com/a/b).fake/path` extracts the clean
    allowlisted URL — the "." after the ")" reads as prose — and leaves
    `.fake/path` behind as text. That is far weaker than the prefix attack: the
    fabricated remainder sits outside the closing delimiter, so it is not part
    of the link and no reader can follow it. But it is not removed either.
    """
    return [url for url, _start, _end in _iter_urls(text)]


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


class GroundingResult(BaseModel):
    """The outcome of validating one tip against one gap's allowlist.

    `stripped_urls` is returned rather than only logged so the caller can
    count violations per run and store the surviving citations.
    """

    text: str
    cited_urls: list[str] = []
    stripped_urls: list[str] = []


# The wrappers prose puts around a citation, matched relative to the URL's own
# span so that removing one URL can never touch another's characters. The
# opener patterns are anchored at the end of the slice preceding the URL with
# \Z; the closer is matched starting at the URL's end.
_MARKDOWN_LINK_OPEN = re.compile(r"\[([^\]]*)\]\(\s*\Z")
_PAREN_OPEN = re.compile(r"\s*\(\s*\Z")
_WRAP_CLOSE = re.compile(r"/?\s*\)")


def _removal_span(text: str, start: int, end: int) -> tuple[int, int, str]:
    """What to cut, and what to put back, to take out the URL at [start, end).

    Returns the wrapper's span when the URL sits inside one, so no debris is
    left behind: `[label](url)` collapses to its label and a parenthesised
    citation goes with its parentheses. Otherwise only the URL's own
    characters are cut.
    """
    close = _WRAP_CLOSE.match(text, end)
    if close is not None:
        # [label](url) -> label: the sentence still reads, minus the link.
        link = _MARKDOWN_LINK_OPEN.search(text, 0, start)
        if link is not None:
            return link.start(), close.end(), link.group(1)
        # " (url)" -> "": a parenthesised citation goes with its parentheses.
        paren = _PAREN_OPEN.search(text, 0, start)
        if paren is not None:
            return paren.start(), close.end(), ""
    return start, end, ""


def _tidy(text: str) -> str:
    text = re.sub(r"\(\s*\)", "", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\s+([.,;:!?])", r"\1", text)
    # A single space stranded at the end of a line: neither rule above fires
    # (one space, no punctuation), and a bullet list is the commonest tip
    # layout, so a line-final citation left one every time it was stripped.
    text = re.sub(r"[ \t]+(?=\n)", "", text)
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

    The text is rebuilt in one pass over the URL spans, copying everything
    between them verbatim and dropping the spans that fail the allowlist, and
    `cited_urls` is then read back out of the rebuilt text. Deriving the
    citations from the result rather than computing them alongside it is the
    point: the caller drops any tip whose `cited_urls` is empty, so a
    `cited_urls` that can name a URL the returned text no longer contains
    turns "uncited advice is worthless" into "uncited advice is stored".
    """
    allowed = {_safe_canonical(url) for url in allowed_urls}
    stripped: list[str] = []
    pieces: list[str] = []
    cursor = 0

    for url, start, end in _iter_urls(text):
        if start < cursor:
            # A widened token already swallowed this match; it is not a
            # separate occurrence, and cutting it again would corrupt the text.
            continue
        if _safe_canonical(url) in allowed:
            continue
        cut_start, cut_end, replacement = _removal_span(text, start, end)
        pieces.append(text[cursor : max(cut_start, cursor)])
        pieces.append(replacement)
        cursor = cut_end
        if url not in stripped:
            stripped.append(url)
    pieces.append(text[cursor:])

    cleaned = _tidy("".join(pieces))
    cited: list[str] = []
    for url in extract_urls(cleaned):
        if url not in cited and _safe_canonical(url) in allowed:
            cited.append(url)

    return GroundingResult(
        text=cleaned, cited_urls=cited, stripped_urls=stripped
    )
