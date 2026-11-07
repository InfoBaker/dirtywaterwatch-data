"""South Dakota operator rows for data/dischargers.json: one row per operator, every South Dakota permit of the outfall
registry in exactly one row.

Usage: pipeline/.venv/bin/python -I scripts/add_sd_operators.py [--dry-run]

Inputs
  - research/sd/dischargers.json (14 rows): EPA's two CSO permittees (the City of Lead's CSO permit and the Lead-Deadwood
    Sanitary District) and the twelve largest or most frequent reporters in EPA's overflow tables. Each keeps its research
    id (the EPA overflow module names it as discharger_id) and its name; the research row for Sioux Falls carries a note
    in its kind field, read here as "sso".
  - data/outfalls-plants-us.json and data/outfalls-us.json: every South Dakota permit EPA lists (498). permit_name is
    the owner as EPA records it; the permits of one owner are one row (key(): EPA's spellings of a city or town, of a
    sanitary district and of the state's departments joined; OWNERS joins the rest by hand).
  - research/sd/private-utilities-candidates.json (12 private sewage permits) and EPA's other privately owned
    facilities: PRIVATE files each with legal_form from the controlled list (docs/legal-forms.md), never an individual's
    name. Two candidates whose permittee the candidates file removed are named here from EPA's own permit name, which
    reads as a body: a fuel-stop company and a community improvement district (a public district by its name, typed
    private by EPA).
Rules
  - legal_form: PRIVATE and OWNERS by hand, else form() from the name and EPA's facility type (Tribal Government ->
    tribal, Federal Facility -> federal facility, State Government -> state facility), else null (a facility name that
    does not say who holds the permit).
  - name: OWNERS, else the owner as EPA spells it, put in order ("ABERDEEN, CITY OF" -> "City of Aberdeen").
  - notification_channel: what South Dakota law and the permits require (no public notice of overflows or bypasses; the
    24-hour and 5-day reports to the permitting authority; the CSO permits' public notification) and where the reports
    become public (EPA's overflow tables, through NeT-SewerOverflow). A permit EPA Region 8 writes in Indian country (the
    SDG589 general-permit series and the tribal governments' permits) reports to EPA, not DANR: its row says so.
    notification_signup_url null: no South Dakota operator or agency runs an overflow alert list (none found).
  - Idempotent: every row with state SD is rebuilt; other states' rows are left as they are; the South Dakota rows are
    written after the last row of the file in id order.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIS = ROOT / "data" / "dischargers.json"
RESEARCH = ROOT / "research" / "sd" / "dischargers.json"
CANDIDATES = ROOT / "research" / "sd" / "private-utilities-candidates.json"
CHECKED = "2026-11-07"
ECHO = "https://echo.epa.gov/tools/data-downloads/sewer-overflow-download-summary"
LAW = ("No South Dakota statute or rule was found that requires public notice of a sewage overflow or bypass: the "
       "standard conditions every sewage permit must carry (40 CFR 122.41(l)(6)) require a report to the Department of Agriculture and Natural Resources (DANR) within 24 hours and a "
       "written report within 5 days, filed through EPA's NeT-SewerOverflow, so the reports become public in EPA's "
       f"overflow tables days to weeks later ({ECHO}).")
EPA_LAW = ("No South Dakota statute or rule was found that requires public notice of a sewage overflow or bypass. The "
           "permit is one EPA "
           "Region 8 writes in Indian country, so the permittee's 24-hour and 5-day reports go to EPA, not DANR; filed "
           "through NeT-SewerOverflow, they become public in EPA's overflow tables days to weeks later "
           f"({ECHO}). The permitting authority was read from the permit series and EPA's facility type, not from the "
           "permit text.")
CSO_LAW = (" As a combined sewer permittee, its permit is expected to require public notice of overflows under the "
           "federal policy for combined sewers (Nine Minimum Controls, no. 8, of EPA's CSO Control Policy); the permit "
           "text was not read and no "
           "web notice of the operator was found.")
SEARCHED = " No overflow page of the operator's own was found (search only)."
OWN_PAGES = " The operator's own pages were not searched individually."
RESEARCH_KIND = {"sd-sioux-falls": "sso"}
CSO_PERMITS = {"SD0027481", "SD0020796"}
# EPA permit_name -> (row id, name, legal_form, note): one owner's spellings joined, a body named for its owner
OWNERS = {
    "Oglala Sioux Tribe Water and Sewer": ("sd-oglala-sioux-tribe-water-sewer", "Oglala Sioux Tribe Water and Sewer",
                                           "tribal", None),
    "Oglala Sioux Tribe, Water and Sewer": ("sd-oglala-sioux-tribe-water-sewer", None, "tribal", None),
    "Oglala Sioux Tribe, Water & Sewer": ("sd-oglala-sioux-tribe-water-sewer", None, "tribal", None),
    "Rosebud Sioux Tribe Water and Sewer": ("sd-rosebud-sioux-tribe-water-sewer", "Rosebud Sioux Tribe Water and Sewer",
                                            "tribal", None),
    "Lower Brule Sioux Tribe": ("sd-lower-brule-sioux-tribe", "Lower Brule Sioux Tribe", "tribal", None),
    "Tri-County Water Associations Inc": ("sd-tri-county-water-associations", "Tri-County Water Associations, Inc.",
                                          "member-owned utility",
                                          "A rural water association on the Cheyenne River reservation; EPA types its "
                                          "plants POTW. Its form was read from the name, not from its charter."),
    "SPRING/COW CREEK SANITARY DIST": ("sd-spring-cow-creek-sanitary-district",
                                       "Spring Creek/Cow Creek Sanitary District", "special district", None),
    "Spring Creek/Cow Creek Sanitary District": ("sd-spring-cow-creek-sanitary-district", None, "special district",
                                                 None),
    "ST ONGE SEWER & WATER": ("sd-st-onge-water-sewer", "St. Onge Water & Sewer", None,
                              "Who holds the permit (a district, an association or the town) was not checked."),
    "St. Onge Water & Sewer": ("sd-st-onge-water-sewer", None, None, None),
    "Brookings Municipal Utilities": ("sd-brookings", None, "city", None),
    "South Dakota Ellsworth Development Authority (SDEDA)": ("sd-ellsworth-development-authority",
                                                              "South Dakota Ellsworth Development Authority",
                                                              "authority", None),
    "South Dakota Ellsworth Development Authority (Biosolids)": ("sd-ellsworth-development-authority", None,
                                                                 "authority", None),
    "SD Developmental Center": ("sd-developmental-center", "South Dakota Developmental Center (Redfield)",
                                "state facility", None),
    "SD DOC - State Penitentiary West Farm": ("sd-department-of-corrections", "South Dakota Department of Corrections "
                                              "(State Penitentiary West Farm)", "state facility", None),
    "Tri-valley School District 49-6": ("sd-tri-valley-school-district", "Tri-Valley School District 49-6",
                                        "special district", "A public school district."),
    "OGLALA LAKOTA COLLEGE": ("sd-oglala-lakota-college", "Oglala Lakota College", "tribal",
                              "The Oglala Sioux Tribe's chartered college."),
    "USAF - Ellsworth AFB": ("sd-ellsworth-afb", "U.S. Air Force, Ellsworth Air Force Base", "federal facility", None),
    "USGS - Eros Data Center": ("sd-usgs-eros", "U.S. Geological Survey, EROS Data Center", "federal facility", None),
    "USFS - Boxelder JCCCC": ("sd-usfs-boxelder-job-corps", "U.S. Forest Service, Boxelder Job Corps Civilian "
                              "Conservation Center", "federal facility", None),
    "USCOE - Big Bend Dam": ("sd-usace-big-bend-dam", "U.S. Army Corps of Engineers, Big Bend Dam", "federal facility",
                             None),
    "USCOE - Oahe Dam": ("sd-usace-oahe-dam", "U.S. Army Corps of Engineers, Oahe Dam", "federal facility", None),
    "USNPS - Mt. Rushmore National Memorial": ("sd-nps-mount-rushmore", "National Park Service, Mount Rushmore "
                                               "National Memorial", "federal facility", None),
    "USNPS - Mt. Rushmore National Memorial (Biosolids)": ("sd-nps-mount-rushmore", None, "federal facility", None),
    "USNPS - Badlands National Park": ("sd-nps-badlands", "National Park Service, Badlands National Park",
                                       "federal facility", None),
    "USNPS - Jewel Cave National Monument": ("sd-nps-jewel-cave", "National Park Service, Jewel Cave National Monument",
                                             "federal facility", None),
    "USNPS - Wind Cave National Park": ("sd-nps-wind-cave", "National Park Service, Wind Cave National Park",
                                        "federal facility", None),
}
# owner prefixes of the state's departments: every permit of one department is one row
DEPARTMENTS = {
    "SD GFP - ": ("sd-game-fish-parks", "South Dakota Game, Fish and Parks (state parks and recreation areas)"),
    "SD DOT - ": ("sd-department-of-transportation", "South Dakota Department of Transportation (rest areas, ports of "
                                                     "entry and shops)"),
}
# permit -> (row id, name, legal_form, note): EPA's privately owned sewage permits, the body as EPA records it
PRIVATE = {
    "SD0020443": ("sd-star-academy", "Star Academy, West Campus (SLIC-E Holdings)", "institution",
                  "A residential school's campus; EPA records SLIC-E Holdings as the facility and Star Academy as "
                  "permit name."),
    "SD0026999": ("sd-country-village-mhc", "Country Village Manufactured Home Community", "mobile-home park", None),
    "SDG826999": ("sd-country-village-mhc", None, "mobile-home park", None),
    "SD0027456": ("sd-coffee-cup-fuel-stops", "Coffee Cup Fuel Stops", "business or industrial",
                  "A fuel-stop company's plant; the candidates file removed the name, which reads as a company."),
    "SD0028177": ("sd-rosedale-colony", "Rosedale Hutterian Brethren", "institution", "A Hutterite colony."),
    "SDG828177": ("sd-rosedale-colony", None, "institution", None),
    "SD0028401": ("sd-evergreen-colony", "Evergreen Colony (turkey production)", "business or industrial",
                  "A Hutterite colony's turkey operation."),
    "SD0028410": ("sd-deerfield-colony", "Deerfield Hutterian Brethren, Inc.", "institution", "A Hutterite colony."),
    "SD0028615": ("sd-powder-house-pass-cid", "Powder House Pass Community Improvement District", "special district",
                  "EPA types the permit privately owned; the name (CID) reads as a community improvement district, a "
                  "public district. The candidates file removed the name; South Dakota's permit records were not read."),
    "SD0028620": ("sd-apple-springs-resort", "Apple Springs Resort (H2O Clear Solutions LLC)", "campground or resort",
                  None),
    "SD0028621": ("sd-pearl-creek-colony", "Pearl Creek Colony", "institution", "A Hutterite colony."),
    "SD0028622": ("sd-hutterville-colony", "Hutterville Hutterian Brethren, Inc.", "institution",
                  "A Hutterite colony (EPA: Hutterville H.B., Inc.)."),
    "SD0028648": ("sd-grass-ranch-colony", "Grass Ranch Hutterian Brethren", "institution", "A Hutterite colony."),
    "SD0028651": ("sd-sunset-colony", "Sunset Colony", "institution", "A Hutterite colony."),
    "SDG828291": ("sd-old-elm-springs-colony", "Old Elm Springs Hutterian Brethren", "institution", "A Hutterite colony."),
    "SDG828340": ("sd-silver-lake-colony", "Silver Lake Hutterian Brethren, Inc.", "institution", "A Hutterite colony."),
    "SDG828655": ("sd-clearfield-colony", "Clearfield Colony", "institution", "A Hutterite colony."),
    "SDG829001": ("sd-newdale-colony", "Newdale Colony", "institution", "A Hutterite colony."),
    "SD0028534": ("sd-sunshine-bible-academy", "Sunshine Bible Academy", "institution", "A private boarding school."),
    "SDG828534": ("sd-sunshine-bible-academy", None, "institution", None),
    "SDG824210": ("sd-yesway-1178", "Yesway Store 1178", "business or industrial", "A convenience store's plant."),
    "SDG824333": ("sd-truck-towne", "Truck Towne", "business or industrial", "A truck stop's plant."),
    "SDG825178": ("sd-wonderland-homes-water", "Wonderland Homes Water and Service Company", "investor-owned utility",
                  None),
    "SDG827502": ("sd-simunek-utility", "Simunek Utility", "investor-owned utility",
                  "A private utility company as EPA records it."),
    "SDG827952": ("sd-edelweiss-mountain", "Edelweiss Mountain Improvement Association", "homeowners' association",
                  None),
    "SDG828100": ("sd-1880-town", "1880 Town", "business or industrial", "A roadside attraction's plant."),
    "SDG828151": ("sd-buffalo-chip-campground", "Buffalo Chip Campground LLC", "campground or resort", None),
    "SDG828363": ("sd-commerce-park-association", "Commerce Park Association", "homeowners' association",
                  "A business park's owners' association."),
    "SDG828398": ("sd-horsethief-campground", "Horsethief Campground and Resort (LT Campground LLC)",
                  "campground or resort", None),
    "SDG828533": ("sd-recreational-adventures", "Recreational Adventures Co.", "campground or resort",
                  "A campground company (Hill City)."),
}
PRIVATE_FORMS = {"investor-owned utility", "member-owned utility", "homeowners' association", "mobile-home park",
                 "campground or resort", "private club", "business or industrial", "institution",
                 "facility (permittee not named)"}


def slug(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s.lower())).strip("-")


def title(s: str) -> str:
    s = re.sub(r"\s+", " ", (s or "").strip())
    if s.isupper() or s.islower():
        s = s.title()
    s = re.sub(r"\b(Wwtf|Wwtp|Stp|Potw|Wwf|Mhc|Llc|Cid)\b", lambda m: m.group(1).upper(), s)
    return re.sub(r"(?<=\w )\b(Of|And|The)\b", lambda m: m.group(1).lower(), s).replace("'S ", "'s ")


CITY_TAIL = re.compile(r"^(?P<n>.+?)[\s,-]*\b(?P<k>city|town)[\s-]*of$", re.I)
CITY_HEAD = re.compile(r"^(?P<k>city|town) of (?P<n>.+?)(?:/.*|\s+(?:wastewater\b.*|lagoons?|wwt?f|wwtp))?$", re.I)


def municipal(owner: str) -> tuple[str, str] | None:
    """('City', 'Aberdeen') from EPA's spellings: 'ABERDEEN, CITY OF', 'HECLA - CITY OF', 'CLAIRE CITY-TOWN OF',
    'City of Mission Lagoons', 'Town of Isabel Wastewater Facility'; a parenthesis ('(CSO)', '(Biosolids)') is dropped."""
    s = re.sub(r"\s*\([^)]*\)\s*$", "", re.sub(r"\s+", " ", owner or "").strip())
    m = CITY_TAIL.match(s) or CITY_HEAD.match(s)
    if not m:
        return None
    return m.group("k").title(), title(m.group("n").strip(" ,-"))


def tidy(name: str) -> str:
    """EPA's abbreviations written out: 'Sanitary Dist' -> 'Sanitary District', 'Pickerel Lk.' -> 'Pickerel Lake',
    'Ft. Pierre' -> 'Fort Pierre'."""
    name = re.sub(r"\bDist\b\.?", "District", name)
    name = re.sub(r"\bLk\b\.?", "Lake", name)
    return re.sub(r"\bFt\.?\s", "Fort ", name)


def owner_key(owner: str) -> str:
    """One owner's spellings: punctuation, 'Dist'/'District', 'Lk.'/'Lake' and a final parenthesis aside."""
    s = re.sub(r"\s*\([^)]*\)\s*$", "", owner or "").lower()
    s = re.sub(r"\blk\b\.?", "lake", s)
    s = re.sub(r"\bdist\b\.?", "district", s)
    s = re.sub(r"\bbrethern\b|\bbretheren\b", "brethren", s)
    return re.sub(r"[^a-z0-9]", "", s)


