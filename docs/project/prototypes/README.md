# Job Market Scout — Advisor UI Prototypes

> **Historical — superseded.** These mockups did their job: the real report UI
> now lives in `scout/sub_agents/advisor/templates/` (Jinja2), rendered by
> `scout/sub_agents/advisor/report.py` and published to the live dashboard
> after each run. They are kept only as a design-history record for the
> `advisor-report` initiative (`docs/agent/specs/advisor-report/spec.md`,
> `docs/agent/plans/advisor-report/`). Details below describe the mockups as
> designed, not the shipped product — e.g. the static "How to position your
> application" section survives only here (deliberately retired in Career
> Coach P4), and per-gap resources ship via the Coach stage, not the Advisor.

Clickable, self-contained HTML mockups of the **Advisor report UI**. Throwaway —
built for reacting to layout/flow before the real Jinja2 report was built.

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
