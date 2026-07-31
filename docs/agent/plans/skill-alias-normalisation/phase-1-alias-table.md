# Phase 1: Alias Table From Data

> **Parent plan:** [plan.md](plan.md)
> **Status:** Complete — all five tasks done; Tasks 4 and 5 needed no code change
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
  - [x] From the VM, list the stored tokens for the variant families in
        question:

        ```sql
        SELECT s, count(*) FROM resources, unnest(skills) s
        WHERE s LIKE '%gcp%' OR s LIKE '%google%' OR s LIKE '%node%'
           OR s LIKE '%rest%' OR s LIKE '%net%' OR s LIKE '%cicd%'
           OR s LIKE '%vue%' OR s LIKE '%infrastructure%'
        GROUP BY s ORDER BY count(*) DESC;
        ```

  - [x] Record in Notes which spelling the tagger actually emits for each
        family — that spelling becomes the canonical direction, since the
        corpus side cannot be re-asked without spending LLM calls
  - [x] Note any family where the corpus is already consistent and only the
        gap side varies; those need an alias but no backfill effect
  - [x] No commit

### Task 2: Confirm the ambiguous families against real spellings

- **Files:** none — decisions recorded in this doc's Notes
- **Gate:** ⚠️ human sign-off **already given** (spec A1): the listed families
  are the same technology, so their resource tokens merge while gaps stay
  separate as written. This task now confirms the decision survives contact
  with Task 1's data rather than re-opening it — but a spelling that turns out
  to mean something different still stops and returns to the human
- **Steps:**
  - [x] Check Task 1's counts against the approved merges: `.NET`/`.NET Core`,
        `REST`/`REST API`/`RESTful APIs`, `GCP`/`Google Cloud`/`Google Cloud
        Platform`, `CI/CD`/`CI/CD pipelines`, `Node.js`/`NodeJS`,
        `Vue.js`/`VueJS`, `Infrastructure as Code` variants, case-only variants
  - [x] Confirm `Security` / `Cloud Security` stays **unmerged** — a generic
        parent and a specialisation, not two spellings (plan Key Decisions)
  - [x] Flag to the human any spelling in Task 1's output that looks like a
        different technology rather than a variant, before it is written in
  - [x] Record the final list in Notes, including what was left unmerged
  - [x] No commit

### Task 3: Extend the alias table

- **Files:** `scout/shared/skills.py`, `tests/test_advisor_gaps.py`
- **Gate:** none — Task 2's gate already covers the judgement
- **Steps:**
  - [x] Write failing test: each approved variant family reduces to one token,
        one test case per family, using the real observed spellings
  - [x] Verify it fails (`python -m pytest tests/test_advisor_gaps.py -k variant -q`)
  - [x] Implement: add the entries to `_SKILL_ALIASES`, keyed and valued in
        normalised form so phase 2 can apply the same table to stored tokens
  - [x] Verify it passes (`python -m pytest tests/test_advisor_gaps.py -q`)
  - [x] Commit: `fix(skills): collapse observed spelling variants onto one token`

### Task 4: Handle the multi-word cases the strip order mangles *(no change needed)*

- **Files:** `scout/shared/skills.py`, `tests/test_advisor_gaps.py`
- **Gate:** none
- **Steps:**
  - [x] Write failing test: `.NET Core` reaches the same token as `.NET` (if
        Task 2 decided they merge) — today the punctuation strip runs before
        any alias lookup, so it becomes `netcore` and no table entry can catch
        it
  - [x] Verify it fails (`python -m pytest tests/test_advisor_gaps.py -k multiword -q`)
  - [x] Implement the minimal ordering change that lets these resolve, without
        disturbing the `_PUNCTUATED_SKILLS` early return that keeps `C++` and
        `C#` distinct
  - [x] Verify it passes (`python -m pytest tests/test_advisor_gaps.py -q`)
  - [x] Commit: `fix(skills): resolve multi-word names the punctuation strip flattened`

### Task 5: Pin the separations the new aliases could break *(guards already passed)*

- **Files:** `tests/test_advisor_gaps.py`
- **Gate:** none
- **Steps:**
  - [x] **Scope corrected during execution:** the C-family guard this task was
        written for *already exists* as
        `test_normalize_skill_keeps_c_family_languages_distinct`, along with
        `Java`/`JavaScript`, `F#`/`F` and `ASP.NET`/`.NET`. Nothing to add
        there
  - [x] Write failing test for the separations the *new* entries put at risk,
        which no guard covers: `Google Cloud Run` and `Google Cloud Storage`
        must not collapse into `GCP` (distinct products a `%google%` pattern
        would have swept in), `ASP.NET Core` must not reach `.NET`, and
        `Cloud Security` must not reach `Security`
  - [x] Verify it fails
        (`python -m pytest tests/test_advisor_gaps.py -k separat -q`)
  - [x] Implement only if a guard actually fails — the product of this task is
        the guard, not a behaviour change
  - [x] Verify (`python -m pytest -q`)
  - [x] Commit: `test(skills): pin the separations the new aliases could break`

