from __future__ import annotations

import logging
from datetime import datetime

from pydantic import ValidationError

from scout.shared.schemas import Listing

logger = logging.getLogger(__name__)


def normalize_job(job: dict, scraped_at: datetime) -> Listing | None:
    """Convert one scraped job into a Listing, or None if it isn't usable.

    ``site`` and ``id`` are guarded alongside the display fields because
    together they are the primary key every later stage joins on. The
    blanket ``ValidationError`` catch is deliberate: a single malformed job
    out of a hundred should cost that job, not the whole scrape.
    """
    title = job.get("title")
    company = job.get("company")
    url = job.get("jobUrl")
    source = job.get("site")
    external_id = job.get("id")
    if not title or not company or not url or not source or not external_id:
        logger.warning(
            "skipping job with missing required field(s): "
            "site=%r id=%r title=%r company=%r url=%r",
            source,
            external_id,
            title,
            company,
            url,
        )
        return None

    try:
        return Listing(
            source=source,
            external_id=external_id,
            title=title,
            company=company,
            location=job.get("location") or "",
            is_remote=bool(job.get("isRemote")),
            url=url,
            description=job.get("description") or "",
            salary_min=job.get("minAmount"),
            salary_max=job.get("maxAmount"),
            date_posted=job.get("datePosted"),
            scraped_at=scraped_at,
        )
    except ValidationError as exc:
        logger.warning("skipping job %s/%s: %s", source, external_id, exc)
        return None
