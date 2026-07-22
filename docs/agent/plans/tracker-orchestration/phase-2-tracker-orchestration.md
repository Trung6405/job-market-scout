# Phase 2: Tracker Orchestration

> **Parent plan:** [plan.md](plan.md)
> **Status:** Complete
> **Depends on:** Phase 1 complete

---

## Goal

Implement `track_listings()` in `scout/tools/tracker.py`, orchestrating
Phase 1's Storage primitives: upsert every listing in a batch, collect
those classified `new`/`changed`, close stale listings once per batch, and
manage its own pool lifecycle when the caller doesn't supply one. We'll
know it worked when `tests/test_tracker.py` passes against a local
Postgres and demonstrates the full new/changed/unchanged/closed lifecycle
end to end.

## Safety Checklist

- **Touches user input, auth, secrets, or external calls?** Yes — same
  Postgres connection as Phase 1, via the Storage module. No new external
  surface; failures still raise (fail-fast), no retry.
- **Contains a one-way door (schema, public API shape, new dependency)?**
  No — `track_listings` is a new, currently-uncalled function. No schema
  or dependency changes in this phase.

---

## Tasks

### Task 1: Core batch upsert and new/changed/unchanged routing

- **Files:** `scout/tools/tracker.py`, `tests/test_tracker.py` (new)
- **Gate:** none
- **Interfaces:**
  - Consumes: `create_pool`, `apply_schema`, `upsert_listing`, `close_stale_listings` from `scout.shared.db` (Phase 1); `Listing` from `scout.shared.schemas`; `Settings` from `scout.config`.
  - Produces: `async def track_listings(listings: list[Listing], pool: asyncpg.Pool | None = None, settings: Settings | None = None) -> list[Listing]` — the pipeline's Tracker entry point, to be called directly by a future root-agent wiring.
- **Steps:**
  - [ ] Write `tests/test_tracker.py`:
    ```python
    from __future__ import annotations

    import pytest

    from scout.shared.db import upsert_listing
    from scout.tools.tracker import track_listings
    from tests.test_db import _make_listing


    @pytest.mark.asyncio
    async def test_track_listings_returns_only_new_and_changed(db_pool):
        existing = _make_listing(source="linkedin", external_id="job-existing")
        async with db_pool.acquire() as conn:
            await upsert_listing(conn, existing)

        changed = _make_listing(
            source="linkedin", external_id="job-existing", title="Updated Title"
        )
        unchanged = _make_listing(source="linkedin", external_id="job-unchanged-src")
        async with db_pool.acquire() as conn:
            await upsert_listing(conn, unchanged)
        new = _make_listing(source="linkedin", external_id="job-new")

        result = await track_listings([changed, unchanged, new], pool=db_pool)

        assert result == [changed, new]

        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT external_id, title FROM listings ORDER BY external_id"
            )
        stored = {row["external_id"]: row["title"] for row in rows}
        assert stored["job-existing"] == "Updated Title"
        assert stored["job-new"] == new.title
    ```
  - [ ] Verify it fails (`python -m pytest tests/test_tracker.py -v`)
    Expected: FAIL with `ImportError: cannot import name 'track_listings' from 'scout.tools.tracker'` (the file is currently empty).
  - [ ] Implement the initial version of `track_listings` in `scout/tools/tracker.py`:
    ```python
    from __future__ import annotations

    import asyncpg

    from scout.config import Settings
    from scout.shared.db import apply_schema, create_pool, upsert_listing
    from scout.shared.schemas import Listing


    async def track_listings(
        listings: list[Listing],
        pool: asyncpg.Pool | None = None,
        settings: Settings | None = None,
    ) -> list[Listing]:
        owns_pool = pool is None
        active_pool = pool if pool is not None else await create_pool(settings)
        if owns_pool:
            await apply_schema(active_pool)

        relevant: list[Listing] = []
        async with active_pool.acquire() as conn:
            for listing in listings:
                classification = await upsert_listing(conn, listing)
                if classification in ("new", "changed"):
                    relevant.append(listing)

        if owns_pool:
            await active_pool.close()
        return relevant
    ```
  - [ ] Verify it passes (`python -m pytest tests/test_tracker.py -v`)
    Expected: PASS.
  - [ ] Commit:
    ```bash
    git add scout/tools/tracker.py tests/test_tracker.py
    git commit -m "feat(tracker): add track_listings core upsert routing"
    ```

