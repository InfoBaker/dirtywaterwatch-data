"""Nebraska operator rows for data/dischargers.json: one row per operator, every Nebraska permit in exactly one row.

Usage: pipeline/.venv/bin/python -I scripts/add_ne_operators.py [--dry-run]

Inputs
  1. research/ne/dischargers.json (13 rows): Omaha's CSO permit and the plants that report most in EPA's overflow
     tables. Omaha's three permits (the CSO permit NE0133680, Papillion Creek WRRF NE0112810, Missouri River WRRF
     NE0036358) are one operator, the City of Omaha, and Lincoln's two (Northeast NE0112488, Theresa Street NE0036820)
     one, the City of Lincoln: each joined row keeps the research ids as aliases, so the overflow module's discharger
     ids (taken from the research rows) resolve to it. Every research row is kind "sso" here (EPA's overflow tables
     carry their reports) and Omaha's "cso".
  2. data/outfalls-plants-us.json and data/outfalls-us.json: every Nebraska permit EPA lists (322 plant permits, the one
     CSO inventory permit). Nebraska's permit names are mostly the plant's ("BEATRICE WWTF"), so the operator is read
     from the name: a plant named for the town it lies in is that town's (one row per town key, so "HERMAN WWTF" and
     "Village of Herman" are one row); OWNERS joins other spellings and names the owner where the name does not.
     Sanitary improvement districts ("SID 5 CASS CO - ...") are special districts, homeowners' associations private.
  3. research/ne/private-utilities-candidates.json (22 private sewage permits, 13 of them not in EPA's plant list):
     PRIVATE files each under its permittee as EPA ICIS-NPDES records it, with legal_form from the controlled list
     (docs/legal-forms.md), never an individual's name; where the candidates file removed the permittee or the
     facility, the row names the facility or the permit and its town, legal_form "facility (permittee not named)".
     NE0113298 (Hastings' Maxon Avenue plant) and the two sanitary improvement districts EPA types private are public.
  4. The Nebraska permits of EPA's overflow tables that no row holds (NE0139611, Verdigre's sanitary sewer system),
     joined to the town's row by the collection system's name EPA's table gives (the 2026-11-04 extract).
Rules
  - legal_form: OWNERS and PRIVATE by hand; else from the name (a sanitary improvement district, a homeowners'
    association, "Village of", "City of", a tribe); else, for a plant named for the town it lies in and typed municipal
    by EPA, the town's class among the Census Bureau's incorporated places (data/reference/ne-incorporated-places.json:
    a city is "city", a village "town"; review 2026-11-07 P3-5); else null, with the reason in the notes.
  - notification_channel says what Nebraska law and the permits require (no public notice of overflows; reports to
    DWEE within 24 hours and 5 days, filed through EPA's NeT-SewerOverflow, public in EPA's overflow tables weeks
    later; Omaha's CSO permit's public notification clause, not read). notification_signup_url null: no overflow
    e-mail list exists.
  - EPA_ISSUED: the Indian-country permits EPA Region 7 issues (ECHO, read 2026-11-07); their rows say the report goes
    to EPA, not DWEE, and say which agency issued the permit (review 2026-11-07 P2-4).
  - Idempotent: every row with state NE is rebuilt; other states' rows are left as they are; the Nebraska rows are
    written after the last row of the file in id order.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIS = ROOT / "data" / "dischargers.json"
RESEARCH = ROOT / "research" / "ne" / "dischargers.json"
CANDIDATES = ROOT / "research" / "ne" / "private-utilities-candidates.json"
CHECKED = "2026-11-07"
SOBE_URL = "https://echo.epa.gov/tools/data-downloads/sewer-overflow-download-summary"
LAW = ("No Nebraska statute or rule requires public notice of a sewage overflow or a bypass: the permit's standard "
       "conditions require a report to the Department of Water, Energy, and Environment (DWEE) within 24 hours and in "
       "writing within 5 days, filed through EPA's NeT-SewerOverflow, so the reports become public in EPA's overflow "
       f"tables (ECHO, {SOBE_URL}) weeks later (a median 23 days after the start in the 2026-11-04 extract).")
OWN_PAGES = " The operator's own pages were not searched individually."
OMAHA = (LAW + " As a combined sewer permittee (NE0133680) Omaha's permit is expected to carry a public notification "
         "condition (Nine Minimum Controls, no. 8); its terms could not be read (the permit text sits in DWEE's document "
         "viewer). No web notice of Omaha's overflows was found (the CSO program site omahacso.com carries "
         "projects and reports only); Omaha Public Works announces large overflows through the news media.")
CHANNEL = {"ne-omaha": OMAHA}
# permits EPA Region 7 issues in Indian country (ECHO facility search, read 2026-11-07: IssuingAgency "EPA", permitting
# agency "U.S. EPA", CWPIndianCntryFlg "Y"; the other 327 Nebraska permits of the rows are the State's). Nebraska's
# NPDES authorization does not reach Indian country, so these permittees report to EPA, not to DWEE (review 2026-11-07
# P2-4). The Omaha Reservation's villages (Walthill, Thurston, Pender, Rosalie, Emerson), Winnebago on the Winnebago
# Reservation and Santee on the Santee Sioux Reservation.
EPA_ISSUED = {"NE0021211", "NE0031739", "NE0040908", "NE0041351", "NE0046302", "NE0061263", "NE0113212", "NE0132641",
              "NE0138932"}
EPA_LAW = ("NPDES permit issued by EPA Region 7 (in Indian country, where Nebraska's NPDES authorization does not "
           "apply: EPA's facility record gives the issuing agency as EPA, read 2026-11-07). No statute or rule requires "
           "public notice of a sewage overflow or a bypass: the permit's standard conditions (40 CFR 122.41(l)(6)-(7)) "
           "require a report to EPA within 24 hours and in writing within 5 days, filed through EPA's "
           f"NeT-SewerOverflow, so the reports become public in EPA's overflow tables (ECHO, {SOBE_URL}). None of these "
           "permits has a report there in the 2026-11-04 extract.")
PRIVATE_FORMS = {"investor-owned utility", "member-owned utility", "homeowners' association", "mobile-home park",
                 "campground or resort", "private club", "business or industrial", "institution",
                 "facility (permittee not named)"}

# research ids joined into one operator row: row id -> (research ids, name, short name, legal_form, kind)
JOINED = {
    "ne-omaha": (["ne-omaha-cso", "ne-omaha-papillion", "ne-omaha-missouri"],
                 "City of Omaha Public Works (combined sewer system; Papillion Creek and Missouri River water resource "
                 "recovery facilities)", "City of Omaha", "city", "cso"),
    "ne-lincoln": (["ne-lincoln-northeast", "ne-lincoln-theresa"],
                   "City of Lincoln Transportation and Utilities (Northeast and Theresa Street water resource recovery "
                   "facilities)", "City of Lincoln", "city", "sso"),
}
# the other research rows: research id -> (short name, legal_form); kind "sso" (EPA's overflow tables carry them)
RESEARCH_ROWS = {
    "ne-grand-island": ("City of Grand Island", "city"), "ne-seward": ("City of Seward", "city"),
    "ne-falls-city": ("City of Falls City", "city"), "ne-nebraska-city": ("City of Nebraska City", "city"),
    "ne-mccook": ("City of McCook", "city"), "ne-north-platte": ("City of North Platte", "city"),
    "ne-bellevue": ("City of Bellevue", "city"), "ne-kearney": ("City of Kearney", "city"),
}
# permit -> (row id, name, legal_form, note): owners the name does not give, or spellings of one owner
OWNERS = {
    "NE0138932": ("ne-walthill", "Village of Walthill", "town", "EPA spells the second permit 'VILLAGE OF WATHILL'"),
    "NE0140295": ("ne-plattsmouth", "City of Plattsmouth", "city", "EPA records the second permit as 'City of "
                  "Plattsmouth'"),
    "NE0027332": ("ne-saint-edward", "City of St. Edward", "city",
                  "EPA records the permit name 'SAINT EDWARD'; St. Edward is a city (Census Bureau, incorporated "
                  "places)"),
    "NE0038946": ("ne-hastings", "City of Hastings (Hastings Utilities: pollution control facility, Maxon Avenue plant, "
                  "aquifer storage)", "city", None),
    "NE0113298": ("ne-hastings", None, "city", "EPA types the Maxon Avenue plant privately owned; it is the City's "
                  "plant (permittee recorded as 'HASTINGS PCF MAXON AVE')"),
    "NE0139343": ("ne-hastings", None, "city", None),
    "NE0139904": ("ne-south-sioux-city", "City of South Sioux City", "city", None),
    "NE0061263": ("ne-omaha-tribe-macy", "Omaha Tribe of Nebraska (Macy plant)", "tribal", None),
    "NE0132641": ("ne-santee-sioux-nation", "Santee Sioux Nation (Village of Santee plant)", "tribal",
                  "EPA types the permittee a tribal government"),
    "NE0114286": ("ne-camp-ashland", "Nebraska Army National Guard, Camp Ashland Training Site", "federal facility",
                  "EPA types the permittee a federal facility"),
    "NE0139971": ("ne-centura-public-schools", "Centura Public Schools", "special district",
                  "EPA records 'Centua Pulic School'; a public school district"),
    "NE0123064": ("ne-south-bend-lakes", "NEBCO, Inc. (South Bend Lakes)", "business or industrial",
                  "EPA records 'NEBCO, Inc -dba- South Bend Lakes, Inc'"),
    "NE0114251": ("ne-ne0114251", "Johnson Development (Plattsmouth plant)", "business or industrial",
                  "A development company's plant; EPA types it POTW"),
    "NE0139076": ("ne-preserve-at-cross-creek", "The Preserve at Cross Creek (Hickman plant)", None,
                  "A subdivision's plant (EPA type NON-POTW); its owner was not read"),
    "NE0140104": ("ne-hastings-aqua-court", "Hastings Aqua Court", None,
                  "EPA type NON-POTW; its owner was not read"),
    "NE0137529": ("ne-riverview-shores", "Riverview Shores (North Bend plant)", None,
                  "A lake subdivision's plant (EPA type Municipal or Water District); its owner was not read"),
    "NE0112283": ("ne-sid-177-douglas", "Sanitary Improvement District No. 177 of Douglas County (Riverside Lakes)",
                  "special district", "EPA records 'SID 177 DOUGLAS RIVERSIDE LAKE'"),
    "NE0112950": ("ne-sid-2-cass", "Sanitary Improvement District No. 2 of Cass County (Greenwood Interchange)",
                  "special district", "EPA records 'SID 2 CASS GREENWOOD INTRCHNGE'"),
}
# permit -> (row id, name, legal_form, towns, note): the private candidates, by permittee; no individual's name
PRIVATE = {
    "NE0043371": ("ne-innovative-exhaust-solutions", "Innovative Exhaust Solutions, Inc.", "business or industrial",
                  ["Lincoln"], None),
    "NE0050890": ("ne-beaver-lake-association", "Beaver Lake Association", "homeowners' association", ["Plattsmouth"],
                  None),
    "NE0112330": ("ne-gibbon-inn", "Gibbon Inn Wastewater Treatment Facility", "facility (permittee not named)",
                  ["Gibbon"], "The candidates file removed the permittee's name; the row names the facility."),
    "NE0112895": ("ne-eagle-lake-subdivision", "Eagle Lake Subdivision Wastewater Treatment Facility", None, ["Eagle"],
                  "EPA records 'EAGLE LAKE WWTF' as permittee; who owns the subdivision's plant was not read."),
    "NE0113450": ("ne-valley-view-hoa", "Valley View Homeowners Association", "homeowners' association", ["Fremont"],
                  None),
    "NE0123986": ("ne-woodland-hills-hoa", "Woodland Hills Homeowners Association", "homeowners' association", ["Eagle"],
                  None),
    "NE0132608": ("ne-sid-8-saunders", "Sanitary Improvement District No. 8 of Saunders County", "special district",
                  [], "EPA types it privately owned; a sanitary improvement district is a public body (Neb. Rev. Stat. "
                  "31-727 and following)."),
    "NE0132632": ("ne-sid-101-sarpy", "Sanitary Improvement District No. 101 of Sarpy County (Hanson Lake)",
                  "special district", ["Bellevue"],
                  "EPA types it privately owned; a sanitary improvement district is a public body (Neb. Rev. Stat. "
                  "31-727 and following). EPA's overflow tables carry one report (2025-07-07, to Hanson Lake 2)."),
    "NE0133167": ("ne-ne0133167", "Private sewage permit NE0133167 (Ashland)", "facility (permittee not named)",
                  ["Ashland"], "The candidates file removed the facility's and the permittee's names."),
    "NE0133841": ("ne-cardwell-woods-hoa", "Cardwell Woods Homeowners Association", "homeowners' association",
                  ["Lincoln"], "EPA records 'CARDWELL WOOD WWTF' as permittee."),
    "NE0137499": ("ne-travelcenters-alda", "TravelCenters of America (Grand Island travel center)",
                  "business or industrial", ["Alda"], None),
    "NE0137553": ("ne-foreman-ridge", "Foreman Ridge Wastewater Treatment Facility", "facility (permittee not named)",
                  ["Lincoln"], "The candidates file removed the permittee's name; the row names the facility."),
    "NE0137596": ("ne-cardwell-reserve-hoa", "Cardwell Reserve Homeowners' Association, Inc.", "homeowners' association",
                  ["Lincoln"], None),
    "NE0137669": ("ne-hidden-valley-estates", "Hidden Valley Estates, LLC", "business or industrial", ["Lincoln"], None),
    "NE0137821": ("ne-dakota-springs", "Dakota Springs Wastewater Treatment Facility", None, ["Roca"],
                  "EPA records the facility as permittee; who owns it was not read."),
    "NE0139700": ("ne-ne0139700", "Single-residence sewage permit NE0139700", "facility (permittee not named)", [],
                  "A single residence: only the permit and the state are kept."),
    "NE0140341": ("ne-farmers-cooperative-cortland", "Farmers Cooperative (Cortland service center)",
                  "business or industrial", ["Cortland"], None),
    "NE0140350": ("ne-ne0140350", "Trucking company plant (Brady)", "business or industrial", ["Brady"],
                  "The candidates file removed the facility's name; the row names the business's kind and town."),
    "NE0140431": ("ne-dutton-lainson", "Dutton-Lainson Company (Hastings plant)", "business or industrial",
                  ["Hastings"], None),
    "NE0140457": ("ne-ne0140457", "Industrial plant with a sewage permit NE0140457 (Lincoln)",
                  "facility (permittee not named)", ["Lincoln"],
                  "The candidates file removed the facility's and the permittee's names."),
    "NE0113441": None,   # SID 3 Dodge County: a public SID, filed by name (step 2)
}
# EPA overflow-table permits that no plant list carries: permit -> (row id, name, towns)
SOBE_ONLY = {"NE0139611": ("ne-verdigre", "Verdigre Sanitary Sewer System", ["Verdigre"])}

WORKS = re.compile(r"\b(wwtf|wwtp|stp|potw|lagoons?|wastewater\s+treat\w*(\s+facility)?|water resource recovery "
                   r"facility|treatment facility|pollution control|sewage treatment|wtf|#\s*\d+)\b", re.I)


def _places() -> dict[str, str]:
    """town key -> 'city' or 'village' (data/reference/ne-incorporated-places.json, Census TIGERweb)."""
    doc = json.loads((ROOT / "data" / "reference" / "ne-incorporated-places.json").read_text())
    return {slug(p["name"]): p["kind"] for p in doc["places"]}


def slug(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", (s or "").lower())).strip("-")


PLACES: dict[str, str] = {}
# a town key as EPA spells the plant -> the Census place's key
PLACE_ALIASES = {"dewitt": "de-witt", "saint-edward": "st-edward", "greeley": "greeley-center"}


def place(s: str) -> str:
    """EPA's upper-case city as a place name ('ST EDWARD' -> 'St Edward', 'MCCOOK' -> 'McCook')."""
    t = re.sub(r"\s+", " ", (s or "").strip()).title()
    t = re.sub(r"\bMc([a-z])", lambda m: "Mc" + m.group(1).upper(), t)
    return re.sub(r"(?<=\w)'S\b", "'s", t)


