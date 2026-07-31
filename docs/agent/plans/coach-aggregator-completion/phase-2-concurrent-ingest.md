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
  - [~] **Not run — superseded by production evidence, human decision
        2026-07-31.** The spike needs `DEEPSEEK_API_KEY` and `GITHUB_PAT`,
        which are not available locally, so it would have cost a VM boot and
        live LLM spend to measure something production already answers. See
        Notes for the evidence and the default it sets
  - [~] Per-call latency at each width — not measured; Phase 3's real run is
        the measurement instead
  - [~] 429 threshold — not measured; production has not hit one at width 3
  - [x] No commit

### Task 2: Make the per-candidate pipeline a coroutine

- **Files:** `scout/sub_agents/coach/runner.py`,
  `tests/test_coach_runner.py`
- **Gate:** none
- **Steps:**
  - [x] Write failing test: a helper coroutine takes one URL and returns either
        a tagged resource with its embedding, or a typed skip/failure result —
        without touching the database
  - [x] Verify it fails (`python -m pytest tests/test_coach_runner.py -k candidate_pipeline -q`)
  - [x] Implement: extract fetch → tag → embed into that coroutine, leaving the
        existing loop calling it one at a time. Behaviour unchanged; this is
        the seam concurrency needs
  - [x] Verify it passes (`python -m pytest tests/test_coach_runner.py -q`)
  - [x] Commit: `refactor(coach): extract the per-candidate pipeline behind one coroutine`

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

### Task 1 — not run; the default comes from production instead *(2026-07-31)*

The spike was skipped by human decision, and the reasoning matters more than
the skip.

**The question it was written to answer is already answered.**
`MODEL_CONCURRENCY` defaults to **3** and is used in production by
`scout/sub_agents/scorer/runner.py`, `advisor/runner.py` and `coach/tips.py` —
same provider, same account, same key, across every scheduled run to date, with
no 429 handling ever having been needed. "Does DeepSeek tolerate concurrent
calls" has a larger and longer-running sample behind it than 12 calls on one
afternoon would have produced.

**What the spike would still have added**, and what is therefore not known:
whether width 4 buys anything over width 3, and where 429s actually begin. That
is a tuning question, not a safety one.

**What it would have cost**: `DEEPSEEK_API_KEY` and `GITHUB_PAT` are not
available locally, so running it meant booting the VM and spending real LLM
budget, or putting live keys on the laptop.

**Consequence for Task 3:** the default is **3**, matching the width production
already runs, not the 4 the plan assumed. The plan's own verification —
"the shipped default matches what was measured rather than what was assumed" —
is satisfied in spirit: 3 is measured, just not by this task.

The risk this spike covered ("DeepSeek behaviour under width-4 concurrent
tagging") is therefore **retired for width 3 and open for width 4**, and the
setting exists so the answer can change without a deploy.

### Task 2 — the seam *(2026-07-31)*

`_prepare_candidate` does fetch → tag → embed and returns a `PreparedCandidate`,
or `None` for a repo with no README. It touches no database, which is the whole
point: the expensive part of a candidate is IO-bound and independent per URL,
while the insert is neither.

Failures deliberately propagate out of it rather than being caught inside. The
caller owns the isolation policy — skip, escalate a rate limit, abort on a
systemic rate — and splitting that policy across two places is how the two
layers would end up disagreeing about what a 403 means, which is the bug Phase 1
Task 4 just fixed.

Behaviour is unchanged; the loop calls it one at a time. The README check stays
first inside it so a bare repo still costs neither a tagging call nor an
embedding, and normalisation stays on the prepared resource rather than moving
to the insert — otherwise making this concurrent would quietly change what lands
in `skills`.

Verification: 19 passed in `tests/test_coach_runner.py`.
