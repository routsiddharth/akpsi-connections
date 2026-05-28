"""Step-3 config. Re-uses Step-1/2 DB + thresholds; adds brother-specific paths.

Three persisted JSON files for state across runs (mirrors lin/firm review pattern):
  brother_review.json     -- ambiguous name matches (80-92 fuzzy)
  brother_conflicts.json  -- per-field decisions when brother profile data
                             disagrees with an existing alumni_master_key row
  brother_parse_log.json  -- every parser normalization decision (auditable)
"""
from __future__ import annotations

from alumni_pipeline import config as _step1

DATABASE_URL     = _step1.DATABASE_URL
DATA_DIR         = _step1.DATA_DIR
ROOT             = _step1.ROOT
FUZZY_AUTO_MERGE = _step1.FUZZY_AUTO_MERGE
FUZZY_REVIEW_MIN = _step1.FUZZY_REVIEW_MIN

# Real file in the repo root; the on-disk name has spaces which we tolerate.
BROTHER_XLSX = ROOT / "Online Brother Profile Spring 2026.xlsx"

REVIEW_FILE    = DATA_DIR / "brother_review.json"
CONFLICTS_FILE = DATA_DIR / "brother_conflicts.json"
PARSE_LOG_FILE = DATA_DIR / "brother_parse_log.json"

# Precedence: Brother Profile may overwrite these sources freely; cannot overwrite
# the others without an explicit conflict-resolution decision.
SOURCES_OVERWRITEABLE = {"linktree_inferred", "linktree_explicit"}
SOURCES_CONFLICT      = {"alumni_master_key"}
SOURCES_FILL_NULLS    = {"brother_profile", "manual", "external_added"}
