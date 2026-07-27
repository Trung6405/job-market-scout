# Phase 2: Retriever Module and Config

> **Parent plan:** [plan.md](plan.md)
> **Status:** In progress
> **Depends on:** Phase 1 complete — `get_resources_for_skills` and
> `RetrievedResource` exist and are tested

---

## Goal

Wrap the Phase 1 query in the retriever's public API: normalize and dedupe the
caller's gap skill names, embed the distinct ones in a single pass, and map
results back onto the caller's original strings. It worked when
`retrieve_for_skills` can be handed raw `SkillGap.skill` values — variants and
duplicates included — and returns each one's resources under the key the caller
passed in.

## Safety Checklist

- **Touches user input, auth, secrets, or external calls?**
  No external calls. The embedding model is local and already loaded by P1's
  singleton. Skill names come from `listing_gaps` and reach SQL only as bound
  parameters.
- **Contains a one-way door (schema, public API shape, new dependency)?**
  No. The two new `Settings` fields are additive with defaults, so every
  existing `Settings()` construction site keeps working. No new dependency —
  `sentence-transformers` arrived with P1.

---

## Tasks

### Task 1: Config settings for `k` and the staleness window

- **Files:** `scout/config.py`, `tests/test_coach_config.py`
- **Gate:** none
- **Steps:**
  - [x] Write failing test: `Settings()` exposes `coach_top_k == 3` and
        `coach_resource_max_age_days == 90` by default, and both read from
        `COACH_TOP_K` / `COACH_RESOURCE_MAX_AGE_DAYS` when set
  - [x] Verify it fails (`pytest tests/test_coach_config.py -q`)
  - [x] Add both fields with `partial(_env_int, ...)` default factories,
        alongside the existing `coach_*` settings
  - [x] Verify it passes (`pytest tests/test_coach_config.py -q`)
  - [x] Commit: `feat(coach): add retriever top-k and staleness settings`

### Task 2: Normalization and dedupe of incoming skills

- **Files:** `scout/sub_agents/coach/retriever.py`, `tests/test_coach_retriever.py`
- **Gate:** none
- **Steps:**
  - [x] Write failing test: the module's skill-preparation helper turns
        `["K8s", "kubernetes", "React.js", "  "]` into the distinct normalized
        names `["kubernetes", "react"]`, preserving first-seen order
  - [x] Verify it fails (`pytest tests/test_coach_retriever.py -q`)
  - [x] Implement the helper using `scout.shared.skills.normalize_skill`
  - [x] Verify it passes (`pytest tests/test_coach_retriever.py -q`)
  - [x] Commit: `feat(coach): normalize and dedupe gap skills for retrieval`

### Task 3: `retrieve_for_skills` — embed once, query once, map back

- **Files:** `scout/sub_agents/coach/retriever.py`, `tests/test_coach_retriever.py`
- **Gate:** none
- **Steps:**
  - [x] Write failing test, with `embed` and `get_resources_for_skills` both
        stubbed: calling with `["K8s", "kubernetes", "React.js"]` returns a
        dict keyed by all three *original* strings, where `"K8s"` and
        `"kubernetes"` both map to the same resource list
  - [x] Write failing test: `embed` is called once per *distinct normalized*
        skill — twice for the input above, not three times
  - [x] Write failing test: an empty skill list returns `{}` without calling
        `embed` or touching the database at all
  - [x] Verify they fail (`pytest tests/test_coach_retriever.py -q`)
  - [x] Implement `retrieve_for_skills(conn, skills, settings=None, k=None)`,
        defaulting `k` and the staleness window from `Settings`
  - [x] Verify they pass (`pytest tests/test_coach_retriever.py -q`)
  - [x] Commit: `feat(coach): add retrieve_for_skills public retriever API`

### Task 4: End-to-end retrieval against real seeded rows

- **Files:** `tests/test_coach_retriever.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing test: seed `kubernetes` and `java` resources in the
        `scout_test` database, then call the public `retrieve_for_skills` with
        a real connection, a stubbed `embed`, and the gap wording `"K8s"`;
        assert the kubernetes resources come back under the `"K8s"` key and no
        java resource appears
  - [ ] Verify it fails (`pytest tests/test_coach_retriever.py -q`)
  - [ ] Fix whatever the seam between module and SQL exposes (a correct Task 3
        may already satisfy this — record which in Notes / Learnings)
  - [ ] Verify it passes (`pytest tests/test_coach_retriever.py -q`)
  - [ ] Commit: `test(coach): cover retriever end-to-end against seeded rows`

---

## Verification

- [ ] All phase tests pass:
      `pytest tests/test_coach_retriever.py tests/test_coach_config.py -q`
- [ ] Full regression: `pytest -q` — in particular confirms the two new
      `Settings` fields break no existing construction site
- [ ] Plan acceptance criteria re-read against the finished code, and
      `plan.md`'s Definition of Done ticked in this phase's final commit

## Observability

The retriever is a library function with no caller yet, so it emits no logs of
its own — a silent function with no consumer has nothing to report. What
confirms it works in practice is P3: when the grounded-tip stage lands, an
empty result for a gap is the signal worth logging there, since that is where
"no resource for this skill" becomes a visible product outcome. Deliberately
left to P3 rather than guessed at here.

## Rollback

Revert the phase's feat commits, then Phase 1's. `retriever.py` is a new file
with no importers, and the two `Settings` fields are unread once it is gone, so
removal restores the previous state exactly.

---

## Notes / Learnings

<Filled in during execution.>
