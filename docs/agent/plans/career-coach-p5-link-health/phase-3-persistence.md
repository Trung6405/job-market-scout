# Phase 3: Health-State Persistence

> **Parent plan:** [plan.md](plan.md)
> **Status:** Complete
> **Depends on:** Phase 1 complete (the columns), Phase 2 complete (the verdict type)

---

## Goal

Two database helpers: one that picks the next batch of resources to check,
least-recently-checked first, and one that applies a verdict to a row and
reports which transition happened. Done when every transition in the spec's
verdict table — including recovery — is proven against a real Postgres.

## Safety Checklist

- **Touches user input, auth, secrets, or external calls?**
  No. Both helpers are parameterised SQL against the local pool; the verdict
  they persist comes from Phase 2, not from a user.
- **Contains a one-way door (schema, public API shape, new dependency)?**
  No. Both are new functions; nothing existing changes shape. The writes they
  perform are reversible with a single `UPDATE` (see plan.md → Rollout).

---

## Tasks

### Task 1: Selecting the next batch

- **Files:** `scout/shared/db.py`, `tests/test_coach_link_health_db.py`
- **Gate:** none
- **Steps:**
  - [x] Write failing test: with rows whose `last_verified` is old, recent, and
        NULL, `get_resources_to_check(conn, limit)` returns the NULL-verified
        rows first, then oldest-verified before newest, honours `limit`, and
        breaks ties on equal `last_verified` deterministically by `id` — so
        consecutive runs advance through the corpus instead of revisiting the
        same rows
  - [x] Verify it fails (`pytest tests/test_coach_link_health_db.py -q`)
  - [x] Implement: `SELECT id, url FROM resources ORDER BY last_verified ASC
        NULLS FIRST, id LIMIT $1`, with a comment on why the `id` tiebreak
        exists — every row starts with a NULL `last_verified`, so without it
        the ordering among them is unspecified
  - [x] Verify it passes (`pytest tests/test_coach_link_health_db.py -q`)
  - [x] Commit: `feat(coach): select the next link-check batch`

### Task 2: A healthy check clears all failure state

- **Files:** `scout/shared/db.py`, `tests/test_coach_link_health_db.py`
- **Gate:** none
- **Steps:**
  - [x] Write failing test: `record_link_check(conn, id, healthy, …)` on a
        clean row stamps `last_verified`, leaves `consecutive_failures` at 0,
        `dead_since` NULL, `last_check_error` NULL, and returns `"verified"`;
        run against a row already marked dead with a non-zero failure count, it
        clears both and returns `"recovered"` — proving a resource returns to
        circulation on its own
  - [x] Verify it fails (`pytest tests/test_coach_link_health_db.py -q`)
  - [x] Implement the healthy branch, returning the transition so the runner
        can count recoveries without a second query
  - [x] Verify it passes (`pytest tests/test_coach_link_health_db.py -q`)
  - [x] Commit: `feat(coach): record a healthy link check`

### Task 3: A permanently-gone URL is dead immediately

- **Files:** `scout/shared/db.py`, `tests/test_coach_link_health_db.py`
- **Gate:** none
- **Steps:**
  - [x] Write failing test: a `gone` verdict on a healthy row sets `dead_since`
        on the **first** observation, increments the failure count, stores the
        reason, leaves `last_verified` untouched (it was not verified), and
        returns `"newly_dead"`; a second `gone` verdict does not move the
        original `dead_since` and returns `"still_dead"`
  - [x] Verify it fails (`pytest tests/test_coach_link_health_db.py -q`)
  - [x] Implement the gone branch, preserving the first `dead_since` with
        `COALESCE` so the record of *when* it died survives repeat checks
  - [x] Verify it passes (`pytest tests/test_coach_link_health_db.py -q`)
  - [x] Commit: `feat(coach): mark a permanently-gone resource dead`

### Task 4: Transient failures need the threshold

- **Files:** `scout/shared/db.py`, `tests/test_coach_link_health_db.py`
- **Gate:** none
- **Steps:**
  - [x] Write failing test, with `max_failures` of 3: transient verdicts leave
        `dead_since` NULL after the first and second, and set it on the third,
        returning `"failing"`, `"failing"`, `"newly_dead"`; a healthy check
        between the second and third resets the count so the next transient
        failure starts over — one blip must not combine with an unrelated later
        one to kill a healthy resource
  - [x] Verify it fails (`pytest tests/test_coach_link_health_db.py -q`)
  - [x] Implement the transient branch: increment, and mark dead only when the
        incremented count reaches the threshold, computing the comparison in
        SQL against the stored count so two concurrent runs cannot disagree
  - [x] Verify it passes (`pytest tests/test_coach_link_health_db.py -q`)
  - [x] Commit: `feat(coach): mark a resource dead after repeated failures`

---

## Verification

- [x] All phase tests pass: `pytest tests/test_coach_link_health_db.py -q`
- [x] Existing database tests are unaffected:
      `pytest tests/test_coach_db.py tests/test_coach_retrieval_db.py -q`
- [x] Tests skip cleanly rather than fail when Postgres is unreachable

## Observability

`record_link_check`'s returned transition is what the Phase 5 summary counts —
"3 newly dead, 1 recovered" comes from these return values, not from a
follow-up scan of the table. `last_check_error` on the row answers "why did
this drop out" directly from SQL.

## Rollback

Revert the four commits. If a run has already written health state, restore
every resource with
`UPDATE resources SET dead_since = NULL, consecutive_failures = 0,
last_check_error = NULL;` — no row is ever deleted, so nothing is lost.

---

## Notes / Learnings

All four transitions (`verified`, `recovered`, `newly_dead`, `still_dead`,
`failing`) proven against real Postgres via the DB-backed suite, and
re-confirmed manually against production: a `gone` verdict produced
`newly_dead` on first observation and `still_dead` on a repeat check without
moving the original `dead_since`.
