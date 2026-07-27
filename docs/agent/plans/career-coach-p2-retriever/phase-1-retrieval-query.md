# Phase 1: Retrieval Query in the Shared Data Layer

> **Parent plan:** [plan.md](plan.md)
> **Status:** Complete
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
  - [x] Write failing test: seed two resources tagged `kubernetes` with
        different embeddings plus one tagged `java`; query for `kubernetes`
        with a vector nearer the second; assert both kubernetes rows come
        back, nearest first, and the java row does not appear at all
  - [x] Verify it fails (`pytest tests/test_coach_retrieval_db.py -q`)
  - [x] Implement `get_resources_for_skills(conn, skills, vectors, k, max_age_days) -> dict[str, list[RetrievedResource]]`
        using the form Task 1 chose; every skill passed in gets a key, `[]` if
        it matched nothing
  - [x] Verify it passes (`pytest tests/test_coach_retrieval_db.py -q`)
  - [x] Commit: `feat(coach): add skills-prefiltered pgvector retrieval query`

### Task 4: `k` limit and per-skill result mapping

- **Files:** `tests/test_coach_retrieval_db.py`
- **Gate:** none
- **Steps:**
  - [x] Write failing test: seed four `kubernetes` resources, query with
        `k=3`, assert exactly the three nearest come back
  - [x] Write failing test: query for `["kubernetes", "react", "rust"]` in one
        call where only the first two have rows; assert each key holds only
        its own skill's resources and `"rust"` maps to `[]`
  - [x] Verify they fail (`pytest tests/test_coach_retrieval_db.py -q`)
  - [x] Fix the helper if either exposes a defect (a correct Task 3 may
        already satisfy both — record which in Notes / Learnings)
  - [x] Verify they pass (`pytest tests/test_coach_retrieval_db.py -q`)
  - [x] Commit: `test(coach): cover top-k limit and per-skill result mapping`

### Task 5: Liveness and unrankable-row exclusion

- **Files:** `scout/shared/db.py`, `tests/test_coach_retrieval_db.py`
- **Gate:** none
- **Steps:**
  - [x] Write failing test: seed one `kubernetes` row with `last_verified`
        NULL, one verified yesterday, one verified 200 days ago, and one with
        a NULL embedding; assert only the first two are returned
  - [x] Verify it fails (`pytest tests/test_coach_retrieval_db.py -q`)
  - [x] Add `embedding IS NOT NULL` and
        `(last_verified IS NULL OR last_verified > now() - make_interval(days => $n))`
        to the pre-filter
  - [x] Verify it passes (`pytest tests/test_coach_retrieval_db.py -q`)
  - [x] Commit: `feat(coach): exclude stale and unrankable resources from retrieval`

---

## Verification

- [x] All phase tests pass:
      `pytest tests/test_coach_retrieval_db.py tests/test_coach_schemas.py -q`
- [x] Full regression: `pytest -q` — confirms the new `scout/shared/db.py`
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

**Task 4 — no defect found; both tests passed on first run.** Neither the
`k` limit nor the per-skill mapping needed a change: Task 3's `LIMIT $4`
already bounded each skill's ranking, and its pre-seeded result dict already
produced `"rust" -> []`. These are guard tests rather than the product of a
red-green cycle, and worth keeping regardless — the `[]` behaviour in
particular is a contract no consumer should have to rediscover, and the SQL
alone does not provide it.

A third test beyond the two the plan listed covers the `skills=[]` early
return, which short-circuits before any query is issued. Added because Phase 2
depends on that behaviour: `retrieve_for_skills` must touch neither `embed`
nor the database when a run has no gaps.

**Task 5 — deviation from the planned task order.** Both filters were written
into Task 3's query rather than added here, so this test passed on first run.
Since no red-green cycle proved it, the test was checked by mutation instead:
widening the staleness window and dropping the `embedding IS NOT NULL` guard
makes it fail, so it does constrain the behaviour it claims to.

That mutation exposed something worth keeping: a NULL-embedding row comes back
with `similarity = None`, which `RetrievedResource` rejects outright because
Task 2 made the field required. The SQL guard is still the real defence — an
unrankable row should never reach the model — but the required field means a
regression there surfaces as a loud validation error rather than a silently
unranked result.

**Unplanned finding — `CROSS JOIN LATERAL` drops skills with no matches.**
Querying for `["kubernetes", "react"]` where nothing is tagged `react`
returned rows for `kubernetes` only; `react` produced no row at all rather
than a null-filled one. The helper's contract says *every* skill passed in
gets a key, so that cannot come from the SQL alone. Task 3 seeds the result
dict with `[]` for all requested skills before folding in the returned rows —
chosen over `LEFT JOIN LATERAL ... ON true`, which would work but forces every
consumer to filter null-URL placeholder rows back out. Task 4's
`"rust" -> []` assertion is what pins this down.


---

## Post-review findings *(code review, 2026-07-27)*

**The pre-filter predicate was not index-ready — and the spec analysed the
wrong index.** `spec.md` argues carefully against an `ivfflat`/`hnsw` index and
is right to, but the vector index was never the one that governs cost. The
`skills[]` pre-filter runs *first and over every row*, and the original
`q.skill = ANY(skills)` form cannot use a GIN index (`gin__array_ops` supports
`@>`, `<@`, `&&` — not scalar `= ANY`). So the query scanned the whole
`resources` table once per distinct gap skill. Rewritten to the equivalent
`skills @> ARRAY[q.skill]`, which is index-ready. The index itself is
**not** added here: creating one is a schema change, and `plan.md`'s Blast
Radius excludes schema migrations. Follow-up for whoever needs it:
`CREATE INDEX IF NOT EXISTS resources_skills_gin ON resources USING GIN (skills);`

**Nothing tested the skills/vectors pairing.** The parallel-array
`unnest($1::text[], $2::text[])` is the one novel thing this phase does, and
an off-by-one in it would have passed every test written: the single-skill
tests have nothing to misalign, the multi-skill test seeded one row per skill
so the pre-filter alone determined the output, and the end-to-end test stubbed
every query vector to the same value. Added
`test_each_skill_is_ranked_by_its_own_query_vector` — two skills, two rows
each, each skill's vector favouring a different position — and confirmed by
mutation (reversing `vectors` against `skills`) that it fails when the pairing
breaks.

**Cleanups:** vector text formatting was duplicated in four places and is now
`db.vector_text`; the cosine distance was computed twice per row and the full
384-dim embedding hauled out of the `LATERAL` only to recompute it — the
similarity is now computed once inside the subquery.
