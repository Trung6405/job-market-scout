CREATE TABLE IF NOT EXISTS listings (
    id BIGSERIAL PRIMARY KEY,
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    location TEXT NOT NULL,
    url TEXT NOT NULL,
    description TEXT NOT NULL,
    is_remote BOOLEAN NOT NULL,
    salary_min DOUBLE PRECISION,
    salary_max DOUBLE PRECISION,
    date_posted TIMESTAMPTZ,
    scraped_at TIMESTAMPTZ NOT NULL,
    content_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at TIMESTAMPTZ,
    UNIQUE (source, external_id)
);

CREATE INDEX IF NOT EXISTS idx_listings_status ON listings (status);

CREATE TABLE IF NOT EXISTS runs (
    id BIGSERIAL PRIMARY KEY,
    run_date DATE NOT NULL UNIQUE,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    listings_scraped INT NOT NULL DEFAULT 0,
    listings_scored INT NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS run_listings (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT NOT NULL REFERENCES runs (id) ON DELETE CASCADE,
    listing_id BIGINT NOT NULL REFERENCES listings (id),
    score INT NOT NULL CHECK (score BETWEEN 0 AND 100),
    reasoning TEXT NOT NULL,
    UNIQUE (run_id, listing_id)
);

ALTER TABLE run_listings ADD COLUMN IF NOT EXISTS band TEXT;
ALTER TABLE run_listings ADD COLUMN IF NOT EXISTS seniority TEXT;
ALTER TABLE run_listings ADD COLUMN IF NOT EXISTS work_type TEXT;
ALTER TABLE run_listings ADD COLUMN IF NOT EXISTS team TEXT;

CREATE TABLE IF NOT EXISTS listing_gaps (
    id BIGSERIAL PRIMARY KEY,
    run_listing_id BIGINT NOT NULL REFERENCES run_listings (id) ON DELETE CASCADE,
    skill TEXT NOT NULL,
    requirement_level TEXT NOT NULL CHECK (requirement_level IN ('must_have', 'nice_to_have'))
);

ALTER TABLE listing_gaps ADD COLUMN IF NOT EXISTS met BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE listing_gaps ADD COLUMN IF NOT EXISTS kind TEXT NOT NULL DEFAULT 'skill';

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS resources (
    id BIGSERIAL PRIMARY KEY,
    url TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    resource_type TEXT NOT NULL
        CHECK (resource_type IN ('doc', 'course', 'repo', 'note')),
    skills TEXT[] NOT NULL,
    level TEXT CHECK (level IN ('beginner', 'intermediate', 'advanced')),
    summary TEXT,
    embedding VECTOR(384),
    source TEXT NOT NULL,
    last_verified TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
