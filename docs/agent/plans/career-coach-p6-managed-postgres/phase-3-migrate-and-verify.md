# Phase 3: Migrate and Verify

> **Parent plan:** [plan.md](plan.md)
> **Status:** In progress — Task 1 done, Task 2 (dump and restore) next
> **Depends on:** Phase 2 complete (the instance exists, TLS and pgvector proven)
>
> **This is the last phase that executes in the current pass.** Scope is
> evaluation only (spec A1): the cutover in phase 4 is deferred, so this phase
> now ends by tearing the instance down rather than handing it on.

---

## Goal

Copy the six tables onto the managed instance and produce the side-by-side row
counts the cutover gate is decided from. Done when the verification script
reports every table matching plus an equal count of `resources` carrying a
non-NULL `embedding`, with the VM's database untouched and still serving the
pipeline.

## Safety Checklist

- **Touches user input, auth, secrets, or external calls?**
  Yes — the dump and restore run against both databases using the
  administrator credentials from Phase 2. Both DSNs are passed through the
  environment rather than argv, so neither lands in shell history or the
  process list.
- **Contains a one-way door (schema, public API shape, new dependency)?**
  No. The source is read-only throughout and the target is disposable until
  Phase 4 repoints anything at it.

---

## Tasks

### Task 1: A script that compares the two databases

- **Files:**
  - Create: `scripts/verify_migration.py`
  - Create: `tests/test_verify_migration.py`
- **Gate:** none
- **Steps:**

  - [x] **Step 1: Write the failing test**

    Create `tests/test_verify_migration.py`:

    ```python
    """The comparison the cutover gate is read from.

    The DB round-trip is thin and exercised for real in Task 3; what is worth
    testing is the comparison itself, because a report that reads "all match"
    for the wrong reason is exactly how a one-way door gets walked through
    without anyone having looked.
    """

    from __future__ import annotations

    from scripts.verify_migration import (
        CountComparison,
        EMBEDDING_LABEL,
        TABLES,
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
        resources = next(c for c in compare_counts(source, target) if c.label == "resources")
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
    ```

  - [x] **Step 2: Run the test to verify it fails**

    Run: `pytest tests/test_verify_migration.py -v`
    Expected: FAIL at collection with
    `ModuleNotFoundError: No module named 'scripts.verify_migration'`

  - [x] **Step 3: Write minimal implementation**

    Create `scripts/verify_migration.py`:

    ```python
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


    async def collect_counts(dsn: str) -> dict[str, int]:
        conn = await asyncpg.connect(dsn=dsn)
        try:
            counts = {
                table: await conn.fetchval(f"SELECT count(*) FROM {table}")
                for table in TABLES
            }
            counts[EMBEDDING_LABEL] = await conn.fetchval(
                "SELECT count(*) FROM resources WHERE embedding IS NOT NULL"
            )
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
    ```

  - [x] **Step 4: Run the test to verify it passes**

    Run: `pytest tests/test_verify_migration.py -v`
    Expected: PASS (7 tests)

  - [x] **Step 5: Commit**

    ```bash
    git add scripts/verify_migration.py tests/test_verify_migration.py
    git commit -m "feat(scripts): row-count verification for the P6 database move

The cutover is a one-way door decided by a human reading numbers, so the
numbers get a committed, testable script rather than ad-hoc psql. Counts all
six foreign-key-connected tables (the umbrella PRS names four) and counts
resources carrying a non-NULL embedding separately — a vector column can
restore as NULL with every row present, which is the only part of this copy
whose failure is silent rather than loud.

DSNs come from the environment, not argv, so neither lands in shell history."
    ```

### Task 2: Dump and restore

- **Files:** none — this runs on the VM.
- **Gate:** none — the source is read-only and the target is disposable until
  Phase 4.
