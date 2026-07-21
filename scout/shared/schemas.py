from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, HttpUrl


class Listing(BaseModel):
    source: str
    external_id: str
    title: str
    company: str
    location: str
    is_remote: bool
    url: HttpUrl
    description: str
    salary_min: float | None = None
    salary_max: float | None = None
    date_posted: datetime | None = None
    scraped_at: datetime

class MatchResult(BaseModel):
    listing: Listing
    score: int
    reasoning: str


class ListingScore(BaseModel):
    source: str
    external_id: str
    score: int = Field(ge=0, le=100)
    reasoning: str


class ListingScoreBatch(BaseModel):
    scores: list[ListingScore]


class BriefingTakeaway(BaseModel):
    source: str
    external_id: str
    takeaway: str


class BriefingProse(BaseModel):
    intro: str
    takeaways: list[BriefingTakeaway]