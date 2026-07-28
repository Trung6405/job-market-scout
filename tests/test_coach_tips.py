from __future__ import annotations

import pytest

from scout.config import Settings
from scout.shared.schemas import (
    GeneratedTip,
    GeneratedTips,
    RetrievedResource,
    SkillGap,
)
from scout.sub_agents.coach import tips as tips_module

pytestmark = pytest.mark.asyncio


def _resource(url: str) -> RetrievedResource:
    return RetrievedResource(
        url=url,
        title="examples",
        resource_type="repo",
        skills=["kubernetes"],
        summary="Worked examples.",
        similarity=0.9,
    )


@pytest.fixture
def stub_llm(monkeypatch):
    """Record prompts and reply with one tip per requested skill."""
    calls = []

    async def _complete_json(prompt, schema, settings, **kwargs):
        calls.append(prompt)
        skills = [
            skill for skill in ("Kubernetes", "Terraform") if skill in prompt
        ]
        return GeneratedTips(
            tips=[
                GeneratedTip(
                    gap_skill=skill,
                    tip=f"Start with https://github.com/k/examples for {skill}.",
                )
                for skill in skills
            ]
        )

    monkeypatch.setattr(tips_module, "complete_json", _complete_json)
    return calls


@pytest.fixture
def stub_retriever(monkeypatch):
    """Record retrieval calls; cover Kubernetes only."""
    calls = []

    async def _retrieve(conn, skills, settings=None, k=None):
        calls.append(list(skills))
        return {
            skill: (
                [_resource("https://github.com/k/examples")]
                if skill == "Kubernetes"
                else []
            )
            for skill in skills
        }

    monkeypatch.setattr(tips_module, "retrieve_for_skills", _retrieve)
    return calls


async def test_retrieval_runs_once_for_the_whole_run(
    stub_llm, stub_retriever, match_factory, listing_factory
):
    first = match_factory(listing=listing_factory(external_id="a"))
    second = match_factory(listing=listing_factory(external_id="b"))
    gap = SkillGap(skill="Kubernetes", requirement_level="must_have", met=False)

    await tips_module.run_grounded_tips(
        None, [(first, [gap]), (second, [gap])], Settings()
    )

    assert len(stub_retriever) == 1
    assert len(stub_llm) == 2  # one call per listing


async def test_listing_without_coverage_is_never_sent_to_the_model(
    stub_llm, stub_retriever, match_factory, listing_factory
):
    match = match_factory(listing=listing_factory(external_id="a"))
    gap = SkillGap(skill="Terraform", requirement_level="must_have", met=False)

    result = await tips_module.run_grounded_tips(None, [(match, [gap])], Settings())

    assert stub_llm == []
    assert result == [(match, [])]


async def test_only_unmet_skill_gaps_are_tipped(
    stub_llm, stub_retriever, match_factory, listing_factory
):
    match = match_factory(listing=listing_factory(external_id="a"))
    checks = [
        SkillGap(skill="Kubernetes", requirement_level="must_have", met=False),
        SkillGap(skill="Terraform", requirement_level="must_have", met=True),
        SkillGap(
            skill="Bachelor's degree",
            requirement_level="must_have",
            met=False,
            kind="qualification",
        ),
    ]

    await tips_module.run_grounded_tips(None, [(match, checks)], Settings())

    assert stub_retriever == [["Kubernetes"]]


async def test_must_have_gaps_win_the_per_listing_cap(
    stub_llm, stub_retriever, monkeypatch, match_factory, listing_factory
):
    # Settings is a frozen dataclass — build a capped one from the
    # environment rather than mutating an instance.
    monkeypatch.setenv("COACH_TIPS_MAX_GAPS_PER_LISTING", "1")
    match = match_factory(listing=listing_factory(external_id="a"))
    checks = [
        SkillGap(skill="Terraform", requirement_level="nice_to_have", met=False),
        SkillGap(skill="Kubernetes", requirement_level="must_have", met=False),
    ]

    await tips_module.run_grounded_tips(None, [(match, checks)], Settings())

    assert stub_retriever == [["Kubernetes"]]


async def test_failed_call_skips_only_its_listing(
    stub_retriever, monkeypatch, match_factory, listing_factory
):
    async def _boom(prompt, schema, settings, **kwargs):
        if "listing-b" in prompt:
            raise ValueError("model returned no content")
        return GeneratedTips(
            tips=[
                GeneratedTip(
                    gap_skill="Kubernetes",
                    tip="Read https://github.com/k/examples.",
                )
            ]
        )

    monkeypatch.setattr(tips_module, "complete_json", _boom)
    good = match_factory(listing=listing_factory(external_id="a", title="listing-a"))
    bad = match_factory(listing=listing_factory(external_id="b", title="listing-b"))
    gap = SkillGap(skill="Kubernetes", requirement_level="must_have", met=False)

    result = await tips_module.run_grounded_tips(
        None, [(good, [gap]), (bad, [gap])], Settings()
    )

    by_id = {m.listing.external_id: tips for m, tips in result}
    assert len(by_id["a"]) == 1
    assert by_id["b"] == []


import logging


def _reply(*pairs):
    async def _complete_json(prompt, schema, settings, **kwargs):
        return GeneratedTips(
            tips=[GeneratedTip(gap_skill=skill, tip=tip) for skill, tip in pairs]
        )

    return _complete_json


