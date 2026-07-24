# Phase 1: Config + Embed Builder

> **Parent plan:** [plan.md](plan.md)
> **Status:** Complete
> **Depends on:** nothing

---

## Goal

Swap the Gmail settings for Discord settings and replace the email builder
with a pure function that builds a Discord embed payload from the selected
matches and prose. No network calls yet — this phase is entirely pure and
unit-testable.

## Safety Checklist

- **Touches user input, auth, secrets, or external calls?**
  Yes — introduces `DISCORD_BOT_TOKEN` / `DISCORD_CHANNEL_ID` config (a
  secret). No external call in this phase; the token is only read into
  `Settings`. No token value is logged or embedded in output.
- **Contains a one-way door (schema, public API shape, new dependency)?**
  No — no new dependency, no schema, no stored data.

---

## Tasks

### Task 1: Swap Gmail config for Discord config

- **Files:** `scout/config.py`, `scout/.env.example`, `tests/test_config.py`
- **Gate:** none
- **Steps:**
  - [x] Write failing test: `Settings` exposes `discord_bot_token` and
        `discord_channel_id` from `DISCORD_BOT_TOKEN` / `DISCORD_CHANNEL_ID`
        (default `""`), and no longer defines `gmail_address`,
        `gmail_app_password`, or `gmail_recipient`.
  - [x] Verify it fails (`python -m pytest tests/test_config.py`)
  - [x] Remove the three `gmail_*` fields; add `discord_bot_token` and
        `discord_channel_id` via the existing `_env_str` pattern. Update
        `scout/.env.example`: drop `GMAIL_*` and the `REPORT_HOST_DIR`
        email-link comment wording, add `DISCORD_BOT_TOKEN=` and
        `DISCORD_CHANNEL_ID=`.
  - [x] Verify it passes (`python -m pytest tests/test_config.py`)
  - [x] Commit: `feat(config): replace Gmail settings with Discord bot config`

### Task 2: Embed builder — matches present

- **Files:** `scout/sub_agents/briefing/embed_builder.py`,
  `tests/test_briefing_embed_builder.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing test: `build_embed(top_matches, prose, settings)`
        returns `{"embeds": [embed]}` where the single embed has a title
        `"Job Market Scout: N matches today"` (correct singular/plural),
        `description` equal to the intro prose, and one field per match
        whose `name` is `"{title} at {company} — {score}/100"` and whose
        `value` contains a `[View listing]({url})` link and the takeaway.
        Include a case exercising the fallback takeaway (a match not in
        the prose index).
  - [x] Verify it fails (`python -m pytest tests/test_briefing_embed_builder.py`)
  - [x] Implement `build_embed`, porting `_index_takeaways`, `_takeaway_for`,
        and `_FALLBACK_TAKEAWAY_TEMPLATE` from `email_builder.py`. No HTML
        escaping. `report_path` is intentionally NOT a parameter (report
        link dropped).
  - [x] Verify it passes (`python -m pytest tests/test_briefing_embed_builder.py`)
  - [x] Commit: `feat(briefing): build Discord embed for matched listings`

### Task 3: Embed builder — no-match case, field clamping

- **Files:** `scout/sub_agents/briefing/embed_builder.py`,
  `tests/test_briefing_embed_builder.py`
- **Gate:** none
- **Steps:**
  - [x] Write failing test: with `top_matches == []`, the embed title is
        `"Job Market Scout: no strong matches today"` with a short
        description and no fields. Add tests that an over-long field name /
        field value is clamped to Discord's limits (field name ≤256,
        field value ≤1024). (Title clamp is defensive-only — a
        count-based title is always short — so it is not unit-tested with a
        trivially-passing assertion.)
  - [x] Verify it fails (`python -m pytest tests/test_briefing_embed_builder.py`)
  - [x] Implement the empty-day embed and a small `_clamp` helper applied
        to title, field names, and field values.
  - [x] Verify it passes (`python -m pytest tests/test_briefing_embed_builder.py`)
  - [x] Commit: `feat(briefing): handle no-match embed and clamp field limits`

> **Deferral (see Notes):** deleting `email_builder.py` and
> `tests/test_briefing_email_builder.py` moved to Phase 2 Task 2, so no
> commit leaves `briefing.py` with a dangling `build_email` import.

---

## Verification

- [x] Phase tests pass: `python -m pytest tests/test_config.py tests/test_briefing_embed_builder.py`
- [ ] `email_builder.py` removed — deferred to Phase 2 Task 2 (kept here so
      `briefing.py` stays importable until it is rewired).

## Rollback

Revert the phase's commits; `email_builder.py` and the Gmail config are
restored from git history. No state to unwind.

---

## Notes / Learnings

- Retiring `email_builder.py` was moved out of this phase into Phase 2
  Task 2. Deleting it here would break `briefing.py`'s `build_email`
  import (and the briefing entrypoint test collection) for the span
  between Phase 1 and Phase 2 Task 2. Deferring keeps every commit's
  import graph intact; the deletion now rides with the `briefing.py`
  rewire that removes the import.
