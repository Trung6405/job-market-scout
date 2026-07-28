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

    Surrounding whitespace is dropped, the scheme is lowercased, and the
    whole authority is lowercased — host, and with it any port or userinfo
    that happens to be present. The host is the only part of that where
    lowercasing is actually cosmetic (DNS names are case-insensitive); a port
    is digits, so it is a no-op there; and userinfo *is* case-sensitive per
    RFC 3986, so folding it is a real (if remote) risk, accepted because the
    corpus is GitHub repo roots and never carries userinfo at all. A trailing
    slash on a path names the same resource, so it goes too. Together these
    stop a real citation being stripped over formatting. Everything else is
    left alone deliberately: path case is significant, and folding it would
    let a fabricated near-miss path canonicalize onto a real one — which is
    exactly the failure this validator exists to catch. The scheme is
    compared, not normalized away, so http:// and https:// stay distinct,
    and a port or userinfo is kept rather than folded away, so a lookalike
    authority cannot canonicalize onto the bare host.
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
# Markdown emphasis run: the only thing allowed to sit between a link's own
# closing paren and the end of a widened token without being treated as
# fabrication glued onto the URL.
_EMPHASIS_RUN = re.compile(r"[*_`~]*\Z")


def _link_close(text: str, start: int, end: int) -> int:
    """Where a `[label](url)` construct ends inside a widened token.

    `**[label](url)**` is one of the commonest shapes a model emits, and the
    `*` after the closing paren makes `_is_truncated` widen the match to the
    whole `url)**` token — so the link's own `)` sits *inside* [start, end)
    and `_WRAP_CLOSE` finds nothing at `end`. Cutting all the way to `end`
    would take the closing emphasis with it and leave the opening `**`
    unbalanced, so the cut stops just past that paren instead.

    Only when nothing but emphasis characters follows it: anything else after
    the paren is fabrication glued onto the link, and that must go with the
    URL rather than survive in the prose.
    """
    closer = text.rfind(")", start, end)
    if closer == -1 or _EMPHASIS_RUN.match(text, closer + 1, end) is None:
        return end
    return closer + 1


def _removal_span(text: str, start: int, end: int) -> tuple[int, int, str]:
    """What to cut, and what to put back, to take out the URL at [start, end).

    Returns the wrapper's span when the URL sits inside one, so no debris is
    left behind: `[label](url)` collapses to its label and a parenthesised
    citation goes with its parentheses. Otherwise only the URL's own
    characters are cut.

    The Markdown-link opener is tried unconditionally rather than only when a
    wrap-close matches at `end`, because an emphasis-wrapped link has already
    had its closing paren swallowed by the widened token. Requiring the close
    first left `[label](` stranded in the prose. The `\\Z` anchor on the opener
    is what makes this safe: it only fires when `[label](` sits immediately
    before this URL, never on some earlier link elsewhere in the tip.
    """
    close = _WRAP_CLOSE.match(text, end)
    # [label](url) -> label: the sentence still reads, minus the link.
    link = _MARKDOWN_LINK_OPEN.search(text, 0, start)
    if link is not None:
        cut_end = close.end() if close is not None else _link_close(text, start, end)
        return link.start(), cut_end, link.group(1)
    if close is not None:
        # " (url)" -> "": a parenthesised citation goes with its parentheses.
        paren = _PAREN_OPEN.search(text, 0, start)
        if paren is not None:
            return paren.start(), close.end(), ""
    return start, end, ""


def _tidy(text: str) -> str:
    # An emptied parenthetical. The optional short word covers the lead-in a
    # model writes inside the parentheses — "(see url)", "(docs: url)",
    # "(via url)" — which `_PAREN_OPEN` deliberately refuses to swallow
    # because it does not sit flush against the URL. The trailing `\s+` is
    # what keeps this off ordinary prose: the space is the hole the URL left,
    # so "(now)" and "(v2)" are untouched while "(see )" is not.
    text = re.sub(r"\(\s*\)|\(\s*[A-Za-z]{1,6}:?\s+\)", "", text)
    # The other wrappers the extractor stops at. Unlike parentheses these are
    # never taken with the URL by `_removal_span` — there is no close pattern
    # for them — so stripping a wrapped citation always orphans one or both
    # sides of the pair. P4 renders `listing_tips.tip` verbatim, so this
    # debris is user-visible.
    #
    # The bracket forms tolerate whitespace between the pair (`< >`, `[ ]`)
    # because those shapes are never meaningful prose on their own. The quote
    # form must not: two adjacent quoted terms — `"apply" "diff"` — are
    # ordinary writing, and `_tidy` runs on every tip, not just ones a strip
    # touched, so a `\s*` here would eat the text between them along with the
    # whitespace. An orphaned pair left by a strip has nothing at all between
    # its delimiters (both are stop characters the URL match halts at, so
    # neither is ever pulled into the removed span), so matching only the
    # empty pair still clears every orphan.
    text = re.sub(r"<\s*>|\[\s*\]|\"\"|''", "", text)
    # `*` and the backtick are not stop characters — the URL pattern's
    # negated class does not exclude them — so `**url**` and `` `url` `` are
    # not wrapped, they widen the match: the closing delimiter is swallowed
    # into the URL and removed with it, leaving only the opening one stray in
    # the prose (`See **https://bad/x** then` -> `See ** then`). What is left
    # behind is therefore a single delimiter with whitespace on both sides,
    # not a pair, so this rule clears a lone token rather than an empty pair.
    # It must not touch `**bold** and **also bold**`: every `**` there sits
    # flush against a word on at least one side, so the whitespace-on-both-
    # sides test excludes all four of them.
    text = re.sub(r"(?<!\S)(?:\*\*|`)(?!\S)", "", text)
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

    `cited_urls` carries the **allowlist's** spelling of each surviving
    citation, not the model's. Comparison is canonical, so the two can differ
    by case or a trailing slash, and this is durable data: `listing_tips`
    rows are joined back to `resources.url` by string equality, which a
    model's "HTTPS://GitHub.com/k/examples/" would silently miss. The tip
    *text* is left exactly as written — that is prose, not a key.
    """
    # First spelling wins, so two allowlist entries differing only
    # cosmetically resolve deterministically to the earlier one.
    allowed_spelling: dict[str, str] = {}
    for url in allowed_urls:
        allowed_spelling.setdefault(_safe_canonical(url), url)
    allowed = set(allowed_spelling)
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
        spelling = allowed_spelling.get(_safe_canonical(url))
        if spelling is not None and spelling not in cited:
            cited.append(spelling)

    return GroundingResult(
        text=cleaned, cited_urls=cited, stripped_urls=stripped
    )