- **Steps:**
  - [ ] Merge Task 1 to `main` so the script reaches the VM (`Deploy` rsyncs
    the repo) before it is needed:

    ```bash
    gh pr create --fill && gh pr merge --squash
    gh run watch "$(gh run list --workflow=Deploy --limit 1 --json databaseId --jq '.[0].databaseId')"
    ```

  - [ ] Pick a window when nothing is writing. The pipeline runs once a day at
    19:00 UTC and the deploy only runs on a push, so any time well clear of
    both is fine. Confirm nothing is in flight:

    ```bash
    gh run list --workflow='Scheduled run' --limit 1
    ```

  - [ ] SSH to the VM, start the stack if the VM was deallocated, and take the
    dump. Both `pg_dump` and `psql` run inside the VM's own
    `pgvector/pgvector:pg16` container, so the client versions match the source
    exactly and the VM needs no Postgres packages installed:

    ```bash
    az vm start -g "$RESOURCE_GROUP" -n scout-vm
    ssh azureuser@"$VM_HOST"
    cd /opt/job-market-scout
    docker compose -f docker-compose.yaml -f docker-compose.prod.yaml up -d postgres

    docker compose -f docker-compose.yaml -f docker-compose.prod.yaml exec -T postgres \
      pg_dump -U scout -d scout --format=plain --no-owner --no-privileges \
      > /tmp/scout-migration.sql
    wc -l /tmp/scout-migration.sql
    grep -c 'CREATE TABLE' /tmp/scout-migration.sql
    ```

    `--no-owner --no-privileges` because the administrative role on the managed
    instance (`scoutadmin`) is not the container's (`scout`), so ownership and
    grant statements would fail on restore. Plain format rather than custom:
    this database is small and an inspectable file is worth more here than
    `pg_restore`'s parallelism.

    Expected: 6 `CREATE TABLE` statements.

  - [ ] Restore into the managed instance. `ON_ERROR_STOP=1` so a failure stops
    at the first bad statement instead of leaving a half-copied database that
    still counts rows:

    ```bash
    read -rs -p 'managed DSN: ' TARGET_DSN && export TARGET_DSN
    docker compose -f docker-compose.yaml -f docker-compose.prod.yaml exec -T postgres \
      psql "$TARGET_DSN" -v ON_ERROR_STOP=1 -f - < /tmp/scout-migration.sql
    ```

    Expected: `CREATE TABLE` / `COPY` output and exit 0. An error on
    `CREATE EXTENSION vector` means the `azure.extensions` allow-list from
    Phase 2 did not apply — fix that before retrying rather than creating the
    extension by hand, or the next deployment will silently differ from the
    template.

  - [ ] Shred the dump — it holds the entire listings corpus and every scored
    result:

    ```bash
    shred -u /tmp/scout-migration.sql 2>/dev/null || rm -f /tmp/scout-migration.sql
    ```

  - [ ] No commit.

### Task 3: Run the verification and read the numbers

- **Files:** none — output is recorded in this doc's Notes section.
- **Gate:** none here; the numbers this produces are what Phase 4's gate is
  decided from.
- **Steps:**
  - [ ] From the VM, with both DSNs in the environment:

    ```bash
    cd /opt/job-market-scout
    export SOURCE_DSN='postgresql://scout:scout@postgres:5432/scout'
    read -rs -p 'managed DSN: ' TARGET_DSN && export TARGET_DSN
    docker compose -f docker-compose.yaml -f docker-compose.prod.yaml \
      run --rm -e SOURCE_DSN -e TARGET_DSN app python -m scripts.verify_migration
    echo "exit: $?"
    ```

    Expected: every row `yes`, the closing line
    `All counts match — safe to proceed to cutover.`, and exit 0.

  - [ ] Spot-check that the vectors survived as vectors rather than as nulls or
    text — the count alone cannot tell those apart:

    ```bash
    docker compose -f docker-compose.yaml -f docker-compose.prod.yaml \
      run --rm -e TARGET_DSN app python -c "
    import asyncio, os, asyncpg

    async def main():
        conn = await asyncpg.connect(dsn=os.environ['TARGET_DSN'])
        print('dimensions:', await conn.fetchval(
            'SELECT vector_dims(embedding) FROM resources WHERE embedding IS NOT NULL LIMIT 1'))
        print('nearest:', await conn.fetchval('''
            SELECT title FROM resources
            WHERE embedding IS NOT NULL
            ORDER BY embedding <=> (SELECT embedding FROM resources WHERE embedding IS NOT NULL LIMIT 1)
            LIMIT 1'''))
        await conn.close()

    asyncio.run(main())
    "
    ```

    Expected: `dimensions: 384` and a resource title.

  - [ ] Paste the full report into Notes below.
  - [ ] No commit.

### Task 4: Record the evaluation and tear the instance down

- **Files:** findings recorded in this doc's Notes.
- **Gate:** ⚠️ human sign-off before deletion — it is irreversible, and it is
  the point at which the evaluation's cost stops accruing. Confirm the numbers
  are captured first; they are the whole return on this pass.
