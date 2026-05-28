"""Resolve raw Lin-Trees names to persons.id, mirroring Step 1's Canonicalizer.

Resolution order per raw name:
  0. Idempotency cache: raw_string already in person_aliases  -> method=cached
  1. Persisted human decision (data/lin_review.json)          -> method=reviewed
  2. Exact normalized match vs persons.full_name              -> method=exact
  3. rapidfuzz.token_sort_ratio vs persons.full_name:
       >= FUZZY_AUTO_MERGE  -> match                          -> method=fuzzy_auto
       >= FUZZY_REVIEW_MIN  -> review queue (raw left unresolved)
       else                 -> new undergrad (loader creates)  -> method=new_undergrad

Nicknames (Tommy -> Thomas) are baked into _norm so they collapse to one key —
that's what lets us avoid inserting Tommy Soltanian AND Thomas Soltanian as two
separate undergrads when both appear in the workbook.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass

from rapidfuzz import fuzz, process

from . import config


# Conservative seed of nicknames observed in the data. Add to as needed —
# mirrors the curated ALIASES dict in alumni_pipeline.aliases.
NICKNAMES = {
    "tommy": "thomas",
    "bill": "william",
    "mike": "michael",
    "will": "william",
    "alex": "alexander",
}


@dataclass
class Resolution:
    raw: str
    person_id: int | None
    method: str           # cached | reviewed | exact | fuzzy_auto | review | new_undergrad
    score: float          # 0..100 (0 if not applicable)
    full_name: str | None = None


@dataclass
class ReviewItem:
    raw: str
    suggestion: str
    suggestion_id: int
    score: float
    decision: str = "pending"     # pending | match | new
    matched_id: int | None = None


def _norm(s: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace, apply nickname seed.

    Nickname rewrite happens here so Tommy/Thomas collapse to one key in by_norm
    — that's the single trick that prevents same-person duplicates."""
    parts = re.sub(r"[.,]", "", s.lower().strip()).split()
    if parts and parts[0] in NICKNAMES:
        parts[0] = NICKNAMES[parts[0]]
    return " ".join(parts)


class NameResolver:
    def __init__(self, persons: list[dict], aliases: dict[str, int] | None = None):
        """persons: [{id, full_name, grad_year}] — current DB rows.
        aliases: {raw_string: person_id} from person_aliases (idempotency layer)."""
        self.persons_by_id: dict[int, dict] = {p["id"]: p for p in persons}
        self.by_norm: dict[str, dict] = {}
        for p in persons:
            self.by_norm.setdefault(_norm(p["full_name"]), p)
        self.aliases = dict(aliases or {})
        self.resolutions: dict[str, Resolution] = {}
        self.review: dict[str, ReviewItem] = {}
        self._decisions = self._load_decisions()

    def _load_decisions(self) -> dict:
        if config.REVIEW_FILE.exists():
            data = json.loads(config.REVIEW_FILE.read_text())
            return {d["raw"]: d for d in data if d.get("decision") in ("match", "new")}
        return {}

    def dump_review(self):
        config.DATA_DIR.mkdir(exist_ok=True)
        out = [vars(it) for it in self.review.values()]
        # preserve already-decided rows so the file is the full audit log
        out += [d for raw, d in self._decisions.items() if raw not in self.review]
        config.REVIEW_FILE.write_text(json.dumps(out, indent=2, sort_keys=True))

    def add_person(self, full_name: str, person_id: int):
        """Tell the resolver about a person inserted DURING this run, so subsequent
        resolves can match against them (prevents Tommy/Thomas duplicates)."""
        p = {"id": person_id, "full_name": full_name}
        self.persons_by_id[person_id] = p
        self.by_norm.setdefault(_norm(full_name), p)

    def resolve(self, raw: str, grad_year_hint: int | None = None) -> Resolution:
        """grad_year_hint: when the caller knows the person's grad year (e.g. from
        the roster tab), a fuzzy_auto match against an existing person whose grad
        year is >2 years off gets downgraded to the review queue. Catches
        'Jake Lee (2027 undergrad)' ~ 'Jae Lee (2023 alum)' — high token similarity
        but obviously different people."""
        if raw in self.resolutions:
            return self.resolutions[raw]

        # 0. Idempotency cache — raw_string already mapped on a previous run.
        if raw in self.aliases:
            pid = self.aliases[raw]
            p = self.persons_by_id.get(pid)
            r = Resolution(raw, pid, "cached", 100.0, p["full_name"] if p else raw)
            self.resolutions[raw] = r
            return r

        # 1. Persisted human decision.
        if raw in self._decisions:
            d = self._decisions[raw]
            if d["decision"] == "match":
                p = self.persons_by_id.get(d.get("matched_id"))
                r = Resolution(raw, d.get("matched_id"), "reviewed",
                               d.get("score", 0.0), p["full_name"] if p else None)
            else:                                # 'new' — loader creates the undergrad
                r = Resolution(raw, None, "new_undergrad", 0.0, raw)
            self.resolutions[raw] = r
            return r

        # 2. Exact normalized match (nickname rewrite baked into _norm).
        norm = _norm(raw)
        if norm in self.by_norm:
            p = self.by_norm[norm]
            r = Resolution(raw, p["id"], "exact", 100.0, p["full_name"])
            self.resolutions[raw] = r
            return r

        # 3. Fuzzy.
        choices = list(self.by_norm.keys())
        best = process.extractOne(norm, choices, scorer=fuzz.token_sort_ratio) if choices else None
        if best and best[1] >= config.FUZZY_AUTO_MERGE:
            p = self.by_norm[best[0]]
            # Grad-year sanity check: if we have a hint and the candidate is >2yrs
            # off, this is almost certainly a name collision, not a match.
            if (grad_year_hint and p.get("grad_year")
                    and abs(grad_year_hint - p["grad_year"]) > 2):
                self.review[raw] = ReviewItem(
                    raw=raw, suggestion=p["full_name"], suggestion_id=p["id"],
                    score=round(best[1], 1),
                )
                r = Resolution(raw, None, "review", best[1])
                self.resolutions[raw] = r
                return r
            r = Resolution(raw, p["id"], "fuzzy_auto", best[1], p["full_name"])
        elif best and best[1] >= config.FUZZY_REVIEW_MIN:
            p = self.by_norm[best[0]]
            self.review[raw] = ReviewItem(
                raw=raw, suggestion=p["full_name"], suggestion_id=p["id"],
                score=round(best[1], 1),
            )
            r = Resolution(raw, None, "review", best[1])
        else:
            r = Resolution(raw, None, "new_undergrad",
                           best[1] if best else 0.0, raw)

        self.resolutions[raw] = r
        return r

    def summary(self) -> str:
        methods = Counter(r.method for r in self.resolutions.values())
        return (f"{len(self.resolutions)} raw names | methods={dict(methods)} | "
                f"pending review={len(self.review)}")
