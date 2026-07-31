"""One-off migration: re-tag resources whose skill names lost their punctuation.

`fix(skills)` in this branch stops `normalize_skill` collapsing C, C++ and C#
onto ``c`` (and F# onto ``f``, .NET onto ``net``). That fixes every *future*
write, but it cannot fix the rows already stored, and — unlike
``scripts/backfill_resource_skills.py`` — re-normalizing them is not enough.

That script worked because normalization was a pure function of data still
present in the row: raw skill strings were sitting there waiting to be
canonicalized. Here the information is genuinely gone. A repo about C# was
tagged "C#", normalized to ``c`` on write, and the raw tag was never stored.
``normalize_skill("c")`` is still ``c`` — there is nothing left to recover
from. The only source of truth is the README, so affected rows have to go
back through the LLM tagging pass.

Scope is deliberately narrow: only rows carrying a token the old strip could
have produced from a punctuated name. A row tagged ``c`` might legitimately be
about C, so this does not guess — it re-reads and re-tags.

Usage:
    python -m scripts.retag_punctuated_skills            # dry run, no writes
    python -m scripts.retag_punctuated_skills --apply    # perform the update
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from scout.config import settings as default_settings
from scout.shared.db import create_pool
from scout.shared.skills import normalize_skills
from scout.sub_agents.coach.github_search import fetch_readme
from scout.sub_agents.coach.tagging import tag_readme

logger = logging.getLogger("scripts.retag_punctuated_skills")

#: Normalized tokens the *old* strip could produce from a punctuated name:
#: ``c`` from C/C++/C#, ``f`` from F/F#, ``net`` from .NET/ASP.NET. A row is a
#: candidate if it carries any of these — including rows that were always
#: correct, which re-tagging simply confirms.
AMBIGUOUS_TOKENS = ("c", "f", "net")

#: Seconds between README fetches. The aggregator throttles its own GitHub
#: calls for the same reason (see P1's rate-limit fix); this is a one-off run
#: over a few dozen rows, so it stays well inside the PAT's budget.
_FETCH_DELAY_SECONDS = 1.0


async def retag(*, apply: bool) -> None:
    settings = default_settings
    pool = await create_pool(settings)
    changed = unchanged = skipped = 0
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, url, title, skills
                FROM resources
                WHERE skills && $1::text[]
                ORDER BY id
                """,
                list(AMBIGUOUS_TOKENS),
            )
        logger.info("%s candidate row(s) carrying %s", len(rows), list(AMBIGUOUS_TOKENS))

        for index, row in enumerate(rows):
            if index:
                await asyncio.sleep(_FETCH_DELAY_SECONDS)

            readme = fetch_readme(str(row["url"]), settings)
            if not readme:
                logger.warning(
                    "skipped %s (%s): README unavailable", row["title"], row["url"]
                )
                skipped += 1
                continue

            try:
                tags = await tag_readme(readme, settings)
            except Exception as exc:
                # One unreadable README must not abort a migration that has
                # already rewritten earlier rows.
                logger.warning("skipped %s: tagging failed: %s", row["title"], exc)
                skipped += 1
                continue

            new_skills = normalize_skills(tags.skills)
            if not new_skills:
                logger.warning(
                    "skipped %s: re-tagging produced no skills", row["title"]
                )
                skipped += 1
                continue

            if new_skills == list(row["skills"]):
                unchanged += 1
                continue

            logger.info(
                "%s %s: %s -> %s",
                "updating" if apply else "would update",
                row["title"],
                list(row["skills"]),
                new_skills,
            )
            if apply:
                async with pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE resources SET skills = $1 WHERE id = $2",
                        new_skills,
                        row["id"],
                    )
            changed += 1
    finally:
        await pool.close()

    logger.info(
        "%s: %s changed, %s already correct, %s skipped.",
        "Applied" if apply else "Dry run (no writes)",
        changed,
        unchanged,
        skipped,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="perform the update; without it the script only reports.",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    asyncio.run(retag(apply=args.apply))


if __name__ == "__main__":
    main()