def town_key(name: str) -> str:
    """The town a plant name names: 'Village of Herman' and 'HERMAN WWTF' -> 'herman'."""
    n = re.sub(r"(?i)^(the\s+)?(village|city|town)\s+of\s+", "", (name or "").strip())
    n = WORKS.sub(" ", n)
    return slug(n)


def sid_id(name: str) -> str | None:
    """'Sanitary Improvement District No. 5 of Cass County (...)' -> 'ne-sid-5-cass'."""
    m = re.match(r"Sanitary Improvement District No\. (\d+) of (\w+) County", name or "")
    return f"ne-sid-{m.group(1)}-{m.group(2).lower()}" if m else None


def sid_name(name: str) -> str | None:
    m = re.match(r"(?i)^SID\s*#?\s*(\d+)[,\s-]*(?:of\s+)?([A-Za-z]+)\s+(?:CO\.?|COUNTY)\b[,.\s-]*(.*)$", name.strip())
    if not m:
        return None
    rest = WORKS.sub(" ", m.group(3)).strip(" -,")
    return (f"Sanitary Improvement District No. {m.group(1)} of {m.group(2).title()} County"
            + (f" ({place(rest)})" if rest else ""))


def form(name: str) -> str | None:
    n = (name or "").lower()
    if re.search(r"\bsid\b|sanitary improvement district", n):
        return "special district"
    if re.search(r"home ?owners|townhome association|\bassociation\b|\bassn\b|\bhoa\b", n):
        return "homeowners' association"
    if re.search(r"\b(tribe|tribal|nation)\b", n):
        return "tribal"
    if re.search(r"^village of\b", n):
        return "town"
    if re.search(r"^city of\b", n):
        return "city"
    return None


