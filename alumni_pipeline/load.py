"""Load the alumni xlsx into Postgres: persons, firms, groups, worked_at, firm_aliases.

Idempotent full rebuild — truncates the loaded tables and repopulates. Run any time:

    python -m alumni_pipeline.load
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict

import psycopg2

from . import config
from .aliases import CANONICAL_META
from .canonicalize import Canonicalizer
from .extract import Person, extract_people
from .firmparse import parse_postgrad


def _industry(raw: str | None) -> str | None:
    if not raw:
        return None
    # "Other (Media)" / "Finance " -> "Other" / "Finance"
    return re.sub(r"\s*\(.*\)", "", str(raw)).strip() or None


def _build():
    """Return (people, resolved_stints, firm_meta, groups, canon)."""
    people = extract_people()

    # token frequencies for canonicalization
    counts: Counter = Counter()
    for p in people:
        for st in parse_postgrad(p.post_grad_raw).stints:
            counts[st.firm_raw.strip()] += 1

    canon = Canonicalizer()
    canon.fit(counts)

    # resolve each person's stints to canonical firms/groups
    resolved: dict[int, list[dict]] = {}        # person idx -> [stint dicts]
    firm_org_types: dict[str, Counter] = defaultdict(Counter)
    firm_industries: dict[str, Counter] = defaultdict(Counter)
    groups: set[tuple[str, str]] = set()

    for idx, p in enumerate(people):
        stints = parse_postgrad(p.post_grad_raw).stints
        out = []
        for seq, st in enumerate(stints):
            firm, group_override = canon.resolve(st.firm_raw)
            group = group_override or st.group_raw
            # org_type: curated meta wins, else firmparse hint, else company
            ot = CANONICAL_META.get(firm, {}).get("org_type") or st.org_type
            if ot:
                firm_org_types[firm][ot] += 1
            if st.is_current and p.industry:
                firm_industries[firm][_industry(p.industry)] += 1
            if group:
                groups.add((firm, group.strip()))
            out.append({
                "firm": firm, "group": group.strip() if group else None,
                "title": p.position_raw if st.is_current else None,
                "is_current": st.is_current, "seq": seq,
            })
        resolved[idx] = out

    # finalize firm metadata
    firm_meta = {}
    all_firms = set(g[0] for g in groups) | set(firm_org_types) | {
        s["firm"] for sts in resolved.values() for s in sts}
    for f in all_firms:
        ot = (CANONICAL_META.get(f, {}).get("org_type")
              or (firm_org_types[f].most_common(1)[0][0] if firm_org_types[f] else "company"))
        ind = firm_industries[f].most_common(1)[0][0] if firm_industries[f] else None
        firm_meta[f] = {"org_type": ot, "industry": ind}

    return people, resolved, firm_meta, groups, canon


def load():
    people, resolved, firm_meta, groups, canon = _build()
    print(canon.summary())

    conn = psycopg2.connect(config.DATABASE_URL)
    conn.autocommit = False
    cur = conn.cursor()

    cur.execute("TRUNCATE firm_aliases, worked_at, relationships, groups, persons, firms "
                "RESTART IDENTITY CASCADE;")

    # firms
    firm_id: dict[str, int] = {}
    for name, meta in sorted(firm_meta.items()):
        cur.execute(
            "INSERT INTO firms (canonical_name, org_type, industry) VALUES (%s,%s,%s) "
            "RETURNING id", (name, meta["org_type"], meta["industry"]))
        firm_id[name] = cur.fetchone()[0]

    # groups
    group_id: dict[tuple[str, str], int] = {}
    for fname, gname in sorted(groups):
        cur.execute(
            "INSERT INTO groups (firm_id, canonical_name) VALUES (%s,%s) RETURNING id",
            (firm_id[fname], gname))
        group_id[(fname, gname)] = cur.fetchone()[0]

    # persons (dedupe on full_name+grad_year)
    person_id: dict[tuple[str, int], int] = {}
    for idx, p in enumerate(people):
        key = (p.full_name, p.grad_year)
        if key in person_id:
            continue
        cur.execute(
            """INSERT INTO persons
               (first_name,last_name,full_name,grad_year,school,industry,location,
                email_personal,email_school,phone,linkedin,is_alumnus)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,TRUE) RETURNING id""",
            (p.first_name, p.last_name, p.full_name, p.grad_year, p.school,
             _industry(p.industry), p.location, p.email_personal, p.email_school,
             p.phone, p.linkedin))
        person_id[key] = cur.fetchone()[0]

    # worked_at
    n_edges = 0
    for idx, p in enumerate(people):
        pid = person_id[(p.full_name, p.grad_year)]
        for st in resolved[idx]:
            gid = group_id.get((st["firm"], st["group"])) if st["group"] else None
            cur.execute(
                """INSERT INTO worked_at
                   (person_id,firm_id,group_id,title,is_current,seq,source)
                   VALUES (%s,%s,%s,%s,%s,%s,'alumni_master')
                   ON CONFLICT (person_id,firm_id,COALESCE(group_id,-1)) DO NOTHING""",
                (pid, firm_id[st["firm"]], gid, st["title"], st["is_current"], st["seq"]))
            n_edges += cur.rowcount

    # firm_aliases audit trail
    for raw, (cname, _grp, method, score) in canon.resolution.items():
        cur.execute(
            "INSERT INTO firm_aliases (raw_string, firm_id, method, score) "
            "VALUES (%s,%s,%s,%s) ON CONFLICT (raw_string) DO NOTHING",
            (raw, firm_id.get(cname), method, score))

    conn.commit()
    print(f"Loaded: {len(person_id)} persons, {len(firm_id)} firms, "
          f"{len(group_id)} groups, {n_edges} worked_at edges.")
    cur.close()
    conn.close()


if __name__ == "__main__":
    load()
