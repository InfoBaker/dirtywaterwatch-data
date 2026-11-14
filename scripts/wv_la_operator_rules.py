"""Owner names and legal forms from EPA's permit names, for scripts/add_wv_operators.py and scripts/add_la_operators.py
(a helper, not a script to run).

owner(permit_name, permittee, facility_type, state) -> (name, legal_form, how)
  - West Virginia: EPA's permit_name is the permittee as ICIS records it ("FAIRMONT, CITY OF", "SCOTTS RUN PSD",
    "MORGANTOWN UTILITY BD"); the permittee field is mostly the plant.
  - Louisiana: EPA's permit_name is "<owner> - <plant>" ("City of Shreveport- Lucas WWTP", "Walker City of - Walker
    Wastewater Treatment Plant"); the owner is the part before the dash.
  Rules, in order: OVERRIDES (per state, by a pattern on the owner text: one name for an operator EPA spells several
  ways); "<X>, City of" / "City of <X>" / "<X> City of" (also Town, Village) -> "City of <X>" (city; a town or village:
  town); a public service district ("PSD"), a sewerage, sewer, water or waterworks district, a sanitation or utility
  district -> special district; a board, commission or authority -> authority; a parish or county government, a police
  jury, a board of education -> county; a state agency or university, EPA facility type 'State Government' -> state
  facility; a federal agency or EPA type 'Federal Facility' -> federal facility; a name with LLC, Inc., Corporation,
  Company -> business or industrial (investor-owned utility when the name says utilities or water company);
  homeowners' associations, mobile-home parks, campgrounds and resorts, schools and churches by their words.
  Anything else keeps the name EPA gives, in title case, legal_form null (not read). A name shaped like a person's
  (build.redact.person_shaped, no operator word) is never used: the row is "Holder of permit <permit>", legal_form
  "facility (permittee not named)".
"""
from __future__ import annotations

import re
import string
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
from common import OPERATOR_WORDS  # noqa: E402

SMALL = {"of", "and", "the", "at", "for", "in", "on", "de", "du", "la"}
UPPER = {"psd", "wwtp", "stp", "llc", "lp", "wv", "us", "usa", "ii", "iii", "iv", "lus", "swb", "mhp", "rv", "dg"}


def title(s: str) -> str:
    out = []
    for i, w in enumerate(s.split()):
        lw = w.lower()
        if lw.strip(".,") in UPPER:
            out.append(w.upper())
        elif i and lw in SMALL:
            out.append(lw)
        else:
            out.append("-".join(p[:1].upper() + p[1:].lower() for p in w.split("-")))
    return " ".join(out)


def clean(s) -> str:
    return " ".join(str(s or "").replace("’", "'").split()).strip(" ,-")


def person_shaped(s: str) -> bool:
    words = {w.lower() for w in re.split(r"[\s\-/.,()&']+", s) if w}
    if words & OPERATOR_WORDS:
        return False
    from build import redact
    return bool(redact.person_shaped(s) or redact.person_shaped(string.capwords(s)))


MUNI = re.compile(r"^(?:(?P<a>city|town|village|corporation)\s+of\s+(?P<x>.+)|(?P<y>.+?),?\s+(?P<b>city|town|village|corporation)\s+of)$",
                  re.I)


# Louisiana's permit names put the place first in several ways: "Bastrop, City of (Main Plant)", "Sarepta,town of",
# "Downsville, Village-Downsville", "Plain Dealing, Town-WWTP", "Haynesville Town Of-WWTP (002)", "Moreauville WWT
# Facility, Vill"
MUNI_AFTER = re.compile(r"^(?P<y>[A-Za-z .']+?)\s*,\s*(?P<b>city|town|village|vill)\b|"
                        r"^(?P<z>[A-Za-z .']+?)\s+(?P<c>city|town|village)\s+of\b", re.I)


def municipal(s: str) -> tuple[str, str] | None:
    m = MUNI.match(s)
    if m:
        kind = (m.group("a") or m.group("b")).lower()
        place = clean(m.group("x") or m.group("y"))
    elif (m := MUNI_AFTER.match(s)):
        kind = (m.group("b") or m.group("c")).lower().replace("vill", "village").replace("villageage", "village")
        place = clean(m.group("y") or m.group("z"))
        place = re.sub(r"\s+(?:wwt|wwtp|stp|facility)\b.*$", "", place, flags=re.I).strip()
    else:
        return None
    if not place or re.search(r"\b(?:llc|inc|corp|company)\b", place, re.I):
        return None
    if kind == "corporation":             # West Virginia's older towns are chartered as "the Corporation of <X>"
        return f"Town of {title(place)}", "town"
    return f"{kind.title()} of {title(place)}", "city" if kind == "city" else "town"


