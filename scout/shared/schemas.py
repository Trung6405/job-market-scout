from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl

# The Scorer's 0-100 score buckets into one of these qualitative bands via
# advisor.bands.classify_band. Keeping it a closed Literal makes the vocabulary
# type-checked and pydantic-validated end to end; the values stay plain strings
# so the DB column, report filters, and templates are unaffected.
Band = Literal["strong_match", "competitive", "reach"]

# A stated listing requirement is one of these kinds. Only ``skill`` items are
# string-matched against the profile's tech stack and can become gaps; the rest
# are non-technical qualifications shown as context, never gap-matched (fuzzy
# matching free-text degrees/experience is exactly the false-positive source we
# avoid). Closed Literal like ``Band`` so the vocabulary is validated end to end;
# defaults to ``skill`` for backward/forward compatibility (legacy rows and an
# extractor that omits the field both read as skill).
RequirementKind = Literal["skill", "qualification", "experience", "soft_skill"]


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
    band: Band


class ListingScore(BaseModel):
    source: str
    external_id: str
    score: int = Field(ge=0, le=100)
    reasoning: str


class ListingScoreBatch(BaseModel):
    scores: list[ListingScore]


class RequirementItem(BaseModel):
    name: str
    kind: RequirementKind = "skill"


class ListingRequirements(BaseModel):
    source: str
    external_id: str
    must_have: list[RequirementItem]
    nice_to_have: list[RequirementItem]
    seniority: str | None = None
    work_type: str | None = None
    team: str | None = None


class ListingRequirementsBatch(BaseModel):
    requirements: list[ListingRequirements]


class SkillGap(BaseModel):
    skill: str
    requirement_level: str
    met: bool = False
    kind: RequirementKind = "skill"


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


class RunListingDetail(BaseModel):
    run_listing_id: int
    listing: Listing
    score: int
    reasoning: str
    band: Band
    gaps: list[SkillGap]
    requirements: list[SkillGap] = []
    seniority: str | None = None
    work_type: str | None = None
    team: str | None = None


class Profile(BaseModel):
    name: str
    target_role: str
    target_locations: list[str]
    tech_stack: list[TechCategory]
    domain_knowledge: list[DomainKnowledge]
    background: Background
    projects: list[Project]