### Task 2: Stale-listing closing scoped to the batch

- **Files:** `scout/tools/tracker.py`, `tests/test_tracker.py`
- **Gate:** none
- **Steps:**
  - [ ] Write the failing test, appended to `tests/test_tracker.py`:
    ```python
    @pytest.mark.asyncio
    async def test_track_listings_closes_previously_open_listings_absent_from_batch(
        db_pool,
    ):
        stale = _make_listing(source="linkedin", external_id="job-stale")
        async with db_pool.acquire() as conn:
            await upsert_listing(conn, stale)

        current = _make_listing(source="linkedin", external_id="job-current")

        await track_listings([current], pool=db_pool)

        async with db_pool.acquire() as conn:
            stale_row = await conn.fetchrow(
                "SELECT status FROM listings WHERE external_id = $1", "job-stale"
            )
            current_row = await conn.fetchrow(
                "SELECT status FROM listings WHERE external_id = $1", "job-current"
            )

        assert stale_row["status"] == "closed"
        assert current_row["status"] == "open"
    ```
  - [ ] Verify it fails (`python -m pytest tests/test_tracker.py -v`)
    Expected: FAIL — `stale_row["status"]` is `"open"` instead of `"closed"` (nothing calls `close_stale_listings` yet).
  - [ ] Update `scout/tools/tracker.py`'s import line and function body to close stale listings once per batch, after all upserts. Replace the import line:
    ```python
    from scout.shared.db import apply_schema, create_pool, upsert_listing
    ```
    with:
    ```python
    from scout.shared.db import (
        apply_schema,
        close_stale_listings,
        create_pool,
        upsert_listing,
    )
    ```
    Then replace the body of `track_listings` (from `relevant: list[Listing] = []` through the final `return relevant`) with:
    ```python
        try:
            relevant: list[Listing] = []
            async with active_pool.acquire() as conn:
                for listing in listings:
                    classification = await upsert_listing(conn, listing)
                    if classification in ("new", "changed"):
                        relevant.append(listing)
                seen_keys = [
                    (listing.source, listing.external_id) for listing in listings
                ]
                await close_stale_listings(conn, seen_keys)
            return relevant
        finally:
            if owns_pool:
                await active_pool.close()
    ```
  - [ ] Verify it passes (`python -m pytest tests/test_tracker.py -v`)
    Expected: PASS (2 tests).
  - [ ] Commit:
    ```bash
    git add scout/tools/tracker.py tests/test_tracker.py
    git commit -m "feat(tracker): close stale listings once per batch"
    ```

### Task 3: Self-managed vs. caller-supplied pool lifecycle

