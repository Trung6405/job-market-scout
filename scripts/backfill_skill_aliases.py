"""Rewrite `resources.skills` through the current normalisation rules.

`resources.skills` stores tokens that are *already normalised*, so extending
the alias table leaves every existing row spelled the old way: a resource
tagged `nodejs` is one the retriever now looks up as `node` and never finds.
The corpus and the code disagree until this runs.

It is a lookup, not a re-tagging run — aliases map normalised form to
normalised form, so the original string is never needed and no LLM or network
call is involved. Idempotent by construction: re-normalising an
already-canonical token is a no-op, so a second pass reports zero changes. If
it ever reports more, the alias table has a cycle.

The DSN comes from the environment rather than argv, matching
`scripts/verify_migration.py`: a DSN on the command line lands in shell history
and in the process list.

    DATABASE_URL=... python -m scripts.backfill_skill_aliases --dry-run
    DATABASE_URL=... python -m scripts.backfill_skill_aliases
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from typing import Iterable, NamedTuple

import asyncpg

from scout.shared.skills import normalize_skills


class Change(NamedTuple):
    row_id: int
    before: list[str]
    after: list[str]


def rewritten(skills: list[str]) -> list[str]:
    """Stored tokens re-normalised through today's rules.

    Order is preserved because the retriever pairs skill names positionally
    with their query embeddings, and duplicates are dropped because two stale
    spellings can collapse onto one canonical token.
    """
    return normalize_skills(skills)


def plan_changes(rows: Iterable[tuple[int, list[str]]]) -> list[Change]:
    """Only the rows whose tokens actually move.

    Excluding no-ops is what lets "rows changed" mean something, and what lets
    a second pass legitimately report zero.
    """
    changes = []
    for row_id, skills in rows:
        after = rewritten(list(skills or []))
        if after != list(skills or []):
            changes.append(Change(row_id, list(skills or []), after))
    return changes


async def collect_rows(conn: asyncpg.Connection) -> list[tuple[int, list[str]]]:
    records = await conn.fetch("SELECT id, skills FROM resources ORDER BY id")
    return [(record["id"], list(record["skills"] or [])) for record in records]


async def apply_changes(conn: asyncpg.Connection, changes: list[Change]) -> None:
    """One statement per changed row, inside a transaction.

    Small enough to be atomic: the corpus is low thousands of rows and only the
    moved ones are touched, so a failure part-way leaves nothing half-rewritten.
    """
    async with conn.transaction():
        for change in changes:
            await conn.execute(
                "UPDATE resources SET skills = $2 WHERE id = $1",
                change.row_id,
                change.after,
            )


def format_report(changes: list[Change], total: int, *, dry_run: bool) -> str:
    verb = "would change" if dry_run else "changed"
    lines = [f"{len(changes)} of {total} rows {verb}."]
    for change in changes[:20]:
        lines.append(
            f"  id={change.row_id}  {', '.join(change.before)}"
            f"  ->  {', '.join(change.after)}"
        )
    if len(changes) > 20:
        lines.append(f"  … and {len(changes) - 20} more")
    return "\n".join(lines)


async def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dsn-env",
        default="DATABASE_URL",
        help="environment variable holding the DSN (default: DATABASE_URL)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would change without writing anything",
    )
    args = parser.parse_args()

    conn = await asyncpg.connect(dsn=os.environ[args.dsn_env])
    try:
        rows = await collect_rows(conn)
        changes = plan_changes(rows)
        print(format_report(changes, len(rows), dry_run=args.dry_run))
        if args.dry_run or not changes:
            return 0
        await apply_changes(conn, changes)

        # Re-plan against what is now stored. A non-zero count here means the
        # rewrite is not a fixed point, which would make the whole operation
        # unsafe to repeat — worth failing loudly rather than reporting success.
        remaining = plan_changes(await collect_rows(conn))
        if remaining:
            print(
                f"ERROR: {len(remaining)} row(s) still not canonical after the "
                "rewrite — the alias table has a cycle.",
                file=sys.stderr,
            )
            return 1
        print("Verified: a second pass finds nothing left to change.")
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