def plant_name(permit_name: str, city: str) -> str:
    """'BEATRICE WWTF' -> 'Beatrice wastewater treatment facility'; other names as EPA spells them, in order."""
    s = re.sub(r"\s+", " ", permit_name or "").strip()
    sid = sid_name(s)
    if sid:
        return sid
    if s.isupper():
        s = place(s)
    s = re.sub(r"(?i)\bTREATEMENT\b", "Treatment", s)
    s = re.sub(r"(?i)\bWWTF\b|\bWWTP\b|\bwastewater treat\w*(?: facility)?(?=\s|$)", "Wastewater Treatment Facility", s)
    s = re.sub(r"\b(Ne|Sid|Hoa|Llc|Inc)\b", lambda m: {"Ne": "NE", "Sid": "SID", "Hoa": "HOA", "Llc": "LLC",
                                                       "Inc": "Inc."}[m.group(1)], s)
    return re.sub(r"\b(Village|City|Town) Of\b", lambda m: f"{m.group(1)} of", s)


def load_epa() -> dict[str, dict]:
    """permit -> {owner, facility, city, waters, outfalls, open_cso, ftype}."""
    out: dict[str, dict] = {}
    for f in ("outfalls-plants-us.json", "outfalls-us.json"):
        doc = json.loads((ROOT / "data" / f).read_text())
        for r in doc["outfalls"] if isinstance(doc, dict) else doc:
            p = str(r.get("npdes_permit") or "").upper()
            if not p.startswith("NE") or r.get("state") not in (None, "NE"):
                continue
            o = out.setdefault(p, {"owner": None, "facility": None, "city": None, "waters": [], "outfalls": 0,
                                   "open_cso": 0, "ftype": None})
            o["owner"] = o["owner"] or r.get("permit_name") or r.get("permittee")
            o["facility"] = o["facility"] or r.get("permittee")
            o["city"] = o["city"] or r.get("city")
            o["ftype"] = o["ftype"] or r.get("facility_type")
            w = (r.get("receiving_water_echo") or "").strip()
            if w and w not in o["waters"]:
                o["waters"].append(w)
            o["outfalls"] += 1
            if f == "outfalls-us.json" and not str(r.get("outfall_status") or "").upper().startswith("CLS"):
                o["open_cso"] += 1
    return out


