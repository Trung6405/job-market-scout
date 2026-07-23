# Phase 1: Gap-Matching Accuracy

> **Parent plan:** [plan.md](plan.md)
> **Status:** In progress
> **Depends on:** nothing

---

## Goal

Stop false gaps: a skill the student holds must not be flagged missing
because a listing phrased it as a common variant. Achieved with a
deterministic `normalize_skill()` applied to both sides of the match, plus
extraction-prompt canonicalization as an upstream improvement.

## Safety Checklist

- **Touches user input, auth, secrets, or external calls?**
  Yes — changes the extraction LLM prompt. No new external calls; failure
  handling unchanged (extraction already validated downstream).
- **Contains a one-way door (schema, public API shape, new dependency)?**
  No.

---

## Tasks

### Task 1: Deterministic `normalize_skill()`

- **Files:** `scout/sub_agents/advisor/gaps.py`, `tests/test_advisor_gaps.py`
- **Gate:** none
- **Steps:**
  - [x] Write failing test: `normalize_skill("React.js") == normalize_skill("React")`, `normalize_skill("Postgres") == normalize_skill("PostgreSQL")`, `normalize_skill("JS") == normalize_skill("JavaScript")`, `normalize_skill("Node.js") == normalize_skill("node")`, and that an unrelated pair (`"React"` vs `"Angular"`) does **not** collapse.
  - [x] Verify it fails (`pytest tests/test_advisor_gaps.py -k normalize -q`)
  - [x] Implement `normalize_skill()`: lowercase, strip surrounding whitespace, remove punctuation/version decoration (`.js`, `.`, `+`, spaces), then map through a small `_SKILL_ALIASES` dict for known non-substring equivalences (`js`→`javascript`, `postgres`→`postgresql`, `ts`→`typescript`, `k8s`→`kubernetes`). Keep the alias set small and commented.
  - [x] Verify it passes (`pytest tests/test_advisor_gaps.py -k normalize -q`)
  - [x] Commit: `feat(advisor): add normalize_skill() for gap matching`

### Task 2: Match on normalized skills in `evaluate_requirements`

- **Files:** `scout/sub_agents/advisor/gaps.py`, `tests/test_advisor_gaps.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing test: a profile with `React` + `PostgreSQL` against a `ListingRequirements` whose `must_have` is `["React.js", "Postgres"]` yields **zero** unmet gaps; a genuinely absent skill (`Rust`) still yields one unmet gap.
  - [ ] Verify it fails (`pytest tests/test_advisor_gaps.py -q`)
  - [ ] Implement: build `profile_skills` as a set of `normalize_skill(...)`; compute `met = normalize_skill(skill) in profile_skills`. Preserve the original `skill` string in the returned `SkillGap` (only the comparison is normalized).
  - [ ] Verify it passes (`pytest tests/test_advisor_gaps.py -q`)
  - [ ] Commit: `fix(advisor): match gaps on normalized skill names`

### Task 3: Canonical skill names in the extraction prompt

- **Files:** `scout/prompts.py`, `tests/` (prompt-content assertion if a prompt test exists; otherwise a lightweight new test)
- **Gate:** none
- **Steps:**
  - [ ] Write failing test: `build_requirements_instruction(...)` output contains the canonicalization guidance (assert on a stable marker phrase, e.g. "canonical name").
  - [ ] Verify it fails (`pytest tests/ -k requirements_instruction -q`)
  - [ ] Implement: add an instruction line telling the model to emit each skill as a single canonical name — no version suffixes (`React`, not `React.js`/`React 18`), no surrounding punctuation, preferring the common full name (`JavaScript` over `JS`).
  - [ ] Verify it passes (`pytest tests/ -k requirements_instruction -q`)
  - [ ] Commit: `feat(advisor): ask extraction LLM for canonical skill names`

---

## Verification

- [ ] All phase tests pass: `pytest tests/test_advisor_gaps.py -q`
- [ ] Manual: re-render a recent run (`python -m scout.rerender` or equivalent) and confirm a skill known to be in `profile.json` is no longer flagged as a gap on the job-detail page.

## Rollback

Revert the three commits; `evaluate_requirements` returns to exact-match.
No state to undo (gaps are recomputed each run).

---

## Notes / Learnings

<Filled in during execution.>
