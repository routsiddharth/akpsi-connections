"""Interactive review queue + conflict resolver.

    python -m brother_pipeline.review_cli

Two sequential sections:
  1. Ambiguous name matches (rapidfuzz score 80-92) — same y/n/r/s/q UX
     as the other review_cli scripts; decisions persist to brother_review.json.
  2. Per-field Master-Key conflicts — each differing field gets its own y/n/s
     choice; decisions persist to brother_conflicts.json. The loader applies
     'overwrite' decisions on the next `python -m brother_pipeline.run`.
"""
from __future__ import annotations

import json

import psycopg2

from . import config
from .load import _load_conflicts, _dump_conflicts
from .parse import parse
from .resolve import BrotherResolver


def _load_persons_and_aliases():
    conn = psycopg2.connect(config.DATABASE_URL)
    cur = conn.cursor()
    cur.execute("SELECT id, full_name, grad_year FROM persons")
    persons = [{"id": i, "full_name": n, "grad_year": gy} for i, n, gy in cur.fetchall()]
    cur.execute("SELECT raw_string, person_id FROM person_aliases "
                "WHERE person_id IS NOT NULL")
    aliases = dict(cur.fetchall())
    cur.close()
    conn.close()
    return persons, aliases


def _review_ambiguous(brothers, persons, aliases):
    resolver = BrotherResolver(persons, aliases)
    for b in brothers:
        resolver.resolve(b.full_name, grad_year_hint=b.grad_year)

    pending = sorted(resolver.review.values(), key=lambda x: -x.score)
    if not pending:
        print("No ambiguous name matches. ✅")
        return

    print(f"\n=== Ambiguous name matches ({len(pending)}) ===")
    print("  [y] match to suggestion       [n] insert as new active brother")
    print("  [r] rename (type a full name) [s] skip   [q] quit & save\n")

    for i, it in enumerate(pending, 1):
        ans = input(
            f"[{i}/{len(pending)}] '{it.raw}'  ~  '{it.suggestion}'   "
            f"score={it.score}  match? [y/n/r/s/q] "
        ).strip().lower()
        if ans == "q":
            break
        if ans in ("s", ""):
            continue
        if ans == "y":
            it.decision, it.matched_id = "match", it.suggestion_id
        elif ans == "r":
            name = input("    full_name to match against: ").strip()
            match = next(
                (p for p in persons if p["full_name"].lower() == name.lower()), None
            ) if name else None
            if match:
                it.decision, it.matched_id = "match", match["id"]
            else:
                print(f"    no person named '{name}' — skipping")
        else:                                    # 'n'
            it.decision = "new"

    resolver.dump_review()
    decided = sum(1 for it in pending if it.decision != "pending")
    print(f"Saved {decided} decision(s) to {config.REVIEW_FILE.name}.")


def _review_conflicts():
    conflicts = _load_conflicts()
    pending = [c for c in conflicts.values()
               if any(v == "pending" for v in c["decisions"].values())]
    if not pending:
        print("\nNo Master-Key conflicts pending. ✅")
        return

    print(f"\n=== Master-Key conflicts ({len(pending)}) ===")
    print("  Per field: [y] overwrite with Brother Profile value")
    print("             [n] keep Master Key value")
    print("             [s] skip this conflict   [q] quit & save\n")

    quit_now = False
    for i, c in enumerate(pending, 1):
        if quit_now:
            break
        print(f"\n[{i}/{len(pending)}] '{c['raw_name']}' "
              f"(persons.id={c['person_id']})")
        # Re-fetch current values from the DB so we show truth-at-decision-time.
        conn = psycopg2.connect(config.DATABASE_URL)
        cur = conn.cursor()
        for field, verdict in list(c["decisions"].items()):
            if verdict != "pending":
                continue
            cur.execute(f"SELECT {field} FROM persons WHERE id = %s", (c["person_id"],))
            current = cur.fetchone()[0]
            # 'new' value isn't in the file — we'd need to re-parse to know.
            # For now we just show current and ask whether to mark for overwrite.
            ans = input(
                f"    {field}: current={current!r}  overwrite on next run? [y/n/s/q] "
            ).strip().lower()
            if ans == "q":
                quit_now = True; break
            if ans == "y":
                c["decisions"][field] = "overwrite"
            elif ans == "n":
                c["decisions"][field] = "keep"
            # 's' or anything else leaves it 'pending'
        cur.close()
        conn.close()

    _dump_conflicts(conflicts)
    decided = sum(1 for c in conflicts.values()
                  for v in c["decisions"].values() if v != "pending")
    print(f"Saved {decided} field decision(s) to {config.CONFLICTS_FILE.name}.")


def main():
    brothers = parse()
    persons, aliases = _load_persons_and_aliases()
    _review_ambiguous(brothers, persons, aliases)
    _review_conflicts()
    print("\nRe-run `python -m brother_pipeline.run` to apply decisions.")


if __name__ == "__main__":
    main()
