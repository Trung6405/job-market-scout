# Phase 2: Discord Sender + Wiring

> **Parent plan:** [plan.md](plan.md)
> **Status:** Not started
> **Depends on:** Phase 1 complete (embed builder + Discord config exist)

---

## Goal

Rewrite the notification module to POST the embed payload to Discord's REST
API as a bot, wire the briefing orchestrator and pipeline agent to the new
builder/sender and Discord config gate, and update the docs. After this
phase a pipeline run posts the briefing to Discord.

## Safety Checklist

- **Touches user input, auth, secrets, or external calls?**
  Yes — makes the outbound HTTPS call to Discord with the bot token in the
  `Authorization` header. The sender raises on non-success; the token is
  never logged. Send only happens when both token and channel id are set.
- **Contains a one-way door (schema, public API shape, new dependency)?**
  No — `httpx` already declared; `run_briefing`'s return type changes from
  `EmailMessage` to `dict`, but its only consumer (`agent.py`) ignores the
  return value.

---

## Tasks

### Task 1: Discord sender

- **Files:** `scout/sub_agents/briefing/notification.py`,
  `tests/test_briefing_notification.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing test (rewrite the file): `ensure_discord_configured`
        raises `ValueError` when token or channel id is missing;
        `send_message(payload, settings)` POSTs to
        `https://discord.com/api/v10/channels/{channel_id}/messages` with
        header `Authorization: Bot {token}` and JSON body == payload, and
        raises on a non-2xx response. Mock `httpx.AsyncClient` via a fake
        transport / monkeypatched client so no real network call is made.
  - [ ] Verify it fails (`python -m pytest tests/test_briefing_notification.py`)
  - [ ] Replace `notification.py`: drop `smtplib`/`EmailMessage`; add
        `ensure_discord_configured(settings)` and
        `async def send_message(payload: dict, settings) -> None` using
        `httpx.AsyncClient` in an `async with`, calling
        `response.raise_for_status()`.
  - [ ] Verify it passes (`python -m pytest tests/test_briefing_notification.py`)
  - [ ] Commit: `feat(briefing): send briefing via Discord bot REST API`

### Task 2: Wire the briefing orchestrator

- **Files:** `scout/sub_agents/briefing/briefing.py`,
  `tests/test_briefing_entrypoint.py`,
  `scout/sub_agents/briefing/email_builder.py` (delete — deferred from
  Phase 1 Task 3), `tests/test_briefing_email_builder.py` (delete)
- **Gate:** none
- **Steps:**
  - [ ] Update the entrypoint tests: monkeypatch `build_embed` and
        `send_message` (instead of `build_email`/`send_email`), configure
        Discord settings (`discord_bot_token`, `discord_channel_id`), and
        assert the built payload is what gets sent. Change the
        not-configured test to assert `ensure_discord_configured` raises
        before summarizing. Remove the `report_path`-threaded-to-builder
        test (report link dropped); keep a test that `run_briefing` still
        accepts `report_path` without error.
  - [ ] Verify it fails (`python -m pytest tests/test_briefing_entrypoint.py`)
  - [ ] Update `run_briefing`: import `build_embed` + `ensure_discord_configured`
        + `send_message`; call `ensure_discord_configured`, build the
        payload, `await send_message(payload, settings)`; return the
        payload `dict`. Keep the `report_path` parameter (agent passes it)
        but do not forward it to `build_embed`. Delete the now-unreferenced
        `email_builder.py` and `tests/test_briefing_email_builder.py`.
  - [ ] Verify it passes (`python -m pytest tests/test_briefing_entrypoint.py`)
  - [ ] Commit: `refactor(briefing): orchestrate Discord embed send`

### Task 3: Wire the pipeline agent gate

- **Files:** `scout/agent.py`, `tests/test_agent.py`
- **Gate:** none
- **Steps:**
  - [ ] Update `test_agent.py`: configure Discord settings for the
        briefing-path test; change the skip test to unset Discord config;
        assert the status event wording is Discord-based.
  - [ ] Verify it fails (`python -m pytest tests/test_agent.py`)
  - [ ] In `agent.py`, change the gate to
        `if settings.discord_bot_token and settings.discord_channel_id:`
        and the status message to `"Briefing: Discord message sent"`.
  - [ ] Verify it passes (`python -m pytest tests/test_agent.py`)
  - [ ] Commit: `feat(agent): gate briefing on Discord config`

### Task 4: Update docs

- **Files:** `README.md`, `docs/commands.md`
- **Gate:** none
- **Steps:**
  - [ ] Rewrite the README prerequisites/config/flow lines that reference
        Gmail/email (lines around the Gmail account prereq, the "At minimum
        set … GMAIL_*" step, "scores and emails matches", "emailed to
        GMAIL_RECIPIENT", and the `REPORT_HOST_DIR` email-link paragraph)
        to describe the Discord bot token + channel and a Discord message.
        Update `docs/commands.md` "emails matches" wording to "posts
        matches to Discord".
  - [ ] Verify: `python -m pytest -q` (full suite green)
  - [ ] Commit: `docs: describe Discord briefing instead of email`

---

## Verification

- [ ] Full suite passes: `python -m pytest -q`
- [ ] No remaining reference to `smtplib`, `build_email`, `send_email`,
      `gmail_`, or `email_builder` in `scout/` (`grep`).
- [ ] Manual (human): run the pipeline with a real `DISCORD_BOT_TOKEN` and
      a test-channel `DISCORD_CHANNEL_ID`; confirm the embed posts and the
      listing links work. Also confirm a no-match run posts the empty-day
      embed.

## Observability

The pipeline emits the status event `"Briefing: Discord message sent"` on
success. A failed send raises out of `send_message` (via
`raise_for_status`), aborting the run with the HTTP status — matching the
old fail-fast SMTP behaviour.

## Rollback

Revert the phase's commits to restore the SMTP `notification.py` and the
Gmail gate from git history.

---

## Notes / Learnings

<Filled in during execution.>
