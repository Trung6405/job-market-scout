# Phase 1: Completion and Ordering

> **Parent plan:** [plan.md](plan.md)
> **Status:** Complete — all five tasks landed; 624 tests passing
> **Depends on:** nothing

---

## Goal

An aggregation run survives a bad candidate and spends its time on the
candidates that matter first. Done when a malformed LLM response is logged and
skipped instead of ending the run, a systemic failure rate still aborts loudly,
and search-derived candidates are ingested ahead of awesome-list survivors.

## Safety Checklist

- **Touches user input, auth, secrets, or external calls?**
  Yes — the ingest loop calls GitHub and the LLM provider. This phase changes
  how their *failures* are handled, which is the point; rate-limit escalation
  is preserved explicitly and pinned by a test.
- **Contains a one-way door (schema, public API shape, new dependency)?**
  No. No schema change, no new dependency, no infrastructure.

---

## Tasks

### Task 1: Ingest search-derived candidates before bootstrap survivors

- **Files:** `scout/sub_agents/coach/runner.py`,
  `tests/test_coach_runner.py`
- **Gate:** none
- **Steps:**
  - [x] Write failing test: `_gather_candidate_urls` returns search-derived
        URLs before awesome-list URLs, with both stubbed, so a truncated
        ingest reaches gap-relevant candidates first
  - [x] Verify it fails (`python -m pytest tests/test_coach_runner.py -k ordering -q`)
  - [x] Implement: assemble the returned list search-first. Keep the bootstrap
        filter running before the skill loop — only the returned order changes,
        so the metadata calls still happen once per unique URL
  - [x] Verify it passes (`python -m pytest tests/test_coach_runner.py -q`)
  - [x] Commit: `fix(coach): ingest gap-matched candidates before bootstrap ones`

### Task 2: Isolate per-candidate failures

- **Files:** `scout/sub_agents/coach/runner.py`,
  `tests/test_coach_runner.py`
- **Gate:** none
- **Steps:**
  - [x] Write failing test: one candidate whose `tag_readme` raises
        `ValidationError` is skipped and counted, while the candidates after it
        are still inserted — asserting the run returns a summary rather than
        propagating
  - [x] Verify it fails (`python -m pytest tests/test_coach_runner.py -k isolat -q`)
  - [x] Implement: wrap the per-candidate body so any non-rate-limit exception
        is logged with the URL, counted as `failed`, and skipped
  - [x] Verify it passes (`python -m pytest tests/test_coach_runner.py -q`)
  - [x] Commit: `fix(coach): skip a candidate that fails to tag instead of ending the run`

### Task 3: Abort on a systemic failure rate

- **Files:** `scout/sub_agents/coach/runner.py`,
  `tests/test_coach_runner.py`
- **Gate:** none
- **Steps:**
  - [x] Write failing test: a run where every candidate raises aborts once
        failures exceed `max(10, 20% of processed)`, and the raised error names
        the failure count — plus a companion asserting that a small number of
        failures does *not* abort
  - [x] Verify it fails (`python -m pytest tests/test_coach_runner.py -k systemic -q`)
  - [x] Implement: track `failed` against the threshold inside the loop; raise
        a clear exception when crossed. Threshold as module constants beside
        the throttle constant
  - [x] Verify it passes (`python -m pytest tests/test_coach_runner.py -q`)
  - [x] Commit: `feat(coach): abort the run when candidate failures look systemic`

### Task 4: Keep rate limits fatal through the isolation layer

- **Files:** `scout/sub_agents/coach/runner.py`,
  `tests/test_coach_runner.py`
- **Gate:** none
- **Steps:**
  - [x] Write failing test: an `HTTPError` carrying a 403 with
        `X-RateLimit-Remaining: 0` propagates out of the ingest loop rather
        than being absorbed as one skipped candidate
  - [x] Verify it fails (`python -m pytest tests/test_coach_runner.py -k rate_limit -q`)
  - [x] Implement: re-raise rate-limit errors before the general handler.
        Mirrors `fetch_repo_metadata`'s existing treatment so both layers agree
  - [x] Verify it passes (`python -m pytest tests/test_coach_runner.py -q`)
  - [x] Commit: `fix(coach): let a rate limit end the run rather than skip one candidate`

### Task 5: Report failure counts in the run summary

- **Files:** `scout/sub_agents/coach/runner.py`,
  `scout/shared/schemas.py`, `tests/test_coach_runner.py`
- **Gate:** none
- **Steps:**
  - [x] Write failing test: `CoachSummary` carries a `failed` count and the
        completion log line reports inserted, duplicate, no-README and failed
  - [x] Verify it fails (`python -m pytest tests/test_coach_runner.py -k summary -q`)
  - [x] Implement: add the field with a default so existing constructions keep
        working; include all four counts in the summary log
  - [x] Verify it passes (`python -m pytest tests/ -q`)
  - [x] Commit: `feat(coach): report skipped and failed candidates in the run summary`

---

## Verification

- [x] All phase tests pass: `python -m pytest tests/test_coach_runner.py -v`
- [x] Full suite still passes: `python -m pytest -q` — 624 passed
- [ ] ~~The ten pre-existing runner tests pass unmodified~~ **Corrected during
      execution.** Nine pass unmodified;
      `test_gather_filters_bootstrap_candidates_through_the_quality_bar` pins
      the assembled order and had to flip, because that order is precisely what
      Task 1 changes. The claim holds as written for Tasks 2-5, where a run
      with no failures must behave exactly as before

## Observability

The completion line gains failure counts, so a degraded run is legible without
opening the code:

