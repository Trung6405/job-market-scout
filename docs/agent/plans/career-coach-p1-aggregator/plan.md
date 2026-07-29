# Plan: Career Coach P1 — Resource Aggregator

> **Status:** Complete — merged as #28 (2026-07-27)
> **Created:** 2026-07-25 · **Last updated:** 2026-07-29
> **Spec:** [spec.md](../../specs/career-coach-p1-aggregator/spec.md)

---

## Overview

Build the aggregator that populates the (currently empty) `resources` table:
a new `scout/sub_agents/coach/` package that searches GitHub per skill gap
and harvests "awesome-X" meta-lists, dedupes against stored URLs, tags each
new candidate's README with DeepSeek, embeds the summary locally, and writes
the row. "Done" means a real skill gap (e.g. `"kubernetes"`) resolves to at
least one stored `resources` row with a reachable GitHub URL, a summary, and
a 384-dim embedding; a second run of the aggregator inserts nothing new for
the same input; and the whole thing runs weekly over the existing nightly
SSH session with no new VM wake/deallocate cycle.

## Acceptance Criteria

- [ ] `insert_resource` writes a new row for a novel URL and returns
  `"duplicate"` (no LLM/embedding call, no write) for a URL already in
  `resources`.
- [ ] `run_coach_aggregator` produces at least one `resources` row whose
  `skills[]` includes a skill returned by `get_distinct_gap_skills` when
  GitHub search is mocked to return a matching repo.
- [ ] Running `run_coach_aggregator` twice against the same mocked candidate
  set inserts the row once (second run: 0 inserted, all reported duplicate).
