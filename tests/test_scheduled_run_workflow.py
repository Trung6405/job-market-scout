from __future__ import annotations

from pathlib import Path

import yaml

_WORKFLOW_PATH = (
    Path(__file__).resolve().parent.parent / ".github" / "workflows" / "scheduled-run.yml"
)


def _workflow() -> dict:
    return yaml.safe_load(_WORKFLOW_PATH.read_text(encoding="utf-8"))


def _steps() -> list[dict]:
    return _workflow()["jobs"]["run-job"]["steps"]


def _crons() -> list[str]:
    # YAML 1.1 (which PyYAML implements) resolves the bare key `on` to the
    # boolean True, so the triggers block is not under the string "on".
    triggers = _workflow()[True]
    return [entry["cron"] for entry in triggers["schedule"]]


def test_pipeline_is_scheduled_once_a_day():
    """One cron fire per day: a second one only re-briefed listings the first
    run had already claimed, so it near-always sent an empty Discord brief."""
    assert _crons() == ["0 19 * * *"]


def test_coach_aggregator_step_runs_between_dashboard_deploy_and_deallocate():
    names = [step["name"] for step in _steps()]
    assert "Run coach aggregator (weekly)" in names
    deploy_idx = names.index("Deploy dashboard to Storage static website")
    coach_idx = names.index("Run coach aggregator (weekly)")
    deallocate_idx = names.index("Deallocate VM")
    assert deploy_idx < coach_idx < deallocate_idx


def test_coach_aggregator_step_does_not_block_the_job():
    coach_step = next(
        s for s in _steps() if s["name"] == "Run coach aggregator (weekly)"
    )
    assert coach_step.get("continue-on-error") is True


def test_coach_aggregator_step_invokes_the_module():
    coach_step = next(
        s for s in _steps() if s["name"] == "Run coach aggregator (weekly)"
    )
    assert "python -m scout.coach_aggregator" in coach_step["run"]


def test_coach_aggregator_is_gated_on_a_cron_that_actually_exists():
    """The weekly coach piggybacks on a named cron slot. If that slot is ever
    renamed or dropped, the `if:` silently stops matching and the aggregator
    just never runs on schedule — so pin the gate to a live cron."""
    coach_step = next(
        s for s in _steps() if s["name"] == "Run coach aggregator (weekly)"
    )
    assert any(f"github.event.schedule == '{cron}'" in coach_step["if"] for cron in _crons())


def test_link_health_step_runs_between_coach_aggregator_and_deallocate():
    names = [step["name"] for step in _steps()]
    assert "Run coach link-health check (daily)" in names
    coach_idx = names.index("Run coach aggregator (weekly)")
    link_health_idx = names.index("Run coach link-health check (daily)")
    deallocate_idx = names.index("Deallocate VM")
    assert coach_idx < link_health_idx < deallocate_idx


def test_link_health_step_does_not_block_the_job():
    step = next(
        s for s in _steps() if s["name"] == "Run coach link-health check (daily)"
    )
    assert step.get("continue-on-error") is True


def test_link_health_step_invokes_the_module():
    step = next(
        s for s in _steps() if s["name"] == "Run coach link-health check (daily)"
    )
    assert "python -m scout.coach_link_health" in step["run"]


def test_link_health_step_runs_every_scheduled_fire_not_just_one_weekday():
    """Unlike the weekly aggregator, the link check should run on every daily
    cron fire — that's what makes it happen *between* aggregations."""
    step = next(
        s for s in _steps() if s["name"] == "Run coach link-health check (daily)"
    )
    assert "if" not in step or "date -u +%u" not in step["run"]
