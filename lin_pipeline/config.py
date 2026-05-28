"""Step-2 config. Re-uses Step-1 env/DB settings; adds the per-tab xlsx quirks.

Same 12-factor approach: DATABASE_URL + thresholds from env (with sane defaults),
LINTREES_XLSX defaulting to the repo-root file Step 1 already points at.
"""
from __future__ import annotations

from alumni_pipeline import config as _step1

# Re-export the data we share with Step 1 so callers don't import both modules.
DATABASE_URL = _step1.DATABASE_URL
DATA_DIR = _step1.DATA_DIR
ROOT = _step1.ROOT
FUZZY_AUTO_MERGE = _step1.FUZZY_AUTO_MERGE
FUZZY_REVIEW_MIN = _step1.FUZZY_REVIEW_MIN
LINTREES_XLSX = _step1.LINTREES_XLSX

# Persisted human review decisions (resumable across runs), mirrors firm_review.json.
REVIEW_FILE = DATA_DIR / "lin_review.json"

# Edges where one side stayed in review (or otherwise unresolvable) — never silently
# dropped; logged here so they can be re-resolved after the review CLI is run.
UNRESOLVED_FILE = DATA_DIR / "unresolved_lin_edges.json"

# Per-tab parsing config. Tabs not listed fall through to the default two-column
# layout (header at row 1, LITTLE in col A, BIG in col B). Real names from the
# 2026 workbook; if a future workbook adds tabs they just inherit the default.
#
# header_row=None -> tab has no header; data starts at row 1.
LINEAGE_TABS = {
    "El Lineage":        {"header_row": 18, "little_col": 2, "big_col": 3},
    "Lin":               {"header_row": None, "little_col": 1, "big_col": 2},
    "PREDLIN":           {"header_row": 1, "little_col": 1, "big_col": 2},  # col 3 = animal nick, ignored
    "Shiestgang":        {"header_row": 1, "little_col": 1, "big_col": 2},
    "W Lin":             {"header_row": 1, "little_col": 1, "big_col": 2},
    "Cash Money Lin":    {"header_row": 1, "little_col": 1, "big_col": 2},
    "HH Lin":            {"header_row": 1, "little_col": 1, "big_col": 2},
    "Bad 2 Bougie(B2B)": {"header_row": 1, "little_col": 1, "big_col": 2},
    "Skibidi Lin":       {"header_row": 1, "little_col": 1, "big_col": 2},
}
DEFAULT_LINEAGE = {"header_row": 1, "little_col": 1, "big_col": 2}

# The roster tab carries grad year + family for current undergrads — bonus signal
# we use to populate new-undergrad rows with a real grad_year (source='roster').
ROSTER_TAB = "TAKING LITTLES 2026"
