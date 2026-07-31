# Phase 2: Backfill Stored Tokens

> **Parent plan:** [plan.md](plan.md)
> **Status:** Complete — backfill applied and verified idempotent; coverage delta recorded
> **Depends on:** Phase 1 complete — the table must exist before rows can be
> rewritten through it, and until this phase runs the corpus disagrees with the
> code

---

## Goal

Every stored token matches what fresh tagging would now produce. Done when
`resources.skills` contains no value the current rules would map elsewhere, a
second run of the backfill changes nothing, and the coverage delta is recorded.

## Safety Checklist

- **Touches user input, auth, secrets, or external calls?**
  Yes — it writes to the production `resources` table. Task 3 takes a dump
  first and runs while nothing is scheduled.
- **Contains a one-way door (schema, public API shape, new dependency)?**
  No. The rewrite is reversible from the dump taken immediately before it, and
  is idempotent by construction: applying the table to an already-canonical
  token is a no-op.

---

## Tasks

### Task 1: The remap script

- **Files:** `scripts/backfill_skill_aliases.py`,
  `tests/test_backfill_skill_aliases.py`
- **Gate:** none
- **Steps:**
  - [x] Write failing test: given rows whose `skills` hold pre-alias tokens,
        the script computes the rewritten arrays, leaves already-canonical rows
        untouched, and preserves order and de-duplicates if two tokens collapse
        onto one
  - [x] Verify it fails
        (`python -m pytest tests/test_backfill_skill_aliases.py -q`)
  - [x] Implement: read `id, skills`, apply `normalize_skills` to each stored
        token, write back only rows that actually change. DSN from the
        environment, never argv, matching `scripts/verify_migration.py`
  - [x] Verify it passes
        (`python -m pytest tests/test_backfill_skill_aliases.py -q`)
  - [x] Commit: `feat(scripts): backfill resources.skills through the alias table`

### Task 2: Idempotency and a dry run

- **Files:** `scripts/backfill_skill_aliases.py`,
  `tests/test_backfill_skill_aliases.py`
- **Gate:** none
- **Steps:**
  - [x] Write failing test: a second pass over already-rewritten rows reports
        zero changes; and a `--dry-run` flag reports what would change without
        writing
  - [x] Verify it fails
        (`python -m pytest tests/test_backfill_skill_aliases.py -k idempot -q`)
  - [x] Implement both
  - [x] Verify it passes (`python -m pytest -q`)
  - [x] Commit: `feat(scripts): make the alias backfill idempotent and dry-runnable`

### Task 3: Run it against production

- **Files:** none — output recorded in this doc's Notes
- **Gate:** ⚠️ human sign-off required before the write pass — it rewrites the
  corpus in place. The dry run and the dump come first
- **Steps:**
  - [x] Confirm nothing is scheduled to run: `gh run list --limit 3`, and check
        the time against the 19:00 UTC cron
  - [x] Boot the VM and take a dump of the current database, copied off the VM,
        exactly as the P6 phase-3 procedure does — this is the rollback
  - [x] Run with `--dry-run` and record in Notes how many rows would change and
        a sample of the rewrites
  - [x] Read the sample: any rewrite that merges two technologies wrongly stops
        this task and returns to phase 1 Task 2
  - [x] Run the write pass, then immediately re-run it and confirm it reports
        zero changes
  - [x] Shred the dump copy on the VM; keep the laptop copy until the next
        successful pipeline run
  - [x] No commit

### Task 4: Measure and record the coverage delta

- **Files:** none — findings recorded in this doc's Notes
- **Gate:** none — read-only
- **Steps:**
  - [x] Count distinct unmet gap skills that have at least one matching corpus
        token, before and after — the before figure comes from the dump taken
        in Task 3, the after from the live table
  - [x] Record the delta in Notes, **including if it is zero**. A zero delta
        here is an honest result, not a failure: most fragmented families are
        cloud technologies the corpus does not hold yet, and the correctness
        argument for the change stands independently of today's numbers
  - [x] Record which families gained matches and which are still waiting on the
        corpus, so coach-aggregator-completion phase 3 can check them again
        after seeding
  - [x] No commit