- **Files:** `scout/tools/tracker.py` (no change expected — this task verifies existing behavior from Tasks 1-2), `tests/test_tracker.py`
- **Gate:** none
- **Steps:**
  - [ ] Write the failing tests, appended to `tests/test_tracker.py`. Add `asyncpg` to the imports at the top of the file (`import asyncpg` alongside the existing imports), then:
    ```python
    @pytest.mark.asyncio
    async def test_track_listings_closes_self_managed_pool(db_pool, monkeypatch):
        from scout.shared.db import create_pool as real_create_pool

        created_pools = []

        async def _tracking_create_pool(settings=None):
            created_pool = await real_create_pool(settings)
            created_pools.append(created_pool)
            return created_pool

        monkeypatch.setattr(
            "scout.tools.tracker.create_pool", _tracking_create_pool
        )

        await track_listings(
            [_make_listing(source="linkedin", external_id="job-self-managed")]
        )

        assert len(created_pools) == 1
        with pytest.raises(asyncpg.InterfaceError):
            await created_pools[0].acquire()


    @pytest.mark.asyncio
    async def test_track_listings_does_not_close_caller_supplied_pool(db_pool):
        await track_listings(
            [_make_listing(source="linkedin", external_id="job-caller-pool")],
            pool=db_pool,
        )

        async with db_pool.acquire() as conn:
            row = await conn.fetchrow("SELECT 1 AS ok")

        assert row["ok"] == 1
    ```
    Note: `test_track_listings_closes_self_managed_pool` connects to the
    same default `DATABASE_URL` as `db_pool` (both resolve to
    `postgresql://scout:scout@localhost:5433/scout` — see
    `scout/config.py`'s `database_url` default from Phase 1 Task 1); the
    `db_pool` fixture is only used here to get the auto-skip-if-unreachable
    behavior before the test creates its own separate pool.
  - [ ] Verify the tests fail or pass as-is (`python -m pytest tests/test_tracker.py -v`)
    Expected: the existing implementation from Tasks 1-2 already satisfies both — this is a **characterization pass**: run once to confirm both PASS with zero production code changes. If either fails, that reveals a bug in Task 1/2's implementation to fix before proceeding (do not skip past a failure here).
  - [ ] Commit:
    ```bash
    git add tests/test_tracker.py
    git commit -m "test(tracker): verify self-managed vs caller-supplied pool lifecycle"
    ```

### Task 4: Safe re-run after a partial failure

- **Files:** `scout/tools/tracker.py` (no change expected), `tests/test_tracker.py`
- **Gate:** none
- **Steps:**
  - [ ] Write the failing test, appended to `tests/test_tracker.py`:
    ```python
    @pytest.mark.asyncio
    async def test_track_listings_rerun_after_partial_failure_is_safe(db_pool):
        listing_a = _make_listing(source="linkedin", external_id="job-a")
        listing_b = _make_listing(source="linkedin", external_id="job-b")

        async with db_pool.acquire() as conn:
            await upsert_listing(conn, listing_a)

        result = await track_listings([listing_a, listing_b], pool=db_pool)

        assert result == [listing_b]
    ```
    This simulates a prior run that upserted `listing_a` and then crashed
    before finishing the batch (Storage's fail-fast, no-transaction design
    from the spec). Re-running the full batch must classify `listing_a` as
    `unchanged` (already committed, content identical) and only return
    `listing_b`.
  - [ ] Verify it passes as-is (`python -m pytest tests/test_tracker.py -v`)
    Expected: PASS — this is another characterization test confirming the
    idempotent-retry property already holds from Tasks 1-2's
    implementation. If it fails, that's a real bug: fix `track_listings` or
    `upsert_listing` before proceeding.
  - [ ] Commit:
    ```bash
    git add tests/test_tracker.py
    git commit -m "test(tracker): verify safe re-run after partial failure"
    ```

---

## Verification

- [ ] All phase tests pass: `docker compose up -d postgres && python -m pytest tests/test_tracker.py tests/test_db.py tests/test_config.py -v`
- [ ] Manual check: with `docker compose up -d postgres` running, execute this snippet twice in a row and confirm the second call prints `[]` (everything now unchanged):
  ```python
  import asyncio
  from datetime import datetime, timezone
  from scout.shared.schemas import Listing
  from scout.tools.tracker import track_listings

  listing = Listing(
      source="linkedin", external_id="manual-check-1", title="Test",
      company="Acme", location="Remote", is_remote=True,
      url="https://example.com/1", description="desc",
      scraped_at=datetime.now(timezone.utc),
  )
  print(asyncio.run(track_listings([listing])))
  print(asyncio.run(track_listings([listing])))
  ```

## Observability

`track_listings` has no logging of its own yet — errors surface as raised
`asyncpg` exceptions (fail-fast, per the spec). If a batch run needs
visibility later (e.g. how many new/changed/closed per run), that's a
follow-up, not required by this phase's acceptance criteria.

## Rollback

Revert the phase's commits. `track_listings` has no caller yet (root
`SequentialAgent` wiring is out of scope), so there's nothing running in
production to roll back.

---

## Notes / Learnings

<Filled in during execution.>
