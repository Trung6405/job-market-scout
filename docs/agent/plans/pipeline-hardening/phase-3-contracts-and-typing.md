# Phase 3: Contracts & Typing

> **Parent plan:** [plan.md](plan.md)
> **Status:** Not started
> **Depends on:** nothing (independent; touches band typing + docs)

---

## Goal

Make three implicit contracts explicit: the band vocabulary becomes a
closed type, and the run-identity/idempotency model plus the gap-matcher
naming are documented where readers will find them.

## Safety Checklist

- **Touches user input, auth, secrets, or external calls?** No.
- **Contains a one-way door (schema, public API shape, new dependency)?**
  No — `band` stays a `TEXT` column storing the enum's string value;
  code-only typing change, backward-compatible with existing rows.

---

## Tasks

### Task 1: Closed `Band` type through `classify_band` and schemas

- **Files:** `scout/sub_agents/advisor/bands.py`, `scout/shared/schemas.py`, `tests/test_advisor_bands.py` (create if absent)
- **Gate:** none
- **Steps:**
  - [ ] Write failing test: `classify_band(95, settings)` / `classify_band(threshold-1, settings)` return the three expected band values, and the return type is the closed `Band` (assert membership in the allowed set).
  - [ ] Verify it fails (`pytest tests/test_advisor_bands.py -q`)
  - [ ] Implement: define `Band = Literal["strong_match", "competitive", "reach"]` (or a `StrEnum`) in `schemas.py`; annotate `classify_band` return and the `band` fields on `RunListing`/`RunListingDetail` with it. Keep the wire/DB value as the existing strings.
  - [ ] Verify it passes (`pytest tests/test_advisor_bands.py -q`)
  - [ ] Commit: `refactor(advisor): make band a closed typed vocabulary`

### Task 2: Verify templates still compare band strings correctly

- **Files:** `scout/sub_agents/advisor/templates/*`, no code change expected
- **Gate:** none
- **Steps:**
  - [ ] Grep templates for band literals (`strong_match`, `competitive`, `reach`) and confirm they compare against the enum's string value (unchanged).
  - [ ] Verify: render a run and confirm band styling is intact (`pytest tests/ -k report -q` if a render test exists, else manual render).
  - [ ] Commit only if a fix was needed: `fix(advisor): align template band comparison with typed band`

### Task 3: Document run-identity & idempotency contract

- **Files:** `docs/project/architecture-pipeline-overview.md`
- **Gate:** none
- **Steps:**
  - [ ] Add a short "Run identity & idempotency" subsection under Persistence: `runs` is keyed by local `run_date`, so both daily cron fires share one row — the later fire is a same-day refresh, not a new historical run; and a run that fails mid-Advisor is healed by the next same-date run because `start_run` upserts, `record_run_listings` upserts, and `record_listing_gaps` delete-then-inserts.
  - [ ] Verify: doc renders / links resolve.
  - [ ] Commit: `docs(architecture): document run identity and idempotency`

### Task 4: Reconcile gap-matcher naming

- **Files:** `docs/agent/specs/advisor-report/spec.md`, `docs/project/architecture-pipeline-overview.md`, any prose referring to `detect_gaps`
- **Gate:** none
- **Steps:**
  - [ ] Grep docs for `detect_gaps`; replace with `evaluate_requirements` (the actual function) or add a one-line note that the prose name maps to `evaluate_requirements` in `advisor/gaps.py`.
  - [ ] Verify: `grep -r detect_gaps docs/` returns only intentional references.
  - [ ] Commit: `docs: reconcile gap-matcher naming with code`

---

## Verification

- [ ] All phase tests pass: `pytest tests/test_advisor_bands.py -q`
- [ ] `grep -rn detect_gaps docs/` shows no stale references.
- [ ] Architecture doc contains the run-identity/idempotency subsection.

## Rollback

Revert the commits; `band` returns to `str` and docs to prior wording. No
state to undo.

---

## Notes / Learnings

<Filled in during execution.>
