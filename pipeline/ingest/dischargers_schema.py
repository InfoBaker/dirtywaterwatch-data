"""The operator registry's legal forms (data/dischargers.json `legal_form`): one controlled list, and a check that warns
and never fails. A helper, not a feed (`make ingest` leaves it out).

Run from pipeline/:  python -m ingest.dischargers_schema [--strict]

The controlled list (LEGAL_FORMS) has a public side and a private side. A value the registry already uses that is not
on the list maps to one (LEGACY); a row whose name contradicts its value's mapping has its own target (ROW_OVERRIDES).
Neither renames anything: the mapping is a proposal (docs/legal-forms.md) applied as its own reviewed change once the
open state branches have merged. The check (check_legal_forms) returns warnings:
  - a value neither on the list nor mapped (unmapped);
  - a private form on a row whose name reads as a public body, or a public form on a row whose name reads as a company
    or association (the North Carolina review's P2-1: a public district filed as a privately owned facility).
A row with no legal_form is not warned about (most rows have none yet). `--strict` exits 1 when a value is unmapped;
without it the exit is 0 whatever the warnings.
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
PRIVATE_FORMS = ("investor-owned utility", "homeowners' association", "mobile-home park", "campground or resort",
                 "private club", "business or industrial", "institution", "facility (permittee not named)")
LEGAL_FORMS = PUBLIC_FORMS + PRIVATE_FORMS

# values in use (data/dischargers.json, scripts/add_nc_operators.py LEGAL_FORMS, research/<st>/dischargers.json) ->
# the controlled value
LEGACY = {
    "municipal": "city",                   # Georgia: a city's or a county's department (ROW_OVERRIDES for counties)
    "municipal utility": "city",           # Florida: JEA (ROW_OVERRIDES)
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

# rows whose name contradicts their value's mapping: id -> (controlled value, why)
ROW_OVERRIDES = {
    "ga-cobb-county": ("county", "Cobb County Water System is a county department"),
    "ga-dekalb-dwm": ("county", "DeKalb County Department of Watershed Management"),
    "ga-fulton-county": ("county", "Fulton County Department of Public Works"),
    "ga-gwinnett-county": ("county", "Gwinnett County Department of Water Resources"),
    "ga-augusta-utilities": ("city", "Augusta-Richmond County is a consolidated city-county government"),
    "ga-columbus-water-works": ("city", "a board of the consolidated city-county government of Columbus"),
    "fl-jea": ("authority", "JEA is an independent authority of the City of Jacksonville, not a city department"),
    "fl-fl0039829": ("county", "LEE COUNTY UTILITIES - FIESTA VILLAGE: Lee County's plant; 'village' is the plant's "
                               "name, not the permittee's form"),
}

PUBLIC_NAME = re.compile(
    r"^(city|town|village|borough|township|county)\s+of\b|\b(city|town|village|borough|township)\s+of\b|"
    r",\s*(city|town|village|borough)\s+of\b|\bcounty\b|\bauthority\b|\bmunicipal|\b(utility|sanitary|sanitation|"
    r"sewer|sewerage|water|improvement|metropolitan|public service)\s+district\b|\bdistrict of columbia\b|"
    r"\bdepartment of\b|\bcommission\b|\bfederal\b|\b(army|navy|naval|air force|marine corps)\b|\btrib(e|al)\b", re.I)
PRIVATE_NAME = re.compile(r"\b(inc|llc|l\.l\.c|ltd|lp|corp|corporation|company|association|assn|poa|hoa|club|mhp|"
                          r"mhc)\b\.?", re.I)


def controlled(row: dict) -> tuple[str | None, str]:
    """(the controlled value, how): how is "controlled", "mapped", "override", "unmapped" or "absent"."""
    v = row.get("legal_form")
    if not v:
        return None, "absent"
    if row.get("id") in ROW_OVERRIDES:
        return ROW_OVERRIDES[row["id"]][0], "override"
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
        if value in PRIVATE_FORMS and PUBLIC_NAME.search(name) and not PRIVATE_NAME.search(name):
            out.append(f"{rid}: legal_form {r.get('legal_form')!r} is private but the name {name!r} reads as a public "
                       f"body: check the permit")
        elif value in PUBLIC_FORMS and PRIVATE_NAME.search(name) and not PUBLIC_NAME.search(name):
            out.append(f"{rid}: legal_form {r.get('legal_form')!r} is public but the name {name!r} reads as a company "
                       f"or association: check the permit")
    return out


def summary(rows: list[dict]) -> dict:
    hows = Counter(controlled(r)[1] for r in rows if isinstance(r, dict))
    values = Counter((r.get("legal_form"), controlled(r)[0]) for r in rows if isinstance(r, dict) and r.get("legal_form"))
    return {"rows": sum(hows.values()), "by_how": dict(sorted(hows.items())),
            "values": {f"{a} -> {b}": n for (a, b), n in sorted(values.items(), key=lambda kv: str(kv[0]))}}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Check data/dischargers.json legal forms (warnings only)")
    ap.add_argument("--file", default=str(DATA_DIR / "dischargers.json"))
    ap.add_argument("--strict", action="store_true", help="exit 1 when a value is unmapped")
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
    return 1 if a.strict and s["by_how"].get("unmapped") else 0


if __name__ == "__main__":
    sys.exit(main())