- **Steps:**
  - [ ] Confirm every measurement is written into Notes: the verification
    report, the observed Postgres and pgvector versions, the TLS result, and
    the latency figures from phase 2 Task 4. Once the server is gone these
    cannot be re-derived without paying again.
  - [ ] Confirm nothing points at the instance — `DATABASE_URL` must still name
    the VM's container, since phase 4 never ran:

    ```bash
    ssh -i ~/.ssh/scout_vm azureuser@"$VM_HOST"       "cd /opt/job-market-scout && docker compose -f docker-compose.yaml -f docker-compose.prod.yaml         run --rm app python -c \"
    from urllib.parse import urlparse
    from scout.config import Settings
    print(urlparse(Settings().database_url).hostname)\""
    ```

    Expected: `postgres`. Anything else means a cutover happened and deleting
    the server would strand data — stop.

  - [ ] Delete the server:

    ```bash
    az postgres flexible-server delete -g "$RESOURCE_GROUP" -n trung6405-scout-pg --yes
    ```

  - [ ] Confirm the cost stopped:

    ```bash
    az postgres flexible-server list -g "$RESOURCE_GROUP" -o table
    ```

    Expected: no rows.

  - [ ] Leave `infra/postgres.bicep` and its guards committed. The template is
    the deliverable that makes re-provisioning a dispatch rather than a
    redesign when the standing cost is funded.
  - [ ] No commit beyond the Notes update.

---

## Verification

- [x] Comparison logic passes: `pytest tests/test_verify_migration.py -v` — 8 passed
- [ ] Full suite still passes: `pytest -q`
- [ ] The dump contains 6 `CREATE TABLE` statements
- [ ] The restore exits 0 under `ON_ERROR_STOP=1`
- [ ] `python -m scripts.verify_migration` reports every table matching, the
      embedding count matching, and exits 0
- [ ] `vector_dims` on the managed instance returns 384 and a nearest-neighbour
      query returns a row
- [ ] The VM database is unchanged: the pipeline is still pointed at it and its
      own counts are the "source" column of the report

## Rollback

Nothing points at the managed instance yet, so a bad copy is thrown away rather
than undone:

```bash
docker compose -f docker-compose.yaml -f docker-compose.prod.yaml exec -T postgres \
  psql "$TARGET_DSN" -c 'DROP SCHEMA public CASCADE; CREATE SCHEMA public;'
```

Then re-run Task 2. The VM's database was never written to, so there is nothing
to restore on the source side. If the dump itself is suspect, revert the Task 1
commit as well and re-approach.

---

## Notes / Learnings

### Task 1 — one deviation from the specified implementation *(2026-07-30)*

The comparison logic is as planned. `collect_counts` is not, and the reason is
worth keeping: **as specified, the script could not produce the report for the
failure it most exists to catch.**

`compare_counts` renders a label missing from the target as `0`, its docstring
calls that "precisely the failure this exists to surface", and a test asserts a
missing table "must read as a row, not a traceback". But nothing could reach
that path through the real entrypoint: `collect_counts` ran
`SELECT count(*) FROM resources` against the target before any comparison
happened, so an absent table raised `UndefinedTableError` out of collection.
The unit test passed because it called `compare_counts` directly.

That absent table is not an exotic case — it is the likeliest way this copy
fails. `resources.embedding` is typed `VECTOR(384)`, so the table depends on the
`vector` type existing; a restore in which `CREATE EXTENSION vector` did not
succeed leaves `resources` missing entirely. The gate would then have shown a
traceback where it was supposed to show numbers.

So counting now tolerates a missing table or column (`UndefinedTableError`,
`UndefinedColumnError`) by omitting the label, which is what makes
`compare_counts`'s documented behaviour reachable. A test drives it through
`collect_counts` with a stubbed connection and asserts both `resources` and the
embedding label come back flagged rather than raising. 8 tests, up from the
planned 7.

Two smaller notes:

- An unset `SOURCE_DSN` / `TARGET_DSN` exits with a bare `KeyError` naming the
  variable. Unfriendly but unambiguous; left alone.
- The report's success line reads "safe to proceed to cutover", which is the
  wording the plan specified and the test pins. Under spec A1 the next step is
  teardown, not cutover, so read that line as "the copy is faithful" rather
  than as an instruction.

*(Tasks 2–4 filled in during execution — paste the full verification report,
including the exit code and the vector_dims spot-check)*
