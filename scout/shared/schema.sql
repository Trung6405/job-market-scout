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

-- The FK column is how every reader reaches gap/tip rows (history counts,
-- render_run's ANY() lookups, re-run DELETEs, and the ON DELETE CASCADE);
-- without these the gap table gets seq-scanned ~30x per history render and
-- the cost grows with every day of history.
CREATE INDEX IF NOT EXISTS idx_listing_gaps_run_listing_id ON listing_gaps (run_listing_id);

CREATE TABLE IF NOT EXISTS listing_tips (
    id BIGSERIAL PRIMARY KEY,
    run_listing_id BIGINT NOT NULL REFERENCES run_listings (id) ON DELETE CASCADE,
    gap_skill TEXT NOT NULL,
    tip TEXT NOT NULL,
    cited_urls TEXT[] NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_listing_tips_run_listing_id ON listing_tips (run_listing_id);

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

-- Link-health state (P5). consecutive_failures counts transient failures
-- since the last success; dead_since is set the moment a resource is
-- excluded from retrieval (either on a permanent 404/410, or once
-- consecutive_failures reaches the configured threshold) and cleared on the
-- next successful check, so exclusion is always reversible.
ALTER TABLE resources ADD COLUMN IF NOT EXISTS consecutive_failures INT NOT NULL DEFAULT 0;
ALTER TABLE resources ADD COLUMN IF NOT EXISTS dead_since TIMESTAMPTZ;
ALTER TABLE resources ADD COLUMN IF NOT EXISTS last_check_error TEXT;

-- Serves the retrieval pre-filter, which was deliberately written as
-- `skills @> ARRAY[q.skill]` (the containment form GIN can use) rather than
-- `= ANY(skills)` — this index was its documented follow-up. It runs first
-- and over every row on each retrieval, so it gets the index even while the
-- corpus is small.
CREATE INDEX IF NOT EXISTS idx_resources_skills_gin ON resources USING gin (skills);
