# Spec: Pipeline Orchestration

> **Status:** Draft
> **Created:** 2026-07-19 · **Approved:** —
> **Implementation plan:** [plan.md](../../plans/pipeline-orchestration/plan.md) *(created after approval)*

---

## Problem

`job-market-scout`'s four stages — Scraper, Tracker, Scorer, Briefing — each work and are tested in isolation, but nothing runs them end-to-end. `scout/agent.py`, the intended root wiring point, is an empty stub; every prior spec (tracker-orchestration, scorer-agent) explicitly deferred "root `SequentialAgent` wiring" to a later session. Two of the four stages (Scraper, Scorer) also have no code that actually invokes their `LlmAgent` and parses its structured output — only the Briefing stage has that runner glue today. Separately, the container's `Dockerfile` `CMD` starts `adk api_server`, a long-running interactive chat server, which cannot execute a one-shot daily batch run even if the wiring existed. Without this work, the pipeline described in the PRS (§3.1: Scraper → Tracker → Scorer → Briefing, once per day) cannot actually execute; it only exists as four disconnected, individually-testable pieces.

## Success Criteria

- A single call runs the full pipeline: scraped listings are tracked, relevant (new/changed) listings are scored, and a briefing email is sent for them — with no manual gluing of stage outputs to inputs.
- When the Tracker finds no new/changed listings, the Scorer and Briefing stages are not invoked (no wasted LLM calls).
- The container's default startup command actually executes one pipeline run to completion and exits, rather than starting a chat server that never triggers the pipeline.
- A stage failure aborts the run visibly (raises), with no partial-success masking.

---

## Requirements

### Must have

- A `run_scraper` function that runs the existing Scraper `LlmAgent` via an ADK runner and returns parsed `list[Listing]`, following the invocation pattern `briefing/summarize.py` already uses.
- A `run_scorer` function with the same shape for the Scorer `LlmAgent`, returning parsed `list[ListingScore]`.
- A `run_scout` orchestrator (in `scout/agent.py`) that calls, in order: `run_scraper` → `track_listings` → (short-circuit if empty) → `run_scorer` → `run_briefing`, threading a single `Settings` instance through every call.
- A batch entrypoint (`scout/main.py`) that runs `run_scout` once via `asyncio.run` and exits.
- `Dockerfile`'s `CMD` updated to invoke that entrypoint instead of `adk api_server`.

### Should have

- A shared parsing helper (`scout/shared/parsing.py`) extracted from `briefing/summarize.py`'s existing code-fence-stripping logic, reused by the three LLM-output parsers (briefing prose, scraper listings, scorer scores) instead of duplicating it a third time.

### Won't have

- A literal ADK `SequentialAgent` chaining the four stages as agent instances — infeasible given Decision D3 (listing data never round-trips through the LLM), which requires the Scorer and Briefing agents to be *constructed* with the previous stage's typed Python output already known, not received via ADK session state at runtime.
- A scheduler / cron trigger for daily runs — planned separately per PRS §7 (Azure Container Apps Jobs), out of scope here.
- Persisting match scores (`matches` table) — deferred per PRS Decision D4, unrelated to this wiring.
- Retry or partial-failure recovery across stages — fail-fast matches the existing project-wide convention (Tracker and Briefing already raise on failure with no retry).

---

## Proposed Approach

`run_scout` is a plain async Python function, not an ADK agent construct. It calls each stage's existing (or newly added) async entry point directly, passing typed Python values (`list[Listing]`, `list[ListingScore]`) from one stage's return value into the next stage's arguments — the same style `briefing/briefing.py`'s `run_briefing` already uses internally to join `Listing`s and `ListingScore`s by key. `run_scraper` and `run_scorer` fill the one missing piece of that style: each builds its stage's `LlmAgent` (via the existing `build_scraper_agent`/`build_scorer_agent`), runs it through an `InMemoryRunner` exactly as `briefing/summarize.py`'s `_run_briefing_agent` does, and parses the final response text into the stage's Pydantic output type using `TypeAdapter(list[X]).validate_json(...)` after stripping any markdown code fence.

The batch entrypoint (`scout/main.py`) is a thin `asyncio.run(run_scout())` wrapper; the `Dockerfile`'s `CMD` is changed to run it, so a scheduled container invocation actually executes the pipeline instead of starting an idle API server.

## Alternatives Considered

| Alternative | Why rejected |
|-------------|--------------|
| Literal ADK `SequentialAgent` wiring the four stages as agent instances | Scorer/Briefing agents must be built with the prior stage's data already baked into their instructions (D3); `SequentialAgent` shares state at runtime between pre-built agent instances, which doesn't fit that construction-time dependency. |
| Leave `Dockerfile`'s `CMD` as `adk api_server` | The new orchestrator would have no caller in the running container — a scheduler hitting this image would start a chat server, not execute the batch pipeline; the PRS's "one run per day" behavior would remain unreachable in production. |
| Keep the code-fence-stripping parsing helper duplicated per stage | Three near-identical copies of the same small regex helper; low cost to extract once, reused by briefing, scraper, and scorer parsers. |

---

## Open Questions

| Question | Who decides | Blocks planning? |
|----------|-------------|------------------|
| Whether `run_scout`'s zero-relevant-listings short circuit should still log/return anything distinguishable from "pipeline ran but nothing to brief" vs. "pipeline errored" | Implementation-time judgment | No |

---

## Amendments *(only after approval — never silently edit approved content)*

- (none yet)
