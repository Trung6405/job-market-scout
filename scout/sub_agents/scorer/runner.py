from __future__ import annotations

from pydantic import TypeAdapter

from scout.shared.parsing import strip_code_fence
from scout.shared.schemas import ListingScore

_SCORE_LIST_ADAPTER = TypeAdapter(list[ListingScore])


def parse_scores(raw_text: str) -> list[ListingScore]:
    return _SCORE_LIST_ADAPTER.validate_json(strip_code_fence(raw_text))
