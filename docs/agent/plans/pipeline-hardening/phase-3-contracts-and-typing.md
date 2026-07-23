# Phase 3: Contracts & Typing

> **Parent plan:** [plan.md](plan.md)
> **Status:** Complete
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
  - [x] Write failing test: `classify_band(...)` returns members of the band vocabulary; `RunListing` rejects an unknown band via pydantic `ValidationError`; `get_args(Band)` is the closed set.
  - [x] Verify it fails (`pytest tests/test_advisor_bands.py -q`)
  - [x] Implement: define `Band = Literal["strong_match", "competitive", "reach"]` in `schemas.py`; annotate `classify_band` return and the `band` fields on `RunListing`/`RunListingDetail`. Values stay plain strings, so DB column and templates are unaffected.
  - [x] Verify it passes (`pytest tests/test_advisor_bands.py -q` — 9 passed)
  - [x] Commit: `refactor(advisor): make band a closed typed vocabulary`

### Task 2: Verify templates still compare band strings correctly

- **Files:** `scout/sub_agents/advisor/templates/*`, no code change expected
- **Gate:** none
- **Steps:**
  - [x] Grep templates + `report.py` for band literals: `report.py` maps band strings via `_BAND_INFO`/`_band_css`/`_band_label` and counts `d.band == "strong_match"`; templates key off derived CSS classes. Because `Band` is a `Literal` (plain strings), all of this is unchanged.
  - [x] Verify: `test_advisor_report.py` render tests pass (non-DB green). No fix needed.
  - [x] No commit needed — no code change (folded into Task 1's verification).

### Task 3: Document run-identity & idempotency contract

- **Files:** `docs/project/architecture-pipeline-overview.md`
- **Gate:** none
- **Steps:**
  - [x] Add a short "Run identity & idempotency" subsection under Persistence: `runs` is keyed by local `run_date`, so both daily cron fires share one row — the later fire is a same-day refresh, not a new historical run; and a run that fails mid-Advisor is healed by the next same-date run because `start_run` upserts, `record_run_listings` upserts, and `record_listing_gaps` delete-then-inserts.
  - [x] Verify: doc renders / links resolve.
  - [x] Commit: `docs(architecture): document run identity and idempotency`

### Task 4: Reconcile gap-matcher naming

- **Files:** `docs/agent/specs/advisor-report/spec.md`, `docs/project/architecture-pipeline-overview.md`, any prose referring to `detect_gaps`
- **Gate:** none
- **Steps:**
  - [x] Grep docs for `detect_gaps`. Fixed the two *authoritative/current* docs: the PRS amendment now names `evaluate_requirements(...)`, and the advisor-report spec's live prose gained a pointer to the real function. The architecture overview already used `evaluate_requirements`.
  - [x] Verify: remaining `detect_gaps` references live only in **historical execution logs** (`advisor-report/plan.md`, `phase-3-gaps.md`) and the advisor-report spec's own Amendments — point-in-time records of what was built then, intentionally left as-is rather than rewriting history.
  - [x] Commit: `docs: reconcile gap-matcher naming with code`

---

## Verification

- [x] All phase tests pass: `pytest tests/test_advisor_bands.py -q` (9 passed)
- [x] `grep -rn detect_gaps docs/` shows only historical-log references (see Task 4).
- [x] Architecture doc contains the run-identity/idempotency subsection.

## Rollback

Revert the commits; `band` returns to `str` and docs to prior wording. No
state to undo.

---

## Notes / Learnings

<Filled in during execution.>
