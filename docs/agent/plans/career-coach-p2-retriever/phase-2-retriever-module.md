# Phase 2: Retriever Module and Config

> **Parent plan:** [plan.md](plan.md)
> **Status:** Complete
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
  - [~] Commit: `feat(coach): normalize and dedupe gap skills for retrieval`
        — **no such commit exists**; folded into Task 3's commit, see Notes

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
  - [x] Write failing test: seed `kubernetes` and `java` resources in the
        `scout_test` database, then call the public `retrieve_for_skills` with
        a real connection, a stubbed `embed`, and the gap wording `"K8s"`;
        assert the kubernetes resources come back under the `"K8s"` key and no
        java resource appears
  - [x] Verify it fails (`pytest tests/test_coach_retriever.py -q`)
  - [x] Fix whatever the seam between module and SQL exposes (a correct Task 3
        may already satisfy this — record which in Notes / Learnings)
  - [x] Verify it passes (`pytest tests/test_coach_retriever.py -q`)
  - [x] Commit: `test(coach): cover retriever end-to-end against seeded rows`

---

## Verification

- [x] All phase tests pass:
      `pytest tests/test_coach_retriever.py tests/test_coach_config.py -q`
- [x] Full regression: `pytest -q` — in particular confirms the two new
      `Settings` fields break no existing construction site
- [x] Plan acceptance criteria re-read against the finished code, and
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

**Tasks 2 and 3 landed in one commit.** `_distinct_normalized` has no meaning
apart from the function that calls it; committing it alone would have left a
private helper with no caller and a test reaching past the module's public API
for no reason.

**The `k` override was dropped, then restored.** The first implementation took
`k` only from `Settings`, contradicting both the spec's interface sketch and
this phase's Task 3 wording. Restored with its own test rather than amending
the plan to match the code — P3 is the reason it exists, since a single tip
may want fewer resources than the global default.

**Task 4 passed on first run**, like Phase 1's Task 4. Verified by mutation
instead of a red-green cycle: replacing `normalize_skill(skill)` with a bare
`.strip()` in `_distinct_normalized` makes it fail, because `"K8s"` then
reaches the pre-filter unnormalized and matches nothing. That is precisely
the behaviour the test exists to pin, and precisely the bug that would have
shipped had the P1 write-side fix not gone in first — the two halves only
work as a pair.


---

## Post-review findings *(code review, 2026-07-27)*

**A skill that normalized to nothing was silently dropped from the result.**
The worst of the findings, because two adjacent layers disagreed about the
same invariant: `db.get_resources_for_skills` goes out of its way to guarantee
every requested skill gets a key, and the public function directly above it
quietly violated that for degenerate input. `P3` indexing `results[gap.skill]`
would have hit a `KeyError` on a gap whose extracted wording was punctuation.
Fixed — every skill passed in now gets a key, `[]` when it normalizes to
nothing, which is also semantically right: no normalized form means no
coverage. Covered by two new tests, including the all-degenerate case that
short-circuits before embedding.

**Aliased keys shared one list object.** `results["K8s"] is
results["kubernetes"]` was `True`, and both aliased the list inside the db
helper's dict, so a consumer sorting or trimming one key would have mutated
the other and the helper's internals. Now a fresh list per key.

**`_distinct_normalized` was a verbatim copy of the aggregator's
`_canonical_skills`.** These are not incidental duplicates — they are the read
and write halves of the *same* guarantee, and if they ever drifted the exact
pre-filter would silently stop matching, which is the one failure mode this
whole phase exists to prevent. Both now call
`scout.shared.skills.normalize_skills`, whose docstring records that order
preservation is load-bearing (the retriever pairs names to vectors by index).

**Embedding is now genuinely batched.** `spec.md` said "embed the distinct
normalized names in **one batched call**"; the implementation was a list
comprehension calling `embed()` per skill, and this phase doc had softened the
wording to "a single pass" without flagging the drift. That softening was the
one place these notes were not fully forthcoming. Added `embeddings.embed_many`
(one `encode` over the whole list) and the retriever now uses it.

### Known limitation — read/write embedding asymmetry

Not fixed, deliberately, but it changes how P3 should read `similarity`.

The write side embeds `tags.summary`, a paragraph of prose. The read side
embeds a bare normalized token like `"kubernetes"`. `all-MiniLM-L6-v2` is a
symmetric sentence-similarity model, not an asymmetric retrieval model, so
token-vs-paragraph cosine scores land in a compressed, low band. Consequences:

- The ranking half of "hybrid" carries less signal than the spec's "the 2–3
  **most semantically relevant**" implies. Correctness is unaffected — that is
  the pre-filter's job, and it is exact.
- **Absolute `similarity` values are not meaningful; only the ordering within
  one skill is.** A P3 author who gates on a threshold will be gating on a
  number that does not mean what it appears to.

`plan.md`'s risk table anticipated ranking being weak *because the corpus is
thin*, which is real but different — that resolves as coverage grows, whereas
this does not. If P3 finds the ordering unhelpful, the fix is to make the two
sides symmetric: embed a templated query (`"resources for learning {skill}"`)
on read, or `title + summary` on write. Deferred because it should be decided
against real retrieval output, which does not exist until P3.