def muni_key(mm: tuple[str, str]) -> str:
    """A municipality by its name alone: EPA writes some as a city on one permit and a town on another."""
    return "muni:" + owner_key(tidy(mm[1]))


def form(name: str, facility_type: str | None) -> str | None:
    n = (name or "").lower()
    if re.search(r"\b(sanitary|sanitation|improvement) district\b|\bsanitary dist\b", n):
        return "special district"
    if facility_type == "Tribal Government" or re.search(r"\b(tribe|tribal|oyate)\b", n):
        return "tribal"
    if facility_type == "Federal Facility (U.S. Government)":
        return "federal facility"
    if facility_type == "State Government":
        return "state facility"
    if re.search(r"^town of\b", n):
        return "town"
    if re.search(r"^city of\b", n):
        return "city"
    return None


def mm_of(owner: str) -> tuple[str, str] | None:
    return municipal(owner)


def load_epa() -> dict[str, dict]:
    """permit -> {owner, facility, city, type, waters, outfalls, open_cso}."""
    out: dict[str, dict] = {}
    for f in ("outfalls-plants-us.json", "outfalls-us.json"):
        doc = json.loads((ROOT / "data" / f).read_text())
        for r in doc["outfalls"]:
            p = str(r.get("npdes_permit") or "").upper()
            if not p.startswith("SD") or r.get("state") not in (None, "SD"):
                continue
            o = out.setdefault(p, {"owner": None, "facility": None, "city": None, "type": None, "waters": [],
                                   "outfalls": 0, "open_cso": 0})
            o["owner"] = o["owner"] or r.get("permit_name") or r.get("permittee")
            o["facility"] = o["facility"] or r.get("permittee")
            o["city"] = o["city"] or r.get("city")
            o["type"] = o["type"] or r.get("facility_type")
            w = (r.get("receiving_water_echo") or "").strip()
            if w and w not in o["waters"]:
                o["waters"].append(w)
            o["outfalls"] += 1
            if f == "outfalls-us.json" and not str(r.get("outfall_status") or "").upper().startswith("CLS"):
                o["open_cso"] += 1
    return out


