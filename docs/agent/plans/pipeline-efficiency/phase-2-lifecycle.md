# Phase 2: Listing Lifecycle & Run Record

> **Parent plan:** [plan.md](plan.md)
> **Status:** Complete
> **Depends on:** Phase 1 complete

---

## Goal

Stop the pipeline paying twice for listings it has already analysed, and
stop a same-day re-run degrading the earlier run's record. We'll know it
worked when a listing missing from one day's scrape stays `open`, a
description-only edit does not mark a listing `changed`, and a second run
on the same date leaves the first's counts and gaps intact.

## Safety Checklist

- **Touches user input, auth, secrets, or external calls?**
  No — this phase is entirely `scout/shared/db.py` and `scout/config.py`.
- **Contains a one-way door (schema, public API shape, new dependency)?**
  Yes — **Task 2** rewrites `content_hash` across every row of `listings`.
  No DDL is involved and `schema.sql` is unchanged, but the pre-backfill
  hashes are not recoverable. Gated on human sign-off.

---

## Tasks

### Task 1: Narrow the content hash

- **Files:** `scout/shared/db.py`, `tests/test_db.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing test in `tests/test_db.py`:

```python
def test_content_hash_ignores_description(listing_factory):
    from scout.shared.db import _content_hash

    original = listing_factory(description="We need Python.")
    reworded = listing_factory(description="We are looking for Python skills!")
    assert _content_hash(original) == _content_hash(reworded)


def test_content_hash_still_tracks_substantive_fields(listing_factory):
    from scout.shared.db import _content_hash

    base = listing_factory()
    assert _content_hash(base) != _content_hash(listing_factory(title="Staff Engineer"))
    assert _content_hash(base) != _content_hash(listing_factory(company="Other Ltd"))
    assert _content_hash(base) != _content_hash(listing_factory(location="Sydney NSW"))
    assert _content_hash(base) != _content_hash(listing_factory(is_remote=True))
    assert _content_hash(base) != _content_hash(listing_factory(salary_min=90000.0))
    assert _content_hash(base) != _content_hash(listing_factory(salary_max=120000.0))
