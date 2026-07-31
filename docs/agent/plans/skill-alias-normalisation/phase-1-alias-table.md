# Phase 1: Alias Table From Data

> **Parent plan:** [plan.md](plan.md)
> **Status:** Not started
> **Depends on:** nothing

---

## Goal

Common spellings of one technology reduce to one token, and technologies that
merely look alike still do not. Done when the measured variant families collapse
under `normalize_skill`, `C`/`C++`/`C#`/`Java`/`JavaScript` remain distinct, and
every alias entry traces to a spelling observed in real data.

## Safety Checklist

- **Touches user input, auth, secrets, or external calls?**
  No. `normalize_skill` is a pure function over strings; this phase makes no
  network or database calls beyond the read-only spike.
- **Contains a one-way door (schema, public API shape, new dependency)?**
  No — but note the *consequence*: this function is the contract on both sides
  of retrieval, so changing it makes stored tokens stale until phase 2 runs.
  The two phases ship together or the corpus disagrees with the code.

---

## Tasks

### Task 1: Spike — read the corpus's actual spellings

- **Files:** none — findings recorded in this doc's Notes
- **Gate:** none — read-only query
- **Steps:**
  - [ ] From the VM, list the stored tokens for the variant families in
        question:

        ```sql
        SELECT s, count(*) FROM resources, unnest(skills) s
        WHERE s LIKE '%gcp%' OR s LIKE '%google%' OR s LIKE '%node%'
           OR s LIKE '%rest%' OR s LIKE '%net%' OR s LIKE '%cicd%'
           OR s LIKE '%vue%' OR s LIKE '%infrastructure%'
        GROUP BY s ORDER BY count(*) DESC;
        ```

  - [ ] Record in Notes which spelling the tagger actually emits for each
        family — that spelling becomes the canonical direction, since the
        corpus side cannot be re-asked without spending LLM calls
  - [ ] Note any family where the corpus is already consistent and only the
        gap side varies; those need an alias but no backfill effect
  - [ ] No commit

### Task 2: Confirm the ambiguous families against real spellings

- **Files:** none — decisions recorded in this doc's Notes
- **Gate:** ⚠️ human sign-off **already given** (spec A1): the listed families
  are the same technology, so their resource tokens merge while gaps stay
  separate as written. This task now confirms the decision survives contact
  with Task 1's data rather than re-opening it — but a spelling that turns out
  to mean something different still stops and returns to the human
- **Steps:**
  - [ ] Check Task 1's counts against the approved merges: `.NET`/`.NET Core`,
        `REST`/`REST API`/`RESTful APIs`, `GCP`/`Google Cloud`/`Google Cloud
        Platform`, `CI/CD`/`CI/CD pipelines`, `Node.js`/`NodeJS`,
        `Vue.js`/`VueJS`, `Infrastructure as Code` variants, case-only variants
  - [ ] Confirm `Security` / `Cloud Security` stays **unmerged** — a generic
        parent and a specialisation, not two spellings (plan Key Decisions)
  - [ ] Flag to the human any spelling in Task 1's output that looks like a
        different technology rather than a variant, before it is written in
  - [ ] Record the final list in Notes, including what was left unmerged
  - [ ] No commit

### Task 3: Extend the alias table

- **Files:** `scout/shared/skills.py`, `tests/test_skills.py`
- **Gate:** none — Task 2's gate already covers the judgement
- **Steps:**
  - [ ] Write failing test: each approved variant family reduces to one token,
        one test case per family, using the real observed spellings
  - [ ] Verify it fails (`python -m pytest tests/test_skills.py -k variant -q`)
  - [ ] Implement: add the entries to `_SKILL_ALIASES`, keyed and valued in
        normalised form so phase 2 can apply the same table to stored tokens
  - [ ] Verify it passes (`python -m pytest tests/test_skills.py -q`)
  - [ ] Commit: `fix(skills): collapse observed spelling variants onto one token`

### Task 4: Handle the multi-word cases the strip order mangles

- **Files:** `scout/shared/skills.py`, `tests/test_skills.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing test: `.NET Core` reaches the same token as `.NET` (if
        Task 2 decided they merge) — today the punctuation strip runs before
        any alias lookup, so it becomes `netcore` and no table entry can catch
        it
  - [ ] Verify it fails (`python -m pytest tests/test_skills.py -k multiword -q`)
  - [ ] Implement the minimal ordering change that lets these resolve, without
        disturbing the `_PUNCTUATED_SKILLS` early return that keeps `C++` and
        `C#` distinct
  - [ ] Verify it passes (`python -m pytest tests/test_skills.py -q`)
  - [ ] Commit: `fix(skills): resolve multi-word names the punctuation strip flattened`

### Task 5: Pin the dangerous separations

- **Files:** `tests/test_skills.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing test (if not already failing): `C`, `C++`, `C#`, `Java`,
        `JavaScript`, `TypeScript` produce six distinct tokens, asserted as a
        set-size check so any future alias merging two of them fails loudly
  - [ ] Verify it fails or passes as appropriate
        (`python -m pytest tests/test_skills.py -k distinct -q`)
  - [ ] Implement nothing if already correct — this task's product is the
        guard, not a behaviour change
  - [ ] Verify (`python -m pytest -q`)
  - [ ] Commit: `test(skills): pin the language separations an alias must never merge`

---

## Verification

- [ ] All phase tests pass: `python -m pytest tests/test_skills.py -v`
- [ ] Full suite still passes: `python -m pytest -q`
- [ ] Every entry added to `_SKILL_ALIASES` appears in Task 1's observed
      spellings — no speculative entries
- [ ] Gap "met" detection tests still pass: this function also decides whether
      a profile skill satisfies a requirement, so a wrong merge would mark gaps
      met that are not

## Rollback

Revert the phase's commits. Stored tokens then agree with the code again,
because phase 2 has not run yet — which is why these two phases ship together.

---

## Notes / Learnings

<Filled in during execution — record Task 1's observed spellings and Task 2's
decisions, including the families deliberately left unmerged and why.>
