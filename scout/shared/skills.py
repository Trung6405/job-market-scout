from __future__ import annotations

import re

# Known equivalences that a substring/punctuation strip alone can't collapse.
# Keys and values are in normalized (lowercase, alphanumeric-only) form.
_SKILL_ALIASES = {
    "js": "javascript",
    "ts": "typescript",
    "postgres": "postgresql",
    "postgre": "postgresql",
    "k8s": "kubernetes",
    "golang": "go",
}

# Framework version suffixes stripped before comparison ("React.js" -> "react").
_VERSION_SUFFIXES = (".js", ".ts")


def normalize_skill(skill: str) -> str:
    """Canonicalize a skill name so common variants compare equal.

    Lowercases, strips a framework version suffix (``.js``/``.ts``), removes
    remaining punctuation/whitespace, then folds a small set of known aliases
    (``postgres`` -> ``postgresql``). Deterministic and side-effect free — it
    is the guarantee behind gap matching; the extraction prompt's canonical
    naming is a best-effort improvement on top.

    Shared rather than advisor-local because it is the single canonical form
    on both sides of resource retrieval: the Coach normalizes ``resources.skills``
    on write, and the retriever normalizes gap names on read, so an exact
    ``skills[]`` pre-filter can be trusted to match.
    """
    value = skill.strip().lower()
    for suffix in _VERSION_SUFFIXES:
        if value.endswith(suffix) and len(value) > len(suffix):
            value = value[: -len(suffix)]
            break
    value = re.sub(r"[^a-z0-9]", "", value)
    return _SKILL_ALIASES.get(value, value)
