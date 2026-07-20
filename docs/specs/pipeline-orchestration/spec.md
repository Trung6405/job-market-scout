# Spec: Pipeline Orchestration

> **Status:** Draft
> **Created:** 2026-07-19 · **Approved:** —
> **Implementation plan:** [plan.md](../../plans/pipeline-orchestration/plan.md) *(created after approval)*

---

## Problem

`job-market-scout`'s four stages — Scraper, Tracker, Scorer, Briefing — each work and are tested in isolation, but nothing runs them end-to-end. `scout/agent.py`, the intended root wiring point, is an empty stub; every prior spec (tracker-orchestration, scorer-agent) explicitly deferred "root `SequentialAgent` wiring" to a later session. Two of the four stages (Scraper, Scorer) also have no code that actually invokes their `LlmAgent` and parses its structured output — only the Briefing stage has that runner glue today. Separately, the container's `Dockerfile` `CMD` starts `adk api_server`, a long-running interactive chat server, which cannot execute a one-shot daily batch run even if the wiring existed. Without this work, the pipeline described in the PRS (§3.1: Scraper → Tracker → Scorer → Briefing, once per day) cannot actually execute; it only exists as four disconnected, individually-testable pieces. There is also no way to exercise the whole pipeline interactively during development — each sub-agent can already be pointed at individually via `adk web` (each exports a module-level `root_agent`), but there is no equivalent top-level entry point to watch the full Scraper → Tracker → Scorer → Briefing run happen stage by stage while developing or debugging it.

## Success Criteria

- A single call runs the full pipeline: scraped listings are tracked, relevant (new/changed) listings are scored, and a briefing email is sent for them — with no manual gluing of stage outputs to inputs.
- When the Tracker finds no new/changed listings, the Scorer and Briefing stages are not invoked (no wasted LLM calls).
- The container's default startup command actually executes one pipeline run to completion and exits, rather than starting a chat server that never triggers the pipeline.
- A stage failure aborts the run visibly (raises), with no partial-success masking.
- A developer can run `adk web`, send one message to the root agent, and watch the pipeline progress stage by stage (listing count, new/changed count, scores computed, email sent) in the ADK web UI — without needing the Docker/batch path to inspect behavior.

---

## Requirements

### Must have

- A `run_scraper` function that runs the existing Scraper `LlmAgent` via an ADK runner and returns parsed `list[Listing]`, following the invocation pattern `briefing/summarize.py` already uses.
- A `run_scorer` function with the same shape for the Scorer `LlmAgent`, returning parsed `list[ListingScore]`.
- A `run_scout` function that calls, in order: `run_scraper` → `track_listings` → (short-circuit if empty) → `run_scorer` → `run_briefing`, threading a single `Settings` instance through every call. This is the one place the full stage sequence is implemented.
- A custom (non-LLM) `BaseAgent` in `scout/agent.py` — `ScoutPipelineAgent` — whose `_run_async_impl` calls `run_scout`'s stage sequence directly (not `run_scout` as an opaque call, since it needs to emit an ADK `Event` after each stage completes: listing count after Scraper, new/changed count after Tracker, score count after Scorer, "email sent" after Briefing). `scout/agent.py` exports `root_agent = ScoutPipelineAgent()`, so `adk web` (pointed at the repo root) discovers it and a developer can send it one message to trigger a full run and watch stage-by-stage progress in the UI, the same way each sub-agent's own `root_agent` already works standalone today.
- A batch entrypoint (`scout/main.py`) that runs the same stage sequence once via `asyncio.run` and exits — either by calling `run_scout` directly or by driving `ScoutPipelineAgent` through an `InMemoryRunner` (implementation detail for the plan); either way there is one implementation of the stage sequence, not two.
- `Dockerfile`'s `CMD` updated to invoke that batch entrypoint instead of `adk api_server`.

### Should have

- A shared parsing helper (`scout/shared/parsing.py`) extracted from `briefing/summarize.py`'s existing code-fence-stripping logic, reused by the three LLM-output parsers (briefing prose, scraper listings, scorer scores) instead of duplicating it a third time.

### Won't have

- A literal ADK `SequentialAgent` chaining the four stages as agent instances — infeasible given Decision D3 (listing data never round-trips through the LLM), which requires the Scorer and Briefing agents to be *constructed* with the previous stage's typed Python output already known, not received via ADK session state at runtime. `ScoutPipelineAgent` does not change this: it is a thin custom wrapper that calls the same typed Python functions internally and only uses ADK `Event`s to report progress, not to pass stage data between sub-agents.
- A scheduler / cron trigger for daily runs — planned separately per PRS §7 (Azure VM instance), out of scope here.
- Persisting match scores (`matches` table) — deferred per PRS Decision D4, unrelated to this wiring.
- Retry or partial-failure recovery across stages — fail-fast matches the existing project-wide convention (Tracker and Briefing already raise on failure with no retry).

---

## Proposed Approach

`run_scout` is a plain async Python function, not an ADK agent construct. It calls each stage's existing (or newly added) async entry point directly, passing typed Python values (`list[Listing]`, `list[ListingScore]`) from one stage's return value into the next stage's arguments — the same style `briefing/briefing.py`'s `run_briefing` already uses internally to join `Listing`s and `ListingScore`s by key. `run_scraper` and `run_scorer` fill the one missing piece of that style: each builds its stage's `LlmAgent` (via the existing `build_scraper_agent`/`build_scorer_agent`), runs it through an `InMemoryRunner` exactly as `briefing/summarize.py`'s `_run_briefing_agent` does, and parses the final response text into the stage's Pydantic output type using `TypeAdapter(list[X]).validate_json(...)` after stripping any markdown code fence.

`ScoutPipelineAgent` (in `scout/agent.py`) is a thin `BaseAgent` subclass that gives `run_scout`'s stage sequence a face `adk web` can talk to. Its `_run_async_impl` runs the same steps `run_scout` runs, but after each stage it yields an `Event` carrying a short human-readable status (e.g. `"Scraper: 18 listings found"`, `"Tracker: 5 new, 13 existing"`, `"Scorer: 5 scored"`, `"Briefing: email sent"`), so a developer running `adk web` and sending it any message sees the whole pipeline's behavior unfold turn by turn instead of only a final result. `scout/agent.py` exports `root_agent = ScoutPipelineAgent()` for ADK's agent discovery, mirroring the `root_agent = build_scraper_agent()` pattern each sub-agent module already uses standalone.

The batch entrypoint (`scout/main.py`) exists so the same sequence can run to completion non-interactively: `asyncio.run` over either `run_scout` directly or `ScoutPipelineAgent` driven through an `InMemoryRunner` (the plan picks whichever keeps a single source of truth for the sequence — likely `run_scout` as the shared implementation, with `ScoutPipelineAgent` calling it and translating its return value into progress `Event`s, rather than duplicating the stage sequence in two places). The `Dockerfile`'s `CMD` is changed to run `scout/main.py`, so a scheduled container invocation actually executes the pipeline instead of starting an idle API server.

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
