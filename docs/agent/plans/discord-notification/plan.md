# Plan: Discord Bot Briefing Notification

> **Status:** Complete (code + tests; live manual post pending human)
> **Created:** 2026-07-23 · **Last updated:** 2026-07-23
> **Spec:** [spec.md](../../specs/discord-notification/spec.md)

---

## Overview

Replace the Gmail/SMTP briefing notification with a Discord bot that posts
one rich embed to a channel via Discord's REST API. Match selection and
prose summarization are untouched; only the message-building, sending, and
configuration layers change. "Done" means a pipeline run posts the daily
briefing to Discord (or the "no matches" embed), with no Gmail config
anywhere in the codebase.

## Acceptance Criteria

- [ ] A run with strong matches posts a single embed listing each match
      (title, company, score, listing link, takeaway) to the configured
      Discord channel.
- [ ] A run with no strong matches posts a "no strong matches today" embed.
- [ ] The send authenticates as a bot (`Authorization: Bot <token>`) and
      targets `POST /channels/{channel_id}/messages`.
- [ ] The briefing step is skipped (run does not fail) when Discord is not
      configured; it runs when both token and channel id are set.
- [ ] No `gmail_*` settings, SMTP code, or email-builder module remain.

---

## Risks & Unknowns

| Risk / unknown | Impact if wrong | Resolution |
|----------------|-----------------|------------|
| Exact Discord embed JSON shape / field-length limits (title ≤256, field name ≤256, value ≤1024, ≤25 fields, embed ≤6000) | Discord rejects the message with 400 | Encoded as constants + clamping in the builder; asserted in unit tests. Accepted from documented Discord limits — no live spike needed for a well-under-limit payload (default 5 matches). |
| `httpx` async client usage is new to `scout/` code | Send fails or blocks the event loop | Use `httpx.AsyncClient` in an `async with`; sender is unit-tested with a mocked transport. `httpx` already declared in `requirements.txt`. |
| Other code may depend on `run_briefing`/`build_email` returning an `EmailMessage` | Type break at call sites | Blast-radius grep before Phase 2; only `agent.py` consumes it (return value currently unused). Return type becomes the payload dict. |

## Blast Radius

- **Code that will change:** `scout/config.py`, `scout/.env.example`,
  `scout/sub_agents/briefing/` (`notification.py`, `briefing.py`, new
  `embed_builder.py`, delete `email_builder.py`), `scout/agent.py`, and
  the corresponding tests under `tests/`.
- **Existing behaviour that could break:** the pipeline's briefing/send
  step and its config gate; any test asserting Gmail config or email
  structure.
- **Off-limits:** Do not modify scraper/scorer/advisor logic, DB layer, or
  the match-selection/summarization steps of the briefing beyond import
  wiring. Flag before touching anything outside the directories above.

---

## Phases

| # | Phase | Document | Status |
|---|-------|----------|--------|
| 1 | Config + embed builder | [phase-1-config-and-embed.md](phase-1-config-and-embed.md) | Complete |
| 2 | Discord sender + wiring | [phase-2-sender-and-wiring.md](phase-2-sender-and-wiring.md) | Complete |

> All phases are planned in advance — every row above has a written,
> human-approved phase doc before phase 1 execution starts. If executing
> an earlier phase surfaces a needed change to a later phase doc, update
> that doc explicitly and record the change in its Notes / Learnings
> section; don't leave later phases undocumented.

---

## Testing Strategy

- **Unit:** per-task TDD covers the embed builder (match list, no-match
  case, takeaway fallback, field clamping) and the Discord sender (POST
  URL, `Bot` auth header, payload body, raise-on-error, `ensure_*` guard).
- **Integration:** the briefing entrypoint test drives
  `run_briefing` end-to-end with the sender mocked, asserting the built
  payload is what gets sent; the agent test asserts the Discord config
  gate.
- **Manual:** one live run against a real bot token + test channel to
  confirm the embed renders and links work (recorded in Phase 2
  verification, run by the human).

## Rollout & Reversibility *(config change only)*

- **Feature flag:** no — presence of `DISCORD_BOT_TOKEN` +
  `DISCORD_CHANNEL_ID` gates the send, mirroring the old Gmail gate.
- **Migrations:** none (no schema or stored data touched).
- **Rollback plan:** revert the branch; the removed Gmail path is restored
  from git history. No data to unwind.

---

## Key Decisions & Constraints

- Bot token + REST API (not webhook, not gateway) — user wants a named bot
  with room to grow toward interactivity.
- Email is removed outright; no dual-channel dispatch.
- Single rich embed, one field per match; report link dropped.
- `run_briefing` / builder return the Discord payload `dict`, replacing the
  `EmailMessage` return.
- No one-way doors: no schema, no public API, no new dependency.

## Out of Scope

- Gateway/interactive bot, slash commands, reactions, message editing.
- Retry / rate-limit backoff beyond raising on a non-success response.
- Per-match embeds or attachments.

---

## Definition of Done

- [x] All acceptance criteria met (code + automated tests)
- [x] All phase verification steps pass (bar the pre-existing
      Postgres-dependent `test_main_entrypoint` failure)
- [ ] Feature verified manually in a running environment (live Discord
      post) — pending human with a real bot token + channel
- [x] Docs / README + `.env.example` updated where behaviour changed
- [x] No new lint or type-check warnings

## Update Rules

- Phase docs hold task-level detail; this file holds phase-level status only.
- When a phase's scope changes, update its row here **in the same commit**.
- On conflict, this file wins for *what* the phases are; the phase doc
  wins for *how* its tasks are done.
