from __future__ import annotations

from datetime import datetime, timezone

from scout.sub_agents.scraper.normalize import normalize_job

_SCRAPED_AT = datetime(2026, 7, 20, tzinfo=timezone.utc)


def _job(**overrides):
    defaults = dict(
        id="in-1",
        site="indeed",
        jobUrl="https://www.indeed.com/viewjob?jk=1",
        title="Backend Engineer",
        company="Acme Corp",
        location="Remote, US",
        datePosted="2026-07-19T00:00:00.000Z",
        minAmount=100000,
        maxAmount=120000,
        isRemote=True,
        description="Build backend systems.",
    )
    defaults.update(overrides)
    return defaults


def test_normalize_job_maps_all_fields():
    listing = normalize_job(_job(), _SCRAPED_AT)

    assert listing is not None
    assert listing.source == "indeed"
    assert listing.external_id == "in-1"
    assert listing.title == "Backend Engineer"
    assert listing.company == "Acme Corp"
    assert listing.location == "Remote, US"
    assert str(listing.url) == "https://www.indeed.com/viewjob?jk=1"
    assert listing.description == "Build backend systems."
    assert listing.is_remote is True
    assert listing.salary_min == 100000
    assert listing.salary_max == 120000
    assert listing.date_posted == datetime(2026, 7, 19, tzinfo=timezone.utc)
    assert listing.scraped_at == _SCRAPED_AT


def test_normalize_job_drops_missing_title():
    assert normalize_job(_job(title=None), _SCRAPED_AT) is None


def test_normalize_job_drops_missing_company():
    assert normalize_job(_job(company=None), _SCRAPED_AT) is None


def test_normalize_job_drops_missing_url():
    assert normalize_job(_job(jobUrl=None), _SCRAPED_AT) is None


def test_normalize_job_defaults_is_remote_false_when_missing():
    listing = normalize_job(_job(isRemote=None), _SCRAPED_AT)

    assert listing is not None
    assert listing.is_remote is False


def test_normalize_job_handles_missing_optional_fields():
    job = _job()
    del job["minAmount"]
    del job["maxAmount"]
    del job["datePosted"]

    listing = normalize_job(job, _SCRAPED_AT)

    assert listing is not None
    assert listing.salary_min is None
    assert listing.salary_max is None
    assert listing.date_posted is None


def test_normalize_job_skips_missing_site():
    assert normalize_job(_job(site=None), _SCRAPED_AT) is None


def test_normalize_job_skips_missing_id():
    assert normalize_job(_job(id=None), _SCRAPED_AT) is None


def test_normalize_job_skips_unparseable_url():
    assert normalize_job(_job(jobUrl="not-a-url"), _SCRAPED_AT) is None