```
Aggregation complete in X min: N inserted, D duplicate(s), R without a README,
F failed, out of C seen.
```

A skipped candidate logs at WARNING with its URL and the exception type. The
systemic abort raises with the count in its message, so the workflow step's
failure names the reason.

## Rollback

Revert the phase's commits. Nothing persists that depends on this code: the
corpus is additive and idempotent per URL, so a reverted run resumes the old
behaviour against the same rows.

---

## Notes / Learnings

### Task 1 — ordering *(2026-07-31)*

The two pools are now accumulated in separate lists and the function returns
`searched + bootstrap`. Nothing about filtering or dedup moved: `seen` still
spans both pools, the quality bar still runs on the deduped harvest, and the
metadata calls still happen once per unique URL.

**The phase's "ten pre-existing tests pass unmodified" claim was wrong for this
task** and is corrected in Verification above.
`test_gather_filters_bootstrap_candidates_through_the_quality_bar` asserts the
assembled order, which is the one thing Task 1 exists to change. Its expectation
was flipped and a comment added saying it pins *which* links survive, not the
order — an assertion edited to match new behaviour is worth explaining, since
that edit is indistinguishable from papering over a regression.

**A limitation the ordering does not fix.** Because `seen` spans both pools, a
repo that is both harvested and searched stays in the bootstrap half — the
search loop skips it as already-seen. With the configured lists
(awesome-python/fastapi/react/typescript/docker) that overlap is real for
`docker`, `react` and `typescript`. It is not real for `terraform`, `snowflake`,
`eks` or `bedrock`, which is where the uncovered gaps actually are, so the
reordering delivers where it matters. Promoting a searched-and-harvested URL out
of the bootstrap half would be a further improvement; it is deliberately not
done here rather than added unplanned mid-task.

Verification: 11 passed in `tests/test_coach_runner.py`.

### Task 2 — per-candidate isolation *(2026-07-31)*

The per-candidate body is wrapped; anything it raises is logged at WARNING with
the URL and exception type, counted, and skipped. The test raises a genuine
`ValidationError` via `ResourceTags.model_validate({...})` rather than a stand-in
exception, so it exercises the actual failure the corpus hit.

`except Exception` is deliberate over `except BaseException`:
`asyncio.CancelledError` derives from `BaseException`, so a cancelled workflow
step still unwinds instead of being recorded as one skipped candidate per
remaining URL. That distinction matters here specifically — cancelled dispatches
are how the earlier diagnosis went wrong twice.

The assertion that carries the test is the candidate *after* the failure being
stored. "The failing one was skipped" is also true of a run that died on it.

Verification: 12 passed.

### Task 3 — systemic abort *(2026-07-31)*

`_MIN_FAILURES_BEFORE_ABORT = 10` and `_ABORT_FAILURE_RATE = 0.2`, beside the
throttle constant. Both halves earn their place: the floor stops a run aborting
on its first candidates, when one failure is 100% of what has been processed;
the rate is what catches a systemic fault in a long run. With everything
failing, the 11th failure trips it.

Raised from inside the `except` handler and chained with `from exc`, so the
traceback carries the last failure as its cause. The abort says *how many*, the
chain says *what they looked like* — a bare count would leave the operator
guessing whether it was the token, the provider or the prompt.

The abort message names the inserted count too. An aborted run is not
necessarily an empty one, and the difference decides whether anything needs
re-running.

Threshold honesty: it is tuned against exactly one observation (one malformed
response in ~920), which is why the failed count goes into the run summary in
Task 5. The next few runs are what will actually characterise it.

Verification: 14 passed.

### Task 4 — rate limits stay fatal *(2026-07-31)*

`_is_rate_limited` is checked before the failure counter moves, so a rate limit
neither counts as a failed candidate nor feeds the systemic threshold. It is
deliberately narrow — 403 **and** `X-RateLimit-Remaining: 0` — because a plain
403 is a private, blocked or DMCA'd repo, which is one bad candidate.

The plan specified one test; two were written. A predicate as broad as "any
`HTTPError` is fatal" passes the escalation test while silently undoing Task 2's
isolation, so `test_run_coach_aggregator_still_skips_a_plain_403` is the one
that actually constrains the implementation.

**Duplication, flagged rather than fixed.** This mirrors the check inside
`fetch_repo_metadata`. A shared predicate would be better, but `github_search.py`
is outside this plan's Blast Radius, so it is left for the human to approve as
follow-up rather than taken unilaterally.

**An unrelated hazard observed.** One run reported "15 passed, 1 skipped" where
the re-run gave 16 passed. The cause is `tests/conftest.py:97`, where the
`db_pool` fixture calls `pytest.skip` when Postgres is briefly unreachable — so
a transient blip silently removes a test from a run that still reports green.
Pre-existing and out of scope here, but worth its own fix: a skip on
infrastructure failure is indistinguishable from a test that was never written.

Verification: 16 passed.

### Task 5 — the run summary *(2026-07-31)*

`CoachSummary.failed`, defaulted to 0 so existing constructions keep working,
and all four counts in the completion line. The mid-run progress line gained
`failed` too — the completion line is no use for a run that is still going, and
a run whose failures are climbing is exactly the one worth interrupting.

The wording changed from `%d candidate(s) without a README` to
`%d without a README`, matching the format this doc's Observability section
already specified.

`scout/coach_aggregator.py` also logs a summary line and still reports only
seen/inserted/duplicates. It is outside this plan's Blast Radius and the
runner's line is logged at INFO through the same handler, so both appear in the
workflow log — the count is not hidden. Adding it there is a one-line follow-up
for the human to approve.

Verification: full suite, 624 passed.