STRONG_COMPANY = re.compile(r"\b(?:llc|l\.l\.c|corporation|corp|company|coal|incorporated)\b\.?", re.I)
RULES = [
    (re.compile(r"\b(?:u\.?\s?s\.?|united states|usda)\b.*\b(?:army|navy|air force|corps|department|forest|park|fish|"
                r"service|protection)|\bcorps of engineers\b|\bnational (?:park|forest|guard)\b|\bveterans affairs\b|"
                r"\bfederal\b|\bbureau of prisons\b|\bva medical\b|\bveterans\b", re.I), "federal facility"),
    (re.compile(r"\b(?:utilities|utility|water company|american water|aqua)\b.*\b(?:llc|inc|corp|company)\b|"
                r"\b(?:american water|aqua (?:louisiana|west virginia)|utilities,? inc)\b", re.I), "investor-owned utility"),
    (STRONG_COMPANY, "business or industrial"),
    (re.compile(r"\b(?:church|school of|academy|college|hospital|baptist|methodist|ministries|foundation)\b", re.I),
     "institution"),
    (re.compile(r"\b(?:public service district|psd|p\.s\.d\.?|sewerage district|sewer district|sanitation district|"
                r"sanitary district|water district|waterworks district|utility district|water ?works district|"
                r"water & sewer district|water and sewer district|sewerage dist|sd ?#?\s?\d+|development district|"
                r"industrial district)\b", re.I),
     "special district"),
    (re.compile(r"\b(?:parish|county|cnty|co\.? schools|police jury|board of education)\b", re.I), "county"),
    (re.compile(r"\b(?:state of|state park|division of|department of (?:corrections|transportation|health|natural|"
                r"environmental|highways|military|education|public safety|agriculture|wildlife)|wv dnr|dnr|"
                r"university|state police|regional jail|correctional (?:center|complex)|corrections|la ?dotd|la dept)\b", re.I),
     "state facility"),
    (re.compile(r"\b(?:board|bd|commission|authority|auth|comm|boparc)\b", re.I), "authority"),
    (re.compile(r"\b(?:home ?owners|owners'? association|property owners|poa|hoa)\b", re.I), "homeowners' association"),
    (re.compile(r"\b(?:mobile home|trailer park|mhp|mobile court|manufactured home)\b", re.I), "mobile-home park"),
    (re.compile(r"\b(?:campground|resort|rv park|camp ?ground|kampground)\b", re.I), "campground or resort"),
    (re.compile(r"\b(?:inc|corp|lp|ltd)\b\.?", re.I), "business or industrial"),
]


def owner_text(permit_name: str, state: str) -> str:
    s = clean(permit_name)
    if state == "LA":
        s = clean(re.split(r"\s*-\s+|\s+-\s*|-\s{1,2}(?=[A-Z])", s, maxsplit=1)[0])
    return s


def owner(permit_name, permittee, facility_type, state: str, permit: str, overrides: list) -> tuple[str, str | None, str]:
    raw = owner_text(permit_name or permittee or "", state)
    for pat, name, form in overrides:
        if re.search(pat, raw, re.I) or re.search(pat, clean(permit_name), re.I) or re.search(pat, clean(permittee), re.I):
            return name, form, "override"
    if not raw or "name removed" in raw.lower():
        return f"Holder of permit {permit}", "facility (permittee not named)", "no name"
    m = municipal(raw)
    if m:
        return m[0], m[1], "municipal"
    if re.search(r"\btribe\b|\bnation\b|\bband of\b", raw, re.I):
        return title(raw), "tribal", "rule"
    if re.search(r"\bparish\b|\bph\b", raw, re.I) and not STRONG_COMPANY.search(raw):
        return re.sub(r"\bPh\b", "Parish", title(raw)), "county", "rule"
    if person_shaped(raw):
        return f"Holder of permit {permit}", "facility (permittee not named)", "person-shaped name withheld"
    name = title(raw)
    name = re.sub(r"\bPSD\b", "Public Service District", name)
    for pat, form in RULES:
        if pat.search(raw):
            return name, form, "rule"
    ft = str(facility_type or "")
    if ft.startswith("State Government"):
        return name, "state facility", "EPA facility type"
    if ft.startswith("Federal"):
        return name, "federal facility", "EPA facility type"
    if ft.startswith("County Government"):
        return name, "county", "EPA facility type"
    return name, None, "as EPA names it"


def slug(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s.lower())).strip("-")