- [ ] `python -m scout.coach_aggregator` runs standalone (mirrors
  `scout/main.py`'s shape) and the CI workflow only ever invokes it as an
  extra step inside the already-open nightly SSH session — no new
  `.github/workflows/*.yml` file, no new `az vm start`/`deallocate` call.

---

## Risks & Unknowns

| Risk / unknown | Impact if wrong | Resolution |
|----------------|-----------------|------------|
| GitHub Search API has a stricter authenticated rate limit (30 req/min) than core REST (5000/hr); one aggregator pass issues one search call per gap skill plus one README fetch per surviving candidate | A week with many new gap skills could hit 403/`rate limit exceeded` mid-run | Accepted risk for P1 — `requests.raise_for_status()` surfaces the failure, the step is `continue-on-error: true` in the workflow (below) so it can't block the dashboard deploy, and the next week's run resumes from wherever dedup left off (no partial-row corruption, since insert is per-candidate). Revisit with backoff/pagination limits if it materializes. |
| GitHub Search API responses don't expose "has a README" directly | Filtering on README presence can't happen at search time | Resolved by design, not deferred: README existence is checked once per surviving candidate via `fetch_readme` (404 → candidate dropped) at the point tagging needs the README text anyway — one fetch serves both the filter and the tagging input, no separate existence check. |
| Awesome-list README link extraction is a regex over markdown, not a markdown parser | Some awesome-lists' link formatting could yield 0 or few extracted links | Accepted risk — bootstrap coverage is explicitly the "seed initial coverage" mechanism (spec), not the only source; per-skill GitHub search is the ongoing driver. A list that under-extracts just means slower bootstrap coverage for that domain, not a correctness bug. |
| `GITHUB_PAT` must reach the VM's runtime environment (the SSH-invoked `docker compose run` reads `.env` on the VM, the same way `DEEPSEEK_API_KEY`/`DISCORD_BOT_TOKEN` already do) — this repo's CI has no mechanism to inject it there | Aggregator step fails every week with an auth error until someone adds it | **One-way-door-adjacent, not code:** flagged here as a required manual deploy step (add `GITHUB_PAT=...` to the VM's `.env`) before Phase 3's workflow step can succeed in prod. `github_pat` defaults to `""` like `discord_bot_token`, so local dev/tests are unaffected either way. |
| Default awesome-list URLs (umbrella Q1, spec's one open question) | A wrong/dead URL just means one bootstrap source under-contributes | Verified each of the six default URLs actually exists (web search, 2026-07-25) before hardcoding them in Phase 1's config default. Non-blocking per the spec — refinable later via `COACH_AWESOME_LISTS` env var, no code change. |

## Blast Radius

- **Code that will change:** `scout/shared/schemas.py`, `scout/shared/db.py`,
  `scout/config.py`, `scout/prompts.py` (new prompt builder only), a new
  `scout/sub_agents/coach/` package, a new `scout/coach_aggregator.py`,
  `requirements.txt`, `.github/workflows/scheduled-run.yml`, new files under
  `tests/`.
- **Existing behaviour that could break:** none of the touched shared files
  have their existing functions modified — every change to
  `schemas.py`/`db.py`/`config.py`/`prompts.py` is a pure addition. The one
  behavioral risk is the new workflow step: if it could fail the job, it
  would also skip "Deploy dashboard" and leave the VM allocated. Mitigated
  by placement (after dashboard deploy, before deallocate — see Phase 3) and
  `continue-on-error: true`.
- **Off-limits:** no changes to the `resources` table DDL (P0 already
  shipped the correct shape), no retriever/query code (P2), no Advisor
  grounded-tip code (P3). Do not touch anything outside the files above
  without flagging it.

---

## Phases

| # | Phase | Document | Status |
|---|-------|----------|--------|
| 1 | Shared data layer | [phase-1-shared-data-layer.md](phase-1-shared-data-layer.md) | Not started |
| 2 | Candidate gathering & tagging | [phase-2-candidate-gathering-and-tagging.md](phase-2-candidate-gathering-and-tagging.md) | Not started |
| 3 | Runner, entrypoint & CI wiring | [phase-3-runner-entrypoint-and-ci.md](phase-3-runner-entrypoint-and-ci.md) | Not started |

> All phases are planned in advance — every row above has a written,
> human-approved phase doc before phase 1 execution starts. If executing an
> earlier phase surfaces a needed change to a later phase doc, update that
> doc explicitly and record the change in its Notes / Learnings section.

---

## Testing Strategy

- **Unit:** Phase 1's `Resource`/`ResourceTags` models and `db.py` helpers
  get direct tests (`db_pool` fixture, mirroring `tests/test_resources_schema.py`).
  Phase 2's `github_search.py`/`bootstrap.py`/`tagging.py`/`embeddings.py`
  are tested with `requests`/`complete_json`/`SentenceTransformer` mocked
  via `monkeypatch`, mirroring `tests/test_briefing_notification.py`'s
  `_FakeAsyncClient` pattern.
- **Integration:** Phase 3's `run_coach_aggregator` is tested end-to-end
  against the real `db_pool` fixture with every external call
  (GitHub, LLM, embedding model) mocked, verifying the full
  dedupe → tag → embed → insert path and the "second run inserts nothing
  new" idempotency property from the spec's Success Criteria.
- **Manual:** run `python -m scout.coach_aggregator` locally against the dev
  DB with a real `GITHUB_PAT` (and `DEEPSEEK_API_KEY`) once, before touching
  the CI workflow, and confirm at least one real `resources` row lands with
  a reachable URL, a non-empty summary, and a 384-dim embedding (spec's
  Success Criteria, checked for real rather than only via mocks).

## Rollout & Reversibility

- **Feature flag:** no dedicated flag. `github_pat` defaults to `""`
  (mirrors `discord_bot_token`); `run_coach_aggregator` should no-op with a
  clear log line if it's unset, so an unconfigured environment (any local
  dev machine, or prod before the manual `.env` step above) never crashes.
- **Migrations:** none — `resources` (P0) is unchanged DDL. All writes are
  `INSERT ... ON CONFLICT (url) DO NOTHING`, fully additive.
- **Rollback plan:** revert the touched files listed under Blast Radius.
  Inserted rows are harmless to leave in place; if a full rollback of data
  is ever wanted, `DELETE FROM resources WHERE source = 'github'` removes
  everything this aggregator wrote (nothing else writes `resources` yet).

---

## Key Decisions & Constraints

- Async DB/LLM calls (`asyncpg`, `complete_json`) mix with synchronous
  GitHub HTTP calls (`requests`, per the spec's own alternatives analysis)
  and synchronous embedding inference (`sentence-transformers`) inside one
  `async def run_coach_aggregator`. This blocks the event loop during those
  calls, which is acceptable here: the aggregator is a standalone weekly
  batch entrypoint with no concurrent coroutines to starve, unlike the main
  pipeline's `asyncio.gather` fan-outs.
- Dedup happens *before* any LLM/embedding spend, per the spec: candidate
  URLs are diffed against a `get_resource_urls(conn) -> set[str]` snapshot
  taken once at the start of the run, not re-checked per-URL against the DB
  (cheaper, and matches "skipped entirely" from the spec's requirements —
  no per-candidate round trip).
- "Has a README" is enforced by trying to fetch it (see Risks table), not by
  a separate existence probe — one fewer GitHub API call per candidate.
- The new CI step is placed after "Deploy dashboard to Storage static
  website" and before "Deallocate VM" (not immediately after "Run scout
  cycle" as the spec's Proposed Approach loosely suggested) so a coach
  failure can never delay or mask the dashboard deploy that users actually
  see daily. `continue-on-error: true` on the new step reinforces this.
- ⚠️ **One-way doors:** adding `sentence-transformers` (pulls in `torch`) to
  `requirements.txt` is a real image-size/cold-start cost — already
  pre-accepted by the umbrella PRS (D-CC-4), not re-litigated here, but
  flagged since it's irreversible-in-spirit (hard to "un-adopt" a corpus
  built on MiniLM embeddings without re-embedding everything). No other
  one-way door in this plan.

## Out of Scope

- The retriever (P2) — nothing here queries `resources` for similarity.
- The Advisor grounded-tip stage or URL validator (P3).
- Non-`repo` resource types (`doc`/`course`/`note`).
- Link-health re-verification of already-stored resources (P5).
- A dedicated GitHub client library (`requests` only, per spec).

---

## Definition of Done

- [ ] All acceptance criteria met.
- [ ] All phase verification steps pass.
- [ ] Feature verified manually against the dev DB with a real `GITHUB_PAT`
  (see Testing Strategy → Manual).
- [ ] `GITHUB_PAT` added to the VM's `.env` (manual deploy step, tracked in
  Phase 3 — flagged again there as a pre-merge-to-prod gate, not a code task).
- [ ] No new lint or type-check warnings.

## Update Rules

- Phase docs hold task-level detail; this file holds phase-level status only.
- When a phase's scope changes, update its row here **in the same commit**.
- On conflict, this file wins for *what* the phases are; the phase doc wins
  for *how* its tasks are done.