async def test_fabricated_url_is_stripped_and_logged(
    stub_retriever, monkeypatch, caplog, match_factory, listing_factory
):
    monkeypatch.setattr(
        tips_module,
        "complete_json",
        _reply(
            (
                "Kubernetes",
                "Read https://kubernetes.io/invented and "
                "https://github.com/k/examples.",
            )
        ),
    )
    match = match_factory(listing=listing_factory(external_id="a"))
    gap = SkillGap(skill="Kubernetes", requirement_level="must_have", met=False)

    with caplog.at_level(logging.WARNING):
        result = await tips_module.run_grounded_tips(
            None, [(match, [gap])], Settings()
        )

    tip = result[0][1][0]
    assert "invented" not in tip.tip
    assert tip.cited_urls == ["https://github.com/k/examples"]
    assert "https://kubernetes.io/invented" in caplog.text


async def test_tip_left_citing_nothing_is_dropped(
    stub_retriever, monkeypatch, match_factory, listing_factory
):
    monkeypatch.setattr(
        tips_module,
        "complete_json",
        _reply(("Kubernetes", "Just read https://kubernetes.io/invented.")),
    )
    match = match_factory(listing=listing_factory(external_id="a"))
    gap = SkillGap(skill="Kubernetes", requirement_level="must_have", met=False)

    result = await tips_module.run_grounded_tips(None, [(match, [gap])], Settings())

    assert result == [(match, [])]


async def test_tip_citing_no_url_at_all_is_dropped(
    stub_retriever, monkeypatch, match_factory, listing_factory
):
    """Distinct from the fabricated-URL case: nothing is stripped, there is
    simply nothing to cite. Uncited prose is the static-template advice this
    stage exists to replace, so it is not worth storing."""
    monkeypatch.setattr(
        tips_module,
        "complete_json",
        _reply(("Kubernetes", "Just practise more and read the docs.")),
    )
    match = match_factory(listing=listing_factory(external_id="a"))
    gap = SkillGap(skill="Kubernetes", requirement_level="must_have", met=False)

    result = await tips_module.run_grounded_tips(None, [(match, [gap])], Settings())

    assert result == [(match, [])]


async def test_duplicate_tips_for_one_gap_keep_only_the_first(
    stub_retriever, monkeypatch, caplog, match_factory, listing_factory
):
    """One row per covered gap. `listing_tips` has no unique constraint to
    lean on — `record_listing_tips` inserts with `executemany` and no
    `ON CONFLICT`, so a constraint would fail the write instead of degrading,
    and a duplicate would give P4 a doubled card."""
    monkeypatch.setattr(
        tips_module,
        "complete_json",
        _reply(
            ("Kubernetes", "First: read https://github.com/k/examples."),
            ("Kubernetes", "Second: also read https://github.com/k/examples."),
        ),
    )
    match = match_factory(listing=listing_factory(external_id="a"))
    gap = SkillGap(skill="Kubernetes", requirement_level="must_have", met=False)

    with caplog.at_level(logging.WARNING):
        result = await tips_module.run_grounded_tips(
            None, [(match, [gap])], Settings()
        )

    tips = result[0][1]
    assert len(tips) == 1
    assert tips[0].tip.startswith("First:")
    assert "duplicate tip" in caplog.text


async def test_duplicate_is_measured_against_stored_tips_not_returned_ones(
    stub_retriever, monkeypatch, match_factory, listing_factory
):
    """A lead tip dropped for citing nothing must not also cost the gap the
    grounded tip that followed it — the cap is one *stored* row per gap."""
    monkeypatch.setattr(
        tips_module,
        "complete_json",
        _reply(
            ("Kubernetes", "Just practise more."),
            ("Kubernetes", "Read https://github.com/k/examples."),
        ),
    )
    match = match_factory(listing=listing_factory(external_id="a"))
    gap = SkillGap(skill="Kubernetes", requirement_level="must_have", met=False)

    result = await tips_module.run_grounded_tips(None, [(match, [gap])], Settings())

    tips = result[0][1]
    assert len(tips) == 1
    assert tips[0].cited_urls == ["https://github.com/k/examples"]


async def test_tip_for_unrequested_skill_is_dropped(
    stub_retriever, monkeypatch, match_factory, listing_factory
):
    monkeypatch.setattr(
        tips_module,
        "complete_json",
        _reply(("Rust", "Learn Rust at https://github.com/k/examples.")),
    )
    match = match_factory(listing=listing_factory(external_id="a"))
    gap = SkillGap(skill="Kubernetes", requirement_level="must_have", met=False)

    result = await tips_module.run_grounded_tips(None, [(match, [gap])], Settings())

    assert result == [(match, [])]


async def test_cross_gap_url_is_stripped(
    monkeypatch, match_factory, listing_factory
):
    """Both gaps' resources share one prompt, so a real URL cited under the
    wrong skill is the cheapest hallucination available — and the one a
    per-listing allowlist would miss."""

    async def _retrieve(conn, skills, settings=None, k=None):
        return {
            "Kubernetes": [_resource("https://github.com/k/examples")],
            "Terraform": [_resource("https://github.com/t/modules")],
        }

    monkeypatch.setattr(tips_module, "retrieve_for_skills", _retrieve)
    monkeypatch.setattr(
        tips_module,
        "complete_json",
        _reply(
            (
                "Kubernetes",
                "Start with https://github.com/t/modules and "
                "https://github.com/k/examples.",
            )
        ),
    )
    match = match_factory(listing=listing_factory(external_id="a"))
    gaps = [
        SkillGap(skill="Kubernetes", requirement_level="must_have", met=False),
        SkillGap(skill="Terraform", requirement_level="must_have", met=False),
    ]

    result = await tips_module.run_grounded_tips(None, [(match, gaps)], Settings())

    tip = result[0][1][0]
    assert tip.cited_urls == ["https://github.com/k/examples"]
    assert "t/modules" not in tip.tip
