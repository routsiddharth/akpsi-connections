"""Name resolution for brother profile rows.

Inherits lin_pipeline.NameResolver to get the same exact / fuzzy_auto / review /
new_undergrad machinery and the idempotency cache through person_aliases. Only
override is where decisions persist: brother_review.json (not lin_review.json),
so the two pipelines' decision sets stay independent and auditable.

Conflict detection (existing person has source='alumni_master_key' and Brother
Profile data differs) lives in load.py — it needs the full BrotherRow context
to compare field-by-field, which is more than a name resolver should know.
"""
from __future__ import annotations

import json

from lin_pipeline.resolve import NameResolver

from . import config


class BrotherResolver(NameResolver):
    """NameResolver that reads/writes brother_review.json instead of lin_review.json."""

    def _load_decisions(self) -> dict:
        if config.REVIEW_FILE.exists():
            data = json.loads(config.REVIEW_FILE.read_text())
            return {d["raw"]: d for d in data if d.get("decision") in ("match", "new")}
        return {}

    def dump_review(self):
        config.DATA_DIR.mkdir(exist_ok=True)
        out = [vars(it) for it in self.review.values()]
        out += [d for raw, d in self._decisions.items() if raw not in self.review]
        config.REVIEW_FILE.write_text(json.dumps(out, indent=2, sort_keys=True))
