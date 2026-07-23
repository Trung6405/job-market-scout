# Phase 1: Config + Embed Builder

> **Parent plan:** [plan.md](plan.md)
> **Status:** Not started
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
  - [ ] Write failing test: `Settings` exposes `discord_bot_token` and
        `discord_channel_id` from `DISCORD_BOT_TOKEN` / `DISCORD_CHANNEL_ID`
        (default `""`), and no longer defines `gmail_address`,
        `gmail_app_password`, or `gmail_recipient`.
  - [ ] Verify it fails (`python -m pytest tests/test_config.py`)
  - [ ] Remove the three `gmail_*` fields; add `discord_bot_token` and
        `discord_channel_id` via the existing `_env_str` pattern. Update
        `scout/.env.example`: drop `GMAIL_*` and the `REPORT_HOST_DIR`
        email-link comment wording, add `DISCORD_BOT_TOKEN=` and
        `DISCORD_CHANNEL_ID=`.
  - [ ] Verify it passes (`python -m pytest tests/test_config.py`)
  - [ ] Commit: `feat(config): replace Gmail settings with Discord bot config`

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
  - [ ] Verify it fails (`python -m pytest tests/test_briefing_embed_builder.py`)
  - [ ] Implement `build_embed`, porting `_index_takeaways`, `_takeaway_for`,
        and `_FALLBACK_TAKEAWAY_TEMPLATE` from `email_builder.py`. No HTML
        escaping. `report_path` is intentionally NOT a parameter (report
        link dropped).
  - [ ] Verify it passes (`python -m pytest tests/test_briefing_embed_builder.py`)
  - [ ] Commit: `feat(briefing): build Discord embed for matched listings`

### Task 3: Embed builder — no-match case, field clamping, retire email builder

- **Files:** `scout/sub_agents/briefing/embed_builder.py`,
  `tests/test_briefing_embed_builder.py`,
  `scout/sub_agents/briefing/email_builder.py` (delete),
  `tests/test_briefing_email_builder.py` (delete)
- **Gate:** none
- **Steps:**
  - [ ] Write failing test: with `top_matches == []`, the embed title is
        `"Job Market Scout: no strong matches today"` with a short
        description and no fields. Add a test that an over-long title /
        field name / field value is clamped to Discord's limits (title
        ≤256, field name ≤256, field value ≤1024).
  - [ ] Verify it fails (`python -m pytest tests/test_briefing_embed_builder.py`)
  - [ ] Implement the empty-day embed and a small `_clamp` helper applied
        to title, field names, and field values. Delete `email_builder.py`
        and `tests/test_briefing_email_builder.py`.
  - [ ] Verify it passes (`python -m pytest tests/test_briefing_embed_builder.py`)
  - [ ] Commit: `feat(briefing): handle no-match embed and clamp field limits`

---

## Verification

- [ ] Phase tests pass: `python -m pytest tests/test_config.py tests/test_briefing_embed_builder.py`
- [ ] `email_builder.py` and its test are gone; no import of them remains
      (`python -m pytest -q` collects without import errors for briefing —
      note `briefing.py` still imports `build_email` until Phase 2, so run
      the two files above specifically here).

## Rollback

Revert the phase's commits; `email_builder.py` and the Gmail config are
restored from git history. No state to unwind.

---

## Notes / Learnings

<Filled in during execution.>
