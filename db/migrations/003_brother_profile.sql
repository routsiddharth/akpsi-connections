-- Step 3: Brother Profile ingestion.
-- Additive over Steps 1+2 — leaves the unused `relationships` placeholder alone,
-- keeps grad_year_source for back-compat (Step 2 writes it), introduces row-level
-- `source` as the canonical provenance field going forward.

-- ---------------------------------------------------------------------------
-- persons.source: ROW-level provenance (vs grad_year_source which is column-level).
-- The Brother Profile loader treats this enum as a precedence order:
--   alumni_master_key      -- highest for alumni (conflicts go to review)
--   brother_profile        -- highest for actives
--   linktree_explicit      -- roster tab has grad_year, mid precedence
--   linktree_inferred      -- lin-tree-only stub, lowest precedence
--   manual / external_added- treated as authoritative (only fill NULLs)
-- ---------------------------------------------------------------------------
ALTER TABLE persons ADD COLUMN IF NOT EXISTS source TEXT
    DEFAULT 'alumni_master_key'
    CHECK (source IN ('alumni_master_key','brother_profile','linktree_inferred',
                      'linktree_explicit','manual','external_added'));

ALTER TABLE persons ADD COLUMN IF NOT EXISTS person_type TEXT
    DEFAULT 'alumnus'
    CHECK (person_type IN ('alumnus','active','prospective','unknown'));

-- All careers/industry interests from the Brother Profile, comma-separated.
-- Distinct from persons.industry (which is the broad category from the alumni sheet).
ALTER TABLE persons ADD COLUMN IF NOT EXISTS industry_interests TEXT;

-- ---------------------------------------------------------------------------
-- One-time backfill of `source` and `person_type` from the data we already have.
-- Idempotent: the WHERE clauses match only DEFAULT-filled rows, so subsequent
-- runs of the same migration are no-ops (manual or brother-pipeline updates
-- have moved those rows out of the matching set).
-- ---------------------------------------------------------------------------
UPDATE persons SET source = CASE grad_year_source
    WHEN 'alumni_master' THEN 'alumni_master_key'
    WHEN 'roster'        THEN 'linktree_explicit'
    WHEN 'inferred'      THEN 'linktree_inferred'
    ELSE                      'manual'
END
WHERE source = 'alumni_master_key';   -- only DEFAULT-filled rows

UPDATE persons SET person_type = CASE WHEN is_alumnus THEN 'alumnus' ELSE 'active' END
WHERE person_type = 'alumnus';        -- only DEFAULT-filled rows

-- ---------------------------------------------------------------------------
-- pledged_with: flat — pledge class is just a name (PSI, OMEGA, ALPHA ALPHA, ...)
-- One row per person; a brother only pledges once. Skip the separate
-- pledge_classes entity table per user direction.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pledged_with (
    person_id    INT PRIMARY KEY REFERENCES persons(id) ON DELETE CASCADE,
    pledge_class TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pledged_with_class ON pledged_with(pledge_class);

-- ---------------------------------------------------------------------------
-- persons_audit: every UPDATE to persons by a pipeline must land a row here.
-- Spec calls this non-negotiable — without it you can't tell what overwrote
-- what when Step-2 stubs start disagreeing with reality.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS persons_audit (
    id            SERIAL PRIMARY KEY,
    person_id     INT NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
    column_name   TEXT NOT NULL,
    old_value     TEXT,
    new_value     TEXT,
    source_before TEXT,
    source_after  TEXT,
    pipeline      TEXT NOT NULL,
    changed_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_persons_audit_person ON persons_audit(person_id);
CREATE INDEX IF NOT EXISTS idx_persons_audit_when   ON persons_audit(changed_at);
