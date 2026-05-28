"""Load Lin Trees into Postgres: new undergrads, person_aliases, big_of.

Idempotent. Re-running produces the same DB state and adds no duplicates:
  - person_aliases.raw_string is the idempotency key (ON CONFLICT DO NOTHING).
  - big_of has UNIQUE (big_id, little_id)             (ON CONFLICT DO NOTHING).
  - undergrads are only created when their raw_string isn't in person_aliases.

Unresolved edges (one side in the 80-92 review band) are written to
data/unresolved_lin_edges.json — never silently dropped.
"""
from __future__ import annotations

import json
from collections import Counter

import psycopg2

from . import config
from .parse import parse
from .resolve import NameResolver


def _existing_persons(cur) -> list[dict]:
    cur.execute("SELECT id, full_name, grad_year FROM persons")
    return [{"id": i, "full_name": n, "grad_year": gy} for i, n, gy in cur.fetchall()]


def _existing_aliases(cur) -> dict[str, int]:
    cur.execute("SELECT raw_string, person_id FROM person_aliases "
                "WHERE person_id IS NOT NULL")
    return dict(cur.fetchall())


def _create_undergrad(cur, name: str, grad_year: int | None) -> int:
    """Insert a new lin-tree-only undergrad. Returns the new persons.id.

    Source-tags grad_year as 'roster' if it came from TAKING LITTLES 2026, else
    'inferred'. Also sets row-level `source` (the Step-3 column) so future
    brother-pipeline runs know this row is overwriteable lin-tree-derived data,
    not authoritative master-key data."""
    parts = name.split()
    first = parts[0] if parts else None
    last = " ".join(parts[1:]) if len(parts) > 1 else None
    gy_src = "roster" if grad_year else "inferred"
    row_src = "linktree_explicit" if grad_year else "linktree_inferred"
    cur.execute(
        """INSERT INTO persons (first_name, last_name, full_name, grad_year,
                                is_alumnus, grad_year_source, source, person_type)
           VALUES (%s, %s, %s, %s, FALSE, %s, %s, 'active') RETURNING id""",
        (first, last, name, grad_year, gy_src, row_src),
    )
    return cur.fetchone()[0]


def load(xlsx_path=None):
    edges, roster = parse(xlsx_path)
    # name -> grad_year from the roster tab (authoritative for current undergrads).
    roster_year = {r.name_raw: r.grad_year for r in roster if r.grad_year}

    conn = psycopg2.connect(config.DATABASE_URL)
    conn.autocommit = False
    cur = conn.cursor()

    persons = _existing_persons(cur)
    aliases = _existing_aliases(cur)
    resolver = NameResolver(persons, aliases)

    new_count = 0

    def _resolve_and_maybe_create(raw: str, grad_year_hint: int | None = None):
        """Resolve, and if it's a brand-new undergrad, insert the person row
        immediately AND tell the resolver about it (so the next raw name with
        the same normalized form matches instead of creating a duplicate).
        grad_year_hint guards fuzzy_auto from matching across class generations."""
        nonlocal new_count
        res = resolver.resolve(raw, grad_year_hint=grad_year_hint)
        if res.method == "new_undergrad" and res.person_id is None:
            gy = grad_year_hint or roster_year.get(raw)
            pid = _create_undergrad(cur, raw, gy)
            res.person_id, res.full_name = pid, raw
            resolver.add_person(raw, pid)
            new_count += 1

    # Phase 1: roster names first — they carry grad_year, which (a) gives new
    # undergrads a real grad year and (b) blocks cross-generation false positives
    # like Jake Lee (2027) ~ Jae Lee (2023).
    for r in roster:
        _resolve_and_maybe_create(r.name_raw, grad_year_hint=r.grad_year)

    # Phase 2: every name that appears in lineage edges (no hint available here).
    for e in edges:
        _resolve_and_maybe_create(e.little_raw)
        _resolve_and_maybe_create(e.big_raw)

    # Phase 3: person_aliases audit trail for everything we resolved this run.
    # 'cached' rows already exist by definition; everything else gets recorded
    # (ON CONFLICT DO NOTHING covers a partial-prior-run safety case).
    alias_inserts = 0
    for raw, res in resolver.resolutions.items():
        if res.method == "cached" or res.person_id is None:
            continue
        cur.execute(
            """INSERT INTO person_aliases (raw_string, person_id, method, score, source_tab)
               VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (raw_string) DO NOTHING""",
            (raw, res.person_id, res.method, res.score, None),
        )
        alias_inserts += cur.rowcount

    # Phase 4: big_of — both sides must be resolved or the edge goes to the
    # unresolved log (NEVER silently dropped, per spec).
    # Edge confidence reflects MATCHING certainty: 100 for exact/cached/reviewed/
    # new_undergrad, the fuzzy score for fuzzy_auto. The discarded near-miss score
    # on new_undergrad is *not* edge confidence — that'd be the score of who they
    # aren't, which is misleading.
    def _match_conf(res):
        return res.score if res.method == "fuzzy_auto" else 100.0

    edge_inserts = 0
    unresolved: list[dict] = []
    for e in edges:
        l_res = resolver.resolutions[e.little_raw]
        b_res = resolver.resolutions[e.big_raw]
        if l_res.person_id is None or b_res.person_id is None:
            unresolved.append({
                "source_tab":     e.source_tab,
                "little_raw":     e.little_raw,
                "little_status":  l_res.method,
                "little_score":   l_res.score,
                "big_raw":        e.big_raw,
                "big_status":     b_res.method,
                "big_score":      b_res.score,
            })
            continue
        conf = min(_match_conf(l_res), _match_conf(b_res))
        cur.execute(
            """INSERT INTO big_of (big_id, little_id, family, source, confidence)
               VALUES (%s, %s, %s, 'linktree', %s)
               ON CONFLICT (big_id, little_id) DO NOTHING""",
            (b_res.person_id, l_res.person_id, e.source_tab, conf),
        )
        edge_inserts += cur.rowcount

    conn.commit()
    cur.close()
    conn.close()

    config.DATA_DIR.mkdir(exist_ok=True)
    config.UNRESOLVED_FILE.write_text(json.dumps(unresolved, indent=2, sort_keys=True))

    return {
        "summary":             resolver.summary(),
        "edges_inserted":      edge_inserts,
        "undergrads_created":  new_count,
        "aliases_inserted":    alias_inserts,
        "in_review":           len(resolver.review),
        "unresolved_edges":    len(unresolved),
        "method_counts":       dict(Counter(r.method for r in resolver.resolutions.values())),
    }


if __name__ == "__main__":
    stats = load()
    print(stats["summary"])
    print(f"Loaded: +{stats['edges_inserted']} big_of edges, "
          f"+{stats['undergrads_created']} undergrads, "
          f"+{stats['aliases_inserted']} aliases, "
          f"{stats['in_review']} in review, "
          f"{stats['unresolved_edges']} unresolved edges.")
