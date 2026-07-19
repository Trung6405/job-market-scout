# Spec: Briefing Agent

> **Status:** Approved
> **Created:** 2026-07-17 · **Approved:** 2026-07-19
> **Implementation plan:** [plan.md](../../plans/briefing-agent/plan.md)

---

## Problem

`job-market-scout`'s pipeline (Scraper → Tracker → Scorer → Briefing) has three of its four stages implemented; the Briefing stage — the one the job seeker actually reads — does not exist yet (`scout/sub_agents/briefing/agent.py` and `tools.py` are empty stubs). Per the PRD (FR-9, FR-10), the system must compose a concise daily summary of the best-matching listings and deliver it by email, but nothing currently joins the Scorer's output back to real listing data, decides which matches are worth surfacing, writes summary prose, or sends anything. Without this stage the pipeline produces scores that never reach the user.

## Success Criteria

- Given a scraped/tracked `list[Listing]` and the Scorer's `list[ListingScore]`, the system sends one email containing the day's top matches (title, company, link, score) with LLM-written summary prose, using only real listing data for factual fields.
- A day with no listings meeting `min_match_score` still produces a short "no strong matches today" email rather than silence, so the user can distinguish "nothing matched" from "the run failed."
- The Briefing stage is runnable and testable in isolation via a single entry point, matching the existing per-stage pattern (Scraper, Scorer, Tracker are each independently callable).
- No listing field the LLM did not verifiably see (title, company, URL) can appear altered or hallucinated in the sent email — factual fields are inserted by deterministic code, not model output.

---

## Requirements

### Must have

- Deterministic selection of which matches to include: apply `min_match_score` and cap to a configurable maximum count, sorted by score descending. (The Scorer applies no threshold itself — see Decision 4 precedent in `docs/plans/scorer-agent/plan.md`; thresholding happens here.)
- Reuse the existing `join_match_results` (`scout/sub_agents/scorer/results.py`) to pair `ListingScore` back to `Listing` by `(source, external_id)` — no second join implementation.
- An `LlmAgent` (DeepSeek via LiteLLM, no tools) that generates summary prose (an intro paragraph plus a one-line takeaway per included listing) from the selected matches — never asked to reproduce URLs, titles, or other factual fields verbatim.
- A deterministic email builder that merges real listing fields with the LLM's prose into an HTML + plain-text multipart email, including the zero-matches template (which requires no LLM call).
- A Notification module that sends the composed email via Gmail SMTP using an app password.
- A single entry point callable directly with `list[Listing]` and `list[ListingScore]`, consistent with how Scraper/Scorer/Tracker are each called directly today.
- Fail-fast error handling: missing Gmail config at settings load, and SMTP auth/send failures, both raise — no silent fallback, no retry.

### Should have

- A generic fallback line for any selected listing the LLM's output doesn't cover (malformed/hallucinated takeaway key), so every real match still appears in the email even if LLM prose is incomplete.

### Won't have

- Root `scout/agent.py` `SequentialAgent` wiring connecting all four stages — Briefing stays independently callable, consistent with the Tracker-orchestration spec's deferral of the same wiring question.
- Score persistence / a `matches` table — out of scope per PRD Decision D4; Briefing consumes scores only from in-memory pipeline state.
- Gmail API / OAuth-based sending — SMTP with an app password is sufficient for a single-user tool and avoids consent-screen/token-refresh overhead.
- Retry/backoff logic for the LLM call or SMTP send — YAGNI until a real failure mode is observed, consistent with the Scraper and Scorer sessions.

---

## Proposed Approach

Briefing follows the Scorer's established shape: deterministic steps wrap a narrow-purpose LLM call, and the LLM never touches data that must be reproduced exactly.

1. **Join** — reuse `join_match_results(listings, scores)` to get `list[MatchResult]`.
2. **Select** — a plain function filters to `score >= min_match_score`, sorts descending, and caps to a configurable maximum, producing the day's "top matches."
3. **Summarize** — if top matches is non-empty, an `LlmAgent` receives only title/company/score for each top match (plus resume/preferences context) and returns structured summary prose (intro + one-line takeaway per listing, keyed by `(source, external_id)`). If empty, this step is skipped entirely.
4. **Build** — a plain function deterministically merges the top matches' real fields (title, company, url, score) with the LLM's prose (or the empty-day template) into a multipart HTML + text email.
5. **Send** — a Notification module sends the composed email via Gmail SMTP with an app password, raising on any failure.

The entry point (`run_briefing(listings, scores, settings=None)`) orchestrates all five steps and is callable in isolation, mirroring `track_listings` and `build_scorer_agent`.

## Alternatives Considered

| Alternative | Why rejected |
|-------------|--------------|
| Let the LLM output the full structured briefing (title/company/url/score/blurb) directly, validated by `output_schema` | Schema validation constrains shape, not content — the model could still alter a URL or title while staying schema-valid. Keeping factual fields entirely on the deterministic side removes that failure mode instead of merely mitigating it, consistent with PRD Decision D3. |
| Gmail API with OAuth2 instead of SMTP + app password | More setup (consent screen, token storage/refresh) for a single-user daily-batch tool with no multi-tenant need; SMTP with an app password is stdlib-only and matches the project's file-based-config simplicity. |
| Send no email when nothing meets the score threshold | Leaves the user unable to distinguish "no matches today" from "the pipeline silently failed before Briefing" — a short empty-day email preserves that signal. |
| Rely solely on the Scorer's threshold for conciseness, no additional cap in Briefing | The Scorer intentionally applies no threshold (thresholding is a read-time concern per Decision 4); without a cap here, a day with many above-threshold matches could produce a long, non-concise email, contradicting FR-9. |

---

## Open Questions

| Question | Who decides | Blocks planning? |
|----------|-------------|------------------|
| Exact HTML template styling for the email (minimal inline CSS vs. a more polished layout) | Implementation-time judgment | No |
| Whether `run_briefing` needs to be `async` given `send_email`/SMTP are synchronous stdlib calls, vs. wrapping only the ADK `Runner` invocation in async | Implementation-time judgment, resolved same way Tracker resolved its async entry point | No |

---

## Amendments *(only after approval — never silently edit approved content)*

- None yet.
