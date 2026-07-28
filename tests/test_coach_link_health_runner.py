from __future__ import annotations

import pytest

from scout.config import Settings
from scout.shared.schemas import LinkCheck
from scout.sub_agents.coach import link_health


class _FakeConn:
    pass


class _FakeAcquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc_info):
        return False


class _FakePool:
    def __init__(self, conn):
        self._conn = conn
        self.closed = False

    def acquire(self):
        return _FakeAcquire(self._conn)

    async def close(self):
        self.closed = True


def _settings(**overrides) -> Settings:
    return Settings(**overrides)


def _rows(*urls: str) -> list[dict]:
    return [{"id": index + 1, "url": url} for index, url in enumerate(urls)]


def _patch_pool(monkeypatch):
    conn = _FakeConn()
    pool = _FakePool(conn)

    async def _fake_create_pool(settings):
        return pool

    monkeypatch.setattr(link_health, "create_pool", _fake_create_pool)
    return conn, pool


@pytest.mark.asyncio
async def test_run_link_health_checks_exactly_the_batch(monkeypatch):
    _patch_pool(monkeypatch)
    batch = _rows("https://example.com/a", "https://example.com/b")

    async def _fake_get_resources_to_check(conn, limit):
        return batch

    checked_urls = []

    def _fake_check_url(url, settings):
        checked_urls.append(url)
        return LinkCheck(verdict="healthy")

    async def _fake_record_link_check(conn, resource_id, verdict, reason, max_failures):
        return "verified"

    monkeypatch.setattr(
        link_health, "get_resources_to_check", _fake_get_resources_to_check
    )
    monkeypatch.setattr(link_health, "check_url", _fake_check_url)
    monkeypatch.setattr(link_health, "record_link_check", _fake_record_link_check)
    monkeypatch.setattr(link_health.time, "sleep", lambda seconds: None)

    summary = await link_health.run_link_health(_settings())

    assert checked_urls == ["https://example.com/a", "https://example.com/b"]
    assert summary.checked == 2
    assert summary.verified == 2


@pytest.mark.asyncio
async def test_run_link_health_tallies_every_transition(monkeypatch):
    _patch_pool(monkeypatch)
    batch = _rows(*[f"https://example.com/{i}" for i in range(6)])
    transitions = iter(
        ["verified", "recovered", "newly_dead", "still_dead", "failing", "verified"]
    )

    async def _fake_get_resources_to_check(conn, limit):
        return batch

    monkeypatch.setattr(
        link_health, "get_resources_to_check", _fake_get_resources_to_check
    )
    monkeypatch.setattr(
        link_health, "check_url", lambda url, settings: LinkCheck(verdict="healthy")
    )

    async def _fake_record_link_check(conn, resource_id, verdict, reason, max_failures):
        return next(transitions)

    monkeypatch.setattr(link_health, "record_link_check", _fake_record_link_check)
    monkeypatch.setattr(link_health.time, "sleep", lambda seconds: None)

    summary = await link_health.run_link_health(_settings())

    assert summary.checked == 6
    assert summary.verified == 2
    assert summary.recovered == 1
    assert summary.newly_dead == 1
    assert summary.still_dead == 1
    assert summary.failing == 1


@pytest.mark.asyncio
async def test_run_link_health_keeps_going_when_one_check_raises(monkeypatch):
    """One URL's check_url call raising must not abandon the rest of the batch."""
    _patch_pool(monkeypatch)
    batch = _rows("https://example.com/boom", "https://example.com/fine")

    async def _fake_get_resources_to_check(conn, limit):
        return batch

    def _fake_check_url(url, settings):
        if url == "https://example.com/boom":
            raise RuntimeError("unexpected failure")
        return LinkCheck(verdict="healthy")

    recorded = []

    async def _fake_record_link_check(conn, resource_id, verdict, reason, max_failures):
        recorded.append((resource_id, verdict))
        return "failing" if verdict == "transient" else "verified"

    monkeypatch.setattr(
        link_health, "get_resources_to_check", _fake_get_resources_to_check
    )
    monkeypatch.setattr(link_health, "check_url", _fake_check_url)
    monkeypatch.setattr(link_health, "record_link_check", _fake_record_link_check)
    monkeypatch.setattr(link_health.time, "sleep", lambda seconds: None)

    summary = await link_health.run_link_health(_settings())

    assert summary.checked == 2
    assert recorded == [(1, "transient"), (2, "healthy")]
    assert summary.failing == 1
    assert summary.verified == 1


@pytest.mark.asyncio
async def test_run_link_health_empty_batch_is_a_valid_zero_count_run(monkeypatch):
    _patch_pool(monkeypatch)

    async def _fake_get_resources_to_check(conn, limit):
        return []

    def _explode(*a, **k):
        raise AssertionError("should not be called on an empty batch")

    monkeypatch.setattr(
        link_health, "get_resources_to_check", _fake_get_resources_to_check
    )
    monkeypatch.setattr(link_health, "check_url", _explode)
    monkeypatch.setattr(link_health, "record_link_check", _explode)

    summary = await link_health.run_link_health(_settings())

    assert summary.checked == 0
    assert summary.verified == 0
    assert summary.recovered == 0
    assert summary.newly_dead == 0
    assert summary.still_dead == 0
    assert summary.failing == 0


@pytest.mark.asyncio
async def test_run_link_health_passes_configured_batch_and_threshold(monkeypatch):
    _, pool = _patch_pool(monkeypatch)
    captured = {}

    async def _fake_get_resources_to_check(conn, limit):
        captured["limit"] = limit
        return []

    monkeypatch.setattr(
        link_health, "get_resources_to_check", _fake_get_resources_to_check
    )

    await link_health.run_link_health(_settings(coach_link_health_batch=7))

    assert captured["limit"] == 7
    assert pool.closed is True
