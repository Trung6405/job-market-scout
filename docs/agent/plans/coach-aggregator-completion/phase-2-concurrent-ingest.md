# Phase 2: Concurrent Ingest

> **Parent plan:** [plan.md](plan.md)
> **Status:** Complete — Task 1 skipped by decision; Tasks 2-5 landed;
> 632 tests passing
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
  - [x] Write failing test: ~~with an injected delay per candidate, a chunk of 4
        completes in about the time of one~~ **changed during execution** to
        assert the *peak in-flight count* instead — same property, without a
        wall-clock assertion that a loaded machine can fail spuriously (see
        Notes) — and inserts still occur one at a time in list order
  - [x] Verify it fails (`python -m pytest tests/test_coach_runner.py -k concurren -q`)
  - [x] Implement: `COACH_INGEST_CONCURRENCY` setting (default **3**, from
        production rather than Task 1); process candidates in chunks of that
        width via `gather(return_exceptions=True)`; insert each chunk's
        successes serially on the open connection before starting the next chunk
  - [x] Verify it passes (`python -m pytest tests/test_coach_runner.py -q`)
  - [x] Commit: `perf(coach): tag and embed candidates in concurrent chunks`

### Task 4: Prove isolation and the abort still hold under concurrency

- **Files:** `tests/test_coach_runner.py`
- **Gate:** none
- **Steps:**
  - [x] Write failing test: within one chunk, one candidate raising leaves its
        chunk-mates inserted; and a rate-limit error anywhere in a chunk still
        propagates rather than being swallowed by `return_exceptions=True`
  - [~] ~~Verify it fails~~ **Could not fail — see Notes.** Task 3 had to ship
        the re-inspection to be correct at all, so both tests passed on first
        run. A mutation check was run in place of the red phase
  - [x] ~~Implement whatever the test exposes~~ — already present from Task 3;
        the prediction in this step was right about *what* was needed, only
        wrong about *when*
  - [x] Verify it passes (`python -m pytest tests/ -q`)
  - [x] Commit: `test(coach): pin failure isolation and rate-limit escalation under concurrency`

### Task 5: Apply the same chunking to the bootstrap metadata filter

- **Files:** `scout/sub_agents/coach/runner.py`,
  `tests/test_coach_runner.py`
- **Gate:** none
- **Steps:**
  - [x] Write failing test: metadata lookups for a harvested pool run
        concurrently and still produce one call per unique URL, in a stable
        kept-order
  - [x] Verify it fails (`python -m pytest tests/test_coach_runner.py -k filter_concurren -q`)
  - [x] ~~Reuse the chunk helper from Task 3~~ **Not applicable** — Task 3's
        chunking is `asyncio.gather` inside an async function, and this loop is
        synchronous blocking IO with no event loop to await on. Implemented
        with a `ThreadPoolExecutor` instead; see Notes
  - [x] Verify it passes (`python -m pytest -q`)
  - [x] Commit: `perf(coach): run the bootstrap quality filter concurrently`

---

## Verification

- [x] All phase tests pass: `python -m pytest tests/test_coach_runner.py -v`
- [x] Full suite still passes: `python -m pytest -q` — 632 passed, no skips
- [x] ~~Task 1's measured widths are recorded in Notes~~ — Task 1 was not run.
      The shipped default is still measured rather than assumed: 3 is the width
      `MODEL_CONCURRENCY` already runs against the same provider in production.
      Width 4 remains unmeasured and is explicitly *not* shipped

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

### Task 3 — concurrent chunks *(2026-07-31)*

Chunks of `COACH_INGEST_CONCURRENCY` (default 3) prepared via
`gather(return_exceptions=True)`, then written serially on the one open
connection.

**`return_exceptions=True` is load-bearing and also a trap.** Without it,
`gather` propagates the first exception and its siblings' completed work is
discarded — phase 1's bug reintroduced at chunk granularity. With it, every
escalation phase 1 established stops happening by itself, because a raise
becomes a *value*. All three are re-applied by hand, in the same order as the
serial version: non-`Exception` (cancellation) re-raised first, then rate
limits, then count-and-skip, then the systemic threshold.

**The test asserts peak in-flight count, not elapsed time.** The plan asked for
"a chunk of 4 completes in about the time of one". That is the right property
but a poor assertion: it fails spuriously when the machine is loaded, and this
machine demonstrably is — see below. Peak concurrency measures the same thing
deterministically.

**A regression I introduced and caught before committing.** Moving the loop
body under the chunk structure left the progress log inside the successful
insert branch, so a run whose candidates were mostly failing would have gone
quiet — precisely the run that most needs to be watched. It is now unconditional
and before any `continue`, matching the serial version.

