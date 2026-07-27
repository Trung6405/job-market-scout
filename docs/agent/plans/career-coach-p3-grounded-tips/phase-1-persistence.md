# Phase 1: Persistence & Schema

> **Parent plan:** [plan.md](plan.md)
> **Status:** Not started
> **Depends on:** nothing (P0/P1 merged; P2 not needed by this phase)

---

## Goal

Give generated tips somewhere to live and a way back out: a `listing_tips`
table mirroring `listing_gaps`, a write helper that joins the run transaction,
and a read-back through `get_run_details`. Done when a tip written for a run
listing comes back attached to that listing's `RunListingDetail`, with nothing
generating tips yet.

## Safety Checklist

- **Touches user input, auth, secrets, or external calls?**
  No — this phase is schema and DB helpers only. No LLM call, no network.
- **Contains a one-way door (schema, public API shape, new dependency)?**
  No. `listing_tips` is a new additive table in the existing
  `CREATE TABLE IF NOT EXISTS` style; no existing table or column is altered,
  and undo is `DROP TABLE listing_tips`.

---

## Tasks

### Task 1: `GroundedTip` schema and `RunListingDetail.tips`

- **Files:** `scout/shared/schemas.py`, `tests/test_coach_tips_schemas.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing test: a `GroundedTip` round-trips its three fields, and
        `RunListingDetail` defaults `tips` to `[]` when not supplied.

    ```python
    # tests/test_coach_tips_schemas.py
    from __future__ import annotations

    from scout.shared.schemas import GroundedTip, Listing, RunListingDetail


    def test_grounded_tip_carries_skill_text_and_citations():
        tip = GroundedTip(
            gap_skill="Kubernetes",
            tip="Work through kubernetes/examples (https://github.com/k/examples).",
            cited_urls=["https://github.com/k/examples"],
        )
        assert tip.gap_skill == "Kubernetes"
        assert tip.cited_urls == ["https://github.com/k/examples"]


    def test_run_listing_detail_defaults_tips_to_empty(listing_factory):
        detail = RunListingDetail(
            run_listing_id=1,
            listing=listing_factory(),
            score=80,
            reasoning="fits",
            band="competitive",
            gaps=[],
        )
        assert detail.tips == []
    ```

  - [ ] Verify it fails (`pytest tests/test_coach_tips_schemas.py -v`) —
        expected: `ImportError: cannot import name 'GroundedTip'`
  - [ ] Implement: add `GroundedTip` next to `RetrievedResource` in
        `scout/shared/schemas.py`, and the `tips` field on `RunListingDetail`.

    ```python
    class GroundedTip(BaseModel):
        """One validated coaching tip for a single gap skill (P3).

        `cited_urls` is the post-validation survivor set, not what the model
        emitted: any URL absent from the gap's retrieved resources has already
        been stripped from `tip` and from this list. Storing it rather than
        only logging it is what makes a grounding violation auditable after
        the run.

        `gap_skill` holds the gap's raw stored wording, as `listing_gaps.skill`
        does, so a tip joins back to the gap it answers without renormalizing.
        """

        gap_skill: str
        tip: str
        cited_urls: list[str] = []
    ```

    ```python
    class RunListingDetail(BaseModel):
        run_listing_id: int
        listing: Listing
        score: int
        reasoning: str
        band: Band
        gaps: list[SkillGap]
        requirements: list[SkillGap] = []
        tips: list[GroundedTip] = []
        seniority: str | None = None
        work_type: str | None = None
        team: str | None = None
    ```

  - [ ] Verify it passes (`pytest tests/test_coach_tips_schemas.py -v`)
  - [ ] Commit: `feat(coach): add GroundedTip schema and detail tips field`

### Task 2: `listing_tips` table

- **Files:** `scout/shared/schema.sql`, `tests/test_coach_tips_db.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing test: after `apply_schema`, a tip row inserted against a
        run listing is readable, and deleting the parent run cascades it away.

    ```python
    # tests/test_coach_tips_db.py
    from __future__ import annotations

    from datetime import date

    import pytest

    from scout.shared.db import record_run_listings, start_run, upsert_listing

    pytestmark = pytest.mark.asyncio


    async def _seed_run(conn, matches) -> int:
        """Create one run holding the given matches. Returns the run id.

        Goes through ``upsert_listing`` / ``record_run_listings`` rather than
        raw INSERTs so these tests don't hard-code the run_listings column
        list — note ``upsert_listing`` returns a 'new'/'changed'/'unchanged'
        status, not an id.
        """
        run_id = await start_run(conn, date(2026, 7, 27))
        for match in matches:
            await upsert_listing(conn, match.listing)
        await record_run_listings(conn, run_id, [(m, "competitive") for m in matches])
        return run_id


    async def _run_listing_id(conn, run_id: int, external_id: str) -> int:
        return await conn.fetchval(
            """
            SELECT run_listings.id
            FROM run_listings
            JOIN listings ON listings.id = run_listings.listing_id
            WHERE run_listings.run_id = $1 AND listings.external_id = $2
            """,
            run_id,
            external_id,
        )


    async def test_listing_tips_row_round_trips(db_pool, match_factory, listing_factory):
        async with db_pool.acquire() as conn:
            match = match_factory(listing=listing_factory(external_id="tips-1"))
            run_id = await _seed_run(conn, [match])
            run_listing_id = await _run_listing_id(conn, run_id, "tips-1")
            await conn.execute(
                """
                INSERT INTO listing_tips (run_listing_id, gap_skill, tip, cited_urls)
                VALUES ($1, $2, $3, $4)
                """,
                run_listing_id,
                "Kubernetes",
                "Work through kubernetes/examples.",
                ["https://github.com/k/examples"],
            )
            row = await conn.fetchrow(
                "SELECT gap_skill, tip, cited_urls FROM listing_tips WHERE run_listing_id = $1",
                run_listing_id,
            )
            assert row["gap_skill"] == "Kubernetes"
            assert list(row["cited_urls"]) == ["https://github.com/k/examples"]


    async def test_listing_tips_cascade_with_run_listing(
        db_pool, match_factory, listing_factory
    ):
        async with db_pool.acquire() as conn:
            match = match_factory(listing=listing_factory(external_id="tips-1"))
            run_id = await _seed_run(conn, [match])
            run_listing_id = await _run_listing_id(conn, run_id, "tips-1")
            await conn.execute(
                """
                INSERT INTO listing_tips (run_listing_id, gap_skill, tip, cited_urls)
                VALUES ($1, 'Kubernetes', 'tip', ARRAY['https://github.com/k/examples'])
                """,
                run_listing_id,
            )
            await conn.execute("DELETE FROM run_listings WHERE id = $1", run_listing_id)
            remaining = await conn.fetchval(
                "SELECT count(*) FROM listing_tips WHERE run_listing_id = $1",
                run_listing_id,
            )
            assert remaining == 0
    ```

  - [ ] Verify it fails (`pytest tests/test_coach_tips_db.py -v`) — expected:
        `asyncpg.exceptions.UndefinedTableError: relation "listing_tips" does not exist`
  - [ ] Implement: append to `scout/shared/schema.sql`, after the
        `listing_gaps` block and before the `resources` block, so the tips
        table sits with the run-scoped tables it belongs to.

    ```sql
    CREATE TABLE IF NOT EXISTS listing_tips (
        id BIGSERIAL PRIMARY KEY,
        run_listing_id BIGINT NOT NULL REFERENCES run_listings (id) ON DELETE CASCADE,
        gap_skill TEXT NOT NULL,
        tip TEXT NOT NULL,
        cited_urls TEXT[] NOT NULL
    );
    ```

  - [ ] Verify it passes (`pytest tests/test_coach_tips_db.py -v`)
  - [ ] Commit: `feat(coach): add listing_tips table`

