from __future__ import annotations

import json

from scout.shared.schemas import ListingScore
from scout.sub_agents.scorer.runner import parse_scores


def _score_dict(**overrides):
    defaults = dict(source="linkedin", external_id="1", score=75, reasoning="Good fit.")
    defaults.update(overrides)
    return defaults


def test_parse_scores_valid_json():
    raw = json.dumps([_score_dict()])

    scores = parse_scores(raw)

    assert scores == [ListingScore(**_score_dict())]


def test_parse_scores_strips_markdown_code_fence():
    raw = "```json\n" + json.dumps([_score_dict(external_id="2")]) + "\n```"

    scores = parse_scores(raw)

    assert scores[0].external_id == "2"


def test_parse_scores_empty_list():
    assert parse_scores("[]") == []
