"""Apply Brother Profile data to persons + pledged_with + worked_at.

Three rules drive every UPDATE:
  1. Precedence — Brother Profile may overwrite linktree_inferred / linktree_explicit
     freely; alumni_master_key conflicts route to brother_conflicts.json (no
     auto-write); brother_profile / manual / external_added rows are only
     enriched at NULL fields.
  2. Audit log — every column change writes a persons_audit row with
     (column, old, new, source_before, source_after). Non-negotiable.
  3. Idempotency — re-running adds no audit rows, no worked_at rows, no
     pledged_with rows. Achieved via ON CONFLICT DO NOTHING + value-differs
     guards on the UPDATEs.

Firm canonicalization is reused from alumni_pipeline.Canonicalizer, pre-seeded
with the existing `firms` table so 'Goldman Sachs' from Brother Profile maps to
the same firm row Step 1 created — no duplicates.
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass

import psycopg2

from alumni_pipeline.canonicalize import Canonicalizer
from alumni_pipeline.aliases import CANONICAL_META

from . import config
from .parse import BrotherRow, parse
from .resolve import BrotherResolver


# ----------------------------------------------------------------------------
# Conflict file helpers (per-field decisions persisted across runs).
# Shape:  {"raw_name": str, "person_id": int, "decisions": {field: "overwrite"|"keep"|"pending"}}
# ----------------------------------------------------------------------------
def _load_conflicts() -> dict[str, dict]:
    if config.CONFLICTS_FILE.exists():
        data = json.loads(config.CONFLICTS_FILE.read_text())
        return {c["raw_name"]: c for c in data}
    return {}


def _dump_conflicts(conflicts: dict[str, dict]):
    config.DATA_DIR.mkdir(exist_ok=True)
    config.CONFLICTS_FILE.write_text(
        json.dumps(sorted(conflicts.values(), key=lambda c: c["raw_name"]),
                   indent=2, sort_keys=True))


# ----------------------------------------------------------------------------
# Brother row -> {column: value} for the columns we ever try to write.
# industries is comma-joined into a single string (per user direction).
# ----------------------------------------------------------------------------
def _brother_fields(b: BrotherRow) -> dict:
    return {
        "grad_year":          b.grad_year,
        "school":             b.school,
        "email_school":       b.email,
        "industry_interests": ", ".join(b.industries) if b.industries else None,
    }


# ----------------------------------------------------------------------------
# DB helpers
# ----------------------------------------------------------------------------
def _load_existing(cur):
    cur.execute(
        "SELECT id, full_name, grad_year, school, email_school, industry_interests, "
        "       source, person_type "
        "FROM persons"
    )
    cols = ("id","full_name","grad_year","school","email_school",
            "industry_interests","source","person_type")
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _load_aliases(cur) -> dict[str, int]:
    cur.execute("SELECT raw_string, person_id FROM person_aliases WHERE person_id IS NOT NULL")
    return dict(cur.fetchall())


def _create_active(cur, b: BrotherRow) -> int:
    """Insert a brand-new active brother. Returns persons.id."""
    cur.execute(
        """INSERT INTO persons (first_name, last_name, full_name, grad_year, school,
                                email_school, industry_interests, is_alumnus,
                                grad_year_source, source, person_type)
           VALUES (%s, %s, %s, %s, %s, %s, %s, FALSE, 'manual', 'brother_profile', 'active')
           RETURNING id""",
        (b.first_name, b.last_name, b.full_name, b.grad_year, b.school,
         b.email, ", ".join(b.industries) if b.industries else None),
    )
    return cur.fetchone()[0]


def _update_with_audit(cur, person_id: int, column: str, old_val, new_val,
                       source_before: str, source_after: str):
    """UPDATE persons.<column> AND log to persons_audit. Caller must ensure
    new_val != old_val (this function trusts that and unconditionally writes)."""
    cur.execute(f"UPDATE persons SET {column} = %s WHERE id = %s",
                (new_val, person_id))
    cur.execute(
        """INSERT INTO persons_audit
           (person_id, column_name, old_value, new_value, source_before, source_after, pipeline)
           VALUES (%s, %s, %s, %s, %s, %s, 'brother_pipeline')""",
        (person_id, column,
         None if old_val is None else str(old_val),
         None if new_val is None else str(new_val),
         source_before, source_after),
    )


def _ensure_firm(cur, name: str, firm_cache: dict[str, int]) -> int:
    """Return firm_id for canonical name. Insert if missing (org_type=company)."""
    if name in firm_cache:
        return firm_cache[name]
    org_type = CANONICAL_META.get(name, {}).get("org_type") or "company"
    cur.execute(
        "INSERT INTO firms (canonical_name, org_type) VALUES (%s, %s) "
        "ON CONFLICT (canonical_name) DO UPDATE SET canonical_name = EXCLUDED.canonical_name "
        "RETURNING id",
        (name, org_type))
    fid = cur.fetchone()[0]
    firm_cache[name] = fid
    return fid


# ----------------------------------------------------------------------------
# Main load
# ----------------------------------------------------------------------------
def load(xlsx_path=None):
    brothers = parse(xlsx_path)

    conn = psycopg2.connect(config.DATABASE_URL)
    conn.autocommit = False
    cur = conn.cursor()

    existing = _load_existing(cur)
    persons_by_id = {p["id"]: p for p in existing}
    aliases = _load_aliases(cur)

    # ---- Name resolver (reuses lin_pipeline machinery, brother_review.json file)
    resolver = BrotherResolver(existing, aliases)

    # ---- Firm canonicalizer: pre-seed from existing firms in DB so brother
    # tokens fuzzy-match into the firms Step 1 already canonicalized.
    cur.execute("SELECT canonical_name FROM firms")
    canon = Canonicalizer()
    for (fname,) in cur.fetchall():
        canon._register(fname)
    firm_tokens: Counter = Counter()
    for b in brothers:
        for s in b.work_experience:
            firm_tokens[s.firm_raw.strip()] += 1
    canon.fit(firm_tokens)

    # ---- Existing conflict decisions (apply 'overwrite' decisions on this run).
    conflicts = _load_conflicts()

    firm_cache: dict[str, int] = {}
    cur.execute("SELECT canonical_name, id FROM firms")
    for name, fid in cur.fetchall():
        firm_cache[name] = fid

    stats = {
        "parsed":           len(brothers),
        "matched":          0,
        "via_review":       0,
        "new_actives":      0,
        "in_review":        0,
        "worked_at_added":  0,
        "industries_set":   0,
        "conflicts":        0,
        "audit_rows":       0,
    }

    def _audit_count():
        cur.execute("SELECT COUNT(*) FROM persons_audit")
        return cur.fetchone()[0]
    audit_before = _audit_count()

    for b in brothers:
        # ----- 1. Resolve name -------------------------------------------------
        res = resolver.resolve(b.full_name, grad_year_hint=b.grad_year)

        # ----- 2. Branch on resolution outcome --------------------------------
        if res.method == "review":
            stats["in_review"] += 1
            continue                                          # wait for human

        if res.method == "new_undergrad" and res.person_id is None:
            pid = _create_active(cur, b)
            res.person_id, res.full_name = pid, b.full_name
            resolver.add_person(b.full_name, pid)
            # New row: fields are already populated by INSERT, no audit needed
            # (audit only tracks changes to existing rows).
            stats["new_actives"] += 1
            # Reload this person into persons_by_id so subsequent logic sees it.
            persons_by_id[pid] = {
                "id": pid, "full_name": b.full_name, "grad_year": b.grad_year,
                "school": b.school, "email_school": b.email,
                "industry_interests": ", ".join(b.industries) if b.industries else None,
                "source": "brother_profile", "person_type": "active",
            }
        else:
            pid = res.person_id
            stats["matched"] += 1
            if res.method == "reviewed":
                stats["via_review"] += 1
            existing_row = persons_by_id.get(pid)
            if existing_row is None:
                # Shouldn't happen, but skip safely.
                continue

            existing_source = existing_row.get("source") or "alumni_master_key"
            proposed = _brother_fields(b)
            skip_enrichment = False

            # ----- 3. Conflict gate (alumni_master_key only) -----------------
            # Conflict = both sides have a value AND they differ. NULL fills are
            # NOT conflicts — they're enrichments and happen in step 4.
            if existing_source == "alumni_master_key":
                diffs = []
                for col, new_val in proposed.items():
                    old = existing_row.get(col)
                    if new_val is not None and old is not None and str(old) != str(new_val):
                        diffs.append({"field": col, "old": old, "new": new_val})

                if diffs:
                    decisions = conflicts.get(b.full_name, {}).get("decisions", {})
                    pending_now = []
                    for d in diffs:
                        verdict = decisions.get(d["field"], "pending")
                        if verdict == "overwrite":
                            _update_with_audit(cur, pid, d["field"], d["old"], d["new"],
                                               source_before=existing_source,
                                               source_after="brother_profile")
                            existing_row[d["field"]] = d["new"]
                        else:
                            pending_now.append({**d, "decision": verdict})
                    if pending_now:
                        conflicts[b.full_name] = {
                            "raw_name": b.full_name,
                            "person_id": pid,
                            "decisions": {p["field"]: p["decision"] for p in pending_now},
                        }
                        stats["conflicts"] += 1
                        skip_enrichment = True       # wait for full resolution
                    else:
                        # All conflicts decided 'overwrite' — fall through to enrichment
                        # in the SAME run so NULL fills + person_type happen now,
                        # not deferred to a subsequent (silently non-idempotent) run.
                        conflicts.pop(b.full_name, None)

            # ----- 4. Enrichment ---------------------------------------------
            # For sources we own (linktree_*): overwrite differing values too.
            # For everything else: only fill NULLs — don't silently overwrite
            # authoritative data. Conflicts are already handled above.
            if not skip_enrichment:
                fillable_only = (existing_source in config.SOURCES_FILL_NULLS
                                 or existing_source == "alumni_master_key")
                touched_any = False
                for col, new_val in proposed.items():
                    if new_val is None:
                        continue
                    old = existing_row.get(col)
                    if str(old) == str(new_val):
                        continue
                    if fillable_only and old is not None:
                        continue
                    _update_with_audit(cur, pid, col, old, new_val,
                                       source_before=existing_source,
                                       source_after="brother_profile")
                    existing_row[col] = new_val
                    touched_any = True

                # Source flip: if Brother Profile touched anything, this row is
                # now sourced from brother_profile.
                if touched_any and existing_source != "brother_profile":
                    _update_with_audit(cur, pid, "source", existing_source,
                                       "brother_profile",
                                       existing_source, "brother_profile")
                    existing_row["source"] = "brother_profile"

                # Brother Profile only contains actives — promote person_type
                # on first encounter (idempotent: skipped on subsequent runs).
                if existing_row.get("person_type") != "active":
                    _update_with_audit(cur, pid, "person_type",
                                       existing_row.get("person_type"), "active",
                                       existing_source, "brother_profile")
                    existing_row["person_type"] = "active"

        # ----- 5. Pledged_with --------------------------------------------------
        if b.pledge_class and res.person_id is not None:
            cur.execute(
                """INSERT INTO pledged_with (person_id, pledge_class) VALUES (%s, %s)
                   ON CONFLICT (person_id) DO UPDATE SET pledge_class = EXCLUDED.pledge_class
                   WHERE pledged_with.pledge_class IS DISTINCT FROM EXCLUDED.pledge_class""",
                (res.person_id, b.pledge_class),
            )

        # ----- 6. Worked_at -----------------------------------------------------
        if res.person_id is None:
            continue
        for seq, st in enumerate(b.work_experience, start=1):
            firm_canon, _group_override = canon.resolve(st.firm_raw)
            firm_id = _ensure_firm(cur, firm_canon, firm_cache)
            cur.execute(
                """INSERT INTO worked_at
                   (person_id, firm_id, group_id, title, is_current, seq, source)
                   VALUES (%s, %s, NULL, %s, FALSE, %s, 'brother_profile')
                   ON CONFLICT (person_id, firm_id, COALESCE(group_id, -1)) DO NOTHING""",
                (res.person_id, firm_id, st.role, seq),
            )
            stats["worked_at_added"] += cur.rowcount

        # ----- 7. person_aliases audit (only for new resolutions this run) -----
        if res.method != "cached":
            cur.execute(
                """INSERT INTO person_aliases (raw_string, person_id, method, score, source_tab)
                   VALUES (%s, %s, %s, %s, 'brother_profile')
                   ON CONFLICT (raw_string) DO NOTHING""",
                (b.full_name, res.person_id, res.method, res.score),
            )

    # Industries counter: count rows that now have industry_interests set.
    cur.execute("SELECT COUNT(*) FROM persons WHERE industry_interests IS NOT NULL "
                "AND person_type = 'active'")
    stats["industries_set"] = cur.fetchone()[0]

    conn.commit()
    stats["audit_rows"] = _audit_count() - audit_before

    cur.close()
    conn.close()

    _dump_conflicts(conflicts)
    return stats


if __name__ == "__main__":
    stats = load()
    for k, v in stats.items():
        print(f"  {k}: {v}")
