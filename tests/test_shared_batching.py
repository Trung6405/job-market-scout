from __future__ import annotations

from scout.shared.batching import batches, run_batches


def test_batches_splits_by_size():
    assert batches([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]


def test_batches_treats_zero_size_as_one():
    assert batches([1, 2], 0) == [[1], [2]]


def test_batches_of_empty_list_is_empty():
    assert batches([], 5) == []


async def test_run_batches_concatenates_results():
    async def _call(batch):
        return [item * 10 for item in batch]

    result = await run_batches([[1, 2], [3]], _call, concurrency=2, label="test")
    assert sorted(result) == [10, 20, 30]


async def test_run_batches_skips_failed_single_item_without_retry(caplog):
    attempts = {"n": 0}

    async def _always_fails(batch):
        attempts["n"] += 1
        raise ValueError("truncated JSON")

    result = await run_batches([[1]], _always_fails, concurrency=1, label="scorer")
    assert result == []
    assert attempts["n"] == 1  # size-1 can't be halved: one try, then skip
    assert "scorer" in caplog.text


async def test_run_batches_keeps_good_batches_when_one_fails():
    async def _fail_first(batch):
        if batch == [1]:
            raise ValueError("bad")
        return batch

    result = await run_batches([[1], [2]], _fail_first, concurrency=1, label="scorer")
    assert result == [2]


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
