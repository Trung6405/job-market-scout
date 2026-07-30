"""The comparison the cutover gate is read from.

The DB round-trip is thin and exercised for real in Task 3; what is worth
testing is the comparison itself, because a report that reads "all match"
for the wrong reason is exactly how a one-way door gets walked through
without anyone having looked.
"""

from __future__ import annotations

import asyncpg

from scripts.verify_migration import (
    EMBEDDING_LABEL,
    TABLES,
    CountComparison,
    collect_counts,
    compare_counts,
    format_report,
)


def test_every_foreign_key_connected_table_is_covered():
    """The umbrella PRS names four tables; the connected set is six."""
    assert TABLES == (
        "listings",
        "runs",
        "run_listings",
        "listing_gaps",
        "listing_tips",
        "resources",
    )


def test_matching_counts_all_report_ok():
    counts = {table: 3 for table in TABLES} | {EMBEDDING_LABEL: 3}
    comparisons = compare_counts(counts, dict(counts))
    assert all(comparison.matches for comparison in comparisons)


def test_a_short_table_is_flagged():
    source = {table: 3 for table in TABLES} | {EMBEDDING_LABEL: 3}
    target = source | {"listing_gaps": 2}
    flagged = [c.label for c in compare_counts(source, target) if not c.matches]
    assert flagged == ["listing_gaps"]


def test_a_table_missing_from_the_target_counts_as_zero():
    """"The restore never created it" must read as a row, not a traceback."""
    source = {table: 3 for table in TABLES} | {EMBEDDING_LABEL: 3}
    target = {k: v for k, v in source.items() if k != "resources"}
    resources = next(
        c for c in compare_counts(source, target) if c.label == "resources"
    )
    assert (resources.source, resources.target, resources.matches) == (3, 0, False)


def test_embeddings_are_compared_separately_from_the_rows_holding_them():
    """A vector column can restore as NULL with every row present — the one
    failure in this copy that is silent rather than loud."""
    source = {table: 3 for table in TABLES} | {EMBEDDING_LABEL: 3}
    target = source | {EMBEDDING_LABEL: 0}
    comparisons = compare_counts(source, target)
    assert next(c for c in comparisons if c.label == "resources").matches
    assert not next(c for c in comparisons if c.label == EMBEDDING_LABEL).matches


def test_report_names_every_mismatch_and_refuses_the_cutover():
    comparisons = [
        CountComparison("listings", 10, 10),
        CountComparison("resources", 4, 3),
        CountComparison(EMBEDDING_LABEL, 4, 0),
    ]
    report = format_report(comparisons)
    assert "resources" in report
    assert EMBEDDING_LABEL in report
    assert "do not cut over" in report


def test_report_clears_the_cutover_when_everything_matches():
    comparisons = [CountComparison("listings", 10, 10)]
    assert "safe to proceed" in format_report(comparisons)


async def test_collection_omits_a_table_the_restore_never_created(monkeypatch):
    """The missing-table row above is only reachable if collection tolerates the
    table being absent, and through `compare_counts` alone it was not: the real
    entrypoint counts every table on both sides first, so an absent `resources`
    raised out of collection instead of reporting.

    That is the likeliest failure of this copy, not an exotic one -- `resources`
    depends on the `vector` type, so a restore where `CREATE EXTENSION vector`
    did not succeed leaves exactly this state. The gate must read it as numbers.
    """

    class _Conn:
        async def fetchval(self, sql):
            if "resources" in sql:
                raise asyncpg.UndefinedTableError(
                    'relation "resources" does not exist'
                )
            return 3

        async def close(self):
            return None

    async def _connect(*args, **kwargs):
        return _Conn()

    monkeypatch.setattr(asyncpg, "connect", _connect)

    counts = await collect_counts("postgresql://unused/scout")

    assert "resources" not in counts
    assert EMBEDDING_LABEL not in counts
    assert counts["listings"] == 3

    # And the comparison then renders both as a mismatch rather than dropping
    # them -- the source is what defines the expected set.
    source = {table: 3 for table in TABLES} | {EMBEDDING_LABEL: 3}
    flagged = [c.label for c in compare_counts(source, counts) if not c.matches]
    assert flagged == ["resources", EMBEDDING_LABEL]
