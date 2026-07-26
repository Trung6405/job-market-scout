from __future__ import annotations

from pathlib import Path

import yaml

_WORKFLOW_PATH = (
    Path(__file__).resolve().parent.parent / ".github" / "workflows" / "scheduled-run.yml"
)


def _steps() -> list[dict]:
    workflow = yaml.safe_load(_WORKFLOW_PATH.read_text(encoding="utf-8"))
    return workflow["jobs"]["run-job"]["steps"]


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
