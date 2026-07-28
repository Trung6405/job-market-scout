from __future__ import annotations

import pytest

from scout.shared.schemas import LinkHealthSummary


@pytest.mark.asyncio
async def test_run_once_logs_summary(monkeypatch, caplog):
    async def _fake_run_link_health(settings=None):
        return LinkHealthSummary(
            checked=10,
            verified=6,
            recovered=1,
            newly_dead=1,
            still_dead=1,
            failing=1,
        )

    monkeypatch.setattr(
        "scout.coach_link_health.run_link_health", _fake_run_link_health
    )

    from scout.coach_link_health import run_once

    with caplog.at_level("INFO"):
        await run_once()

    assert "6 verified" in caplog.text
    assert "1 recovered" in caplog.text
    assert "1 newly dead" in caplog.text


def test_main_exits_nonzero_when_run_once_raises(monkeypatch):
    async def _fake_run_once():
        raise RuntimeError("boom")

    monkeypatch.setattr("scout.coach_link_health.run_once", _fake_run_once)

    from scout.coach_link_health import main

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