def town(city: str | None) -> str | None:
    c = re.sub(r",\s*(city|town|township) of$", "", (city or "").strip(), flags=re.I)
    c = re.sub(r"\s*\(.*\)$", "", c)
    return title(c) if c else None


def epa_issued(permits: list[str], epa: dict) -> bool:
    """A permit EPA Region 8 writes in Indian country: the SDG589 general-permit series, or a tribal government's."""
    return all(p.startswith("SDG589") or epa.get(p, {}).get("type") == "Tribal Government" for p in permits)


def channel(permits: list[str], kind: str, epa: dict, searched: bool) -> str:
    text = EPA_LAW if epa_issued(permits, epa) else LAW
    if kind == "cso":
        text += CSO_LAW
    return text + (SEARCHED if searched else OWN_PAGES)


def base_row(rid: str, name: str, permits: list[str], kind: str, legal_form: str | None, towns: list[str],
             waters: list[str], outfalls: int, notes: str, epa: dict, short: str | None = None,
             research: bool = False) -> dict:
    row = {"id": rid, "name": name, "state": "SD", "kind": kind, "npdes_permit": permits[0] if permits else None,
           "npdes_permits": permits, "receiving_waters": waters, "water_slugs": [], "outfall_count": outfalls or None,
           "outfalls_source": ("EPA ECHO ICIS-NPDES discharge points and the national CSO inventory "
                               f"(data/outfalls-plants-us.json, data/outfalls-us.json: {outfalls} rows for these permits)"
                               if outfalls else None),
           "notification_channel": channel(permits, kind, epa, research),
           "notification_feed_machine_readable": True,
           "notification_signup_url": None, "towns": towns, "notes": notes,
           "verified": "fetched", "checked": CHECKED, "aliases": [rid],
           "source_areas": ["sd"] + ([] if research else ["federal"])}
    if short:
        row["short_name"] = short
    if legal_form:
        row["legal_form"] = legal_form
    return row


