# Spec: Discord Bot Briefing Notification

> **Status:** Draft
> **Created:** 2026-07-23 · **Approved:** —
> **Implementation plan:** [plan.md](../../plans/discord-notification/plan.md) *(created after approval)*

---

## Problem

The daily briefing that summarizes the day's strongest job matches is
delivered by email over Gmail SMTP. Email is a heavyweight channel for a
short, glanceable daily digest: it requires a Gmail app password, buries
the briefing among other mail, and offers no good place for the user to
react. The user already lives in Discord and wants the briefing to land in
a channel there instead, where it is immediate and visible.

## Success Criteria

- The daily briefing arrives as a message in a Discord channel instead of
  an email inbox.
- Each strong match is readable at a glance with its title, company,
  match score, a one-line takeaway, and a working link to the listing.
- A day with no strong matches still produces a clear "no matches" message.
- No Gmail credentials or SMTP configuration are required to run the
  pipeline.

---

## Requirements

### Must have

- The briefing is posted to a Discord channel by a bot, authenticated with
  a bot token, via Discord's REST API.
- The message renders as a single rich embed listing the selected matches.
- The "no strong matches today" case produces its own embed.
- Configuration for the Gmail/SMTP path is removed; Discord bot token and
  target channel are configured via environment variables.
- The pipeline only attempts to send when Discord is configured; when it
  isn't, the briefing step is skipped without failing the run.

### Should have

- Sensible handling of Discord's embed size limits so a normal briefing is
  never rejected for being too long.

### Won't have

- A persistent gateway bot or any interactivity (commands, replies,
  reactions) — the briefing is one-way, so a gateway connection is
  unnecessary.
- A configurable choice between email and Discord — email is removed
  outright to keep one notification path.
- A link to the full report in the message — a `file://` path is not
  clickable or meaningful inside Discord, so it is dropped.

---

## Proposed Approach

Replace the email notification layer of the briefing sub-agent with a
Discord layer, leaving match selection and prose summarization untouched.

- **Configuration:** drop `gmail_address`, `gmail_app_password`, and
  `gmail_recipient`; add `discord_bot_token` and `discord_channel_id`,
  sourced from `DISCORD_BOT_TOKEN` and `DISCORD_CHANNEL_ID`.
- **Message builder:** a pure function replaces the email builder,
  producing a Discord message payload (a JSON-serializable dict with an
  `embeds` array) from the selected matches and the summarized prose. The
  embed carries the intro prose as its description and one field per match
  (title, company, score in the field name; a listing link and takeaway in
  the field value). Field and embed lengths are clamped to Discord's
  limits. The takeaway-indexing and fallback logic carries over unchanged.
- **Sender:** a `send`-style function POSTs the payload to
  `POST /channels/{channel_id}/messages` on Discord's REST API with an
  `Authorization: Bot <token>` header, using the async HTTP client already
  available in the project (`httpx`), and raises on a non-success response.
- **Wiring:** the briefing orchestrator swaps the builder and sender calls;
  the pipeline agent's send gate switches from Gmail credentials to Discord
  configuration and reports a Discord-worded status.

No new dependency is introduced — `httpx` is already declared.

## Alternatives Considered

| Alternative | Why rejected |
|-------------|--------------|
| Discord **webhook** URL instead of a bot | Simpler (no bot registration), but the user specifically wants a named bot and the option to grow toward interactivity later. |
| Persistent **gateway bot** (e.g. discord.py) | A long-lived connection is overkill for a scheduled one-way briefing; more moving parts to host and keep online. |
| Keep email and **add** Discord alongside | Doubles the config and code to maintain for no stated benefit; the user wants Discord to be the channel, not an addition. |
| Do nothing (keep email) | Fails the user's goal of an immediate, visible briefing in the channel they already use. |

---

## Open Questions

| Question | Who decides | Blocks planning? |
|----------|-------------|------------------|
| None outstanding — mechanism, scope, format, and report-link handling all settled in brainstorming. | — | no |

---

## Amendments *(only after approval — never silently edit approved content)*

- —