```

  - [ ] Verify it fails (`pytest tests/test_db.py -k content_hash -v`) —
        expect the first test to fail on differing hashes
  - [ ] Change `_content_hash` in `scout/shared/db.py` to drop
        `listing.description` from the payload, and record why:

```python
def _content_hash(listing: Listing) -> str:
    """Fingerprint the fields that change a listing's substance.

    ``description`` is deliberately excluded: job boards re-word and
    re-timestamp descriptions constantly, and including it meant any
    cosmetic edit marked the listing ``changed`` and bought a full
    re-analysis. The trade-off is accepted — a materially rewritten
    description goes unnoticed until some other tracked field moves.
    """
    payload = "\x00".join(
        [
            listing.title,
            listing.company,
            listing.location,
            str(listing.is_remote),
            str(listing.salary_min),
            str(listing.salary_max),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
```

  - [ ] Verify it passes (`pytest tests/test_db.py -k content_hash -v`)
  - [ ] Commit: `fix(tracker): exclude description from the content hash`

### Task 2: Content-hash backfill script

- **Files:** `scout/backfill_hashes.py`, `tests/test_backfill_hashes.py`
- **Gate:** ⚠️ **Human sign-off required before running it against the dev
  or production database.** Writing and testing the script needs no gate;
  executing it does.
- **Steps:**
  - [ ] Write failing test in `tests/test_backfill_hashes.py`:

```python
from __future__ import annotations

from scout.backfill_hashes import backfill_content_hashes
from scout.shared.db import _content_hash, upsert_listing


async def test_backfill_rewrites_stale_hashes(db_pool, listing_factory):
    listing = listing_factory()
    async with db_pool.acquire() as conn:
        await upsert_listing(conn, listing)
        await conn.execute("UPDATE listings SET content_hash = 'stale'")

        updated = await backfill_content_hashes(conn)
        assert updated == 1

        stored = await conn.fetchval("SELECT content_hash FROM listings")
        assert stored == _content_hash(listing)


async def test_backfill_is_idempotent(db_pool, listing_factory):
    async with db_pool.acquire() as conn:
        await upsert_listing(conn, listing_factory())
        await conn.execute("UPDATE listings SET content_hash = 'stale'")
        first = await backfill_content_hashes(conn)
        second = await backfill_content_hashes(conn)
        assert first == 1
        assert second == 0
```

  - [ ] Verify it fails (`pytest tests/test_backfill_hashes.py -v`) — expect
        `ModuleNotFoundError: No module named 'scout.backfill_hashes'`
  - [ ] Implement `scout/backfill_hashes.py`:

```python
"""Recompute every stored ``content_hash`` under the current definition.

Run once, before the first pipeline run on code that narrowed the hash.
Without it, every listing's stored hash disagrees with its freshly computed
one, so the next run marks the entire table ``changed`` and re-analyses it
at full cost:

    python -m scout.backfill_hashes

Idempotent and re-runnable: rows already holding the correct hash are left
alone and not counted.
"""

from __future__ import annotations

import asyncio
import logging
import sys

import asyncpg

from scout.config import settings as default_settings
from scout.shared.db import _content_hash, create_pool
from scout.shared.schemas import Listing

logger = logging.getLogger("scout.backfill_hashes")


async def backfill_content_hashes(conn: asyncpg.Connection) -> int:
    """Rewrite stale hashes in place. Returns the number of rows changed."""
    rows = await conn.fetch(
        """
        SELECT source, external_id, title, company, location, url, description,
               is_remote, salary_min, salary_max, date_posted, scraped_at,
               content_hash
        FROM listings
        """
    )
    updated = 0
    for row in rows:
        data = dict(row)
        stored_hash = data.pop("content_hash")
        expected = _content_hash(Listing(**data))
        if expected == stored_hash:
            continue
        await conn.execute(
            "UPDATE listings SET content_hash = $3 WHERE source = $1 AND external_id = $2",
            data["source"],
            data["external_id"],
            expected,
        )
        updated += 1
    return updated


async def run_backfill() -> None:
    pool = await create_pool(default_settings)
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                updated = await backfill_content_hashes(conn)
        logger.info("backfilled %d listing hash(es)", updated)
    finally:
        await pool.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(run_backfill())
    except Exception:
        logger.exception("backfill failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
```

  - [x] Verify it passes (`pytest tests/test_backfill_hashes.py -v`)
  - [x] Commit: `feat(db): add content-hash backfill script`
  - [x] ⚠️ **Stop for sign-off**, then run against dev:
        `docker compose run --rm app python -m scout.backfill_hashes` —
        human approved 2026-07-24; ran after a rebuild (the image predated
        the new file), backfilled 241 listing hash(es); re-run confirmed
        idempotent (0 on the second pass)

### Task 3: Time-based listing closure

- **Files:** `scout/config.py`, `scout/shared/db.py`,
  `scout/sub_agents/tracker/runner.py`, `tests/test_db.py`,
  `tests/test_tracker.py`
- **Gate:** none
- **Steps:**
  - [ ] Add to `scout/config.py`:

```python
    # Days a listing may go unseen before it is treated as closed. A daily
    # scrape only sees RESULTS_WANTED per role within HOURS_OLD, so a still-open
    # listing routinely misses a day; closing on first absence made it reopen
    # as "changed" and bought a second full analysis of the same listing.
    listing_stale_days: int = field(
        default_factory=partial(_env_int, "LISTING_STALE_DAYS", 7)
    )
```

  - [ ] Write failing test in `tests/test_db.py`:

```python
async def test_close_stale_listings_keeps_recently_seen(db_pool, listing_factory):
    from scout.shared.db import close_stale_listings, upsert_listing

    async with db_pool.acquire() as conn:
        await upsert_listing(conn, listing_factory(external_id="fresh"))
        closed = await close_stale_listings(conn, stale_days=7)
        assert closed == []
        status = await conn.fetchval("SELECT status FROM listings")
        assert status == "open"


async def test_close_stale_listings_closes_long_unseen(db_pool, listing_factory):
    from scout.shared.db import close_stale_listings, upsert_listing

    async with db_pool.acquire() as conn:
        await upsert_listing(conn, listing_factory(external_id="old"))
        await conn.execute("UPDATE listings SET last_seen_at = now() - interval '30 days'")
        closed = await close_stale_listings(conn, stale_days=7)
        assert closed == ["old"]
        status = await conn.fetchval("SELECT status FROM listings")
        assert status == "closed"
```

  - [ ] Verify it fails (`pytest tests/test_db.py -k close_stale -v`) —
        expect a `TypeError` on the changed signature
  - [ ] Replace `close_stale_listings` in `scout/shared/db.py`:

```python
async def close_stale_listings(
    conn: asyncpg.Connection, stale_days: int
) -> list[str]:
    """Close listings unseen for longer than ``stale_days``.

    Closure is deliberately time-based rather than "absent from this run":
    a run only sees RESULTS_WANTED listings per role within HOURS_OLD, so a
    still-open listing drops out of the results routinely. Closing on first
    absence made it reopen as ``changed`` on its return, buying a second
    full analysis of a listing that never changed.

    ``last_seen_at`` is stamped by ``upsert_listing``, so this needs no
    seen-key arrays.
    """
    rows = await conn.fetch(
        """
        UPDATE listings
        SET status = 'closed', closed_at = now()
        WHERE status = 'open'
          AND last_seen_at < now() - make_interval(days => $1)
        RETURNING external_id
        """,
        stale_days,
    )
    return [row["external_id"] for row in rows]
```

  - [ ] Update `scout/sub_agents/tracker/runner.py` to drop the `seen_keys`
        construction and call
        `await close_stale_listings(conn, active_settings.listing_stale_days)`,
        resolving `active_settings` from the `settings` argument the way the
        other runners do
  - [ ] Verify it passes (`pytest tests/test_db.py tests/test_tracker.py -v`)
  - [ ] Commit: `fix(tracker): close listings on staleness, not absence`

### Task 4: Non-destructive run record

- **Files:** `scout/shared/db.py`, `tests/test_db.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing test in `tests/test_db.py`:

```python
async def test_finish_run_derives_scored_from_stored_rows(db_pool, listing_factory, match_factory):
    from datetime import date

    from scout.shared.db import finish_run, record_run_listings, start_run, upsert_listing

    async with db_pool.acquire() as conn:
        listing = listing_factory()
        await upsert_listing(conn, listing)
        run_id = await start_run(conn, date(2026, 7, 24))
        await record_run_listings(conn, run_id, [(match_factory(listing=listing), "competitive")])

        # Report a wrong count; the stored rows are the source of truth.
        await finish_run(conn, run_id, listings_scraped=40, listings_scored=999)
        scored = await conn.fetchval("SELECT listings_scored FROM runs WHERE id = $1", run_id)
        assert scored == 1


async def test_finish_run_never_lowers_scraped_count(db_pool):
    from datetime import date

    from scout.shared.db import finish_run, start_run

    async with db_pool.acquire() as conn:
        run_id = await start_run(conn, date(2026, 7, 24))
        await finish_run(conn, run_id, listings_scraped=81, listings_scored=0)
        # A quieter same-day re-run must not shrink the day's snapshot.
        await finish_run(conn, run_id, listings_scraped=3, listings_scored=0)
        scraped = await conn.fetchval("SELECT listings_scraped FROM runs WHERE id = $1", run_id)
        assert scraped == 81
```

  - [ ] Verify it fails (`pytest tests/test_db.py -k finish_run -v`)
  - [ ] Replace `finish_run` in `scout/shared/db.py`:

```python
async def finish_run(
    conn: asyncpg.Connection,
    run_id: int,
    listings_scraped: int,
    listings_scored: int,
) -> None:
    """Mark a run finished without letting a re-run degrade it.

    Two runs on one date share a row (``runs.run_date`` is unique, kept
    deliberately — see the pipeline-hardening spec). The second is usually
    quieter than the first, so reporting its numbers verbatim used to zero
    the morning's ``listings_scored`` while its ``run_listings`` rows stayed
    in the table. Instead: ``listings_scored`` is derived from those rows,
    and ``listings_scraped`` keeps the larger of the two snapshots.

    ``listings_scored`` is passed but unused; it stays in the signature so
    callers read symmetrically and so the derived value is obviously
    authoritative.
    """
    await conn.execute(
        """
        UPDATE runs
        SET listings_scraped = GREATEST(runs.listings_scraped, $2),
            listings_scored = (
                SELECT count(*) FROM run_listings WHERE run_listings.run_id = $1
            ),
            finished_at = now()
        WHERE id = $1
        """,
        run_id,
        listings_scraped,
    )
```

  - [ ] Verify it passes (`pytest tests/test_db.py -k finish_run -v`)
  - [ ] Commit: `fix(db): make finish_run non-destructive on same-day re-runs`

### Task 5: Scoped gap replacement

- **Files:** `scout/shared/db.py`, `tests/test_db.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing test in `tests/test_db.py`:

```python
async def test_record_listing_gaps_only_replaces_supplied_listings(
    db_pool, listing_factory, match_factory
):
    from datetime import date

    from scout.shared.db import (
        record_listing_gaps,
        record_run_listings,
        start_run,
        upsert_listing,
    )
    from scout.shared.schemas import SkillGap

    async with db_pool.acquire() as conn:
        first = listing_factory(external_id="first")
        second = listing_factory(external_id="second")
        for listing in (first, second):
            await upsert_listing(conn, listing)
        run_id = await start_run(conn, date(2026, 7, 24))
        await record_run_listings(
            conn,
            run_id,
            [
                (match_factory(listing=first), "competitive"),
                (match_factory(listing=second), "competitive"),
            ],
        )

        gap = SkillGap(skill="Go", requirement_level="must_have", met=False, kind="skill")
        await record_listing_gaps(conn, run_id, [(match_factory(listing=first), [gap])])
        await record_listing_gaps(conn, run_id, [(match_factory(listing=second), [gap])])

        # Recording the second listing's gaps must not have wiped the first's.
        total = await conn.fetchval("SELECT count(*) FROM listing_gaps")
        assert total == 2
```

  - [ ] Verify it fails (`pytest tests/test_db.py -k record_listing_gaps -v`)
        — expect `total == 1`, the first listing's row having been deleted
  - [ ] Narrow the `DELETE` in `record_listing_gaps` from the whole run to
        the listings supplied, reusing the arrays it already builds:

```python
        await conn.execute(
            """
            DELETE FROM listing_gaps
            WHERE run_listing_id IN (
                SELECT run_listings.id
                FROM run_listings
                JOIN listings ON listings.id = run_listings.listing_id
                JOIN unnest($2::text[], $3::text[]) AS data(source, external_id)
                    ON listings.source = data.source
                   AND listings.external_id = data.external_id
                WHERE run_listings.run_id = $1
            )
            """,
            run_id,
            sources,
            external_ids,
        )
```

> Note the ordering change: `sources` and `external_ids` must now be built
> **before** the `DELETE` rather than after it. Move the list-building block
> above the delete, and keep the early `return` for an empty `skills` list
> after the delete so a listing whose requirements are all met still clears
> its stale rows.

  - [ ] Verify it passes (`pytest tests/test_db.py -k record_listing_gaps -v`)
  - [ ] Commit: `fix(db): scope gap replacement to the listings supplied`

---

## Verification

- [x] All phase tests pass: `pytest tests/test_db.py tests/test_tracker.py tests/test_backfill_hashes.py -v`
- [x] Full suite passes: `pytest -q` — 236 passed
- [x] Manual: ran the pipeline twice in one day (2026-07-24) against the
      live dev DB — first run 77 scraped/80 scored, second (quieter) run 27
      scraped/10 scored. Run row after both:
      `listings_scraped = 77` (GREATEST kept the larger snapshot, did not
      drop to 27) and `listings_scored = 89` (derived from the real
      `run_listings` row count — 80 + 9 net-new after upserts — which also
      self-corrected a stale `55` the row had held from before Task 4
      existed).
- [x] Manual: `SELECT count(*) FROM listings WHERE status = 'closed' AND
      closed_at > now() - interval '1 hour'` returned 0 after the second
      run — the closed-listing total actually *dropped* (164 → 156) because
      8 previously-closed listings reappeared and were reopened as
      `changed`, not because anything was newly closed.

## Rollback

`git revert` the phase's commits. The backfill is **not** undone by a
revert: hashes written under the narrowed definition stay. Reverting Task 1
therefore causes one expensive run in which everything reads as `changed` —
re-run `python -m scout.backfill_hashes` from the reverted code to avoid it.

---

## Notes / Learnings

<Filled in during execution.>
