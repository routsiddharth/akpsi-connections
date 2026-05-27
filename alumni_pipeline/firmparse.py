"""Parse one messy POST GRAD cell into structured employment segments.

Handled shapes (all observed in the real data):
  "Goldman Sachs"                          -> 1 current firm
  "Carlyle (Prev. GS)"                     -> current Carlyle + prior Goldman Sachs
  "TPG (Prev. KKR & GS)"                   -> current TPG + prior KKR + prior Goldman Sachs
  "(Prev.) Goldman Sachs"                  -> prior Goldman Sachs, current unknown
  "Litmus (YC 26)"                         -> current Y Combinator, group "Litmus"
  "Bank of America - ECM"                  -> current Bank of America, group "ECM"
  "Wharton (Prev. Amazon)"                 -> current Wharton (school) + prior Amazon
  "HBS"                                    -> current Harvard Business School (school)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Name fragments that mean "this org is a school, not an employer".
SCHOOL_HINTS = re.compile(
    r"\b(universit|college|law school|school of|business school|"
    r"masters?|master'?s|mba|ms in|m\.s\.|phd|ph\.d|doctorate|grad school|"
    r"hbs|gsb|wharton|seas|aeronautics)\b",
    re.IGNORECASE,
)
GOV_HINTS = re.compile(
    r"\b(department|dept\.?|u\.s\.|treasury|house of rep|general assembly|legal aid|congress)\b",
    re.IGNORECASE,
)
# Placeholder cells that are not an org at all.
NULLISH = {"n/a", "na", "-", "—", "", "stealth startup", "tbd"}


@dataclass
class Stint:
    firm_raw: str
    group_raw: str | None = None
    is_current: bool = True
    org_type: str | None = None  # None -> let canonicalizer decide; else school/government


@dataclass
class Parsed:
    stints: list[Stint] = field(default_factory=list)


def _org_type(name: str) -> str | None:
    # Law / professional-services firms are LLP/LLC even if a school name appears inside
    # them (e.g. "Paul, Weiss, Rifkind, Wharton & Garrison LLP").
    if re.search(r"\b(llp|llc)\b", name, re.IGNORECASE):
        return None
    if SCHOOL_HINTS.search(name):
        return "school"
    if GOV_HINTS.search(name):
        return "government"
    return None


# Words that follow "&" as part of ONE firm name, not a second firm.
# Lets us split "KKR & GS" (two firms) but keep "Bain & Co" (one firm).
_AMP_CONTINUATION = {
    "co", "company", "cromwell", "marsal", "case", "gray", "wirth",
    "msd", "garrison", "rifkind", "sons", "young", "partners",
}


def _split_multi(s: str) -> list[str]:
    """Split a "previously at ..." blob into separate firms.
    'KKR & GS' -> ['KKR','GS'] ; 'Bain & Co' -> ['Bain & Co'] (stays whole)."""
    out: list[str] = []
    for seg in re.split(r"\s*(?:,|/| and )\s*", s):  # always split , / "and"
        amp = seg.split(" & ")
        merged = [amp[0]]
        for nxt in amp[1:]:
            head = nxt.split()[0].lower().rstrip(".") if nxt.split() else ""
            if head in _AMP_CONTINUATION:
                merged[-1] = f"{merged[-1]} & {nxt}"  # rejoin: part of the name
            else:
                merged.append(nxt)                    # genuinely a second firm
        out.extend(merged)
    return [p.strip() for p in out if p.strip()]


def parse_postgrad(raw: str | None) -> Parsed:
    if raw is None:
        return Parsed()
    s = str(raw).strip()
    if s.lower() in NULLISH:
        return Parsed()

    prior_firms: list[str] = []

    # 1. Pull out "(Prev. ...)" history, then strip it from the string.
    m = re.search(r"\(\s*prev\.?\s*[:.]?\s*(.*?)\s*\)", s, re.IGNORECASE)
    leading_prev = re.match(r"^\(\s*prev\.?\s*\)\s*(.+)$", s, re.IGNORECASE)
    if leading_prev:
        # "(Prev.) Goldman Sachs" -> the whole thing is prior, no current.
        prior_firms.extend(_split_multi(leading_prev.group(1)))
        return Parsed([Stint(firm_raw=f, is_current=False, org_type=_org_type(f))
                       for f in prior_firms])
    if m:
        if m.group(1):
            prior_firms.extend(_split_multi(m.group(1)))
        s = (s[: m.start()] + s[m.end():]).strip()

    # 2. YC startups resolve to "Y Combinator", startup name kept as the group.
    yc = re.search(r"\(\s*yc[^)]*\)", s, re.IGNORECASE)
    if yc:
        startup = (s[: yc.start()] + s[yc.end():]).strip(" -")
        stints = [Stint(firm_raw="Y Combinator", group_raw=startup or None, is_current=True,
                        org_type="startup")]
        stints += [Stint(firm_raw=f, is_current=False, org_type=_org_type(f))
                   for f in prior_firms]
        return Parsed(stints)

    # 3. "Firm - Group" -> firm + group (split on first ' - ' only).
    current_group = None
    if " - " in s:
        firm_part, group_part = s.split(" - ", 1)
        s, current_group = firm_part.strip(), group_part.strip()

    stints: list[Stint] = []
    if s and s.lower() not in NULLISH:
        stints.append(Stint(firm_raw=s, group_raw=current_group, is_current=True,
                            org_type=_org_type(s)))
    stints += [Stint(firm_raw=f, is_current=False, org_type=_org_type(f)) for f in prior_firms]
    return Parsed(stints)


if __name__ == "__main__":
    for t in ["Goldman Sachs", "Carlyle (Prev. GS)", "TPG (Prev. KKR & GS)",
              "(Prev.) Goldman Sachs", "Litmus (YC 26)", "Bank of America - ECM",
              "Wharton (Prev. Amazon)", "HBS", "Stealth Startup", "-"]:
        p = parse_postgrad(t)
        print(f"{t:28} -> " + " | ".join(
            f"{'CUR' if st.is_current else 'PREV'}:{st.firm_raw}"
            + (f"[{st.group_raw}]" if st.group_raw else "")
            + (f"<{st.org_type}>" if st.org_type else "")
            for st in p.stints) or f"{t:28} -> (none)")
