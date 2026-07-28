# Phase 2: Link Checker

> **Parent plan:** [plan.md](plan.md)
> **Status:** Complete
> **Depends on:** Phase 1 complete (uses the timeout setting)

---

## Goal

A single function that takes a URL and returns one of three verdicts — healthy,
permanently gone, or a transient failure — plus a short reason. Done when every
status class and network exception maps to the verdict the spec's table
prescribes, and no caller of it exists yet.

## Safety Checklist

- **Touches user input, auth, secrets, or external calls?**
  Yes — this is the phase that makes outbound HTTP requests to third-party
  URLs. Every request carries an explicit timeout; every network exception is
  caught and converted to a transient verdict rather than propagating; no
  credentials are sent, and redirects are followed so the final response
  decides. Response bodies are never parsed, so nothing untrusted is
  interpreted.
- **Contains a one-way door (schema, public API shape, new dependency)?**
  No. `requests` is already a dependency and is what the aggregator uses.

---

## Tasks

### Task 1: Verdict classification

- **Files:** `scout/sub_agents/coach/link_health.py`,
  `tests/test_coach_link_health.py`
- **Gate:** none
- **Steps:**
  - [x] Write failing test: `classify_status` maps 200/204/302-resolved-to-200
        to `healthy`; 404 and 410 to `gone`; 401, 403, 405, 429, 500, 502, 503
        to `transient`; and any other unexpected code to `transient` (unknown
        is not evidence of removal)
  - [x] Verify it fails (`pytest tests/test_coach_link_health.py -q`)
  - [x] Implement `classify_status(status_code) -> LinkVerdict`, with the
        verdict type and a comment recording *why* 403 is transient: hosts
        return it for anti-bot and rate-limit reasons far more often than for
        genuine removal, and only repeated failures should cost a resource
  - [x] Verify it passes (`pytest tests/test_coach_link_health.py -q`)
  - [x] Commit: `feat(coach): classify link-check status codes`

### Task 2: Checking a URL, with a `GET` fallback

- **Files:** `scout/sub_agents/coach/link_health.py`,
  `tests/test_coach_link_health.py`
- **Gate:** none
- **Steps:**
  - [x] Write failing test, with `requests` stubbed: a successful `HEAD`
        returns `healthy` and issues no second request; a `HEAD` that returns
        405 followed by a `GET` that returns 200 is `healthy`; a `HEAD` 404
        confirmed by a `GET` 404 is `gone`; the configured timeout is passed to
        every request and redirects are followed
  - [x] Verify it fails (`pytest tests/test_coach_link_health.py -q`)
  - [x] Implement `check_url(url, settings) -> LinkCheck` — `HEAD` first, and
        on any non-healthy result re-check with a streamed `GET` whose body is
        never read, since a bodyless method is the cheap path but not the
        authoritative one. The `GET`'s verdict wins
  - [x] Verify it passes (`pytest tests/test_coach_link_health.py -q`)
  - [x] Commit: `feat(coach): check a resource URL with a GET fallback`

### Task 3: Network failures never escape

- **Files:** `scout/sub_agents/coach/link_health.py`,
  `tests/test_coach_link_health.py`
- **Gate:** none
- **Steps:**
  - [x] Write failing test: a `requests.Timeout`, `ConnectionError`, and
        `TooManyRedirects` each produce a `transient` verdict carrying a short
        reason string rather than raising; the reason is bounded in length so
        it cannot bloat the stored column
  - [x] Verify it fails (`pytest tests/test_coach_link_health.py -q`)
  - [x] Implement: catch `requests.RequestException` around both requests,
        returning `transient` with a truncated `type: message` reason
  - [x] Verify it passes (`pytest tests/test_coach_link_health.py -q`)
  - [x] Commit: `fix(coach): treat link-check network errors as transient`

---

## Verification

- [x] All phase tests pass: `pytest tests/test_coach_link_health.py -q`
- [x] No test performs a real network request (stubs only) — confirm the suite
      still passes with networking unavailable
- [x] **Manual, against the real internet:** call `check_url` from a shell on
      three URLs — a known-live repo from the corpus, a deliberately
      nonexistent `github.com/<owner>/<repo>` path, and one non-GitHub URL —
      and confirm the verdicts are `healthy`, `gone`, `healthy`. This is the
      one thing stubs cannot prove, and it is what catches `HEAD` being
      answered differently from `GET` in the wild.

## Observability

`check_url` logs nothing on the healthy path; the runner in Phase 5 owns the
per-run summary. A non-healthy verdict carries its reason string outward so it
lands in `last_check_error` and is answerable from the database later.

## Rollback

Revert the three commits. Nothing calls this module until Phase 5, so removing
it cannot affect the pipeline or retrieval.

---

## Notes / Learnings

Manual real-internet check confirmed the predicted verdicts exactly:
`github.com/pallets/flask` → healthy, a nonexistent `github.com/<owner>/<repo>`
path → gone (`HTTP 404`), `python.org` (non-GitHub) → healthy. No `HEAD`/`GET`
divergence observed against either host.
