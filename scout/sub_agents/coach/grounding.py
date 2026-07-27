from __future__ import annotations

import re

# LLM prose wraps URLs in parentheses, Markdown link syntax, angle brackets
# and quotes, and ends sentences with them, so the pattern stops at whitespace
# and at the bracket and quote characters — <, >, ", ', (, ), [, ] — that are
# prose in practice. The cost is a URL that genuinely contains one of them
# (rare outside wiki links) being truncated — accepted, because the
# alternative is swallowing the closing paren of every parenthesised citation
# into the URL and failing every comparison. The scheme is matched
# case-insensitively: an un-extracted string is invisible to the allowlist
# comparison and so can never be stripped, and HTTPS:// is a real thing models
# write, so it must not be the one shape that slips past unseen.
_URL_PATTERN = re.compile(r"https?://[^\s<>\"'()\[\]]+", re.IGNORECASE)

# Trailing sentence punctuation is prose, never part of the URL. A path
# genuinely ending in one of these would be mis-trimmed; no such URL exists
# in the corpus, which stores GitHub repo roots.
_TRAILING_PUNCTUATION = ".,;:!?"

# The characters the pattern stops at, and — for the closing half of a pair —
# the opener that makes stopping there a legitimate wrap rather than a
# truncation. A URL is genuinely wrapped only when the character before it
# opens the pair the character after it closes: "(url)", "[label](url)",
# "<url>", '"url"'. Anything else that stops a match is truncation.
_CLOSER_TO_OPENER = {")": "(", "]": "[", ">": "<", '"': '"', "'": "'"}
_STOP_CHARACTERS = frozenset("<>\"'()[]")


def _is_truncated(text: str, match: re.Match[str]) -> bool:
    """Did this match stop at a stop character that was not closing a wrap?

    Truncation matters because the prefix left behind can itself be a valid
    allowlist entry. The corpus stores GitHub repo roots, so a fabricated deep
    link written as `https://github.com/a/b(fake/path)` truncates to exactly
    the allowlisted `https://github.com/a/b`, compares equal, and the whole
    fabricated string — parenthesised part included — survives in the tip.
    Same mechanism for any other stop character, e.g. `https://a/b'sfake`.
    """
    end = match.end()
    if end >= len(text):
        return False
    following = text[end]
    if following not in _STOP_CHARACTERS:
        return False
    opener = _CLOSER_TO_OPENER.get(following)
    if opener is None:
        # An *opening* bracket immediately after a URL never wraps it.
        return True
    start = match.start()
    return start == 0 or text[start - 1] != opener


def _full_token(text: str, start: int) -> str:
    """The whole non-whitespace run beginning at `start`."""
    end = start
    while end < len(text) and not text[end].isspace():
        end += 1
    return text[start:end]


def extract_urls(text: str) -> list[str]:
    """Every URL appearing in a tip, in order, duplicates included.

    When a match was truncated by a stop character rather than closed by a
    legitimate wrap, the full non-whitespace token is returned instead of the
    prefix. A token containing a bracket or quote can never equal an allowlist
    entry, so it is always stripped — the safe direction of error — and the
    removal step takes the fabricated string out whole rather than leaving a
    dangling `(fake/path)` behind.
    """
    urls: list[str] = []
    for match in _URL_PATTERN.finditer(text):
        raw = (
            _full_token(text, match.start())
            if _is_truncated(text, match)
            else match.group(0)
        )
        urls.append(raw.rstrip(_TRAILING_PUNCTUATION))
    return urls
