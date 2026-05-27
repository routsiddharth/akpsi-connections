"""Interactive firm-merge review queue.

    python -m alumni_pipeline.review_cli

Surfaces only the AMBIGUOUS matches (rapidfuzz score in [REVIEW_MIN, AUTO_MERGE)).
Decisions persist to data/firm_review.json and are applied automatically on the next
load, so this is resumable — quit any time, pick up later.
"""
from __future__ import annotations

from collections import Counter

from .canonicalize import Canonicalizer
from .extract import extract_people
from .firmparse import parse_postgrad


def _token_counts() -> Counter:
    c: Counter = Counter()
    for p in extract_people():
        for st in parse_postgrad(p.post_grad_raw).stints:
            c[st.firm_raw.strip()] += 1
    return c


def main():
    counts = _token_counts()
    canon = Canonicalizer()
    canon.fit(counts)

    pending = list(canon.review.values())
    if not pending:
        print("Nothing to review — all firms resolved. ✅")
        print(canon.summary())
        return

    print(f"{len(pending)} ambiguous firm(s) to review.\n"
          "  [y] merge into suggestion   [n] keep as new firm\n"
          "  [r] rename (type canonical) [s] skip for now   [q] quit & save\n")

    for i, it in enumerate(sorted(pending, key=lambda x: -x.score), 1):
        n_raw = counts[it.raw]
        n_sug = sum(v for k, v in counts.items() if k.lower() == it.suggestion.lower())
        ans = input(
            f"[{i}/{len(pending)}] '{it.raw}' ({n_raw}x)  ~  "
            f"'{it.suggestion}' ({n_sug}x)   score={it.score}  merge? [y/n/r/s/q] "
        ).strip().lower()

        if ans == "q":
            break
        if ans == "s" or ans == "":
            continue
        if ans == "y":
            it.decision, it.canonical = "merge", it.suggestion
        elif ans == "r":
            name = input("    canonical name: ").strip()
            if name:
                it.decision, it.canonical = "merge", name
        else:  # n
            it.decision, it.canonical = "new", it.raw

    canon.dump_review()
    decided = sum(1 for it in pending if it.decision != "pending")
    print(f"\nSaved {decided} decision(s) to {canon.__class__.__module__}; "
          f"re-run `load` to apply.")


if __name__ == "__main__":
    main()