def build(epa: dict[str, dict], research: list[dict]) -> tuple[list[dict], dict]:
    rows: dict[str, dict] = {}
    held: dict[str, str] = {}
    by_key: dict[str, str] = {}
    # 1. the research rows: each holds its permit, and every permit of the same owner
    for r in research:
        p = r["npdes_permit"]
        kind = RESEARCH_KIND.get(r["id"], r["kind"])
        name = r["name"]
        m = municipal(name)
        lf = "special district" if "Sanitary District" in name else (m[0].lower() if m else form(name, None))
        if r["id"] == "sd-brookings":
            lf = "city"
        note = (r.get("notes") or "").strip()
        note = (note + " " if note else "") + (f"Research row (research/sd/dischargers.json, checked {r.get('checked')}); "
                                                "permits of the same owner joined from EPA's lists.")
        n_out = epa.get(p, {}).get("outfalls", 0)
        rows[r["id"]] = base_row(r["id"], name, [p], kind, lf, r.get("towns") or [],
                                 list(dict.fromkeys(r.get("receiving_waters") or [])), n_out, note, epa,
                                 research=True)
        held[p] = r["id"]
        owner = epa.get(p, {}).get("owner") or ""
        mm = municipal(owner)
        by_key[muni_key(mm) if mm else owner_key(owner)] = r["id"]
    # 2. EPA's permits by owner
    groups: dict[str, list[str]] = defaultdict(list)
    meta: dict[str, list] = {}
    for p, o in sorted(epa.items()):
        if p in held:
            continue
        owner = o["owner"] or o["facility"] or p
        if p in PRIVATE:
            rid, name, lf, note = PRIVATE[p]
        elif owner in OWNERS:
            rid, name, lf, note = OWNERS[owner]
        elif any(owner.startswith(k) for k in DEPARTMENTS):
            rid, name = DEPARTMENTS[next(k for k in DEPARTMENTS if owner.startswith(k))]
            lf, note = "state facility", None
        else:
            mm = municipal(owner)
            key = muni_key(mm) if mm else owner_key(owner)
            if key in by_key and by_key[key] in rows:                    # joins a research row
                rid = by_key[key]
                rows[rid]["npdes_permits"].append(p)
                rows[rid]["outfall_count"] = (rows[rid]["outfall_count"] or 0) + o["outfalls"]
                rows[rid]["notification_channel"] = channel(rows[rid]["npdes_permits"], rows[rid]["kind"], epa, True)
                held[p] = rid
                continue
            name = tidy(f"{mm[0]} of {mm[1]}" if mm else title(re.sub(r"\s*\((?:biosolids|cso)\)\s*$", "", owner,
                                                                                flags=re.I)))
            lf = mm[0].lower() if mm else form(name, o["type"])
            rid = by_key.get(key) or f"sd-{slug(tidy(mm[1]) if mm else name)}"
            by_key[key] = rid
            note = None
        if rid in meta and mm_of(owner) and p.startswith("SD0"):           # the individual permit's word: city or town
            meta[rid][0], meta[rid][1] = name, lf
        if rid in rows:                                                  # a hand-joined owner of a research row
            rows[rid]["npdes_permits"].append(p)
            rows[rid]["outfall_count"] = (rows[rid]["outfall_count"] or 0) + o["outfalls"]
            held[p] = rid
            continue
        groups[rid].append(p)
        if rid not in meta:
            meta[rid] = [name, lf, note]
        elif name and not meta[rid][0]:
            meta[rid][0] = name
    for rid, permits in groups.items():
        name, lf, why = meta[rid]
        name = name or title(epa[permits[0]]["owner"] or permits[0])
        towns = sorted({t for p in permits if (t := town(epa[p].get("city")))})
        waters = list(dict.fromkeys(w for p in permits for w in epa[p]["waters"]))
        n_out = sum(epa[p]["outfalls"] for p in permits)
        kind = "cso" if any(epa[p]["open_cso"] for p in permits) else "plant"
        facs = "; ".join(f"{p} {epa[p]['facility']}" for p in permits)
        note = (f"EPA ECHO ICIS-NPDES: {facs}. Owner as EPA records it: "
                f"{'; '.join(sorted({str(epa[p]['owner']) for p in permits}))}; facility type "
                f"{'; '.join(sorted({str(epa[p]['type']) for p in permits}))}.")
        if lf in PRIVATE_FORMS:
            note = "Privately owned. " + note
        if why:
            note += " " + why
        rows[rid] = base_row(rid, name, permits, kind, lf, towns, waters, n_out, note, epa)
        for p in permits:
            held[p] = rid
    for r in rows.values():
        r["npdes_permits"] = list(dict.fromkeys(r["npdes_permits"]))
        r["npdes_permit"] = r["npdes_permits"][0]
    stats = {"rows": len(rows), "permits": len(held),
             "by_form": dict(Counter(r.get("legal_form") for r in rows.values())),
             "by_kind": dict(Counter(r["kind"] for r in rows.values())),
             "epa_issued": sum(1 for r in rows.values() if r["notification_channel"].startswith(EPA_LAW[:60])
                               and "Region 8" in r["notification_channel"]),
             "private": sorted(r["id"] for r in rows.values() if r.get("legal_form") in PRIVATE_FORMS)}
    return sorted(rows.values(), key=lambda r: r["id"]), stats


def main(argv: list[str]) -> int:
    dis = json.loads(DIS.read_text())
    research = json.loads(RESEARCH.read_text())
    cand = json.loads(CANDIDATES.read_text())
    epa = load_epa()
    missing = sorted(c["npdes_permit"] for c in cand["candidates"] if c["npdes_permit"] not in PRIVATE)
    if missing:
        raise SystemExit(f"private candidates without a PRIVATE row: {missing}")
    new, stats = build(epa, research)
    others = [r for r in dis if r.get("state") != "SD"]
    taken = {p for r in others for p in [r.get("npdes_permit"), *(r.get("npdes_permits") or [])] if p}
    clash = sorted(p for r in new for p in r["npdes_permits"] if p in taken)
    if clash:
        raise SystemExit(f"permits already held by another state's row: {clash}")
    ids = Counter(r["id"] for r in others + new)
    dup = [i for i, n in ids.items() if n > 1]
    if dup:
        raise SystemExit(f"duplicate ids: {dup}")
    unheld = sorted(set(epa) - {p for r in new for p in r["npdes_permits"]})
    if unheld:
        raise SystemExit(f"permits without a row: {unheld}")
    if "--dry-run" not in argv:
        DIS.write_text(json.dumps(others + new, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps(stats, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