**Test-infrastructure hazard, now diagnosed.** `tests/conftest.py:93-97` creates
the pool with `timeout=2` and turns `OSError` into `pytest.skip`. On a loaded
machine a connect can exceed that budget, so a test is silently *removed* from a
run that still reports green. Observed three times during this phase, on
different tests each time. Out of scope here, but it means "N passed" is not by
itself evidence that N tests ran — check the skip count. Worth its own fix:
infrastructure failure should fail, not skip.

Verification: 34 passed, 1 skipped (the skip was
`test_run_coach_aggregator_still_skips_a_plain_403`, a phase 1 test, re-run
green in isolation — not the concurrency test).

### Task 4 — the red phase that could not happen *(2026-07-31)*

Both tests passed on their first run. The plan expected them to fail and then
drive the implementation, but Task 3 could not have been correct without the
gathered-exception re-inspection already in place: shipping concurrent chunks
that swallowed rate limits would have silently undone phase 1 while every phase
1 test still passed. Writing the escalation there was right; the ordering in
this plan was wrong.

**A passing test written after the code proves nothing on its own**, so a
mutation check was run in place of the red phase. Disabling the rate-limit
re-raise (`if _is_rate_limited(outcome) and False`) failed **both**
`test_chunk_failure_from_a_rate_limit_still_ends_the_run` and phase 1's
`test_run_coach_aggregator_lets_a_rate_limit_end_the_run`, then the mutation was
reverted and `git diff` confirmed the file matched its committed state. The
tests constrain the implementation.

That the phase 1 test also caught it is worth noting: the serial-path guarantee
and the chunk-path guarantee are genuinely the same guarantee, which is the
outcome this task was meant to establish.

Verification: full suite.

### Task 5 — the bootstrap filter *(2026-07-31)*

**"Reuse the chunk helper from Task 3" was not possible.** Task 3's chunking is
`asyncio.gather` inside `run_coach_aggregator`; this filter lives in
`_gather_candidate_urls`, which is synchronous and already runs inside
`asyncio.to_thread` — there is no event loop here to await on. A
`ThreadPoolExecutor` is the right lever for blocking `requests` IO, and it is
the same width setting.

Two properties came free and one did not:

- `executor.map` yields in submission order, so the kept-order is stable
  without extra work — load-bearing, since the ingest loop walks that order and
  shuffling it would undo phase 1.
- An exception surfaces when its result is read, so the existing
  "rate-limited filter fails loudly" test stays green unmodified.
- **`cancel_futures=True` did not come free.** `map` submits every URL up
  front, so a plain `with` block would, on a rate limit raised at the first
  result, still wait for hundreds of queued requests to hammer an API that had
  already said stop. The executor is shut down explicitly in a `finally` with
  `wait=False, cancel_futures=True`.

The test deliberately does not patch `time.sleep`: `runner.time` *is* the `time`
module, so patching it — as the older gather tests do — would silence the test's
own injected delay and leave nothing to overlap. Passing no skills means the
search throttle never runs anyway.

It asserts `peak >= 2` rather than `== 3`, since overlap is the property under
test and an exact peak would turn thread start-up jitter into a false failure.

**A correction to my own record.** I first reported the plan's `-k
filter_concuren` selector as a typo that silently matched nothing. The doc is
correct; I mistyped the command. The underlying hazard is still real and worth
knowing — a `-k` matching nothing exits 0 and reads exactly like a pass — but it
was my error, not the plan's.

Verification: full suite, 632 passed, no skips.

### Post-merge — a regression this phase introduced *(2026-07-31)*

The first production run under concurrency lost two candidates to
`NotImplementedError: Cannot copy out of meta tensor; no data!`, both in the
**first chunk**, before the first progress line.

Cause: `embeddings._get_model` did unguarded lazy init. Callers reach it from
worker threads via `asyncio.to_thread`, so once ingest became concurrent several
threads saw `_model is None` at the same moment and all began constructing.
sentence-transformers initialises on a meta device and moves weights across;
the losers of that race get a meta tensor with no data.

**Serial ingest could not have exposed this**, which is why no test caught it —
and it would recur on the first chunk of every cold process. `embed_many` shares
the same path, so the retriever was exposed too.

Fixed with a double-checked lock in `_get_model`, and a test that runs four
concurrent callers against a deliberately slow fake constructor. It fails
`assert 4 == 1` without the lock — all four threads constructed their own model.
The inner re-check matters: without it, every thread queued at the lock would
construct in turn, which is the same bug taking longer.

This widened the plan's Blast Radius to `embeddings.py`, amended in `plan.md`
rather than worked around in the caller. The global belongs to that file, and a
regression introduced by this plan is this plan's to fix.

Cost: 2 of 755 candidates (0.26%). Cheap, but it recurs every run, and the
five *genuine* tagging failures in the same run are the ones the failure budget
was designed for — conflating the two would have mistuned it.
