"""Environment-driven config. Identical code path locally (docker-compose) and on Railway."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# Railway's Postgres plugin sets DATABASE_URL; docker-compose serves the same URL locally.
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://akpsi:akpsi@localhost:5432/akpsi"
)

NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "akpsi_neo4j")

FUZZY_AUTO_MERGE = float(os.environ.get("FUZZY_AUTO_MERGE", 92))
FUZZY_REVIEW_MIN = float(os.environ.get("FUZZY_REVIEW_MIN", 80))

ALUMNI_XLSX = ROOT / "ALUMNI MASTER KEY (since 2013).xlsx"
LINTREES_XLSX = ROOT / "LIN TREES SPRING 2026.xlsx"

DATA_DIR = ROOT / "data"
REVIEW_FILE = DATA_DIR / "firm_review.json"  # persisted canonicalization decisions (resumable)
