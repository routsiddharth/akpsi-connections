"""Resolve messy raw firm tokens to canonical firms.

Pipeline per raw token (after firmparse has split off Prev./YC/group):
  1. SPLIT_OVERRIDE  (raw -> firm + group)        method=seed
  2. ALIAS           (raw -> canonical)           method=seed
  3. persisted human review decision              method=reviewed
  4. exact normalized match to an existing canon  method=exact
  5. rapidfuzz token_sort_ratio vs canon set:
       >= FUZZY_AUTO_MERGE  -> merge               method=fuzzy_auto
       >= FUZZY_REVIEW_MIN  -> queue for review     (kept as new until decided)
       else                 -> new canonical        method=new

Popular firms are processed first so they become the anchors others merge into.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field

from rapidfuzz import fuzz, process

from . import config
from .aliases import ALIASES, SPLIT_OVERRIDES

_SUFFIX = re.compile(r"\b(inc|incorporated|llc|l\.?p\.?|llp|ltd|the)\b", re.IGNORECASE)


def normalize(s: str) -> str:
    """Conservative key for blocking/exact compares. Keeps 'group'/'partners'/'&'
    so distinct firms (Raine Group vs Raine-anything) don't collapse by accident."""
    s = s.lower().strip()
    s = re.sub(r"[.,]", "", s)
    s = _SUFFIX.sub("", s)
    return re.sub(r"\s+", " ", s).strip()


@dataclass
class ReviewItem:
    raw: str
    suggestion: str       # nearest existing canonical
    score: float
    decision: str = "pending"   # pending | merge | new
    canonical: str | None = None  # filled when decided


class Canonicalizer:
    def __init__(self):
        self.canon_norm: dict[str, str] = {}   # normalized -> canonical display name
        self.resolution: dict[str, tuple] = {} # raw_lower -> (canonical, group, method, score)
        self.review: dict[str, ReviewItem] = {}
        self._decisions = self._load_decisions()

    # ---- persisted human decisions (resumable across runs) ----
    def _load_decisions(self) -> dict:
        if config.REVIEW_FILE.exists():
            data = json.loads(config.REVIEW_FILE.read_text())
            return {d["raw"]: d for d in data if d.get("decision") in ("merge", "new")}
        return {}

    def dump_review(self):
        config.DATA_DIR.mkdir(exist_ok=True)
        out = [vars(it) for it in self.review.values()]
        # keep already-decided ones too, so the file is the full audit log
        out += [d for raw, d in self._decisions.items() if raw not in self.review]
        config.REVIEW_FILE.write_text(json.dumps(out, indent=2, sort_keys=True))

    def _register(self, canonical: str):
        self.canon_norm.setdefault(normalize(canonical), canonical)

    def fit(self, tokens: Counter):
        """tokens: Counter of raw firm strings -> frequency."""
        # Pass 1: seed canonical set from curated knowledge so anchors exist first.
        for canon in set(ALIASES.values()) | {v[0] for v in SPLIT_OVERRIDES.values()}:
            self._register(canon)

        # Pass 2: resolve, most-frequent first.
        for raw, _ in tokens.most_common():
            low = raw.lower().strip()

            if low in SPLIT_OVERRIDES:
                firm, group = SPLIT_OVERRIDES[low]
                self._register(firm)
                self.resolution[low] = (firm, group, "seed", 100.0)
                continue
            if low in ALIASES:
                firm = ALIASES[low]
                self._register(firm)
                self.resolution[low] = (firm, None, "seed", 100.0)
                continue
            if raw in self._decisions:
                d = self._decisions[raw]
                firm = d["canonical"] if d["decision"] == "merge" else raw
                self._register(firm)
                self.resolution[low] = (firm, None, "reviewed", d.get("score", 0.0))
                continue

            norm = normalize(raw)
            if norm in self.canon_norm:
                self.resolution[low] = (self.canon_norm[norm], None, "exact", 100.0)
                continue

            # fuzzy vs existing canonical names
            choices = list(self.canon_norm.keys())
            best = process.extractOne(norm, choices, scorer=fuzz.token_sort_ratio) if choices else None
            if best and best[1] >= config.FUZZY_AUTO_MERGE:
                canon = self.canon_norm[best[0]]
                self.resolution[low] = (canon, None, "fuzzy_auto", best[1])
            elif best and best[1] >= config.FUZZY_REVIEW_MIN:
                canon = self.canon_norm[best[0]]
                self.review[raw] = ReviewItem(raw=raw, suggestion=canon, score=round(best[1], 1))
                self._register(raw)  # keep separate until a human decides
                self.resolution[low] = (raw, None, "new", best[1])
            else:
                self._register(raw)
                self.resolution[low] = (raw, None, "new", best[1] if best else 0.0)

    def resolve(self, raw: str) -> tuple[str, str | None]:
        """raw firm string -> (canonical name, group override or None)."""
        low = raw.lower().strip()
        if low in self.resolution:
            c = self.resolution[low]
            return c[0], c[1]
        self._register(raw)
        return raw, None

    def summary(self) -> str:
        methods = Counter(v[2] for v in self.resolution.values())
        return (f"{len(self.resolution)} raw tokens -> {len(self.canon_norm)} canonical firms | "
                f"methods={dict(methods)} | pending review={len(self.review)}")
