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


async def test_run_batches_retries_once_then_skips(caplog):
    attempts = {"n": 0}

    async def _always_fails(batch):
        attempts["n"] += 1
        raise ValueError("truncated JSON")

    result = await run_batches([[1]], _always_fails, concurrency=1, label="scorer")
    assert result == []
    assert attempts["n"] == 2
    assert "scorer batch failed" in caplog.text


async def test_run_batches_keeps_good_batches_when_one_fails():
    async def _fail_first(batch):
        if batch == [1]:
            raise ValueError("bad")
        return batch

    result = await run_batches([[1], [2]], _fail_first, concurrency=1, label="scorer")
    assert result == [2]
