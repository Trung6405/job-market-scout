from __future__ import annotations

import pytest

from scout.shared.schemas import CoachSummary


@pytest.mark.asyncio
async def test_run_once_logs_summary(monkeypatch, caplog):
    async def _fake_run_coach_aggregator(settings=None):
        return CoachSummary(candidates_seen=4, inserted=2, duplicates=2)

    monkeypatch.setattr(
        "scout.coach_aggregator.run_coach_aggregator", _fake_run_coach_aggregator
    )

    from scout.coach_aggregator import run_once

    with caplog.at_level("INFO"):
        await run_once()

    assert "2 inserted" in caplog.text


def test_main_exits_nonzero_when_run_once_raises(monkeypatch):
    async def _fake_run_once():
        raise RuntimeError("boom")

    monkeypatch.setattr("scout.coach_aggregator.run_once", _fake_run_once)

    from scout.coach_aggregator import main

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
