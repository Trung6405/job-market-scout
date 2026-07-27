# Phase 1: Retrieval Query in the Shared Data Layer

> **Parent plan:** [plan.md](plan.md)
> **Status:** Not started
> **Depends on:** nothing (P0 schema and P1's normalized `resources.skills[]`
> are already on this branch)

---

## Goal

Deliver the hybrid retrieval query as a shared database helper: exact
normalized `skills[]` pre-filter, then pgvector cosine ranking within it,
top-`k` per skill, live rows only. It worked when the helper returns correct
resources for seeded rows in the `scout_test` database and refuses to return
wrong-skill, unranked, or stale ones.

## Safety Checklist

- **Touches user input, auth, secrets, or external calls?**
  No. Read-only SQL over a local database; skill names arrive from
  `listing_gaps`, and every value is passed as a bound parameter — no string
  interpolation into SQL anywhere in this phase.
- **Contains a one-way door (schema, public API shape, new dependency)?**
  No. No migration, no new dependency, and the helper has no caller until
  Phase 2, so its signature is freely changeable.

---

## Tasks

### Task 1: Spike — does the set-based query form work in pgvector?

- **Files:** scratch only — no committed source change
- **Gate:** none
- **Steps:**
  - [x] Seed a handful of `resources` rows with distinct embeddings in the
        `scout_test` database
  - [x] Run the candidate statement directly against it, binding two parallel
        `text[]` arrays (skills, and vectors in `[a,b,c]` text form):
        `FROM unnest($1::text[], $2::text[]) AS q(skill, vec) CROSS JOIN LATERAL (SELECT ... ORDER BY embedding <=> q.vec::vector LIMIT $4) r`
  - [x] Record the outcome in this doc's Notes / Learnings — **set-based** if
        the per-row cast and the array binding both work, **looped** otherwise
  - [x] No commit — this task produces a decision, not code

> Everything below is written against the set-based form. If the spike says
> looped, Task 3 implements the same helper as a per-skill loop instead; the
> signature, the tests, and every later task are unchanged.

### Task 2: `RetrievedResource` schema model

- **Files:** `scout/shared/schemas.py`, `tests/test_coach_schemas.py`
- **Gate:** none
- **Steps:**
  - [x] Write failing test: `RetrievedResource` accepts a row's worth of
        fields (`url`, `title`, `resource_type`, `skills`, `level`, `summary`,
        `similarity`) and rejects a missing `similarity`
  - [x] Verify it fails (`pytest tests/test_coach_schemas.py -q`)
  - [x] Add the model, mirroring `Resource`'s field types; `level` optional
  - [x] Verify it passes (`pytest tests/test_coach_schemas.py -q`)
  - [x] Commit: `feat(coach): add RetrievedResource model for retrieval results`

### Task 3: `get_resources_for_skills` — pre-filter and ranking

- **Files:** `scout/shared/db.py`, `tests/test_coach_retrieval_db.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing test: seed two resources tagged `kubernetes` with
        different embeddings plus one tagged `java`; query for `kubernetes`
        with a vector nearer the second; assert both kubernetes rows come
        back, nearest first, and the java row does not appear at all
  - [ ] Verify it fails (`pytest tests/test_coach_retrieval_db.py -q`)
  - [ ] Implement `get_resources_for_skills(conn, skills, vectors, k, max_age_days) -> dict[str, list[RetrievedResource]]`
        using the form Task 1 chose; every skill passed in gets a key, `[]` if
        it matched nothing
  - [ ] Verify it passes (`pytest tests/test_coach_retrieval_db.py -q`)
  - [ ] Commit: `feat(coach): add skills-prefiltered pgvector retrieval query`

### Task 4: `k` limit and per-skill result mapping

- **Files:** `tests/test_coach_retrieval_db.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing test: seed four `kubernetes` resources, query with
        `k=3`, assert exactly the three nearest come back
  - [ ] Write failing test: query for `["kubernetes", "react", "rust"]` in one
        call where only the first two have rows; assert each key holds only
        its own skill's resources and `"rust"` maps to `[]`
  - [ ] Verify they fail (`pytest tests/test_coach_retrieval_db.py -q`)
  - [ ] Fix the helper if either exposes a defect (a correct Task 3 may
        already satisfy both — record which in Notes / Learnings)
  - [ ] Verify they pass (`pytest tests/test_coach_retrieval_db.py -q`)
  - [ ] Commit: `test(coach): cover top-k limit and per-skill result mapping`

### Task 5: Liveness and unrankable-row exclusion

- **Files:** `scout/shared/db.py`, `tests/test_coach_retrieval_db.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing test: seed one `kubernetes` row with `last_verified`
        NULL, one verified yesterday, one verified 200 days ago, and one with
        a NULL embedding; assert only the first two are returned
  - [ ] Verify it fails (`pytest tests/test_coach_retrieval_db.py -q`)
  - [ ] Add `embedding IS NOT NULL` and
        `(last_verified IS NULL OR last_verified > now() - make_interval(days => $n))`
        to the pre-filter
  - [ ] Verify it passes (`pytest tests/test_coach_retrieval_db.py -q`)
  - [ ] Commit: `feat(coach): exclude stale and unrankable resources from retrieval`

---

## Verification

- [ ] All phase tests pass:
      `pytest tests/test_coach_retrieval_db.py tests/test_coach_schemas.py -q`
- [ ] Full regression: `pytest -q` — confirms the new `scout/shared/db.py`
      helper and schema addition break no existing caller

## Rollback

Revert the phase's feat commits. `get_resources_for_skills` and
`RetrievedResource` are purely additive with no caller until Phase 2, so
reverting any subset is safe and touches no existing behaviour.

---

## Notes / Learnings

**Task 1 spike — verdict: set-based.** Run against real Postgres in
`scout_test`. The per-row `q.vec::vector` cast inside `CROSS JOIN LATERAL`
works, and two parallel `text[]` arrays bind without complaint. Ranking
ordered correctly (similarity 1.0 then 0.0), and a `java` row carrying an
embedding *identical* to the winning `kubernetes` row was correctly excluded —
the pre-filter, not the vector distance, is what kept it out. Task 3
implements the set-based form as written.

**Unplanned finding — `CROSS JOIN LATERAL` drops skills with no matches.**
Querying for `["kubernetes", "react"]` where nothing is tagged `react`
returned rows for `kubernetes` only; `react` produced no row at all rather
than a null-filled one. The helper's contract says *every* skill passed in
gets a key, so that cannot come from the SQL alone. Task 3 seeds the result
dict with `[]` for all requested skills before folding in the returned rows —
chosen over `LEFT JOIN LATERAL ... ON true`, which would work but forces every
consumer to filter null-URL placeholder rows back out. Task 4's
`"rust" -> []` assertion is what pins this down.
