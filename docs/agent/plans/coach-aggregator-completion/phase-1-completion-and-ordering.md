# Phase 1: Completion and Ordering

> **Parent plan:** [plan.md](plan.md)
> **Status:** Not started
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
  - [ ] Write failing test: `_gather_candidate_urls` returns search-derived
        URLs before awesome-list URLs, with both stubbed, so a truncated
        ingest reaches gap-relevant candidates first
  - [ ] Verify it fails (`python -m pytest tests/test_coach_runner.py -k ordering -q`)
  - [ ] Implement: assemble the returned list search-first. Keep the bootstrap
        filter running before the skill loop — only the returned order changes,
        so the metadata calls still happen once per unique URL
  - [ ] Verify it passes (`python -m pytest tests/test_coach_runner.py -q`)
  - [ ] Commit: `fix(coach): ingest gap-matched candidates before bootstrap ones`

### Task 2: Isolate per-candidate failures

- **Files:** `scout/sub_agents/coach/runner.py`,
  `tests/test_coach_runner.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing test: one candidate whose `tag_readme` raises
        `ValidationError` is skipped and counted, while the candidates after it
        are still inserted — asserting the run returns a summary rather than
        propagating
  - [ ] Verify it fails (`python -m pytest tests/test_coach_runner.py -k isolat -q`)
  - [ ] Implement: wrap the per-candidate body so any non-rate-limit exception
        is logged with the URL, counted as `failed`, and skipped
  - [ ] Verify it passes (`python -m pytest tests/test_coach_runner.py -q`)
  - [ ] Commit: `fix(coach): skip a candidate that fails to tag instead of ending the run`

### Task 3: Abort on a systemic failure rate

- **Files:** `scout/sub_agents/coach/runner.py`,
  `tests/test_coach_runner.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing test: a run where every candidate raises aborts once
        failures exceed `max(10, 20% of processed)`, and the raised error names
        the failure count — plus a companion asserting that a small number of
        failures does *not* abort
  - [ ] Verify it fails (`python -m pytest tests/test_coach_runner.py -k systemic -q`)
  - [ ] Implement: track `failed` against the threshold inside the loop; raise
        a clear exception when crossed. Threshold as module constants beside
        the throttle constant
  - [ ] Verify it passes (`python -m pytest tests/test_coach_runner.py -q`)
  - [ ] Commit: `feat(coach): abort the run when candidate failures look systemic`

### Task 4: Keep rate limits fatal through the isolation layer

- **Files:** `scout/sub_agents/coach/runner.py`,
  `tests/test_coach_runner.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing test: an `HTTPError` carrying a 403 with
        `X-RateLimit-Remaining: 0` propagates out of the ingest loop rather
        than being absorbed as one skipped candidate
  - [ ] Verify it fails (`python -m pytest tests/test_coach_runner.py -k rate_limit -q`)
  - [ ] Implement: re-raise rate-limit errors before the general handler.
        Mirrors `fetch_repo_metadata`'s existing treatment so both layers agree
  - [ ] Verify it passes (`python -m pytest tests/test_coach_runner.py -q`)
  - [ ] Commit: `fix(coach): let a rate limit end the run rather than skip one candidate`

### Task 5: Report failure counts in the run summary

- **Files:** `scout/sub_agents/coach/runner.py`,
  `scout/shared/schemas.py`, `tests/test_coach_runner.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing test: `CoachSummary` carries a `failed` count and the
        completion log line reports inserted, duplicate, no-README and failed
  - [ ] Verify it fails (`python -m pytest tests/test_coach_runner.py -k summary -q`)
  - [ ] Implement: add the field with a default so existing constructions keep
        working; include all four counts in the summary log
  - [ ] Verify it passes (`python -m pytest tests/ -q`)
  - [ ] Commit: `feat(coach): report skipped and failed candidates in the run summary`

---

## Verification

- [ ] All phase tests pass: `python -m pytest tests/test_coach_runner.py -v`
- [ ] Full suite still passes: `python -m pytest -q`
- [ ] The ten pre-existing runner tests pass unmodified — a run with no
      failures must behave exactly as before

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

<Filled in during execution.>
