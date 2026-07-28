from __future__ import annotations

from datetime import datetime, timezone

from scripts.audit_link_health import summarize


def _row(**overrides):
    defaults = {
        "url": "https://example.com/r",
        "last_verified": None,
        "dead_since": None,
        "consecutive_failures": 0,
        "last_check_error": None,
    }
    defaults.update(overrides)
    return defaults


def test_summarize_empty_corpus():
    counts = summarize([])
    assert counts["total"] == 0
    assert counts["live"] == 0
    assert counts["dead"] == 0
    assert counts["never_checked"] == 0
    assert counts["failing"] == 0


def test_summarize_counts_live_dead_never_checked_and_failing():
    now = datetime.now(timezone.utc)
    rows = [
        _row(url="https://example.com/live", last_verified=now),
        _row(url="https://example.com/never"),
        _row(url="https://example.com/dead", dead_since=now, consecutive_failures=3),
        _row(url="https://example.com/failing", last_verified=now, consecutive_failures=2),
    ]

    counts = summarize(rows)

    assert counts["total"] == 4
    assert counts["dead"] == 1
    assert counts["never_checked"] == 1
    assert counts["failing"] == 1
    # live = total - dead: everything still in circulation, whether never
    # checked, failing-but-not-dead, or cleanly verified.
    assert counts["live"] == 3


def test_summarize_dead_resource_is_not_also_counted_never_checked():
    """A resource dies before its first successful last_verified stamp is
    possible (a `gone` verdict never sets last_verified) — it must count as
    dead, not as never-checked."""
    rows = [_row(url="https://example.com/dead-unverified", dead_since=datetime.now(timezone.utc))]

    counts = summarize(rows)

    assert counts["dead"] == 1
    assert counts["never_checked"] == 0
