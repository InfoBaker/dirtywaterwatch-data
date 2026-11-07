"""The operator registry's legal forms (data/dischargers.json `legal_form`): one controlled list, and a check. A helper,
not a feed (`make ingest` leaves it out).

Run from pipeline/:  python -m ingest.dischargers_schema [--strict]

The controlled list (LEGAL_FORMS) has a public side and a private side. Every row of data/dischargers.json carries a
value on the list (the renaming of 2026-11-04, docs/legal-forms.md, applied the mapping below and the per-row targets
for the Georgia county departments, the consolidated city-counties, JEA and Lee County's Fiesta Village plant to the
rows themselves). A value a builder's source still uses that is not on the list maps to one (LEGACY): a research file
or scripts/add_nc_operators.py, which writes the mapped value. The check (check_legal_forms) returns warnings:
  - a value neither on the list nor mapped (unmapped);
  - a value not on the list but mapped (legacy): map it before the row goes in;
  - a private form on a row whose name reads as a public body, or a public form on a row whose name reads as a company
    or association (a public district once filed as a privately owned facility).
A row with no legal_form is not warned about (most rows have none yet). `--strict` exits 1 when a value is not on the
list (unmapped or legacy); the tests run it on the registry. Without it the exit is 0 whatever the warnings.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

from common import DATA_DIR

PUBLIC_FORMS = ("city", "town", "county", "authority", "special district", "federal facility", "state facility",
                "tribal")
PRIVATE_FORMS = ("investor-owned utility", "member-owned utility", "homeowners' association", "mobile-home park", "campground or resort",
                 "private club", "business or industrial", "institution", "facility (permittee not named)")
LEGAL_FORMS = PUBLIC_FORMS + PRIVATE_FORMS

# values the builders' sources use (scripts/add_nc_operators.py LEGAL_FORMS, research/<st>/dischargers.json, and the
# values data/dischargers.json used before the renaming) -> the controlled value. A row whose name contradicted its
# value's mapping (a Georgia county department filed "municipal", JEA "municipal utility", Lee County's Fiesta Village
# plant "village") now carries its own value; a new such row is set by hand.
LEGACY = {
    "municipal": "city",                   # Georgia, before the renaming (the four county departments are "county")
    "municipal utility": "city",           # Florida, before the renaming (its one row, JEA, is an "authority")
    "village": "town",                     # a village, borough or township is a town on the list
    "borough": "town",
    "township": "town",
    "county department": "county",
    "utility authority": "authority",
    "district": "special district",        # research/<st>/dischargers.json
    "private utility": "investor-owned utility",
    "private company": "business or industrial",
    "industrial facility": "business or industrial",
    "owners' association": "homeowners' association",
}

PUBLIC_NAME = re.compile(
    r"^(city|town|village|borough|township|county)\s+of\b|\b(city|town|village|borough|township)\s+of\b|"
    r",\s*(city|town|village|borough)\s+of\b|\bcounty\b|\bauthority\b|\bmunicipal|\b(utility|sanitary|sanitation|"
    r"sewer|sewerage|water|improvement|metropolitan|public service)\s+district\b|\bdistrict of columbia\b|"
    r"\bdepartment of\b|\bcommission\b|\bfederal\b|\b(army|navy|naval|air force|marine corps)\b|\btrib(e|al)\b|"
    r"\bdistrict agricultural association\b", re.I)   # a California state agency (a fairground's), not a private body
# New Mexico's mutual domestic water and sewage works associations: political subdivisions under the Sanitary Projects
# Act (NMSA 1978, Chapter 3, Article 29), not private bodies; read as public names on New Mexico rows only
STATE_PUBLIC_NAME = {"NM": re.compile(r"\bmutual (?:domestic|sewage|sewer|water and sewer)\b[\w\s&]*\bassociation\b",
                                      re.I),
                     # Alabama's municipal water, sewer, gas and utilities boards are public corporations incorporated
                     # under Ala. Code Title 11, Chapter 50, so their legal names carry "Inc." ("Grand Bay Water Works
                     # Board, Inc."); so is a town's governmental utility services corporation (Moody's)
                     "AL": re.compile(r"\b(?:water ?works|water|sewer|gas|utilities|utility)\b[\w\s,&]*\bboard\b|"
                                      r"\bgovernmental utility services corporation\b", re.I)}
PRIVATE_NAME = re.compile(r"\b(inc|llc|l\.l\.c|ltd|lp|corp|corporation|company|association|assn|poa|hoa|club|mhp|"
                          r"mhc)\b\.?", re.I)


def controlled(row: dict) -> tuple[str | None, str]:
    """(the controlled value, how): how is "controlled", "mapped", "unmapped" or "absent"."""
    v = row.get("legal_form")
    if not v:
        return None, "absent"
    if v in LEGAL_FORMS:
        return v, "controlled"
    if v in LEGACY:
        return LEGACY[v], "mapped"
    return None, "unmapped"


def check_legal_forms(rows: list[dict]) -> list[str]:
    """Warnings for the registry's legal forms (never raises)."""
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        value, how = controlled(r)
        rid, name = r.get("id"), str(r.get("name") or "")
        if how == "unmapped":
            out.append(f"{rid}: legal_form {r.get('legal_form')!r} is not on the controlled list and has no mapping "
                       f"(ingest/dischargers_schema.py LEGAL_FORMS, LEGACY)")
            continue
        if how == "mapped":
            out.append(f"{rid}: legal_form {r.get('legal_form')!r} is not on the controlled list; it maps to "
                       f"{value!r} (ingest/dischargers_schema.py LEGACY): write that")
        if value in PRIVATE_FORMS and PUBLIC_NAME.search(name) and not PRIVATE_NAME.search(name):
            out.append(f"{rid}: legal_form {r.get('legal_form')!r} is private but the name {name!r} reads as a public "
                       f"body: check the permit")
        elif value in PUBLIC_FORMS and PRIVATE_NAME.search(name) and not PUBLIC_NAME.search(name) and not (
                STATE_PUBLIC_NAME.get(r.get("state") or "") and STATE_PUBLIC_NAME[r["state"]].search(name)):
            out.append(f"{rid}: legal_form {r.get('legal_form')!r} is public but the name {name!r} reads as a company "
                       f"or association: check the permit")
    return out


def summary(rows: list[dict]) -> dict:
    hows = Counter(controlled(r)[1] for r in rows if isinstance(r, dict))
    values = Counter((r.get("legal_form"), controlled(r)[0]) for r in rows if isinstance(r, dict) and r.get("legal_form"))
    return {"rows": sum(hows.values()), "by_how": dict(sorted(hows.items())),
            "values": {f"{a} -> {b}": n for (a, b), n in sorted(values.items(), key=lambda kv: str(kv[0]))}}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Check data/dischargers.json legal forms (--strict fails on a value not on the list)")
    ap.add_argument("--file", default=str(DATA_DIR / "dischargers.json"))
    ap.add_argument("--strict", action="store_true", help="exit 1 when a value is not on the controlled list")
    a = ap.parse_args(argv)
    rows = json.loads(Path(a.file).read_text())
    s = summary(rows)
    print(f"{s['rows']} rows; legal_form: {s['by_how']}")
    for k, n in s["values"].items():
        print(f"  {n:4}  {k}")
    warns = check_legal_forms(rows)
    for w in warns:
        print("WARNING " + w)
    print(f"{len(warns)} warning(s)")
    return 1 if a.strict and (s["by_how"].get("unmapped") or s["by_how"].get("mapped")) else 0


if __name__ == "__main__":
    sys.exit(main())
