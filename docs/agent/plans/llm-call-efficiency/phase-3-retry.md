# Phase 3: Halve-once-then-skip retry

> **Parent plan:** [plan.md](plan.md)
> **Status:** Complete
> **Depends on:** nothing (independent of Phases 1–2)

---

## Goal

Replace `run_batches`' identical-retry loop with halve-once-then-skip: on a
batch's first failure, split it in two and run each half once (through the
concurrency limit); skip any half that still fails, and skip a failed
single-item batch directly. Confirmed by tests for split-recovery, bad-half
skip, and single-item skip.

## Safety Checklist

- **Touches user input, auth, secrets, or external calls?**
  Indirectly — it orchestrates the model calls, but adds no new input path.
- **Contains a one-way door (schema, public API shape, new dependency)?**
  No. `run_batches`' signature is unchanged.

---

## Tasks

### Task 1: Rewrite run_batches as halve-once-then-skip

- **Files:** `scout/shared/batching.py`, `tests/test_shared_batching.py`
- **Gate:** none
- **Interfaces:**
  - Produces: `run_batches(batch_list, call, *, concurrency, label)` —
    signature unchanged; only failure-recovery behaviour changes.
- **Steps:**
  - [x] Update the existing single-item test to the new semantics (a
        size-1 failure is skipped after **one** attempt, not two) and add
        the split-behaviour tests:
    ```python
    async def test_run_batches_skips_failed_single_item_without_retry(caplog):
        attempts = {"n": 0}

        async def _always_fails(batch):
            attempts["n"] += 1
            raise ValueError("truncated JSON")

        result = await run_batches([[1]], _always_fails, concurrency=1, label="scorer")
        assert result == []
        assert attempts["n"] == 1  # size-1 can't be halved: one try, then skip
        assert "scorer" in caplog.text

    async def test_run_batches_splits_and_recovers_good_half():
        async def _fails_when_big(batch):
            if len(batch) >= 3:
                raise ValueError("truncated JSON")
            return batch

        result = await run_batches(
            [[1, 2, 3, 4]], _fails_when_big, concurrency=2, label="scorer"
        )
        assert sorted(result) == [1, 2, 3, 4]  # halves of size 2 both succeed

    async def test_run_batches_skips_only_the_failing_half():
        async def _fails_on_99(batch):
            if 99 in batch:
                raise ValueError("bad listing")
            return batch

        result = await run_batches(
            [[1, 2, 99, 4]], _fails_on_99, concurrency=2, label="scorer"
        )
        # Whole batch fails -> split [1,2] (ok) + [99,4] (fails, skipped).
        assert sorted(result) == [1, 2]
    ```
  - [x] Delete the old `test_run_batches_retries_once_then_skips`
        (replaced by the single-item test above). Keep
        `test_run_batches_concatenates_results` and
        `test_run_batches_keeps_good_batches_when_one_fails` (still valid).
  - [x] Verify the new tests fail (`pytest tests/test_shared_batching.py -v`) — expect FAILs against the current identical-retry code.
  - [x] Rewrite `run_batches` (remove `_MAX_ATTEMPTS`):
    ```python
    async def run_batches(
        batch_list: list[list[T]],
        call: Callable[[list[T]], Awaitable[list[R]]],
        *,
        concurrency: int,
        label: str,
    ) -> list[R]:
        """Run ``call`` over each batch concurrently, tolerating failure.

        On a batch's first failure the batch is split in half and each half
        is retried once; a half that still fails is skipped with a warning.
        A single-item batch that fails is skipped directly — retrying it
        unchanged at temperature 0 would just reproduce the same truncation.
        A skipped batch costs its listings, not the whole day's run.
        """
        semaphore = asyncio.Semaphore(max(1, concurrency))

        async def _guarded(batch: list[T]) -> list[R]:
            async with semaphore:
                return await call(batch)

        async def _one(batch: list[T]) -> list[R]:
            try:
                return await _guarded(batch)
            except Exception as first_exc:
                if len(batch) <= 1:
                    logger.warning(
                        "%s batch of %d item(s) failed, skipping: %s",
                        label,
                        len(batch),
                        first_exc,
                    )
                    return []
                mid = len(batch) // 2
                logger.info(
                    "%s batch of %d failed, splitting and retrying each half: %s",
                    label,
                    len(batch),
                    first_exc,
                )
                results: list[R] = []
                for half in (batch[:mid], batch[mid:]):
                    try:
                        results.extend(await _guarded(half))
                    except Exception as exc:
                        logger.warning(
                            "%s retry half of %d item(s) failed, skipping: %s",
                            label,
                            len(half),
                            exc,
                        )
                return results

        results = await asyncio.gather(*(_one(batch) for batch in batch_list))
        return [item for batch_result in results for item in batch_result]
    ```
  - [x] Verify all batching tests pass (`pytest tests/test_shared_batching.py -v`).
  - [x] Commit: `feat(batching): halve-once-then-skip on batch failure`

---

## Verification

- [x] Phase tests pass: `pytest tests/test_shared_batching.py -v`
- [x] Full suite green with Postgres up: `docker compose up -d postgres && pytest`

## Observability

On a truncated batch, logs now show an INFO `... splitting and retrying each
half ...` followed by success or a WARNING `... retry half of N ... skipping`,
distinguishing a recovered split from a genuinely dropped half.

## Rollback

Revert the commit; `run_batches` returns to the identical-retry loop. No
state involved.

---

## Notes / Learnings

Went exactly to plan. Full suite (249 tests, Postgres up) passed after all
three phases landed.
