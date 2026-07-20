from __future__ import annotations

from pydantic import TypeAdapter

from scout.shared.parsing import strip_code_fence
from scout.shared.schemas import Listing

_LISTING_LIST_ADAPTER = TypeAdapter(list[Listing])


def parse_listings(raw_text: str) -> list[Listing]:
    return _LISTING_LIST_ADAPTER.validate_json(strip_code_fence(raw_text))
