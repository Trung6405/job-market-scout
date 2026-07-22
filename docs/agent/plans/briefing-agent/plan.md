# Plan: Briefing Agent

> **Status:** Complete — all 3 phases implemented, unit-tested, and manually verified with a real send
> **Created:** 2026-07-19 · **Last updated:** 2026-07-19
> **Spec:** [spec.md](../../specs/briefing-agent/spec.md)

---

## Overview

Build the fourth and final pipeline stage: given `list[Listing]` and the Scorer's `list[ListingScore]`, join them, deterministically select the day's top matches, have an `LlmAgent` write summary prose for those matches only, deterministically merge that prose with real listing fields into an HTML+text email, and send it via Gmail SMTP. "Done" means `run_briefing(listings, scores)` is callable in isolation (mirroring `track_listings` / `build_scorer_agent`), sends a real email end-to-end against a live DeepSeek key and Gmail app password, and every factual field in that email traces to deterministic code, never LLM output.

## Acceptance Criteria

- [x] Given a `list[Listing]` and matching `list[ListingScore]`, `run_briefing` sends one email with the day's top matches (title, company, link, score) and LLM-written prose, using only real listing data for factual fields. (Verified by unit tests with the LLM/SMTP seams mocked; live end-to-end send is the outstanding Manual Verification step.)
- [x] A day with no listing meeting `min_match_score` still sends a short "no strong matches today" email — no LLM call, no silence.
- [x] `run_briefing` is directly callable and testable in isolation, consistent with the Scraper/Scorer/Tracker pattern.
- [x] No listing field the LLM did not see (title, company, URL) can appear altered in the sent email — those fields are inserted by deterministic code.
- [x] Missing Gmail config or an SMTP send/auth failure raises immediately — no silent fallback, no retry.

---

## Risks & Unknowns

| Risk / unknown | Impact if wrong | Resolution |
|----------------|-----------------|------------|
| The LLM's JSON-object output shape (`{intro, takeaways}`) has no `output_schema` enforcement — wrapping it in a `BaseModel` for `output_schema` is known to make DeepSeek 400 on strict `json_schema` mode (`docs/agent/plans/scorer-agent/plan.md`, 2026-07-16 update), so enforcement is prompt-only, same as the Scorer's bare-list case. | Prose parsing fails or is incomplete for some listings. | Accepted risk. Mitigated by the spec's Should-have fallback line for any listing the LLM's output doesn't cover (Phase 2), and a hard raise only when the response isn't parseable JSON at all (no retry, consistent with Scraper/Scorer precedent). |
| Gmail SMTP send can't be exercised by automated tests without a live app password and real network access. | Auth/multipart-formatting bugs only surface manually. | Phase 3 unit tests monkeypatch `smtplib.SMTP_SSL` to verify wiring (login call, message shape); a Manual Verification section (mirroring the Scorer plan's pattern) covers the real send once, after Phase 3, with a live `GMAIL_APP_PASSWORD`. |
| `run_briefing` mixes an awaited LLM call (`Runner.run_async`) with a synchronous `smtplib` send inside one async function — the SMTP call briefly blocks the event loop. | A multi-second SMTP send blocks whatever else shares the loop. | Accepted risk — this is a single-user daily-batch tool with no concurrent event-loop usage today. Revisit only if `run_briefing` is ever called from something running concurrent async work. |

## Blast Radius

- **Code that will change:** `scout/config.py` (new fields only), `scout/shared/schemas.py` (new models only), `scout/prompts.py` (new function only), `scout/sub_agents/briefing/` (`agent.py` and `tools.py` go from empty stubs to real content; new `select.py`, `summarize.py`, `email_builder.py`, `notification.py`, `briefing.py`), `scout/.env.example` (append only), `tests/` (new/appended test files).
- **Existing behaviour that could break:** none intended — all `Settings`/`schemas.py` changes are additive fields/classes; no existing field, function, or test is modified.
- **Off-limits:** `scout/sub_agents/scraper/**`, `scout/sub_agents/scorer/**`, `scout/tools/tracker.py`, `scout/shared/db.py`, root `scout/agent.py` pipeline wiring — all out of scope per the spec's Won't-have list. Flag before touching any of these.

---

## Phases

| # | Phase | Document | Status |
|---|-------|----------|--------|
| 1 | Selection & config | [phase-1-selection-and-config.md](phase-1-selection-and-config.md) | Complete |
| 2 | Summarize & build | [phase-2-summarize-and-build.md](phase-2-summarize-and-build.md) | Complete |
| 3 | Send & entry point | [phase-3-send-and-entrypoint.md](phase-3-send-and-entrypoint.md) | Complete |

