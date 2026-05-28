-- Step 2: lineage edges from the Lin Trees xlsx.
-- Additive over db/schema.sql — leaves the unused `relationships` placeholder alone.
-- Mirrors the firm_aliases / firms audit pattern from Step 1.

-- ---------------------------------------------------------------------------
-- persons.grad_year_source: where the grad_year came from. Step 1 sets
-- 'alumni_master' via the column DEFAULT; Step 2 may insert undergrads as
-- 'roster' (TAKING LITTLES 2026 tab has explicit Year) or 'inferred' (no
-- source — grad_year NULL, source recorded so a future pass can fill it).
-- ---------------------------------------------------------------------------
ALTER TABLE persons
    ADD COLUMN IF NOT EXISTS grad_year_source TEXT
        DEFAULT 'alumni_master'
        CHECK (grad_year_source IN ('alumni_master','roster','inferred','manual'));

-- ---------------------------------------------------------------------------
-- big_of: one directed edge per (big, little). Source-of-truth for lineage.
-- Distinct table (not `relationships`) per spec; existing `relationships`
-- placeholder is left untouched.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS big_of (
    id          SERIAL PRIMARY KEY,
    big_id      INT NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
    little_id   INT NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
    family      TEXT,            -- source tab name: Lin, El Lineage, PREDLIN, ...
    source      TEXT NOT NULL DEFAULT 'linktree',
    confidence  REAL,            -- weakest side's resolution score (min of the two)
    UNIQUE (big_id, little_id)   -- idempotency: re-running cannot duplicate edges
);
CREATE INDEX IF NOT EXISTS idx_big_of_big    ON big_of(big_id);
CREATE INDEX IF NOT EXISTS idx_big_of_little ON big_of(little_id);

-- ---------------------------------------------------------------------------
-- person_aliases: every raw name string from the xlsx -> the resolved person.
-- Mirrors firm_aliases exactly. UNIQUE (raw_string) is the idempotency key:
-- on rerun we look up here first and reuse the existing person_id instead of
-- inserting a duplicate undergrad.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS person_aliases (
    id          SERIAL PRIMARY KEY,
    raw_string  TEXT NOT NULL UNIQUE,
    person_id   INT REFERENCES persons(id) ON DELETE CASCADE,
    method      TEXT,            -- exact | fuzzy_auto | reviewed | new_undergrad | nickname
    score       REAL,
    source_tab  TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
