"""Curated, hand-reviewed canonicalization knowledge.

These cover the cases fuzzy matching CANNOT get right on its own:
  - abbreviations  (GS -> Goldman Sachs, BCG -> Boston Consulting Group)
  - parent/child   (AWS -> Amazon / group "AWS")
  - true synonyms  (Facebook -> Meta)
Everything keyed by the *lowercased raw* firm token (after firmparse splitting).

Deliberately NOT merged (look similar, are different firms):
  Citi vs Citadel ; Bain & Company vs Bain Capital ; Raine Group vs Riverwood.
"""

# raw (lowercased) -> canonical firm name
ALIASES = {
    "gs": "Goldman Sachs",
    "goldman": "Goldman Sachs",
    "goldman sachs": "Goldman Sachs",
    "bcg": "Boston Consulting Group",
    "boston consulting group (bcg)": "Boston Consulting Group",
    "boston consulting group": "Boston Consulting Group",
    "mckinsey": "McKinsey & Company",
    "mckinsey & company": "McKinsey & Company",
    "jp morgan": "J.P. Morgan",
    "j.p. morgan": "J.P. Morgan",
    "jpm": "J.P. Morgan",
    "jpmorganchase": "J.P. Morgan",
    "jpmorgan chase": "J.P. Morgan",
    "ms": "Morgan Stanley",
    "morgan stanley": "Morgan Stanley",
    "bain & co": "Bain & Company",
    "bain & co.": "Bain & Company",
    "bain & company": "Bain & Company",
    "facebook": "Meta",
    "meta": "Meta",
    "raine": "Raine Group",
    "raine group": "Raine Group",
    "balyasny asset management l.p.": "Balyasny Asset Management",
    "balyasny asset management": "Balyasny Asset Management",
    "citi": "Citi",
    "google": "Google",
    "youtube": "YouTube",
    # school abbreviations -> full names
    "hbs": "Harvard Business School",
    "wharton": "The Wharton School",
    "mit": "Massachusetts Institute of Technology",
}

# raw (lowercased) -> (canonical firm, group within that firm)
SPLIT_OVERRIDES = {
    "aws": ("Amazon", "AWS"),
    "google deepmind": ("Google", "DeepMind"),
    "instagram": ("Meta", "Instagram"),
    "jpm private bank": ("J.P. Morgan", "Private Bank"),
    "bnp paribas cib": ("BNP Paribas", "CIB"),
    "bain nps prism": ("Bain & Company", "NPS Prism"),
    "strategy&": ("PwC", "Strategy&"),
    "pwc (strategy&)": ("PwC", "Strategy&"),
}

# canonical firm name -> metadata overrides (org_type wins over firmparse's guess)
CANONICAL_META = {
    "Harvard Business School": {"org_type": "school"},
    "The Wharton School": {"org_type": "school"},
    "Massachusetts Institute of Technology": {"org_type": "school"},
    "Y Combinator": {"org_type": "company"},
}
