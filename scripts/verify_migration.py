"""Compare row counts between two scout databases, table by table.

Read-only on both sides. This is what the P6 cutover gate is read from: a
logical dump and restore either brought everything across or it did not,
and the one part whose failure is silent rather than loud is
`resources.embedding` — a vector column restores as NULL if the extension
or the column type went missing, leaving a corpus that is fully present and
entirely unretrievable. So embeddings are counted separately from the rows
that hold them.

Both DSNs come from the environment rather than argv: a DSN on the command
line lands in shell history and in the process list.

    SOURCE_DSN=... TARGET_DSN=... python -m scripts.verify_migration
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from typing import NamedTuple

import asyncpg

# The foreign-key-connected set. The umbrella PRS names four of these; the
# set that actually has to move together is six (recorded as an amendment).
#
# Interpolated into `count(*)` below because a parameter cannot bind an
# identifier. It is a module constant and never caller input, so there is
# no injection surface.
TABLES = (
    "listings",
    "runs",
    "run_listings",
    "listing_gaps",
    "listing_tips",
    "resources",
)

EMBEDDING_LABEL = "resources with embedding"


class CountComparison(NamedTuple):
    label: str
    source: int
    target: int

    @property
    def matches(self) -> bool:
        return self.source == self.target


async def _count(conn: asyncpg.Connection, sql: str) -> int | None:
    """The count, or None when the table or column does not exist here.

    Omitting the label rather than letting the error escape is what makes
    `compare_counts`'s missing-key handling reachable. The likeliest way this
    copy fails is `resources` being absent from the target because
    `CREATE EXTENSION vector` did not succeed, so the table depending on the
    `vector` type was never created — and a traceback out of the collection
    step is exactly the outcome the report exists to replace.

    Each statement runs in its own implicit transaction, so a failed one does
    not poison the queries after it.
    """
    try:
        return await conn.fetchval(sql)
    except (asyncpg.UndefinedTableError, asyncpg.UndefinedColumnError):
        return None


async def collect_counts(dsn: str) -> dict[str, int]:
    conn = await asyncpg.connect(dsn=dsn)
    try:
        counts = {}
        for table in TABLES:
            count = await _count(conn, f"SELECT count(*) FROM {table}")
            if count is not None:
                counts[table] = count
        embeddings = await _count(
            conn, "SELECT count(*) FROM resources WHERE embedding IS NOT NULL"
        )
        if embeddings is not None:
            counts[EMBEDDING_LABEL] = embeddings
        return counts
    finally:
        await conn.close()


def compare_counts(
    source: dict[str, int], target: dict[str, int]
) -> list[CountComparison]:
    """Compare on the source's keys, in a fixed order.

    A label absent from the target reads as 0 rather than raising: "the
    restore never created that table" is precisely the failure this exists
    to surface, and it belongs in the report as a row, not as a traceback.
    """
    return [
        CountComparison(label, source[label], target.get(label, 0))
        for label in (*TABLES, EMBEDDING_LABEL)
        if label in source
    ]


def format_report(comparisons: list[CountComparison]) -> str:
    width = max(len(comparison.label) for comparison in comparisons)
    lines = [f"{'table'.ljust(width)}  {'source':>10}  {'target':>10}  ok"]
    for comparison in comparisons:
        lines.append(
            f"{comparison.label.ljust(width)}  {comparison.source:>10}  "
            f"{comparison.target:>10}  {'yes' if comparison.matches else 'NO'}"
        )
    mismatched = [c.label for c in comparisons if not c.matches]
    lines.append("")
    lines.append(
        "All counts match — safe to proceed to cutover."
        if not mismatched
        else f"MISMATCH in: {', '.join(mismatched)} — do not cut over."
    )
    return "\n".join(lines)


async def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-dsn-env",
        default="SOURCE_DSN",
        help="environment variable holding the source DSN (default: SOURCE_DSN)",
    )
    parser.add_argument(
        "--target-dsn-env",
        default="TARGET_DSN",
        help="environment variable holding the target DSN (default: TARGET_DSN)",
    )
    args = parser.parse_args()

    comparisons = compare_counts(
        await collect_counts(os.environ[args.source_dsn_env]),
        await collect_counts(os.environ[args.target_dsn_env]),
    )
    print(format_report(comparisons))
    return 0 if all(comparison.matches for comparison in comparisons) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
