"""Data layer, split by domain to match the sub-agent boundaries.

- ``core``: pool creation and schema application
- ``listings``: listing lifecycle (upsert on scrape, staleness closure)
- ``runs``: run/report persistence (runs, run_listings, gaps, tips)
- ``resources``: the Coach corpus (pgvector inserts, retrieval, link health)

Everything is re-exported here so every existing ``from scout.shared.db
import X`` call site — including tests — keeps working unchanged.
``_content_hash`` is re-exported despite the underscore: ``backfill_hashes``
and its tests must use the exact production fingerprint, not a copy.
"""

from scout.shared.db.core import apply_schema, create_pool
from scout.shared.db.listings import (
    _content_hash,
    close_stale_listings,
    upsert_listing,
)
from scout.shared.db.resources import (
    LinkCheckTransition,
    get_resource_urls,
    get_resources_for_skills,
    get_resources_to_check,
    insert_resource,
    record_link_check,
    vector_text,
)
from scout.shared.db.runs import (
    finish_run,
    get_adjacent_runs,
    get_distinct_gap_skills,
    get_listing_gaps,
    get_run,
    get_run_by_date,
    get_run_details,
    get_run_listings,
    get_run_summaries,
    list_runs,
    record_listing_gaps,
    record_listing_meta,
    record_listing_tips,
    record_run_listings,
    start_run,
)

__all__ = [
    "LinkCheckTransition",
    "_content_hash",
    "apply_schema",
    "close_stale_listings",
    "create_pool",
    "finish_run",
    "get_adjacent_runs",
    "get_distinct_gap_skills",
    "get_listing_gaps",
    "get_resource_urls",
    "get_resources_for_skills",
    "get_resources_to_check",
    "get_run",
    "get_run_by_date",
    "get_run_details",
    "get_run_listings",
    "get_run_summaries",
    "insert_resource",
    "list_runs",
    "record_link_check",
    "record_listing_gaps",
    "record_listing_meta",
    "record_listing_tips",
    "record_run_listings",
    "start_run",
    "upsert_listing",
    "vector_text",
]
