# Phase 2: Concurrent Ingest

> **Parent plan:** [plan.md](plan.md)
> **Status:** Not started
> **Depends on:** Phase 1 complete — isolation must exist before failures can
> arrive concurrently, or one bad candidate takes its whole chunk down

---

## Goal

Cut ingest wall-clock by running the per-candidate pipeline concurrently while
keeping database writes serial. Done when a measured batch shows real overlap,
the corpus produced is identical to the serial path's, and per-candidate
failure isolation still holds under `gather`.

## Safety Checklist

- **Touches user input, auth, secrets, or external calls?**
  Yes — this multiplies the rate at which GitHub and the LLM provider are
  called. Task 1 measures provider behaviour before the loop is rewritten, and
  the width is a setting so it can be lowered without a code change.
- **Contains a one-way door (schema, public API shape, new dependency)?**
  No. `asyncio` is already in use; no new dependency, no schema change.

---

## Tasks

### Task 1: Spike — does the provider tolerate concurrent tagging?

- **Files:** none — a throwaway script run once on the VM, findings recorded
  in this doc's Notes
- **Gate:** none — read-only against the provider, no database writes
- **Steps:**
  - [ ] Run a bounded batch: tag 12 already-stored READMEs at width 1, then at
        width 4, timing both and recording any 429 or provider error
  - [ ] Record in Notes: per-call latency at each width, total elapsed, error
        count, and whether width 4 delivers near-4x or saturates earlier
  - [ ] If 429s appear, record the width at which they start — that becomes the
        default rather than 4
  - [ ] No commit

### Task 2: Make the per-candidate pipeline a coroutine

- **Files:** `scout/sub_agents/coach/runner.py`,
  `tests/test_coach_runner.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing test: a helper coroutine takes one URL and returns either
        a tagged resource with its embedding, or a typed skip/failure result —
        without touching the database
  - [ ] Verify it fails (`python -m pytest tests/test_coach_runner.py -k candidate_pipeline -q`)
  - [ ] Implement: extract fetch → tag → embed into that coroutine, leaving the
        existing loop calling it one at a time. Behaviour unchanged; this is
        the seam concurrency needs
  - [ ] Verify it passes (`python -m pytest tests/test_coach_runner.py -q`)
  - [ ] Commit: `refactor(coach): extract the per-candidate pipeline behind one coroutine`

### Task 3: Process candidates in concurrent chunks

- **Files:** `scout/sub_agents/coach/runner.py`, `scout/config.py`,
  `tests/test_coach_runner.py`, `tests/test_coach_config.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing test: with an injected delay per candidate, a chunk of 4
        completes in about the time of one — proving overlap, not sequence —
        and inserts still occur one at a time in list order
  - [ ] Verify it fails (`python -m pytest tests/test_coach_runner.py -k concurren -q`)
  - [ ] Implement: `COACH_INGEST_CONCURRENCY` setting (default from Task 1's
        finding); process candidates in chunks of that width via
        `gather(return_exceptions=True)`; insert each chunk's successes
        serially on the open connection before starting the next chunk
  - [ ] Verify it passes (`python -m pytest tests/test_coach_runner.py -q`)
  - [ ] Commit: `perf(coach): tag and embed candidates in concurrent chunks`

### Task 4: Prove isolation and the abort still hold under concurrency

- **Files:** `tests/test_coach_runner.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing test: within one chunk, one candidate raising leaves its
        chunk-mates inserted; and a rate-limit error anywhere in a chunk still
        propagates rather than being swallowed by `return_exceptions=True`
  - [ ] Verify it fails (`python -m pytest tests/test_coach_runner.py -k chunk_failure -q`)
  - [ ] Implement whatever the test exposes — most likely explicit
        re-inspection of gathered exceptions, since `return_exceptions=True`
        turns a rate limit into a value rather than a raise
  - [ ] Verify it passes (`python -m pytest tests/ -q`)
  - [ ] Commit: `test(coach): pin failure isolation and rate-limit escalation under concurrency`

### Task 5: Apply the same chunking to the bootstrap metadata filter

- **Files:** `scout/sub_agents/coach/runner.py`,
  `tests/test_coach_runner.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing test: metadata lookups for a harvested pool run
        concurrently and still produce one call per unique URL, in a stable
        kept-order
  - [ ] Verify it fails (`python -m pytest tests/test_coach_runner.py -k filter_concurren -q`)
  - [ ] Implement: reuse the chunk helper from Task 3 for the filter loop
  - [ ] Verify it passes (`python -m pytest -q`)
  - [ ] Commit: `perf(coach): run the bootstrap quality filter concurrently`

---

## Verification

- [ ] All phase tests pass: `python -m pytest tests/test_coach_runner.py -v`
- [ ] Full suite still passes: `python -m pytest -q`
- [ ] Task 1's measured widths are recorded in Notes, and the shipped default
      matches what was measured rather than what was assumed

## Observability

Ingest progress lines keep their existing shape but their rate figure becomes
effective-per-candidate rather than serial-per-candidate, which is the number
that shows whether concurrency is working:

```
Ingest progress: 120/577 candidates, ... (0.5s each, ~4 min left).
```

A width that is silently ineffective looks like an unchanged per-candidate
figure; a width that is too high looks like failures climbing in the summary.

## Rollback

Set `COACH_INGEST_CONCURRENCY=1` to restore serial behaviour without a
deploy — that is the reason it is a setting rather than a constant. Failing
that, revert the phase's commits; no state depends on them.

---

## Notes / Learnings

<Filled in during execution — record Task 1's measured widths here before
Task 3 picks a default.>