def base_row(rid, name, permits, kind, legal_form, towns, waters, outfalls, notes, short=None, aliases=None,
             research=False) -> dict:
    row = {"id": rid, "name": name, "state": "NE", "kind": kind, "npdes_permit": permits[0] if permits else None,
           "npdes_permits": permits, "receiving_waters": waters, "water_slugs": [], "outfall_count": outfalls or None,
           "outfalls_source": ("EPA ECHO ICIS-NPDES discharge points and the national CSO inventory "
                               f"(data/outfalls-plants-us.json, data/outfalls-us.json: {outfalls} rows for these permits)"
                               if outfalls else None),
           "notification_channel": CHANNEL.get(rid) or ((EPA_LAW if set(permits) <= EPA_ISSUED else LAW) + OWN_PAGES),
           "notification_feed_machine_readable": True,
           "notification_signup_url": None, "towns": towns, "notes": notes,
           "verified": "fetched" if research else "inferred", "checked": CHECKED,
           "aliases": list(dict.fromkeys([rid] + list(aliases or []))),
           "source_areas": ["ne"] + ([] if research else ["federal"])}
    if short:
        row["short_name"] = short
    if legal_form:
        row["legal_form"] = legal_form
    return row


def build(epa: dict[str, dict], research: list[dict], candidates: dict[str, dict]) -> tuple[list[dict], dict]:
    PLACES.update(_places())
    rows: dict[str, dict] = {}
    held: dict[str, str] = {}
    rmap = {r["id"]: r for r in research}

    def take(rid: str, permits: list[str]):
        for p in permits:
            if p in held and held[p] != rid:
                raise SystemExit(f"{p} in two rows: {held[p]} and {rid}")
            held[p] = rid

    # 1. the research rows (Omaha's and Lincoln's joined)
    joined_ids = {i for v in JOINED.values() for i in v[0]}
    for rid, (ids, name, short, lf, kind) in JOINED.items():
        rs = [rmap[i] for i in ids]
        permits = [r["npdes_permit"] for r in rs]
        waters = list(dict.fromkeys(w for r in rs for w in r.get("receiving_waters") or []))
        towns = list(dict.fromkeys(t for r in rs for t in r.get("towns") or []))
        n_out = sum(epa.get(p, {}).get("outfalls", 0) for p in permits)
        note = " ".join(f"{r['npdes_permit']} {r['name']}: {(r.get('notes') or '').strip()}".strip() for r in rs)
        note += (f" Research rows {', '.join(ids)} (research/ne/dischargers.json, checked "
                 f"{rs[0].get('checked')}), joined as one operator.")
        rows[rid] = base_row(rid, name, permits, kind, lf, towns, waters, n_out, note, short, ids, research=True)
        take(rid, permits)
    for r in research:
        if r["id"] in joined_ids:
            continue
        short, lf = RESEARCH_ROWS[r["id"]]
        p = r["npdes_permit"]
        n_out = epa.get(p, {}).get("outfalls", 0)
        note = ((r.get("notes") or "").strip() + f" Research row (research/ne/dischargers.json, checked "
                f"{r.get('checked')}); EPA's permit name {epa.get(p, {}).get('owner')!r}.").strip()
        name = f"{short} ({plant_name(epa.get(p, {}).get('owner') or r['name'], '')})"
        rows[r["id"]] = base_row(r["id"], name, [p], "sso", lf, r.get("towns") or [],
                                 list(dict.fromkeys(r.get("receiving_waters") or [])), n_out, note, short, research=True)
        take(r["id"], [p])
    by_town = {town_key(r["short_name"]): rid for rid, r in rows.items() if r.get("short_name")}
    by_town.update({"omaha": "ne-omaha", "lincoln": "ne-lincoln"})

    # 2. EPA's permits: the private candidates, the owners by hand, then by the town the name gives
    groups: dict[str, dict] = {}
    for p, o in sorted(epa.items()):
        if p in held:
            continue
        owner = o["owner"] or o["facility"] or p
        if PRIVATE.get(p):
            rid, name, lf, towns, note = PRIVATE[p]
            g = groups.setdefault(rid, {"permits": [], "name": name, "lf": lf, "towns": towns, "notes": []})
            g["permits"].append(p)
            g["notes"].append(("Privately owned. " if lf in PRIVATE_FORMS else "") + (note or "")
                              + " Permittee from EPA ICIS-NPDES and the private-utilities candidates file.")
            continue
        if p in OWNERS:
            rid, name, lf, note = OWNERS[p]
            if rid in rows:
                rows[rid]["npdes_permits"].append(p)
                rows[rid]["outfall_count"] = (rows[rid]["outfall_count"] or 0) + o["outfalls"] or None
                rows[rid]["notes"] += f" {p} {owner} joined" + (f" ({note})." if note else ".")
                take(rid, [p])
                continue
            g = groups.setdefault(rid, {"permits": [], "name": name, "lf": lf, "towns": None, "notes": []})
            g["permits"].append(p)
            g["name"] = name or g["name"]      # the owner by hand wins over a plant's spelling
            g["lf"] = lf or g["lf"]
            if note:
                g["notes"].append(note + ".")
            continue
        key = town_key(owner)
        city_key = slug(o["city"] or "")
        sid = sid_name(owner)
        if key in by_town and not sid and form(owner) not in PRIVATE_FORMS:
            rid = by_town[key]
            rows[rid]["npdes_permits"].append(p)
            rows[rid]["outfall_count"] = (rows[rid]["outfall_count"] or 0) + o["outfalls"] or None
            rows[rid]["notes"] += f" {p} {owner} joined by its name."
            take(rid, [p])
            continue
        if sid or form(owner) in PRIVATE_FORMS or not key:
            rid = sid_id(sid) if sid else f"ne-{slug(WORKS.sub(' ', plant_name(owner, o['city']))) or p.lower()}"
        else:
            rid = f"ne-{key}"
        g = groups.setdefault(rid, {"permits": [], "name": None, "lf": None, "towns": None, "notes": []})
        g["permits"].append(p)
        nm = plant_name(owner, o["city"])
        if g["name"] is None or (form(owner) in ("city", "town") and form(g["name"]) not in ("city", "town")):
            g["name"] = nm                     # a "City of" or "Village of" spelling names the owner: it wins
        g["lf"] = g["lf"] or form(owner)
        if form(owner) in PRIVATE_FORMS:
            g["notes"].append("Privately owned.")
        elif key and (key == city_key or PLACE_ALIASES.get(key, key) in PLACES) \
                and o["ftype"] in ("Municipal or Water District", "POTW", "Municipality"):
            kind = PLACES.get(PLACE_ALIASES.get(key, key))
            if kind and not g["lf"]:
                g["lf"] = "city" if kind == "city" else "town"
                g["notes"].append(f"A plant named for the town it lies in, typed municipal by EPA: the town's plant; "
                                  f"{place(o['city'])} is a {kind} (Census Bureau, incorporated places).")
            elif not kind:
                g["notes"].append("A plant named for the town it lies in, typed municipal by EPA: the town's plant "
                                  "(the town is not among the Census Bureau's incorporated places, so its form is not "
                                  "stated).")
        elif key and PLACE_ALIASES.get(key, key) in PLACES and not g["lf"]:
            g["notes"].append(f"Named for the town of {place(o['city'] or key)}, but EPA types it {o['ftype'] or 'with no '
                              'facility type'}: who holds the permit was not read, so its form is not stated.")
    # candidates EPA's plant list does not carry: an owner by hand joins its row, the others are rows of their own
    for p, c in sorted(candidates.items()):
        if p in OWNERS and p not in epa and p not in held:
            rid, _, _, note = OWNERS[p]
            target = rows.get(rid) or groups.get(rid)
            if target is None:
                raise SystemExit(f"{p}: OWNERS names {rid}, which has no row")
            target.setdefault("npdes_permits" if rid in rows else "permits", []).append(p)
            if rid in rows:
                rows[rid]["notes"] += f" {p} joined ({note})."
                take(rid, [p])
            else:
                target["notes"].append(f"{p}: {note}.")
    for p, v in PRIVATE.items():
        if not v or p in held or any(p in g["permits"] for g in groups.values()):
            continue
        rid, name, lf, towns, note = v
        g = groups.setdefault(rid, {"permits": [], "name": name, "lf": lf, "towns": towns, "notes": []})
        g["permits"].append(p)
        g["notes"].append(("Privately owned. " if lf in PRIVATE_FORMS else "") + (note or "")
                          + " From the private-utilities candidates file (EPA ICIS-NPDES); not in EPA's plant list.")
    for p, (rid, name, towns) in SOBE_ONLY.items():
        if p in held or any(p in g["permits"] for g in groups.values()):
            continue
        g = groups.setdefault(rid, {"permits": [], "name": name, "lf": None, "towns": towns, "notes": []})
        g["permits"].append(p)
        g["kind"] = "sso"
        g["notes"].append(f"{p}, the collection system in EPA's overflow tables (2026-11-04 extract: one report, an SSO "
                          "naming no water), is not in EPA's plant list; joined by the town's name.")
    for rid, g in groups.items():
        permits = list(dict.fromkeys(g["permits"]))
        towns = g["towns"] if g["towns"] is not None else sorted({place(epa[p]["city"]) for p in permits
                                                                  if epa.get(p, {}).get("city")
                                                                  and "PRECINCT" not in epa[p]["city"].upper()})
        waters = list(dict.fromkeys(w for p in permits for w in epa.get(p, {}).get("waters", [])))
        n_out = sum(epa.get(p, {}).get("outfalls", 0) for p in permits)
        kind = g.get("kind") or ("cso" if any(epa.get(p, {}).get("open_cso") for p in permits) else "plant")
        facs = "; ".join(f"{p} {epa[p]['facility']}" for p in permits if p in epa and g["lf"] not in PRIVATE_FORMS)
        note = (f"EPA ECHO ICIS-NPDES: {facs}. " if facs else "") + " ".join(dict.fromkeys(n for n in g["notes"] if n))
        rows[rid] = base_row(rid, g["name"], permits, kind, g["lf"], towns, waters, n_out, note.strip())
        take(rid, permits)
    for r in rows.values():
        r["npdes_permits"] = list(dict.fromkeys(r["npdes_permits"]))
    missing = sorted((set(epa) | {p for p, v in PRIVATE.items() if v} | set(SOBE_ONLY)
                      | {p for p in OWNERS if p in candidates}) - set(held))
    if missing:
        raise SystemExit(f"permits without a row: {missing}")
    stats = {"rows": len(rows), "permits": len(held), "by_kind": dict(Counter(r["kind"] for r in rows.values())),
             "by_form": dict(Counter(r.get("legal_form") for r in rows.values())),
             "private": sorted(r["id"] for r in rows.values() if r.get("legal_form") in PRIVATE_FORMS)}
    return sorted(rows.values(), key=lambda r: r["id"]), stats


def main(argv: list[str]) -> int:
    dis = json.loads(DIS.read_text())
    research = json.loads(RESEARCH.read_text())
    cand = {c["npdes_permit"]: c for c in json.loads(CANDIDATES.read_text()).get("candidates") or []}
    new, stats = build(load_epa(), research, cand)
    others = [r for r in dis if r.get("state") != "NE"]
    taken = {p for r in others for p in [r.get("npdes_permit"), *(r.get("npdes_permits") or [])] if p}
    clash = sorted(p for r in new for p in r["npdes_permits"] if p in taken)
    if clash:
        raise SystemExit(f"permits already held by another state's row: {clash}")
    ids = Counter(r["id"] for r in others + new)
    dup = [i for i, n in ids.items() if n > 1]
    if dup:
        raise SystemExit(f"duplicate ids: {dup}")
    if "--dry-run" not in argv:
        DIS.write_text(json.dumps(others + new, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps(stats, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
