from __future__ import annotations

from scout.shared.schemas import (
    GeneratedTip,
    GeneratedTips,
    GroundedTip,
    RunListingDetail,
)


def test_grounded_tip_carries_skill_text_and_citations():
    tip = GroundedTip(
        gap_skill="Kubernetes",
        tip="Work through kubernetes/examples (https://github.com/k/examples).",
        cited_urls=["https://github.com/k/examples"],
    )
    assert tip.gap_skill == "Kubernetes"
    assert tip.cited_urls == ["https://github.com/k/examples"]


def test_generated_tips_parses_model_output_keyed_by_skill():
    parsed = GeneratedTips.model_validate_json(
        '{"tips": [{"skill": "Kubernetes", "tip": "Work through the examples."}]}'
    )
    assert parsed.tips[0].gap_skill == "Kubernetes"
    assert parsed.tips[0].tip == "Work through the examples."


def test_generated_tip_constructs_by_field_name():
    tip = GeneratedTip(gap_skill="Kubernetes", tip="Work through the examples.")
    assert tip.gap_skill == "Kubernetes"


def test_run_listing_detail_defaults_tips_to_empty(listing_factory):
    detail = RunListingDetail(
        run_listing_id=1,
        listing=listing_factory(),
        score=80,
        reasoning="fits",
        band="competitive",
        gaps=[],
    )
    assert detail.tips == []
