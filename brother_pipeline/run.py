"""CLI entrypoint for Step 3.

    python -m brother_pipeline.run
    python -m brother_pipeline.run --xlsx path/to/other.xlsx

Prints the spec's required summary lines plus DB totals so idempotency is easy
to verify by eye.
"""
from __future__ import annotations

import argparse

import psycopg2

from . import config
from .load import load


def _db_totals():
    conn = psycopg2.connect(config.DATABASE_URL)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM persons")
    n_persons = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM persons WHERE person_type = 'active'")
    n_actives = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM persons WHERE source = 'brother_profile'")
    n_bp = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM pledged_with")
    n_pl = cur.fetchone()[0]
    cur.execute(
        "SELECT COUNT(*) FROM worked_at WHERE person_id IN "
        "(SELECT id FROM persons WHERE person_type = 'active')"
    )
    n_we_active = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM persons_audit")
    n_audit = cur.fetchone()[0]
    cur.close()
    conn.close()
    return n_persons, n_actives, n_bp, n_pl, n_we_active, n_audit


def main():
    ap = argparse.ArgumentParser(description="Apply Brother Profile to Postgres.")
    ap.add_argument("--xlsx", default=None,
                    help=f"Brother Profile workbook (default: {config.BROTHER_XLSX})")
    args = ap.parse_args()

    s = load(args.xlsx)

    # Spec summary
    print(f"{s['parsed']} profiles parsed")
    print(f"{s['matched']} matched to existing persons ({s['via_review']} via review queue)")
    print(f"{s['new_actives']} new active brothers created")
    print(f"{s['worked_at_added']} worked_at rows added this run")
    print(f"{s['industries_set']} active brothers now have industry_interests")
    print(f"{s['conflicts']} conflicts requiring manual resolution "
          f"(see {config.CONFLICTS_FILE.name})")
    print(f"{s['in_review']} names in review queue "
          f"(see {config.REVIEW_FILE.name})")
    print(f"{s['audit_rows']} persons_audit rows logged this run")

    n_persons, n_actives, n_bp, n_pl, n_we_active, n_audit = _db_totals()
    print(f"\nDB totals: {n_persons} persons ({n_actives} active, "
          f"{n_bp} sourced=brother_profile) | "
          f"{n_pl} pledged_with | {n_we_active} worked_at-for-actives | "
          f"{n_audit} total persons_audit rows")


if __name__ == "__main__":
    main()