> All phases are planned in advance — every row above has a written,
> human-approved phase doc before phase 1 execution starts. If executing
> an earlier phase surfaces a needed change to a later phase doc, update
> that doc explicitly and record the change in its Notes / Learnings
> section; don't leave later phases undocumented.

---

## Testing Strategy

- **Unit:** `select_top_matches` thresholding/sorting/capping (Phase 1); `build_briefing_instruction`'s field projection (Phase 2); `parse_briefing_prose` happy/malformed/partial-coverage cases (Phase 2); `build_email`'s factual-field fidelity, fallback-line substitution, and zero-matches template (Phase 2); `notification.send_email`'s fail-fast and SMTP wiring via a monkeypatched `smtplib.SMTP_SSL` (Phase 3); `run_briefing`'s orchestration wiring with `summarize_matches`/`build_email`/`send_email` monkeypatched (Phase 3).
- **Integration:** none automated — no component in this codebase currently drives a live ADK `Runner` or a live SMTP connection in a test; the Manual Verification step after Phase 3 is the integration check.
- **Manual:** after Phase 3, call `run_briefing` with real `Listing`/`ListingScore` fixtures, a live `DEEPSEEK_API_KEY`, and a live `GMAIL_APP_PASSWORD`; confirm the received email's facts (title/company/link/score) match the fixtures exactly and the prose reads sensibly. Repeat with an empty match list to confirm the zero-matches template sends without an LLM call.

---

## Key Decisions & Constraints

- **`output_schema=None` on the briefing `LlmAgent`.** The prose shape is a single object (`intro` + per-listing `takeaways`), not a bare list like the Scorer's `list[ListingScore]`. Setting `output_schema` to a `BaseModel` for this shape would hit the same DeepSeek 400 the Scorer plan found and reverted (`docs/agent/plans/scorer-agent/plan.md`). Instead the prompt asks for a JSON object directly, and `parse_briefing_prose` (Phase 2) does `json.loads` + `BriefingProse.model_validate` by hand.
- **Gmail fail-fast lives in `notification.send_email`, not `Settings.__post_init__`.** Every other stage constructs `Settings()` freely in its tests today (Scraper/Scorer/Tracker), and `__post_init__` already raises for a missing resume file — adding a blanket raise for missing Gmail credentials there would make `gmail_address`/`gmail_app_password` mandatory to construct `Settings()` anywhere in the codebase, breaking unrelated existing tests. `send_email` raises `ValueError` before attempting any SMTP call if either is blank, which satisfies "fail-fast, no silent fallback" from the caller's perspective (`run_briefing`) without that blast radius.
- **`run_briefing` is `async`**, driven by `Runner.run_async` being inherently async (same reasoning the Tracker plan used for `track_listings`, driven there by `asyncpg`). The synchronous `smtplib` send stays a plain call inside the async function rather than being wrapped — see the accepted risk above.
- **`summarize_matches` is skipped entirely when `select_top_matches` returns `[]`.** No `LlmAgent` is built, no `Runner` invocation happens — `build_email` goes straight to the zero-matches template, exactly as the spec's Proposed Approach states.
- ⚠️ **No one-way doors.** No schema, migration, or public API is introduced by this plan; all `Settings`/`schemas.py` changes are additive.

## Out of Scope

- Root `scout/agent.py` `SequentialAgent` wiring across all four stages (spec Won't-have).
- Score persistence / a `matches` table (spec Won't-have, PRD Decision D4).
- Gmail API / OAuth-based sending (spec Won't-have — SMTP + app password only).
- Retry/backoff for the LLM call or SMTP send (spec Won't-have — YAGNI).

---

## Definition of Done

- [x] All acceptance criteria met
- [x] All phase verification steps pass (77 passed, 12 skipped — pre-existing DB tests needing a live Postgres, unaffected by this work)
- [x] Feature verified manually in a running environment (Manual Verification, Phase 3) — done 2026-07-19, real email sent against live DeepSeek + Gmail
- [ ] Docs / README updated where behaviour changed — not yet done; no README/docs beyond spec+plan reference Briefing today
- [ ] No new lint or type-check warnings — not verified; this project has no lint/type-check tooling configured

## Update Rules

- Phase docs hold task-level detail; this file holds phase-level status only.
- When a phase's scope changes, update its row here **in the same commit**.
- On conflict, this file wins for *what* the phases are; the phase doc
  wins for *how* its tasks are done.
