from __future__ import annotations

from datetime import date, datetime

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


class Run(BaseModel):
    id: int
    run_date: date
    started_at: datetime
    finished_at: datetime | None = None
    listings_scraped: int
    listings_scored: int


class RunListing(BaseModel):
    id: int
    run_id: int
    listing_id: int
    score: int
    reasoning: str
    band: str


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


class TechSkill(BaseModel):
    name: str
    proficiency: int = Field(ge=1, le=5)
    note: str | None = None


class TechCategory(BaseModel):
    category: str
    skills: list[TechSkill]


class DomainKnowledge(BaseModel):
    name: str
    proficiency: int = Field(ge=0, le=100)
    description: str

    @property
    def level(self) -> str:
        if self.proficiency >= 70:
            return "Solid"
        if self.proficiency >= 50:
            return "Good"
        if self.proficiency >= 30:
            return "Developing"
        return "Emerging"


class Background(BaseModel):
    education: str
    experience: str
    preferred_roles: list[str]
    locations: list[str]


class Project(BaseModel):
    title: str
    description: str
    tags: list[str]


class Profile(BaseModel):
    name: str
    target_role: str
    target_locations: list[str]
    tech_stack: list[TechCategory]
    domain_knowledge: list[DomainKnowledge]
    background: Background
    projects: list[Project]