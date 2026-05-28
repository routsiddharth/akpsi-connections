"""CLI entrypoint for Step 2.

    python -m lin_pipeline.run
    python -m lin_pipeline.run --xlsx path/to/other.xlsx

Prints the per-method resolution breakdown and DB totals so it's easy to spot
whether you've added duplicates on a rerun (totals should be unchanged).
"""
from __future__ import annotations

import argparse

import psycopg2

from . import config
from .load import load


def _db_totals():
    conn = psycopg2.connect(config.DATABASE_URL)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM big_of")
    n_edges = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM person_aliases")
    n_aliases = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM persons WHERE is_alumnus = FALSE")
    n_undergrads = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM persons WHERE is_alumnus = TRUE")
    n_alumni = cur.fetchone()[0]
    cur.close()
    conn.close()
    return n_edges, n_aliases, n_undergrads, n_alumni


def main():
    ap = argparse.ArgumentParser(description="Load Lin Trees into Postgres.")
    ap.add_argument("--xlsx", default=None,
                    help=f"Lin Trees workbook path (default: {config.LINTREES_XLSX})")
    args = ap.parse_args()

    stats = load(args.xlsx)
    print(stats["summary"])
    print(f"  methods: {stats['method_counts']}")
    print(f"Loaded this run: +{stats['edges_inserted']} big_of edges, "
          f"+{stats['undergrads_created']} undergrads, "
          f"+{stats['aliases_inserted']} aliases | "
          f"{stats['in_review']} in review, "
          f"{stats['unresolved_edges']} unresolved edges "
          f"({config.UNRESOLVED_FILE.name}).")

    n_edges, n_aliases, n_undergrads, n_alumni = _db_totals()
    print(f"DB totals: {n_edges} big_of | {n_alumni} alumni + "
          f"{n_undergrads} undergrads | {n_aliases} person_aliases.")


if __name__ == "__main__":
    main()
