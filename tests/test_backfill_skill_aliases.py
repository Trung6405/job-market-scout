"""The rewrite that brings stored tokens back in step with the rules.

`resources.skills` holds *already-normalised* tokens, so extending the alias
table leaves every existing row spelled the old way — a `nodejs` resource that
the retriever now looks up as `node` and never finds. The rewrite is a pure
lookup rather than a re-tagging run, because aliases map normalised form to
normalised form.

What is worth testing is the planning, not the round-trip: which rows move,
what they move to, and that a row already correct is left alone. A rewrite that
touches every row would be indistinguishable from one that touches the right
ones, right up until it corrupted something.
"""

from __future__ import annotations

from scripts.backfill_skill_aliases import format_report, plan_changes, rewritten


def test_a_stale_token_is_rewritten():
    assert rewritten(["nodejs", "restapi"]) == ["node", "rest"]


def test_an_already_canonical_row_is_not_planned():
    """The plan must exclude no-op rows, or 'rows changed' stops meaning
    anything and a second pass can never report zero."""
    changes = plan_changes([(1, ["node", "python"]), (2, ["nodejs"])])
    assert [c.row_id for c in changes] == [2]


def test_order_is_preserved():
    """The retriever pairs skill names positionally with query embeddings, so
    reordering a stored array silently mismatches vectors to names."""
    assert rewritten(["python", "nodejs", "docker"]) == ["python", "node", "docker"]


def test_two_tokens_collapsing_onto_one_are_deduplicated():
    """A row holding both spellings must not end up with a repeated token."""
    assert rewritten(["node", "nodejs"]) == ["node"]
    assert rewritten(["restapi", "restfulapis", "rest"]) == ["rest"]


def test_a_change_records_both_sides():
    """The dry run's whole job is showing what would happen, which needs the
    before as well as the after."""
    (change,) = plan_changes([(7, ["googlecloudplatform"])])
    assert change.row_id == 7
    assert change.before == ["googlecloudplatform"]
    assert change.after == ["gcp"]


def test_unknown_tokens_are_left_untouched():
    """Only known aliases move. A token this table says nothing about is not
    the backfill's business."""
    assert rewritten(["somethingobscure", "python"]) == ["somethingobscure", "python"]


def test_a_second_pass_over_rewritten_rows_finds_nothing():
    """Idempotency is the property that makes this safe to re-run, and the
    script asserts it against the database after writing. If it ever failed,
    the alias table would contain a cycle and the rewrite would have no fixed
    point."""
    rows = [(1, ["nodejs", "restapi"]), (2, ["googlecloud"]), (3, ["python"])]
    first = plan_changes(rows)
    assert first, "the fixture must actually exercise a rewrite"

    rewritten_rows = [(c.row_id, c.after) for c in first]
    assert plan_changes(rewritten_rows) == []


def test_the_report_distinguishes_a_dry_run_from_a_write():
    """The dry run is the safety mechanism — it names every rewrite at the
    point one is cheapest to veto — so its output must not read as though the
    change already happened."""
    changes = plan_changes([(1, ["nodejs"])])
    assert "would change" in format_report(changes, total=10, dry_run=True)
    assert "would change" not in format_report(changes, total=10, dry_run=False)


def test_the_report_states_the_denominator():
    """'3 rows changed' is unreadable without knowing 3 of how many."""
    report = format_report(plan_changes([(1, ["nodejs"])]), total=957, dry_run=True)
    assert "of 957 rows" in report


def test_the_report_truncates_a_long_change_list():
    """A 900-row rewrite must stay readable in a terminal, while still saying
    how much was elided."""
    changes = plan_changes([(i, ["nodejs"]) for i in range(50)])
    report = format_report(changes, total=50, dry_run=True)
    assert "and 30 more" in report
