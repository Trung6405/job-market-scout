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


def test_coach_aggregator_failures_reach_the_run_conclusion():
    """This used to assert the opposite — that the step is continue-on-error —
    and that is how an aggregator which never once completed looked green for
    three days.

    The stated reason for swallowing the error was that a coach failure must not
    block the dashboard deploy or the deallocate. Neither needs the protection:
    `test_coach_aggregator_step_runs_after_dashboard_deploy` above pins the
    deploy to run *earlier*, and the deallocate step is `if: always()`. So the
    only thing continue-on-error bought was silence.
    """
    coach_step = next(
        s for s in _steps() if s["name"] == "Run coach aggregator (weekly)"
    )
    assert coach_step.get("continue-on-error") is not True


def test_coach_aggregator_is_time_bounded():
    """A blocked outbound HTTP call otherwise sits until GitHub's 6-hour
    default, with the VM allocated and billing the whole time.

    The bound is deliberately generous, not tight: a first run against an empty
    corpus throttles GitHub Search per distinct gap skill and then makes one LLM
    tagging call per candidate, serially, so a healthy run is long. The bound
    exists to stop an *indefinite* block, and should be tightened once the
    aggregator's phase timings show what healthy actually costs.
    """
    coach_step = next(
        s for s in _steps() if s["name"] == "Run coach aggregator (weekly)"
    )
    timeout = coach_step.get("timeout-minutes")
    assert isinstance(timeout, int) and 0 < timeout <= 120


def test_coach_aggregator_still_requires_an_earlier_success():
    """Naming any `if:` drops GitHub's implicit success() guard, so it has to be
    restated — otherwise the aggregator runs even after the scout cycle failed,
    which is the one time its input is guaranteed stale."""
    coach_step = next(
        s for s in _steps() if s["name"] == "Run coach aggregator (weekly)"
    )
    assert "success()" in coach_step["if"]


def test_coach_aggregator_step_invokes_the_module():
    coach_step = next(
        s for s in _steps() if s["name"] == "Run coach aggregator (weekly)"
    )
    assert "python -m scout.coach_aggregator" in coach_step["run"]


def test_the_weekly_gate_cannot_be_broken_by_renaming_a_cron():
    """This replaces a guard that pinned the `if:` to a literal cron string.

    That guard's concern was exactly right — if the slot is renamed or dropped,
    a gate matching on it silently stops matching and the aggregator just never
    runs on schedule. The fix removes the coupling instead of pinning it: the
    gate now asks whether the event *was* a schedule at all, so there is no cron
    literal left to drift. Asserting the absence is what keeps someone from
    reintroducing the fragile form.
    """
    coach_step = next(
        s for s in _steps() if s["name"] == "Run coach aggregator (weekly)"
    )
    assert not any(
        f"github.event.schedule == '{cron}'" in coach_step["if"] for cron in _crons()
    )


def test_the_weekly_gate_produces_a_real_skip():
    """The weekday check used to live inside the step's script and `exit 0` on
    the wrong day. That reports the same green tick as a run that did the work,
    so "skipped", "succeeded" and (with continue-on-error) "failed" were one
    indistinguishable state.

    Deciding it in a separate step lets GitHub mark the aggregator `skipped`,
    which is a conclusion you can actually read from the API.
    """
    gate = next((s for s in _steps() if s.get("id") == "aggregation_due"), None)
    assert gate is not None, "expected a gate step with id: aggregation_due"

    coach_step = next(
        s for s in _steps() if s["name"] == "Run coach aggregator (weekly)"
    )
    assert "steps.aggregation_due.outputs" in coach_step["if"]
    assert "date -u" not in coach_step["run"]


def test_link_health_step_runs_between_coach_aggregator_and_deallocate():
    names = [step["name"] for step in _steps()]
    assert "Run coach link-health check (daily)" in names
    coach_idx = names.index("Run coach aggregator (weekly)")
    link_health_idx = names.index("Run coach link-health check (daily)")
    deallocate_idx = names.index("Deallocate VM")
    assert coach_idx < link_health_idx < deallocate_idx


def test_link_health_failures_reach_the_run_conclusion():
    """Same reasoning as the aggregator: the only thing continue-on-error
    protected was the deallocate, which is `if: always()` anyway."""
    step = next(
        s for s in _steps() if s["name"] == "Run coach link-health check (daily)"
    )
    assert step.get("continue-on-error") is not True


def test_link_health_is_time_bounded_and_survives_an_aggregator_failure():
    """It makes outbound HTTP calls, so it can block indefinitely too — but its
    batch cap bounds a healthy run, so this bound can be tight where the
    aggregator's cannot.

    It also has to run when the aggregator failed: verifying links that already
    exist does not depend on new ones having been added. `!cancelled()` rather
    than `always()`, so a cancelled run does not SSH into a VM mid-teardown.
    """
    step = next(
        s for s in _steps() if s["name"] == "Run coach link-health check (daily)"
    )
    timeout = step.get("timeout-minutes")
    assert isinstance(timeout, int) and 0 < timeout <= 30
    assert "cancelled()" in step["if"]


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
