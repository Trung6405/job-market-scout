from __future__ import annotations

import re

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
