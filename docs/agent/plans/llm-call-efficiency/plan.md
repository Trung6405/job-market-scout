# Plan: LLM call efficiency — prefix-cache reorder & batch robustness

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Status:** Complete
> **Created:** 2026-07-24 · **Last updated:** 2026-07-24
> **Spec:** [spec.md](../../specs/llm-call-efficiency/spec.md)

---

## Overview

Restructure the Scorer and Extractor prompts so the invariant instructions
and candidate profile lead and the per-batch listings JSON trails, turning
that invariant block into a cacheable prefix across batches and days. Add a
configurable output-token limit and request timeout to the model-call
wrapper, and replace the identical-retry batch path with halve-once-then-skip.
"Done" is: invariant text precedes the listings in both prompts, failed
batches are retried at half size, and the model call carries a token cap and
a timeout — all covered by unit tests.

## Acceptance Criteria

- [x] Both `build_scorer_instruction` and `build_requirements_instruction`
      emit their invariant content before the listings block, which is last.
- [x] The Extractor prompt still contains no profile text.
- [x] `complete_json` forwards a `max_tokens` and a `timeout` to
      `litellm.acompletion`, both sourced from settings.
- [x] A batch that fails as a whole but whose halves succeed is recovered;
      a half that still fails is skipped; a failed single-item batch is
      skipped without a second identical attempt.

---

## Risks & Unknowns

| Risk / unknown | Impact if wrong | Resolution |
|----------------|-----------------|------------|
| Reorder could change model scoring/extraction quality (data now after instructions). | Slightly different scores/requirements. | Accepted risk — instructions-first is standard practice and content is unchanged; temperature stays 0 for both. |
| Prefix-cache reduction is assumed, not measured this task. | No token savings if provider cache behaves differently. | Accepted risk per spec (ship on principle); `spike_prefix_cache.py` remains for later live measurement. |
| `max_tokens` default (8000) sits below deepseek-chat's output cap. | Too-low cap could itself truncate. | 8000 is headroom below the 8192 cap and configurable via `MODEL_MAX_TOKENS`; raise if truncation reappears. |

> Every unknown gets either a spike task or an explicit "accepted risk".

## Blast Radius

- **Code that will change:** `scout/prompts.py`, `scout/shared/llm.py`,
  `scout/config.py`, `scout/shared/batching.py`, and their tests under
  `tests/`; a comment-only touch to `scripts/spike_prefix_cache.py`.
- **Existing behaviour that could break:** the Scorer and Extractor prompt
  text (consumed only by the model), and the batch-retry semantics used by
  `run_scorer` and `run_requirements_extraction`.
- **Off-limits:** Do not modify anything outside the files above without
  flagging it to the human first. No schema, DB, or report-template changes.

---

## Phases

| # | Phase | Document | Status |
|---|-------|----------|--------|
| 1 | Invariant-first prompt reorder | [phase-1-prompt-reorder.md](phase-1-prompt-reorder.md) | Complete |
| 2 | Model-call token cap & timeout | [phase-2-call-limits.md](phase-2-call-limits.md) | Complete |
| 3 | Halve-once-then-skip retry | [phase-3-retry.md](phase-3-retry.md) | Complete |

> All phases are planned in advance. The three phases are independent —
> they touch disjoint files and can execute in any order — but are listed
> 1→3 for a natural review sequence.

---

## Testing Strategy

- **Unit:** per-task TDD in each phase doc — prompt ordering assertions,
  `complete_json` kwarg forwarding, config defaults/overrides, and batch
  split-recovery/skip behaviour. None of these touch Postgres.
- **Integration:** the existing suite (`pytest`) run once at the end; the
  DB-backed tests need `docker compose up -d postgres` per the README.
- **Manual:** none required — no user-facing surface changes. Optionally
  eyeball a rendered Scorer prompt to confirm the profile leads.

---

## Key Decisions & Constraints

- Full invariant-first reorder (not merely aligning batch sizes) — chosen in
  brainstorming to make the large rubric+profile the cached prefix.
- Halve-once-then-skip (single level of splitting), not recursive-to-1.
- Ship on the documented prefix-cache principle; no live-API measurement.
- Extractor stays profile-blind — a hard content rule, re-asserted by test.

## Out of Scope

- Reordering the Briefing prompt (single un-batched call).
- Aligning Scorer/Extractor batch sizes.
- Any live token-usage measurement or spike changes beyond a comment.

---

## Definition of Done

- [x] All acceptance criteria met
- [x] All phase verification steps pass
- [x] Full `pytest` run green (Postgres up) — 249 passed
- [x] `scout/.env.example` documents `MODEL_MAX_TOKENS` and
      `MODEL_TIMEOUT_SECONDS`
- [x] No new lint or type-check warnings

## Update Rules

- Phase docs hold task-level detail; this file holds phase-level status only.
- When a phase's scope changes, update its row here **in the same commit**.
- On conflict, this file wins for *what* the phases are; the phase doc
  wins for *how* its tasks are done.