---

## Verification

- [x] All phase tests pass:
      `python -m pytest tests/test_backfill_skill_aliases.py -v`
- [x] Full suite still passes: `python -m pytest -q`
- [x] The second production run reports zero changes
- [x] A dump taken before the write pass exists off the VM
- [x] The coverage delta is recorded in Notes, zero or not

## Observability

The dry run is the observability: it names every rewrite before any of them
happen, which is the point at which a wrong merge is cheapest to catch. After
the write pass, the signal that it worked is the second run reporting zero
changes — anything else means the rewrite is not a fixed point and the table
has a cycle.

## Rollback

Restore `resources` from the dump taken in Task 3, into an empty table:
dropping and restoring that one table is enough, since nothing else was
touched. If the code is also being reverted, revert phase 1's commits first so
the restored tokens and the rules agree again.

---

## Notes / Learnings

### Tasks 1-2 — the script *(2026-07-31)*

`scripts/backfill_skill_aliases.py`, ten tests. The planning logic is what is
tested; the database round-trip is two thin statements exercised for real in
Task 3. A rewrite that touched every row would look identical to one that
touched the right rows until it corrupted something, so `plan_changes` excludes
no-ops and that exclusion is pinned.

Three properties fell out of `normalize_skills` rather than needing code:
order is preserved (load-bearing — the retriever pairs names positionally with
query embeddings), two stale spellings collapsing onto one token deduplicate,
and unknown tokens pass through untouched.

The script verifies idempotency **against the database** after writing, not just
in tests: it re-plans from what is now stored and exits non-zero if anything
remains non-canonical, since that would mean the alias table has a cycle and no
fixed point. That check is the difference between "safe to re-run" as a claim
and as a fact.

Verification: 629 passed, up 10.

### Tasks 3-4 — the production run and what it bought *(2026-07-31)*

Ran in a 17-hour window clear of the 19:00 UTC cron, with
`pre-backfill-20260731T020310Z.sql` (11,456,396 bytes, complete-marker
verified) copied off the VM first.

**Dry run: 10 of 957 rows.** `restapi`->`rest` 5, `nodejs`->`node` 3,
`googlecloudplatform`->`gcp` 1, `googlecloud`->`gcp` 1. Every line was read for
wrong merges. Two details confirmed the entries are narrow enough:
`realtimeapi` survived untouched sitting directly beside `restapi` in id=811,
and `aws` / `azure` / `awslightsail` / `microsoftazure` all survived beside the
Google rewrites. Order preserved in every row.

**Write pass: exit 0**, and the post-write re-plan reported *"a second pass
finds nothing left to change"*. An independent dry run afterwards agreed —
0 of 957 — and a direct query for the ten stale tokens returned nothing.
Consolidation arithmetic is exact: `node` 29+3=32, `rest` 6+5=11, `gcp`
1+1+1=3.

**The first coverage measurement was wrong and reported a delta of zero.** It
normalised gap skills with the *new* rules on both sides while varying only the
token set, so `RESTful APIs` counted as already-covered because `rest` existed —
when under the old rules it normalised to `restfulapis` and matched nothing.
Both halves have to move together. Recomputed properly:

| | Before | After |
|---|---|---|
| Gap skills with >=1 match | 193 | **199** |
| Reachable (gap, resource) pairs | 1,266 | **1,368** |
| Coverage lost | — | **0** |

Six gap skills went from *zero* matches to matching: `.NET Core`,
`CI/CD Pipelines`, `CI/CD pipelines`, `REST APIs`, `RESTful APIs`, `VueJS`.
Nothing lost coverage, which is the check that matters most — no merge pulled a
gap away from resources it was already finding.

Modest, and expected to be: only 10 of 957 rows held affected spellings because
the corpus is Python-ecosystem. The families that fragment hardest are cloud
technologies the corpus does not hold yet, so the real payoff arrives after the
coach-aggregator-completion seeding run — which is precisely why this landed
first rather than after.
