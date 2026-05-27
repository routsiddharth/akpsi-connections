-- AKPsi alumni network — relational source of truth (Postgres).
-- Neo4j is a derived projection (Step 3); this is canonical.

-- Idempotent: safe to re-run. Drops the loaded data, keeps it simple at chapter scale.
DROP TABLE IF EXISTS firm_aliases CASCADE;
DROP TABLE IF EXISTS worked_at    CASCADE;
DROP TABLE IF EXISTS relationships CASCADE;  -- big/little edges (Step 2)
DROP TABLE IF EXISTS groups       CASCADE;
DROP TABLE IF EXISTS persons      CASCADE;
DROP TABLE IF EXISTS firms        CASCADE;

-- Organizations. "firm" per the spec, but org_type lets us hold the schools /
-- government / startups that show up in the POST GRAD column without lying about them.
CREATE TABLE firms (
    id              SERIAL PRIMARY KEY,
    canonical_name  TEXT NOT NULL UNIQUE,
    org_type        TEXT NOT NULL DEFAULT 'company'
                    CHECK (org_type IN ('company','school','government','nonprofit','startup','other')),
    industry        TEXT,             -- Finance | Consulting | Tech | Law | Other (best-effort)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Divisions within a firm: IBD, ECM, TMT, "L/S Equities", "Strategy&", a YC startup, ...
CREATE TABLE groups (
    id              SERIAL PRIMARY KEY,
    firm_id         INT NOT NULL REFERENCES firms(id) ON DELETE CASCADE,
    canonical_name  TEXT NOT NULL,
    UNIQUE (firm_id, canonical_name)
);

CREATE TABLE persons (
    id              SERIAL PRIMARY KEY,
    first_name      TEXT,
    last_name       TEXT,
    full_name       TEXT NOT NULL,
    grad_year       INT,
    school          TEXT,             -- CC | SEAS | BC | GS
    industry        TEXT,             -- broad category from the sheet
    location        TEXT,
    email_personal  TEXT,
    email_school    TEXT,
    phone           TEXT,
    linkedin        TEXT,
    is_alumnus      BOOLEAN NOT NULL DEFAULT TRUE,  -- FALSE = lin-tree-only undergrad (Step 2)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (full_name, grad_year)
);

-- Employment / education history. One row per (person, org) stint.
-- seq 0 = current; seq 1.. = prior, most-recent-first.
CREATE TABLE worked_at (
    id          SERIAL PRIMARY KEY,
    person_id   INT NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
    firm_id     INT NOT NULL REFERENCES firms(id)   ON DELETE CASCADE,
    group_id    INT REFERENCES groups(id) ON DELETE SET NULL,
    title       TEXT,                 -- POSITION column
    is_current  BOOLEAN NOT NULL DEFAULT TRUE,
    seq         INT NOT NULL DEFAULT 0,
    source      TEXT NOT NULL DEFAULT 'alumni_master',  -- alumni_master | research | linktree
    confidence  TEXT                  -- for research-sourced rows: high | medium | low
);
-- Expression index: one stint per (person, firm, group), treating NULL group as -1.
-- ON CONFLICT in the loader infers this exact index.
CREATE UNIQUE INDEX uq_worked_at ON worked_at (person_id, firm_id, COALESCE(group_id, -1));

-- Audit trail: every raw POST GRAD firm token -> the canonical firm it resolved to,
-- and how. Lets you re-review any decision later.
CREATE TABLE firm_aliases (
    id          SERIAL PRIMARY KEY,
    raw_string  TEXT NOT NULL UNIQUE,
    firm_id     INT REFERENCES firms(id) ON DELETE CASCADE,
    method      TEXT,                 -- seed | exact | fuzzy_auto | reviewed | new
    score       REAL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Big/little edges land here in Step 2 (created now so the schema is complete).
CREATE TABLE relationships (
    id           SERIAL PRIMARY KEY,
    big_id       INT REFERENCES persons(id) ON DELETE CASCADE,
    little_id    INT REFERENCES persons(id) ON DELETE CASCADE,
    family       TEXT,                -- lin family / tab name
    pledge_class TEXT,
    source       TEXT NOT NULL DEFAULT 'linktree',
    UNIQUE (big_id, little_id)
);

CREATE INDEX idx_worked_at_person ON worked_at(person_id);
CREATE INDEX idx_worked_at_firm   ON worked_at(firm_id);
CREATE INDEX idx_groups_firm      ON groups(firm_id);