### Task 3: `record_listing_tips`

- **Files:** `scout/shared/db.py`, `tests/test_coach_tips_db.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing test: recording tips for a match writes one row per tip;
        recording again for the same listing replaces rather than duplicates;
        another listing's tips in the same run are left alone.

    ```python
    # append to tests/test_coach_tips_db.py
    from scout.shared.db import record_listing_tips
    from scout.shared.schemas import GroundedTip


    async def test_record_listing_tips_writes_one_row_per_tip(
        db_pool, listing_factory, match_factory
    ):
        async with db_pool.acquire() as conn:
            match = match_factory(listing=listing_factory(external_id="tips-1"))
            run_id = await _seed_run(conn, [match])

            await record_listing_tips(
                conn,
                run_id,
                [
                    (
                        match,
                        [
                            GroundedTip(
                                gap_skill="Kubernetes",
                                tip="Start with kubernetes/examples.",
                                cited_urls=["https://github.com/k/examples"],
                            ),
                            GroundedTip(
                                gap_skill="Terraform",
                                tip="Read the module registry docs.",
                                cited_urls=["https://github.com/t/modules"],
                            ),
                        ],
                    )
                ],
            )

            rows = await conn.fetch(
                "SELECT gap_skill, cited_urls FROM listing_tips ORDER BY gap_skill"
            )
            assert [row["gap_skill"] for row in rows] == ["Kubernetes", "Terraform"]
            assert list(rows[0]["cited_urls"]) == ["https://github.com/k/examples"]


    async def test_record_listing_tips_replaces_previous_tips(
        db_pool, listing_factory, match_factory
    ):
        async with db_pool.acquire() as conn:
            match = match_factory(listing=listing_factory(external_id="tips-1"))
            run_id = await _seed_run(conn, [match])
            first = [
                GroundedTip(gap_skill="Kubernetes", tip="old", cited_urls=["https://a/b"])
            ]
            second = [
                GroundedTip(gap_skill="Kubernetes", tip="new", cited_urls=["https://a/b"])
            ]

            await record_listing_tips(conn, run_id, [(match, first)])
            await record_listing_tips(conn, run_id, [(match, second)])

            rows = await conn.fetch("SELECT tip FROM listing_tips")
            assert [row["tip"] for row in rows] == ["new"]
    ```

  - [ ] Verify it fails (`pytest tests/test_coach_tips_db.py -v`) — expected:
        `ImportError: cannot import name 'record_listing_tips'`
  - [ ] Implement in `scout/shared/db.py`, below `record_listing_gaps`.
        Note this deliberately resolves ids first and then uses
        `executemany`, rather than `record_listing_gaps`' single `unnest`
        insert: `cited_urls` is a `TEXT[]` column, and an array-of-arrays does
        not pass through `unnest` the way the flat text columns there do.
        asyncpg binds a `list[str]` to `TEXT[]` directly.

    ```python
    async def record_listing_tips(
        conn: asyncpg.Connection,
        run_id: int,
        tips_by_match: list[tuple[MatchResult, list[GroundedTip]]],
    ) -> None:
        """Replace the stored tips for the supplied listings in one run.

        Scoped to the listings supplied, not the whole run, for the same
        reason ``record_listing_gaps`` is: a same-day re-run that only
        re-analyses some listings must not wipe the rest of the run's tips.
        """
        if not tips_by_match:
            return

        # Inner transaction keeps delete-then-insert self-atomic when called on
        # its own; nested inside the pipeline's run transaction asyncpg makes
        # it a harmless savepoint.
        async with conn.transaction():
            rows = await conn.fetch(
                """
                SELECT run_listings.id, listings.source, listings.external_id
                FROM run_listings
                JOIN listings ON listings.id = run_listings.listing_id
                WHERE run_listings.run_id = $1
                """,
                run_id,
            )
            id_by_key = {
                (row["source"], row["external_id"]): row["id"] for row in rows
            }

            # Built from every match supplied — not just those with tips — so a
            # listing whose tips are now all ungrounded has its stale rows
            # cleared rather than left behind.
            target_ids = [
                id_by_key[(match.listing.source, match.listing.external_id)]
                for match, _tips in tips_by_match
                if (match.listing.source, match.listing.external_id) in id_by_key
            ]
            if not target_ids:
                return

            await conn.execute(
                "DELETE FROM listing_tips WHERE run_listing_id = ANY($1::bigint[])",
                target_ids,
            )

            records = [
                (
                    id_by_key[(match.listing.source, match.listing.external_id)],
                    tip.gap_skill,
                    tip.tip,
                    tip.cited_urls,
                )
                for match, tips in tips_by_match
                if (match.listing.source, match.listing.external_id) in id_by_key
                for tip in tips
            ]
            if not records:
                return

            await conn.executemany(
                """
                INSERT INTO listing_tips (run_listing_id, gap_skill, tip, cited_urls)
                VALUES ($1, $2, $3, $4)
                """,
                records,
            )
    ```

    Add `GroundedTip` to the existing `from scout.shared.schemas import (...)`
    block at the top of `db.py`.

  - [ ] Verify it passes (`pytest tests/test_coach_tips_db.py -v`)
  - [ ] Commit: `feat(coach): add record_listing_tips`

### Task 4: `get_run_details` returns stored tips

- **Files:** `scout/shared/db.py:460-525`, `tests/test_coach_tips_db.py`
- **Gate:** none
- **Steps:**
  - [x] Write failing test: tips written for a run listing come back on that
        listing's `RunListingDetail`, and a listing with no tips gets `[]`.

    ```python
    # append to tests/test_coach_tips_db.py
    from scout.shared.db import get_run_details


    async def test_get_run_details_returns_stored_tips(
        db_pool, listing_factory, match_factory
    ):
        async with db_pool.acquire() as conn:
            tipped = match_factory(
                listing=listing_factory(external_id="tips-1"), score=90
            )
            untipped = match_factory(
                listing=listing_factory(external_id="tips-2"), score=70
            )
            run_id = await _seed_run(conn, [tipped, untipped])

            await record_listing_tips(
                conn,
                run_id,
                [
                    (
                        tipped,
                        [
                            GroundedTip(
                                gap_skill="Kubernetes",
                                tip="Start with kubernetes/examples.",
                                cited_urls=["https://github.com/k/examples"],
                            )
                        ],
                    )
                ],
            )

            details = await get_run_details(conn, run_id)
            by_external_id = {d.listing.external_id: d for d in details}
            assert by_external_id["tips-1"].tips[0].gap_skill == "Kubernetes"
            assert by_external_id["tips-1"].tips[0].cited_urls == [
                "https://github.com/k/examples"
            ]
            assert by_external_id["tips-2"].tips == []
    ```

  - [x] Verify it fails (`pytest tests/test_coach_tips_db.py::test_get_run_details_returns_stored_tips -v`)
        — expected: `IndexError: list index out of range` on `.tips[0]`
  - [x] Implement: in `get_run_details`, after the existing `gap_rows` fetch
        and its `requirements_by_id` loop, add the tips fetch, then pass
        `tips=` into the `RunListingDetail(...)` construction.

    ```python
    tip_rows = await conn.fetch(
        """
        SELECT run_listing_id, gap_skill, tip, cited_urls
        FROM listing_tips
        WHERE run_listing_id = ANY($1::bigint[])
        ORDER BY id
        """,
        run_listing_ids,
    )
    tips_by_id: dict[int, list[GroundedTip]] = {}
    for tip_row in tip_rows:
        tips_by_id.setdefault(tip_row["run_listing_id"], []).append(
            GroundedTip(
                gap_skill=tip_row["gap_skill"],
                tip=tip_row["tip"],
                cited_urls=list(tip_row["cited_urls"]),
            )
        )
    ```

    ```python
                requirements=requirements,
                tips=tips_by_id.get(run_listing_id, []),
                seniority=seniority,
    ```

  - [x] Verify it passes (`pytest tests/test_coach_tips_db.py -v`)
  - [x] Commit: `feat(coach): read stored tips back in get_run_details`

---

## Verification

- [x] All phase tests pass: `pytest tests/test_coach_tips_db.py tests/test_coach_tips_schemas.py -v`
- [x] No regression in the reporting path (which now constructs
      `RunListingDetail` with a new field):
      `pytest tests/test_db.py tests/test_advisor_report.py -v`
- [x] Manual: none — nothing writes tips until Phase 3.

## Rollback

Revert the phase's four commits. `listing_tips` is additive and read by nothing
outside this feature, so an already-applied schema can be left in place
harmlessly, or dropped with `DROP TABLE listing_tips;`.

---

## Notes / Learnings

<Filled in during execution.>
