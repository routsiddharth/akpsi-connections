"""Interactive name-resolution review queue.

    python -m lin_pipeline.review_cli

Mirrors alumni_pipeline.review_cli: surfaces only AMBIGUOUS rapidfuzz hits
(score in [REVIEW_MIN, AUTO_MERGE)). Decisions persist to data/lin_review.json
and are applied on the next `python -m lin_pipeline.run`. Resumable.
"""
from __future__ import annotations

import psycopg2

from . import config
from .parse import parse
from .resolve import NameResolver


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


def main():
    edges, roster = parse()
    persons, aliases = _load_persons_and_aliases()
    resolver = NameResolver(persons, aliases)

    # Resolve every raw name so the ambiguous ones surface into resolver.review.
    # Pass grad_year_hint for roster names so the review queue matches what load.py
    # would see — without this, the CLI silently fuzzy_auto-matches things load.py
    # correctly downgrades, and the human never sees the case.
    seen: set[str] = set()
    for r in roster:
        if r.name_raw not in seen:
            seen.add(r.name_raw); resolver.resolve(r.name_raw, grad_year_hint=r.grad_year)
    for e in edges:
        for n in (e.little_raw, e.big_raw):
            if n not in seen:
                seen.add(n); resolver.resolve(n)

    pending = sorted(resolver.review.values(), key=lambda x: -x.score)
    if not pending:
        print("Nothing to review — all names resolved. ✅")
        print(resolver.summary())
        return

    print(f"{len(pending)} ambiguous name(s) to review.\n"
          "  [y] match to suggestion       [n] insert as new undergrad\n"
          "  [r] rename (type a full name) [s] skip   [q] quit & save\n")

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
        else:                                    # 'n' or anything else -> new
            it.decision = "new"

    resolver.dump_review()
    decided = sum(1 for it in pending if it.decision != "pending")
    print(f"\nSaved {decided} decision(s) to {config.REVIEW_FILE.name}; "
          "re-run `python -m lin_pipeline.run` to apply.")


if __name__ == "__main__":
    main()
