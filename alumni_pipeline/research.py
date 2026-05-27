"""Best-effort prior-employer enrichment from public web sources.

Light, hand-verified pass (note #3): each entry's identity was confirmed by matching the
person's LinkedIn slug + school against the alumni record before recording. We only store
employers explicitly documented by a reputable source — no guessing. Rows land in
worked_at with source='research' and a confidence level, so they're distinguishable from
the spreadsheet-sourced data and easy to revisit.

    python -m alumni_pipeline.research
"""
from __future__ import annotations

import psycopg2

from . import config
from .canonicalize import normalize

# (full_name, grad_year): {confidence, source, prior:[(firm, title, org_type)]}
# Prior firms listed most-recent-first; loaded after the person's existing stints.
RESEARCH = {
    ("Dasmer Singh", 2013): {
        "confidence": "high",
        "source": "ycombinator.com/companies/allowance; dasmer.com",
        "prior": [
            ("Uber", "Senior Product Manager (Uber Eats)", "company"),
            ("Petal", "Senior Product Manager", "company"),
            ("Venmo", "Product Manager", "company"),
            ("Stanford Graduate School of Business", "MBA", "school"),
        ],
    },
    ("Millie Yang", 2018): {
        "confidence": "high",
        "source": "theorg.com/org/breeze-4; tracxn.com",
        "prior": [
            ("Stripe", "Software Engineer", "company"),
            ("DoorDash", "Software Engineer", "company"),
            ("Kleiner Perkins", "Engineering Fellow", "company"),
            ("Morgan Stanley", None, "company"),
        ],
    },
    ("Carlo Santelli", 2013): {
        "confidence": "high",
        "source": "theorg.com/org/cortina-capital-partners-llc; rocketreach.co",
        "prior": [
            ("Prospect Capital Management", "Vice President", "company"),
            ("Stonehenge Capital", "Vice President", "company"),
            ("Goldman Sachs", "Investment Banker (Healthcare & TMT)", "company"),
            ("Cantor Fitzgerald", "Senior Analyst", "company"),
            ("Merrill Lynch", "Investment Banking Analyst", "company"),
        ],
    },
    ("Camille Bernier-Green", 2013): {
        "confidence": "medium",  # current role has since changed; Disney stint documented
        "source": "variety.com (2023); imdb.com",
        "prior": [
            ("The Walt Disney Company", "Director of Documentaries (Onyx Collective)", "company"),
        ],
    },
}


def _firm_id(cur, name: str, org_type: str) -> int:
    """Match to an existing canonical firm by normalized name, else create it."""
    cur.execute("SELECT id, canonical_name FROM firms")
    by_norm = {normalize(n): fid for fid, n in cur.fetchall()}
    fid = by_norm.get(normalize(name))
    if fid:
        return fid
    cur.execute(
        "INSERT INTO firms (canonical_name, org_type) VALUES (%s,%s) RETURNING id",
        (name, org_type))
    return cur.fetchone()[0]


def enrich():
    conn = psycopg2.connect(config.DATABASE_URL)
    cur = conn.cursor()
    added = 0
    for (name, year), info in RESEARCH.items():
        cur.execute("SELECT id FROM persons WHERE full_name=%s AND grad_year=%s",
                    (name, year))
        row = cur.fetchone()
        if not row:
            print(f"  ! {name} ({year}) not found — skipping")
            continue
        pid = row[0]
        cur.execute("SELECT COALESCE(MAX(seq),0) FROM worked_at WHERE person_id=%s", (pid,))
        seq = cur.fetchone()[0]
        for firm, title, org_type in info["prior"]:
            seq += 1
            fid = _firm_id(cur, firm, org_type)
            cur.execute(
                """INSERT INTO worked_at
                   (person_id,firm_id,title,is_current,seq,source,confidence)
                   VALUES (%s,%s,%s,FALSE,%s,'research',%s)
                   ON CONFLICT (person_id,firm_id,COALESCE(group_id,-1)) DO NOTHING""",
                (pid, fid, title, seq, info["confidence"]))
            added += cur.rowcount
    conn.commit()
    print(f"Research enrichment: +{added} prior-employer rows "
          f"for {len(RESEARCH)} people (source='research').")
    cur.close()
    conn.close()


if __name__ == "__main__":
    enrich()
