from __future__ import annotations

from datetime import datetime

from scout.shared.schemas import Listing


def normalize_job(job: dict, scraped_at: datetime) -> Listing | None:
    title = job.get("title")
    company = job.get("company")
    url = job.get("jobUrl")
    if not title or not company or not url:
        return None

    return Listing(
        source=job.get("site"),
        external_id=job.get("id"),
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
