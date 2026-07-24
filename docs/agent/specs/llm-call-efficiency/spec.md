# Spec: LLM call efficiency — prefix-cache reorder & batch robustness

> **Status:** Draft
> **Created:** 2026-07-24 · **Approved:** —
> **Implementation plan:** [plan.md](../../plans/llm-call-efficiency/plan.md) *(created after approval)*

---

## Problem

Every scored run issues many batched LLM calls whose prompts contain a
large block of instructions and the candidate profile that are identical
across every batch and every day. DeepSeek's automatic prompt cache
rewards only a shared *leading* prefix, but the pipeline places the
per-batch listings JSON first and the invariant instructions and profile
last, so none of that invariant text is ever cached — it is re-billed on
every batch of every run. The listings-first layout was adopted to let the
Scorer and Extractor share a byte-identical prefix, but the two stages use
different batch sizes, so their per-batch prefixes never actually align and
that sharing never occurs.

Separately, batched calls fail mainly by output-token truncation, yet the
retry path re-sends the identical prompt at temperature 0 — a
deterministic re-truncation that wastes a call before skipping the batch.
The model call also sets no output-token ceiling and no request timeout, so
truncation is more likely than it needs to be and one hung provider call
can stall the whole concurrent stage.

## Success Criteria

- The invariant instruction + profile text sits at the start of every
  Scorer and Extractor prompt, ahead of the per-batch listings, so it forms
  a cacheable shared prefix across batches and across days.
- A batch that fails once is retried at a smaller size that can actually
  succeed, rather than re-sent unchanged.
- A single hung or over-long model call cannot stall or indefinitely block
  a stage.

---

## Requirements

### Must have

- Scorer and Extractor prompts are restructured so all invariant content
  (role, rubric/rules, candidate profile for the Scorer, return-format
  instructions) precedes the variable listings block, which comes last.
- The Extractor prompt remains profile-blind (no profile text in its
  prefix), preserving the existing separation.
- On a batch's first failure, the batch is split into two halves and each
  half is retried once through the concurrency limit; a half that still
  fails is skipped with a warning. A single-item batch that fails is
  skipped directly.
- The model call accepts and forwards an output-token limit and a request
  timeout, both configurable.

### Should have

- Unit tests asserting invariant text precedes the listings block, that the
  Extractor prompt still omits the profile, that the split-retry recovers a
  good half while skipping a bad one, and that the token limit and timeout
  are forwarded.

### Won't have

- Live-API token-usage measurement of the cache reduction — shipped on the
  documented prefix-cache principle and the existing spike; measuring needs
  a live key and is out of scope.
- Reordering the Briefing prompt — it is a single un-batched call, so
  caching is marginal and it is already instructions-first.
- Recursive/unbounded split-retry — one level of halving only.

---

## Proposed Approach

**Prompt layout (invariant-first).** Both prompt builders emit, in order:
the role line, the rubric or extraction rules (worded to reference the
listings "below"), the candidate profile (Scorer only), the JSON
return-format instructions, and finally the per-batch `Listings:` block.
The listings block stays a shared helper but is emitted last as the
variable suffix rather than the leading prefix; its rationale comment is
updated to match. The cross-stage listing projection is unchanged.

**Batch robustness.** The batch runner replaces its identical-retry loop
with a halve-once-then-skip strategy: run the batch; on failure split it in
two and run each half once (each through the existing concurrency
semaphore); skip any half that still fails, and skip a failed single-item
batch outright. The model-call wrapper gains an output-token limit and a
request timeout, both sourced from new settings with sensible defaults
(≈8000 tokens of headroom below the model's output cap; ≈120s timeout).

## Alternatives Considered

| Alternative | Why rejected |
|-------------|--------------|
| Align Scorer/Extractor batch sizes, keep listings-first | Restores only the cross-stage sharing, which was never the big win; leaves the large invariant rubric+profile uncached and re-billed per batch. |
| Split-and-retry recursively to size 1 | More isolation than needed; one level of halving already recovers the common truncation case, and unbounded recursion adds call-fan-out risk. |
| Raise max_tokens only, keep identical retry | Reduces truncation but leaves the deterministic re-truncation retry unfixed when a batch is genuinely too large for the cap. |
| Do nothing | Invariant tokens keep being re-billed every batch, and failed batches keep burning a wasted identical retry before being dropped. |

---

## Open Questions

| Question | Who decides | Blocks planning? |
|----------|-------------|------------------|
| None outstanding — reorder scope, validation approach, and retry strategy resolved during brainstorming. | — | no |

---

## Amendments *(only after approval — never silently edit approved content)*

- —