---

## Verification

- [x] All phase tests pass: `python -m pytest tests/test_advisor_gaps.py -v`
- [x] Full suite still passes: `python -m pytest -q`
- [x] Every entry added to `_SKILL_ALIASES` appears in Task 1's observed
      spellings — no speculative entries
- [x] Gap "met" detection tests still pass: this function also decides whether
      a profile skill satisfies a requirement, so a wrong merge would mark gaps
      met that are not

## Rollback

Revert the phase's commits. Stored tokens then agree with the code again,
because phase 2 has not run yet — which is why these two phases ship together.

---

## Notes / Learnings

### Task 1 — the corpus's actual spellings *(2026-07-30)*

| Family | Corpus tokens | Canonical chosen |
|---|---|---|
| Node | `node` 29, `nodejs` 3 | `node` |
| REST | `rest` 6, `restapi` 5 | `rest` |
| Vue | `vue` 21 | `vue` |
| .NET | `dotnet` 6 (no `netcore`) | `dotnet` |
| CI/CD | `cicd` 2 (no `cicdpipelines`) | `cicd` |
| IaC | `infrastructureascode` 2 (no `iac`) | `infrastructureascode` |
| Google | `gcp` 1, `googlecloud` 1, `googlecloudplatform` 1 | `gcp` — no signal, free choice, shortest |
| Languages | `javascript` 38, `cpp` 12, `java` 11, `c` 7, `csharp` 4 | unchanged, all distinct |

**The corpus is fragmented on its own side, not just against the gaps.** The
tagger emits both `Node.js` and `NodeJS` (29 vs 3) and both `REST` and
`REST API` (6 vs 5), so today a `node` resource is invisible to a `nodejs`
resource's gap and vice versa. This is not only a gap-to-resource problem.

**The risk table's premise about canonical direction was wrong**, and the plan
has been corrected. Direction cannot "move the mismatch": both sides normalise
through the same table and the backfill rewrites stored tokens through it too,
so any consistent choice matches. Direction affects readability and how many
rows the backfill rewrites, nothing else. Chosen by commonest existing spelling
to keep churn low.

**A wildcard warning worth recording.** A first pass using `LIKE '%google%'`
returned `googlecloudrun` and `googlecloudstorage` — different products, not
spellings of GCP — and `LIKE '%net%'` returned `telnet` and `netavark`. Alias
entries must come from exact tokens inspected by hand; pattern matching over
this vocabulary is exactly how C, C++ and C# got merged in the earlier
experiment.

### Task 2 — families confirmed *(2026-07-30)*

Approved merges survive contact with the data: `.NET`/`.NET Core`,
`REST`/`REST API`/`RESTful APIs`, `GCP`/`Google Cloud`/`Google Cloud Platform`,
`CI/CD`/`CI/CD pipelines`, `Node.js`/`NodeJS`, `Vue.js`/`VueJS`,
`Infrastructure as Code` variants, and case-only variants.

Left unmerged, deliberately:

- `Security` / `Cloud Security` — parent and specialisation, not two spellings.
- `googlecloudrun`, `googlecloudstorage` — distinct GCP products that a
  `%google%` pattern would have swept in. They stay separate from `gcp`.
- `c` / `cpp` / `csharp` / `java` / `javascript` — the guarded separations;
  note `cpp` has 12 resources, so a wrong merge would actively pollute `c`
  gaps rather than merely blur them.

### Tasks 3-5 — the table, and two tasks that dissolved *(2026-07-30)*

Thirteen entries added, each traceable to a counted spelling: `nodejs`->`node`,
four REST forms->`rest`, `vuejs`->`vue`, `googlecloud`/`googlecloudplatform`
->`gcp`, `cicdpipeline(s)`->`cicd`, `iac`->`infrastructureascode`,
`netcore`->`dotnet`.

**Task 4 needed no code change, because its premise was wrong.** It assumed the
punctuation strip runs *after* alias lookup, leaving `.NET Core` stranded as
`netcore` where no entry could reach it. The strip runs *before* the lookup, so
`netcore` is precisely what the table is handed — a plain entry resolves it,
with no reordering and no risk to the `_PUNCTUATED_SKILLS` early return that
keeps `C++` and `C#` distinct. The safest change here was no change.

**Task 5 found its guards already written.** `C`/`C++`/`C#` (with the incident
comment), `Java`/`JavaScript`, `F#`/`F` and `ASP.NET`/`.NET` were all pinned
already. What was missing were guards for the separations the *new* entries put
at risk, so those were added instead: `Google Cloud Run` and
`Google Cloud Storage` must not reach `GCP`, `ASP.NET Core` must not reach
`.NET`, and `Cloud Security` must not reach `Security`. All four passed on
first run — the entries were narrow enough — which is the outcome a guard
should have.

Verification: 619 passed, up 2 from 617.
