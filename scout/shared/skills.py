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

# Names where the punctuation IS the distinguishing feature, folded to a
# spelled-out form *before* the strip below erases it. Keyed on the lowercased,
# whitespace-free input rather than the normalized output, because by the time
# the strip has run the information is already gone — "c++" and "c#" are both
# "c" and no later table can tell them apart.
#
# This is the exact opposite case to _VERSION_SUFFIXES above: dropping "." is
# right for "React.js", and wrong here. Getting it wrong marked a C++
# requirement met against a profile listing plain C, and pooled three
# languages' resources into one retrieval bucket.
_PUNCTUATED_SKILLS = {
    "c++": "cpp",
    "c#": "csharp",
    "f#": "fsharp",
    ".net": "dotnet",
    "asp.net": "aspnet",
}


def normalize_skill(skill: str) -> str:
    """Canonicalize a skill name so common variants compare equal.

    Lowercases, folds names whose punctuation is load-bearing (``C++`` ->
    ``cpp``), strips a framework version suffix (``.js``/``.ts``), removes
    remaining punctuation/whitespace, then folds a small set of known aliases
    (``postgres`` -> ``postgresql``). Deterministic and side-effect free — it
    is the guarantee behind gap matching; the extraction prompt's canonical
    naming is a best-effort improvement on top.

    The punctuated-name fold runs first and returns early: the generic strip
    below cannot distinguish ``C``, ``C++`` and ``C#``, so anything that must
    survive it has to be handled before it.

    Shared rather than advisor-local because it is the single canonical form
    on both sides of resource retrieval: the Coach normalizes ``resources.skills``
    on write, and the retriever normalizes gap names on read, so an exact
    ``skills[]`` pre-filter can be trusted to match.
    """
    value = skill.strip().lower()
    # Checked before anything else strips punctuation. Whitespace is squeezed
    # first so "C ++" and "C++" reach the same key.
    punctuated = _PUNCTUATED_SKILLS.get(re.sub(r"\s+", "", value))
    if punctuated is not None:
        return punctuated
    for suffix in _VERSION_SUFFIXES:
        if value.endswith(suffix) and len(value) > len(suffix):
            value = value[: -len(suffix)]
            break
    value = re.sub(r"[^a-z0-9]", "", value)
    return _SKILL_ALIASES.get(value, value)


def normalize_skills(skills: list[str]) -> list[str]:
    """Normalize a list of skill names, dropping empties and duplicates.

    Order is preserved and is **load-bearing** for the retriever, which pairs
    the returned names positionally with their query embeddings.

    Shared rather than duplicated per caller on purpose: the Coach normalizes
    `resources.skills` with this on write and the retriever normalizes gap
    names with it on read. Those are the two halves of one guarantee — if the
    two ever diverged, the exact `skills[]` pre-filter would silently stop
    matching, which is the single failure mode the pre-filter exists to
    prevent.
    """
    normalized: list[str] = []
    seen: set[str] = set()
    for skill in skills:
        value = normalize_skill(skill)
        if value and value not in seen:
            seen.add(value)
            normalized.append(value)
    return normalized
