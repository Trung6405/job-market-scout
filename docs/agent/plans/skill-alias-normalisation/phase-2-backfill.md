# Phase 2: Backfill Stored Tokens

> **Parent plan:** [plan.md](plan.md)
> **Status:** Not started
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
  - [ ] Write failing test: given rows whose `skills` hold pre-alias tokens,
        the script computes the rewritten arrays, leaves already-canonical rows
        untouched, and preserves order and de-duplicates if two tokens collapse
        onto one
  - [ ] Verify it fails
        (`python -m pytest tests/test_backfill_skill_aliases.py -q`)
  - [ ] Implement: read `id, skills`, apply `normalize_skills` to each stored
        token, write back only rows that actually change. DSN from the
        environment, never argv, matching `scripts/verify_migration.py`
  - [ ] Verify it passes
        (`python -m pytest tests/test_backfill_skill_aliases.py -q`)
  - [ ] Commit: `feat(scripts): backfill resources.skills through the alias table`

### Task 2: Idempotency and a dry run

- **Files:** `scripts/backfill_skill_aliases.py`,
  `tests/test_backfill_skill_aliases.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing test: a second pass over already-rewritten rows reports
        zero changes; and a `--dry-run` flag reports what would change without
        writing
  - [ ] Verify it fails
        (`python -m pytest tests/test_backfill_skill_aliases.py -k idempot -q`)
  - [ ] Implement both
  - [ ] Verify it passes (`python -m pytest -q`)
  - [ ] Commit: `feat(scripts): make the alias backfill idempotent and dry-runnable`

### Task 3: Run it against production

- **Files:** none — output recorded in this doc's Notes
- **Gate:** ⚠️ human sign-off required before the write pass — it rewrites the
  corpus in place. The dry run and the dump come first
- **Steps:**
  - [ ] Confirm nothing is scheduled to run: `gh run list --limit 3`, and check
        the time against the 19:00 UTC cron
  - [ ] Boot the VM and take a dump of the current database, copied off the VM,
        exactly as the P6 phase-3 procedure does — this is the rollback
  - [ ] Run with `--dry-run` and record in Notes how many rows would change and
        a sample of the rewrites
  - [ ] Read the sample: any rewrite that merges two technologies wrongly stops
        this task and returns to phase 1 Task 2
  - [ ] Run the write pass, then immediately re-run it and confirm it reports
        zero changes
  - [ ] Shred the dump copy on the VM; keep the laptop copy until the next
        successful pipeline run
  - [ ] No commit

### Task 4: Measure and record the coverage delta

- **Files:** none — findings recorded in this doc's Notes
- **Gate:** none — read-only
- **Steps:**
  - [ ] Count distinct unmet gap skills that have at least one matching corpus
        token, before and after — the before figure comes from the dump taken
        in Task 3, the after from the live table
  - [ ] Record the delta in Notes, **including if it is zero**. A zero delta
        here is an honest result, not a failure: most fragmented families are
        cloud technologies the corpus does not hold yet, and the correctness
        argument for the change stands independently of today's numbers
  - [ ] Record which families gained matches and which are still waiting on the
        corpus, so coach-aggregator-completion phase 3 can check them again
        after seeding
  - [ ] No commit

---

## Verification

- [ ] All phase tests pass:
      `python -m pytest tests/test_backfill_skill_aliases.py -v`
- [ ] Full suite still passes: `python -m pytest -q`
- [ ] The second production run reports zero changes
- [ ] A dump taken before the write pass exists off the VM
- [ ] The coverage delta is recorded in Notes, zero or not

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

<Filled in during execution — record the dry-run counts, a sample of rewrites,
and the coverage delta.>
