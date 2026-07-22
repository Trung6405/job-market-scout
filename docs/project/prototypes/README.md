# Job Market Scout — Advisor UI Prototypes

Clickable, self-contained HTML mockups of the **Advisor report UI** (the Phase 3
deliverable from `agent_plans/260721-1041-advisor-sub-agent/`). Throwaway — for
reacting to layout/flow before the real Jinja2 report is built.

Open any file directly in a browser (no build step, no network). Screens link
to each other.

## Screens

| File | Shows |
|------|-------|
| [`dashboard.html`](./dashboard.html) | **Today's** daily briefing: day-nav strip, run stats + list of scored roles, each with fit score, success band chip, and top skill gaps. Band filter chips (interactive). Entry point. |
| [`history.html`](./history.html) | **Daily reports archive** — one briefing per day, newest first, with per-day stats + band counts. Includes an empty "nothing to score" day. Realises "split the report on a daily basis". |
| [`job-detail.html`](./job-detail.html) | One role drilled in: fit score + success band + must-have coverage, requirements-vs-profile checklist, and per-gap **verified GitHub resources** (the core feature). |
| [`profile.html`](./profile.html) | The student profile the agent matches against — **categorised tech stack with proficiency** + **domain-knowledge** levels + tagged projects. These structured signals drive gap detection. Read-only view of `profile.json`. |

## Flow

```
history.html ──(pick a day)──► dashboard.html ──(click a role)──► job-detail.html
     ▲                              │  │                               │
     └───────(day nav)─────────────┘  └──────► profile.html ◄──────────┘
```

Each day is its own report; `dashboard.html` represents one day, `history.html` is the index of days.

## Design intent reflected here

- **Success = band, not a fake %** — shown as a coloured chip (Strong-match /
  Competitive / Reach), always paired with a disclaimer.
- **D3 honoured visually** — resources show a "✓ verified live link" and the copy
  states the agent never invents URLs.
- **Gap-first coaching** — must-have gaps are flagged red; each gets concrete free
  resources.

## Not real

Static mockups with placeholder content (student "Minh", sample AU roles). No
backend, no live GitHub calls. Some resource links point at real repos for feel;
final links come from the `github_search` step at build time.
