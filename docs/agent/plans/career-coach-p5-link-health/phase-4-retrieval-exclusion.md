# Phase 4: Retrieval Exclusion

> **Parent plan:** [plan.md](plan.md)
> **Status:** Not started
> **Depends on:** Phase 3 complete (something must be able to mark a row dead)

---

## Goal

Make the health state actually mean something: a resource marked dead is never
returned by retrieval, so it can never be cited in a tip. Done when the
pre-filter excludes dead rows while still returning never-checked ones.

## Safety Checklist

- **Touches user input, auth, secrets, or external calls?**
  No. One added condition on an existing parameterised query.
- **Contains a one-way door (schema, public API shape, new dependency)?**
  No — but this is the one phase that changes **existing** behaviour, on the
  read path P3's grounded tips depend on. It is a no-op until a check run has
  written health state, since every row starts with `dead_since` NULL.

---

## Tasks

### Task 1: Dead resources drop out of retrieval

- **Files:** `scout/shared/db.py`, `tests/test_coach_retrieval_db.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing test: two embedded resources both match a skill's
        `skills[]` pre-filter; marking one `dead_since` leaves only the other
        in `get_resources_for_skills`, and a skill whose *only* resource is
        dead maps to an empty list rather than a missing key
  - [ ] Verify it fails (`pytest tests/test_coach_retrieval_db.py -q`)
  - [ ] Implement: add `AND dead_since IS NULL` to the lateral subquery's
        `WHERE`, alongside the existing embedding and staleness conditions, and
        note in the docstring that health exclusion and age staleness are two
        separate rules — one deliberate, one automatic
  - [ ] Verify it passes (`pytest tests/test_coach_retrieval_db.py -q`)
  - [ ] Commit: `feat(coach): exclude dead resources from retrieval`

### Task 2: Never-checked resources stay retrievable

- **Files:** `tests/test_coach_retrieval_db.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing test: a resource with `last_verified` NULL,
        `dead_since` NULL and `consecutive_failures` 0 — the state every
        freshly aggregated resource is in — is still returned; and a resource
        with a non-zero failure count but no `dead_since` is *also* still
        returned, since being below the threshold is not being dead
  - [ ] Verify it fails or passes as written — if it passes immediately,
        keep it: it is a regression guard on the rule that a new resource must
        be usable before its first check
        (`pytest tests/test_coach_retrieval_db.py -q`)
  - [ ] Implement: no change expected; if the test fails, the Task 1 condition
        was written too broadly (e.g. keying off `consecutive_failures` instead
        of `dead_since`) — fix it there
  - [ ] Verify it passes (`pytest tests/test_coach_retrieval_db.py -q`)
  - [ ] Commit: `test(coach): guard that unchecked resources stay retrievable`

### Task 3: End-to-end, from verdict to exclusion

- **Files:** `tests/test_coach_link_health_db.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing test: a resource that `record_link_check` marks dead via
        a `gone` verdict is absent from a subsequent `retrieve_for_skills`
        call, and reappears after a healthy check — the two halves of the
        phase, proven to line up rather than assumed to
  - [ ] Verify it fails (`pytest tests/test_coach_link_health_db.py -q`)
  - [ ] Implement: no production change expected; this test wires Phase 3's
        writer to Phase 4's reader
  - [ ] Verify it passes (`pytest tests/test_coach_link_health_db.py -q`)
  - [ ] Commit: `test(coach): cover dead-to-retrieval round trip`

---

## Verification

- [ ] All phase tests pass:
      `pytest tests/test_coach_retrieval_db.py tests/test_coach_link_health_db.py -q`
- [ ] The retriever's own behaviour is unchanged for healthy corpora:
      `pytest tests/test_coach_retriever.py -q`
- [ ] The grounded-tip stage — a live consumer of this read path since the P3
      merge — is unaffected:
      `pytest tests/test_coach_tips.py tests/test_coach_tips_db.py -q`
- [ ] Full suite green: `pytest -q`

## Rollback

Revert the commits; retrieval returns to filtering on embedding presence and
age only. Any health state already written becomes inert rather than harmful.

---

## Notes / Learnings

<Filled in during execution.>
