from __future__ import annotations

import pytest

from scout.config import Settings
from scout.shared.schemas import ListingScore, ListingScoreBatch
from scout.sub_agents.scorer import runner


def _score(**overrides) -> ListingScore:
    defaults = dict(source="linkedin", external_id="1", score=75, reasoning="Good fit.")
    defaults.update(overrides)
    return ListingScore(**defaults)


@pytest.mark.asyncio
async def test_run_scorer_returns_scores_from_complete_json(monkeypatch, listing_factory):
    async def _fake_complete_json(prompt, schema, settings, **kwargs):
        assert schema is ListingScoreBatch
        return ListingScoreBatch(scores=[_score()])

    monkeypatch.setattr(runner, "complete_json", _fake_complete_json)

    scores = await runner.run_scorer([listing_factory(external_id="1")], Settings())

    assert scores == [_score()]


@pytest.mark.asyncio
async def test_run_scorer_batches_by_configured_size(monkeypatch, listing_factory):
    """One response must cover its whole batch, and the model caps output
    tokens, so a large run is split into batches small enough to parse —
    the same reason extraction is batched (see advisor/runner.py)."""
    listings = [listing_factory(external_id=str(i)) for i in range(5)]
    call_count = {"n": 0}

    async def _fake_complete_json(prompt, schema, settings, **kwargs):
        call_count["n"] += 1
        ids = [l.external_id for l in listings if f'"external_id": "{l.external_id}"' in prompt]
        return ListingScoreBatch(scores=[_score(external_id=i) for i in ids])

    monkeypatch.setattr(runner, "complete_json", _fake_complete_json)

    settings = Settings()
    object.__setattr__(settings, "scorer_batch_size", 2)
    scores = await runner.run_scorer(listings, settings)

    assert call_count["n"] == 3  # 5 listings at batch size 2 -> 3 calls
    assert sorted(s.external_id for s in scores) == ["0", "1", "2", "3", "4"]


@pytest.mark.asyncio
async def test_run_scorer_makes_no_llm_call_for_no_listings(monkeypatch):
    async def _should_not_be_called(*args, **kwargs):
        raise AssertionError("no call expected for an empty listing set")

    monkeypatch.setattr(runner, "complete_json", _should_not_be_called)

    assert await runner.run_scorer([], Settings()) == []
