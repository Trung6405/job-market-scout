# Spec: Pipeline Hardening — Gap Accuracy & Persistence Robustness

> **Status:** Approved
> **Created:** 2026-07-23 · **Approved:** 2026-07-23
> **Implementation plan:** [plan.md](../../plans/pipeline-hardening/plan.md) *(created after approval)*

---

## Problem

The Advisor stage and its persistence path have three correctness and
robustness weaknesses surfaced in review. First, gap detection reports
false gaps: a student is told they lack a skill they actually have
because requirement text (`React.js`, `Postgres`) is compared by exact,
lowercased string equality against profile skills (`React`,
`PostgreSQL`). Because the entire value of the feature is telling a
student what they're missing, false gaps directly erode trust. Second,
the run's persistence is split across several separate database
connections with no enclosing transaction, and the requirements-matching
step silently discards any scored listing the extraction LLM omits — so a
run that dies mid-Advisor can leave a half-written, unfinished run live on
the dashboard with no warning. Third, several contracts are implicit
where they should be explicit: the run identity model (two cron fires per
day collapse into one `run_date` row), the re-run idempotency that
currently heals a broken run only by accident, and the band vocabulary
carried around as bare `str`.

## Success Criteria

- A skill the student possesses is not reported as a gap merely because
  the listing phrased it as a common variant (`React.js` vs `React`,
  `Postgres` vs `PostgreSQL`, `JS` vs `JavaScript`).
- A run that fails partway through the Advisor stage never leaves the
  dashboard showing a partially-persisted run as if it were complete; the
  next run for the same date deterministically heals it.
- When the extraction LLM returns fewer listings than were scored, the
  drop is logged, not silent.
- The run-identity (same-`run_date` overwrite) and idempotency contracts
  are documented where a reader of the architecture will find them.
- The band value is a closed, type-checked vocabulary rather than an
  open `str`.

---

## Requirements

### Must have

- Gap matching tolerant of common skill-name variants, achieved by
  canonicalizing skill names at extraction time plus a deterministic
  normalization applied to both sides before comparison.
- The final score→gaps→meta→finish→report persistence block runs inside a
  single database transaction so it commits all-or-nothing.
- A logged warning when `matches_with_requirements` is shorter than
  `matches` (i.e. the extraction LLM dropped listings).
- `band` typed as a closed `Literal`/enum threaded through `classify_band`,
  the schemas, and persistence.
- Architecture docs state the same-`run_date` overwrite model and the
  re-run idempotency guarantee explicitly.

### Should have

- Naming reconciliation so docs and code agree on one name for the gap
  matcher (`evaluate_requirements` in code vs `detect_gaps` in prose).

### Won't have

- Proficiency-aware gap matching — deferred; presence-only for now, noted
  as future work (avoids scope creep into extraction-level requirement
  inference).
- Splitting runs into distinct intraday rows — the same-`run_date`
  refresh model is kept deliberately (matches the "daily briefing"
  framing; avoids a schema migration and report/email churn).
- Infra rethink (per-execution ACI/Container App Job instead of a VM, or a
  missed-run dead-man's-switch alert) — real ideas but a separate
  initiative, out of scope here.

---

## Proposed Approach

Three independent workstreams, each a phase:

1. **Gap-matching accuracy.** Extend the requirements-extraction prompt
   (`build_requirements_instruction`) to instruct the LLM to emit
   canonical skill names (single canonical token per skill, no version
   suffixes or punctuation decoration). Add a pure `normalize_skill()`
   helper in `advisor/gaps.py` that lowercases, strips punctuation and
   surrounding whitespace, and collapses a small set of known equivalences
   (defensive against LLM misses); apply it to both the requirement skill
   and every profile skill before the membership test. Matching stays
   deterministic and unit-testable.

2. **Persistence robustness.** Wrap the final persistence block in
   `agent.py` (`record_run_listings` through `finish_run` and the report
   renders that must reflect them) in a single `conn.transaction()`, so a
   failure leaves nothing half-written. Emit a warning event/log when the
   extraction step drops scored listings.

3. **Contracts & typing.** Introduce a `Band` `Literal` (or `StrEnum`),
   thread it through `classify_band`, `MatchResult`/`RunListing`
   schemas, and persistence. Document the run-identity/idempotency
   contract in `architecture-pipeline-overview.md`, and reconcile the
   `detect_gaps`/`evaluate_requirements` naming.

## Alternatives Considered

| Alternative | Why rejected |
|-------------|--------------|
| Deterministic alias table only (no LLM canonicalization) | Requires maintaining an ever-growing synonym map; misses unseen variants the LLM can canonicalize for free. Kept only as the defensive fallback layer. |
| Fuzzy/edit-distance skill matching | Non-deterministic-feeling thresholds, risks false *positives* (matching unrelated skills); harder to test than canonical-token equality. |
| Split runs into per-timestamp rows | Enables intraday history but forces a schema migration plus report/history/email changes for marginal benefit; contradicts the daily-briefing framing. |
| Do nothing | Leaves a trust-breaking false-gap bug and an undocumented partial-persistence window in a project about to go to a supervisor. |

---

## Open Questions

| Question | Who decides | Blocks planning? |
|----------|-------------|------------------|
| None outstanding — the three scope decisions (canonicalize in prompt, keep same-day overwrite, defer proficiency) were resolved before planning. | — | no |

---

## Amendments *(only after approval — never silently edit approved content)*

- —
