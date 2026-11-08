"""Kentucky operator rows for data/dischargers.json: one row per operator, every Kentucky permit in exactly one row.

Usage (after pipeline/ingest/echo_sewer_overflow_events.py has written its events and dropped files):
    pipeline/.venv/bin/python -I scripts/add_ky_operators.py [--dry-run]

Inputs
  1. data/outfalls-plants-us.json: EPA's ICIS-NPDES sewage permits with state KY (362). In Kentucky EPA's permit_name
     is mostly the plant's name ("Adairville STP"), not the owner's, so the owner is read by the rules below.
  2. data/outfalls-us.json: the combined sewer permits (17 KY permits, 289 open outfalls); all are among the plants.
  3. research/ky/dischargers.json (18 rows: the 17 CSO permits and Lexington): each research id stays an alias of the
     row holding its permit (Lexington's, which names no permit, of the Lexington-Fayette Urban County Government row).
  4. research/ky/private-utilities-candidates.json (6 private sewage permits).
  5. EPA's overflow tables (the events and dropped files): the Kentucky permits with reports; a permit only those tables
     name gets a row.
Rules
  - OWNERS: the operators of several permits, and of permits whose owner EPA's names do not give, by permit, each named
    as the body calls itself (Louisville MSD, SD1, Lexington-Fayette, the Regional Water Resource Agency, the
    Paducah/McCracken County Joint Sewer Agency, Kentucky-American Water and others).
  - Any other plant: EPA types the owner a municipality and the plant is "<City> STP" (WWTP, WWTF, WRF ...) or "<City>,
    City of": the row is "City of <City>", legal_form city (Kentucky's municipalities are all cities, KRS 81.005). An
    owner EPA types a county government: county. A name with Sanitation District, Water District or the like: special
    district; Authority, Commission, Agency: authority. Otherwise the row is named for the plant as EPA records it and
    legal_form stays null (the owner was not read), with EPA's facility type in the notes.
  - Never an individual's name: the candidates file's removed permittee is filed under the facility, legal_form
    "facility (permittee not named)"; a permit with no name anywhere is "Holder of permit <permit>".
  - kind: "cso" for a combined sewer permit, "sso" for a permit with reports in EPA's overflow tables, else "plant".
  - notification_channel: 401 KAR 5:065 Section 2(5) (an immediate telephone notice to the Division of Water; no public
    notice duty), the federal 24-hour and five-day reports, and EPA's overflow tables (Kentucky's flow stopped after
    January 2026); Louisville MSD's and SD1's own public channels on their rows.
  - Idempotent: a rerun replaces the rows it wrote (state KY, source_areas ["ky"]) and leaves every other row as it is.
Writes data/dischargers.json (indent 1) and prints counts.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
from common import NAME_REMOVED, scrub_discharger  # noqa: E402

DIS = ROOT / "data" / "dischargers.json"
PLANTS = ROOT / "data" / "outfalls-plants-us.json"
CSO = ROOT / "data" / "outfalls-us.json"
RESEARCH = ROOT / "research" / "ky" / "dischargers.json"
CANDIDATES = ROOT / "research" / "ky" / "private-utilities-candidates.json"
EVENTS = ROOT / "data" / "build" / "events" / "echo-sewer-overflow.json"
DROPPED = ROOT / "data" / "build" / "echo-sewer-overflow-dropped.json"
CHECKED = "2026-11-07"
ECHO = "https://echo.epa.gov/tools/data-downloads/sewer-overflow-download-summary"
LAW = ("401 KAR 5:065 Section 2(5) requires the permittee to notify the Kentucky Division of Water immediately by "
       "telephone (the 24-hour environmental emergency line after hours) of a spill, bypass, upset or overflow that may "
       "present an imminent or substantial danger to public health or the environment, with the federal 24-hour and "
       "five-day reports (40 CFR 122.41(l)(6)); the Division publishes no list of these reports. Kentucky's reporting "
       f"system sent its reports to EPA's overflow tables ({ECHO}) for December 2025 and January 2026 only. No duty to "
       "tell the public was found.")
PRIVATE_NOTE = " The permit conditions and the state rule bind a private permittee as they bind a public one."
OWN = " The operator's own pages were not searched individually."
MSD_CHANNEL = ("Louisville MSD shows an Overflow Advisory Level on every page of its website "
               "(https://louisvillemsd.org/overflowalert): MSD-01 'Wet Weather Overflows' system-wide after rain, with "
               "the advice to avoid contact with the Ohio River, streams, drainage ditches and standing water until 48 "
               "hours after the rain has stopped, and MSD-02 notices of a wet- or dry-weather discharge with its start "
               "time, address, receiving stream and amount, removed from the site later; a water quality e-mail list "
               "is offered in the footer. ")
SD1_CHANNEL = ("SD1's Wet Weather Overflow Notification Program (https://sd1.org/218/Wet-Weather-Overflow-Notification-"
               "Progra) sends e-mail and text alerts to subscribers from May through October when 0.25 inch of rain is "
               "recorded in its service area (Boone, Campbell and Kenton counties) or the Ohio River exceeds 38 feet; "
               "the advisories stand for 72 hours. Signs at the combined sewer outfalls ask people to avoid nearby water "
               "during and after rainfall for at least 72 hours. ")

# permit -> (row id, name, short name, legal form, note); a later permit of the same row repeats the id with None
OWNERS = {
    "KY0022411": ("ky-louisville-msd", "Louisville/Jefferson County Metropolitan Sewer District", "Louisville MSD",
                  "special district",
                  "A metropolitan sewer district (KRS Chapter 76). KY0022411 is the Morris Forman Water Quality "
                  "Treatment Center and the combined sewer system (121 open combined sewer outfalls in EPA's inventory, "
                  "120 in the Division of Water's layer). KY0034185 is filed here because its report in EPA's tables is "
                  "in MSD's work-order format and names MSD's crews (Hillview); the permit's own record was not read."),
    "KY0022420": ("ky-louisville-msd", None, None, None, None),
    "KY0034185": ("ky-louisville-msd", None, None, None, None),
    "KY0021466": ("ky-sd1", "Sanitation District No. 1 of Northern Kentucky", "SD1", "special district",
                  "A sanitation district (KRS Chapter 220) serving Boone, Campbell and Kenton counties; KY0021466 is "
                  "the Dry Creek plant and the combined sewer system (88 open combined sewer outfalls), KY0107239 the "
                  "Western Regional plant and KY0105031 the Eastern Regional plant."),
    "KY0107239": ("ky-sd1", None, None, None, None),
    "KY0105031": ("ky-sd1", None, None, None, None),
    "KY0021491": ("ky-lfucg", "Lexington-Fayette Urban County Government", "Lexington-Fayette UCG", "city",
                  "An urban county government (KRS Chapter 67A), filed as a city: the Town Branch and West Hickman "
                  "plants. Its sanitary sewers are under a consent decree (2008, modified 2015 and 2024); no public "
                  "overflow channel was found."),
    "KY0021504": ("ky-lfucg", None, None, None, None),
    "KY0020095": ("ky-rwra", "Regional Water Resource Agency (Owensboro)", "RWRA", "authority",
                  "Owensboro's and Daviess County's sewer agency: the Max Rhoads (west) plant and its combined sewer "
                  "outfalls, and the east plant."),
    "KY0073377": ("ky-rwra", None, None, None, None),
    "KY0022799": ("ky-paducah-mccracken-jsa", "Paducah/McCracken County Joint Sewer Agency", "Paducah/McCracken JSA",
                  "authority", "The Paducah plant and combined sewer system, and the Reidland and Woodlawn plants."),
    "KY0028312": ("ky-kentucky-american-water", "Kentucky-American Water Company", "Kentucky American Water",
                  "investor-owned utility",
                  "A regulated water and sewer company; EPA records its plants as \"Kentucky American Water Co - "
                  "Northern STP\" (Owenton) and \"- Millersburg\", and types them privately owned or a district."),
    "KY0022861": ("ky-city-of-frankfort", "City of Frankfort", "City of Frankfort", "city",
                  "The Frankfort Municipal plant and its combined sewer outfalls. One incident (2025-12-22, a force "
                  "main break) was filed under this permit and under the general permit KYG200034 in EPA's tables."),
    "KYG200034": ("ky-city-of-frankfort", None, None, None, None),
    "KY0020711": ("ky-henderson-water-utility", "City of Henderson (Henderson Water Utility)", "Henderson Water Utility",
                  "city", "The Henderson plant and its combined sewer outfalls, and the South plant."),
    "KY0024414": ("ky-blue-licks-state-park", "Kentucky Department of Parks (Blue Licks Battlefield State Resort Park)",
                  "Blue Licks Battlefield State Resort Park", "state facility",
                  "Named by its report in EPA's overflow tables (the park's lodge lift station); the permit's record "
                  "was not read."),
    "KYR003103": ("ky-kyr003103", "Heaven Hill Brands (permit KYR003103)", "Heaven Hill Brands",
                  "business or industrial",
                  "A general stormwater permit; its report in EPA's overflow tables (2025-12-08) names the company's "
                  "lift station and the company as responsible for the cleanup."),
    "KY0092118": ("ky-precoat-metals", "Precoat Metals", "Precoat Metals", "business or industrial",
                  "An industrial plant treating its own sewage (Hawesville); EPA types it privately owned."),
    "KY0112283": ("ky-mayslick-heritage-apartments", "Mayslick Heritage Apartments", "Mayslick Heritage Apartments",
                  "business or industrial", "An apartment complex's plant (Mays Lick); EPA types it privately owned."),
    "KY0112399": ("ky-cow-creek-wwtp", "Cow Creek Wastewater Treatment Plant (Ravenna)", "Cow Creek WWTP", None,
                  "EPA types it privately owned; the owner was not read."),
    "KYP000093": ("ky-autumn-lake-mhp", "Autumn Lake Mobile Home Park", "Autumn Lake MHP", "mobile-home park",
                  "EPA types it privately owned (Louisville)."),
}
# EPA plant names whose permits join one row (the permit numbers are read from the plant file)
NAME_ROWS = [
    (re.compile(r"WQTC MSD$|^Louisville and Jefferson County MSD$", re.I), "ky-louisville-msd"),
    (re.compile(r"^Paducah/McCracken County JSA", re.I), "ky-paducah-mccracken-jsa"),
    (re.compile(r"^Kentucky American Water", re.I), "ky-kentucky-american-water"),
    (re.compile(r"^Henderson (South )?STP", re.I), "ky-henderson-water-utility"),
    (re.compile(r"^RICHMOND |^Richmond ", re.I), ("ky-richmond-utilities", "City of Richmond (Richmond Utilities)",
                                                  "Richmond Utilities", "city", "Four plants: Dreaming Creek, Tates "
                                                  "Creek, Otter Creek and Silver Creek.")),
    (re.compile(r"^Georgetown STP", re.I), ("ky-georgetown-municipal-water-sewer", "City of Georgetown (Georgetown "
                                           "Municipal Water and Sewer Service)", "Georgetown Municipal Water and Sewer",
                                           "city", "Three plants (STP #1, #2 and #3).")),
    (re.compile(r"^Mayfield (Electric|STP)", re.I), ("ky-mayfield-electric-water", "Mayfield Electric and Water "
                                                    "Systems", "Mayfield Electric and Water Systems", "city",
                                                    "The City of Mayfield's utility, filed as a city.")),
    (re.compile(r"^Shelbyville ", re.I), ("ky-city-of-shelbyville", "City of Shelbyville", "City of Shelbyville", "city", "EPA records its plants under the city's name and types the owner a municipality or a municipal or water district: filed under the city.")),
    (re.compile(r"^Evarts STP", re.I), ("ky-city-of-evarts", "City of Evarts", "City of Evarts", "city", "EPA records its plants under the city's name and types the owner a municipality or a municipal or water district: filed under the city.")),
    (re.compile(r"^Clay City ", re.I), ("ky-city-of-clay-city", "City of Clay City", "City of Clay City", "city", "EPA records its plants under the city's name and types the owner a municipality or a municipal or water district: filed under the city.")),
    (re.compile(r"^Greenup STP$", re.I), ("ky-city-of-greenup", "City of Greenup", "City of Greenup", "city", "EPA records its plants under the city's name and types the owner a municipality or a municipal or water district: filed under the city.")),
    (re.compile(r"^Bloomfield ", re.I), ("ky-city-of-bloomfield", "City of Bloomfield", "City of Bloomfield", "city", "EPA records its plants under the city's name and types the owner a municipality or a municipal or water district: filed under the city.")),
    (re.compile(r"^Prestonsburg ", re.I), ("ky-city-of-prestonsburg", "City of Prestonsburg", "City of Prestonsburg", "city", "EPA records its plants under the city's name and types the owner a municipality or a municipal or water district: filed under the city.")),
    (re.compile(r"^Hillview ", re.I), ("ky-city-of-hillview", "City of Hillview", "City of Hillview", "city", "EPA records its plants under the city's name and types the owner a municipality or a municipal or water district: filed under the city.")),
    (re.compile(r"^Mercer County Sanitation District", re.I), ("ky-mercer-county-sanitation-district",
                                                              "Mercer County Sanitation District",
                                                              "Mercer County Sanitation District", "special district",
                                                              None)),
    (re.compile(r"^Perry County (SD|Sanitation District) 1", re.I), ("ky-perry-county-sanitation-district-1",
                                                                    "Perry County Sanitation District No. 1",
                                                                    "Perry County Sanitation District No. 1",
                                                                    "special district", None)),
]
PLANT_WORDS = re.compile(r"\s+(?:STP|WWTP|WWTF|WRF|WQTC|Wastewater Treatment Plant|Wastewater Collection|Regional STP|"
                         r"Regional WWTP|Regional WRF|Municipal STP|Municipal Utilities WWTP|Municipal Utilities|"
                         r"Collection System|Collection Sys|Sewer System Plant \d+|Treatment Plant)\b.*$", re.I)
DISTRICT = re.compile(r"\b(sanitation district|water dist(?:rict)?\b|sewer district|sd ?#?\s*\d|sanitation co\b|water & sewer "
                      r"district|environmental control|sanitation district #)", re.I)
AUTH = re.compile(r"\b(authority|auth\b|commission|agency|jsa|joint sewer)", re.I)
PUBLIC_FORMS = {"city", "town", "county", "authority", "special district", "federal facility", "state facility",
                "tribal"}
PRIVATE_FORMS = {"investor-owned utility", "member-owned utility", "homeowners' association", "mobile-home park",
                 "campground or resort", "private club", "business or industrial", "institution",
                 "facility (permittee not named)"}
ABBR = {"stp", "wwtp", "wwtf", "wrf", "wqtc", "msd", "sd", "ky", "mhp", "jsa", "cmuc", "nmcsd", "ii"}


def smart_title(s: str) -> str:
    out = []
    for i, w in enumerate((s or "").split()):
        bare = re.sub(r"[^A-Za-z0-9]", "", w).lower()
        if bare in ABBR:
            out.append(w.upper())
        elif bare in ("of", "and", "the") and i:
            out.append(w.lower())
        else:
            out.append(w.capitalize() if w.isupper() or w.islower() else w)
    return " ".join(out)


def slug(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", (s or "").lower())).strip("-")


def person(name: str) -> bool:
    return bool(name) and scrub_discharger({"discharger_name": name})["discharger_name"] == NAME_REMOVED


def default_owner(pn: str, ftype: str | None, cso_permit: bool = False) -> tuple[str, str, str | None, str | None]:
    """(id, name, legal form, note) for a plant EPA names: see the module docstring. A combined sewer permit's
    "<City> STP" is the city's (Kentucky's combined sewers are cities' old systems; research/ky/dischargers.json)."""
    pn = " ".join((pn or "").split())
    m = re.match(r"^(.+?),\s*City of$", pn, re.I)
    t = ftype or ""
    if cso_permit and t != "Municipality":
        t = "Municipality"
    if m:
        city = smart_title(m.group(1))
        return f"ky-city-of-{slug(city)}", f"City of {city}", "city", None
    if DISTRICT.search(pn):
        name = smart_title(pn)
        return f"ky-{slug(name)}", name, "special district", None
    if AUTH.search(pn):
        name = smart_title(pn)
        return f"ky-{slug(name)}", name, "authority", None
    if t.startswith("County") or re.search(r"\bFiscal Court\b", pn, re.I):
        name = smart_title(pn)
        return f"ky-{slug(name)}", name, "county", None
    if t.startswith("State") or re.search(r"\bState Park\b", pn, re.I):
        name = smart_title(pn)
        return f"ky-{slug(name)}", name, "state facility", None
    if re.search(r"\bMunicipal Utilities\b", pn, re.I):
        name = smart_title(PLANT_WORDS.sub("", pn) if not pn.lower().endswith("municipal utilities") else pn)
        name = name if name.lower().endswith("municipal utilities") else name + " Municipal Utilities"
        return f"ky-{slug(name)}", name, "city", "A city's utility, filed as a city."
    if re.search(r"\b(elementary|intermediate|middle|high) school\b|\bcounty schools\b", pn, re.I):
        name = smart_title(pn)
        return f"ky-{slug(name)}", name, "special district", "A public school district's plant."
    if re.search(r"\bmobile home park\b|\bMHP\b", pn, re.I):
        name = smart_title(pn)
        return f"ky-{slug(name)}", name, "mobile-home park", None
    if re.search(r"\b(inc|llc|co)\b\.?$|\bsanitation co\b", pn, re.I):
        name = smart_title(pn)
        return f"ky-{slug(name)}", name, "business or industrial", None
    if t.startswith("School"):
        name = smart_title(pn)
        return f"ky-{slug(name)}", name, "special district", "A public school district's plant."
    town = PLANT_WORDS.sub("", pn).strip(" -#0123456789")
    town = re.sub(r"\s+(New|#\s*\d+)$", "", town, flags=re.I).strip()
    if t == "Municipality" and town and town != pn and not re.search(r"\d|subdivision|park|village|estates|camp|"
                                                                      r"school|housing|industrial", town, re.I):
        city = smart_title(town)
        return (f"ky-city-of-{slug(city)}", f"City of {city}", "city",
                f"EPA records the plant as \"{pn}\" and types its owner a municipality: filed under the city.")
    name = smart_title(pn)
    return (f"ky-{slug(name)}", name, None,
            f"EPA records the permittee as the plant (\"{pn}\") and types the owner \"{t or 'not given'}\"; the owner "
            "was not read.")


def epa_reports() -> tuple[Counter, Counter]:
    allr, kept = Counter(), Counter()
    for r in json.loads(EVENTS.read_text()).get("records", []):
        if str(r.get("npdes_permit") or "").startswith("KY"):
            kept[r["npdes_permit"]] += 1
            allr[r["npdes_permit"]] += 1
    for r in json.loads(DROPPED.read_text()).get("dropped", []):
        if str(r.get("permit") or "").startswith("KY"):
            allr[r["permit"]] += 1
    return allr, kept


def build(dis: list[dict]) -> tuple[list[dict], dict]:
    missing = [str(p.relative_to(ROOT)) for p in (EVENTS, DROPPED) if not p.exists()]
    if missing:
        raise SystemExit("run pipeline/ingest/echo_sewer_overflow_events.py first; missing: " + ", ".join(missing))
    keep = [d for d in dis if not (d.get("state") == "KY" and "ky" in (d.get("source_areas") or []))]
    held_elsewhere = {str(p).upper() for d in keep for p in [d.get("npdes_permit"), *(d.get("npdes_permits") or [])] if p}
    plants: dict[str, list[dict]] = defaultdict(list)
    for r in json.loads(PLANTS.read_text())["outfalls"]:
        if r.get("state") == "KY" and str(r.get("npdes_permit") or "").startswith("KY"):
            plants[r["npdes_permit"]].append(r)
    cso: dict[str, list[dict]] = defaultdict(list)
    for r in json.loads(CSO.read_text())["outfalls"]:
        if str(r.get("npdes_permit") or "").startswith("KY"):
            cso[r["npdes_permit"]].append(r)
    research: dict[str, list[dict]] = defaultdict(list)
    for r in json.loads(RESEARCH.read_text()):
        research[r.get("npdes_permit") or "KY0021491"].append(r)     # Lexington names no permit: LFUCG's row
    cand = json.loads(CANDIDATES.read_text())
    cands = {c["npdes_permit"]: c for c in cand["candidates"] + cand.get("public_by_name", [])}
    allr, kept = epa_reports()
    permits = sorted((set(plants) | set(cso) | set(research) | set(cands) | set(allr)) - held_elsewhere)

    meta: dict[str, dict] = {}
    by_row: dict[str, list[str]] = defaultdict(list)
    for p, (rid, name, short, lf, note) in OWNERS.items():
        if name:
            meta[rid] = {"name": name, "short": short, "lf": lf, "note": note}
    for p in permits:
        rows = plants.get(p) or []
        pn = (rows[0].get("permit_name") or rows[0].get("permittee") or "") if rows else ""
        if p in OWNERS:
            rid = OWNERS[p][0]
        else:
            rid = None
            for pat, target in NAME_ROWS:
                if pn and pat.search(pn):
                    if isinstance(target, tuple):
                        rid = target[0]
                        meta.setdefault(rid, {"name": target[1], "short": target[2], "lf": target[3],
                                              "note": target[4]})
                    elif isinstance(target, str):
                        rid = target
                    else:       # one owner for the plants of one name stem: the first plant's default owner
                        stem = pat.pattern
                        first = next(q for q in sorted(plants) if pat.search(plants[q][0].get("permit_name") or ""))
                        rid, name, lf, note = default_owner(plants[first][0].get("permit_name"),
                                                            plants[first][0].get("facility_type"))
                        meta.setdefault(rid, {"name": name, "short": name, "lf": lf, "note": note, "stem": stem})
                    break
            if rid is None:
                c = cands.get(p)
                if c and (NAME_REMOVED in (c.get("permittee_as_recorded") or "") or person(c.get("permittee_as_recorded"))):
                    fac = c.get("facility") or ""
                    name = (f"{smart_title(fac)} (permit {p})" if fac and NAME_REMOVED not in fac
                            else f"Holder of permit {p}")
                    rid = f"ky-{p.lower()}"
                    meta.setdefault(rid, {"name": name, "short": name, "lf": "facility (permittee not named)",
                                          "note": "EPA's permittee name reads as an individual's: not named here."})
                elif pn:
                    if person(pn):
                        rid, name, lf, note = f"ky-{p.lower()}", f"Holder of permit {p}", "facility (permittee not named)", None
                    else:
                        rid, name, lf, note = default_owner(pn, rows[0].get("facility_type"), p in cso)
                    meta.setdefault(rid, {"name": name, "short": name, "lf": lf, "note": note})
                elif c:
                    name = smart_title(c.get("facility") or "")
                    rid = f"ky-{slug(name)}"
                    meta.setdefault(rid, {"name": name, "short": name, "lf": c.get("legal_form_proposed"),
                                          "note": "EPA types it privately owned."})
                else:
                    rid = f"ky-{p.lower()}"
                    meta.setdefault(rid, {"name": f"Holder of permit {p}", "short": f"Holder of permit {p}", "lf": None,
                                          "note": "Named in EPA's overflow tables only; the permit's record was not "
                                                  "read, so the holder is not named here."})
        by_row[rid].append(p)
    research_ids = {p: [r["id"] for r in rs] for p, rs in research.items()}
    new = []
    for rid, ps in sorted(by_row.items()):
        m = meta[rid]
        prow = [r for p in ps for r in plants.get(p, [])]
        crow = [r for p in ps for r in cso.get(p, [])]
        towns = sorted({smart_title(r["city"]) for r in prow + crow if r.get("city")
                        and "COUNTY" not in r["city"].upper() and r["city"].upper() != "UNKNOWN"}
                       | {smart_title(cands[p]["city"]) for p in ps if p in cands and cands[p].get("city")})
        own = re.match(r"^City of ([^(]+?)(?: \(|$)", m["name"])
        if own and own.group(1) not in towns:
            towns.append(own.group(1))
        waters = list(dict.fromkeys([r["receiving_water_echo"].strip() for r in prow + crow
                                     if r.get("receiving_water_echo")]
                                    + [w for p in ps if p in cands for w in cands[p].get("receiving_waters_echo") or []]))[:10]
        open_cso = [r for r in crow if not str(r.get("outfall_status") or "").upper().startswith("CLS")]
        facs = "; ".join(f"{p} {smart_title((plants.get(p) or [{}])[0].get('permit_name') or '')}".strip() for p in ps)
        note = f"EPA ICIS-NPDES: {facs}." if m["lf"] != "facility (permittee not named)" else f"EPA ICIS-NPDES: {ps[0]}."
        reports = sum(allr[p] for p in ps)
        if reports:
            note += (f" EPA's overflow tables (2026-11-04 extract): {reports} Kentucky report(s), {sum(kept[p] for p in ps)}"
                     " with evidence the discharge reached a water.")
        if open_cso:
            note += f" {len(open_cso)} open combined sewer outfall(s) in EPA's national CSO inventory."
        if m.get("note"):
            note += " " + m["note"]
        kind = "cso" if open_cso else ("sso" if reports else "plant")
        private = m["lf"] in PRIVATE_FORMS
        channel = (MSD_CHANNEL if rid == "ky-louisville-msd" else SD1_CHANNEL if rid == "ky-sd1" else "") + LAW \
            + (PRIVATE_NOTE if private else "") + ("" if rid in ("ky-louisville-msd", "ky-sd1") else OWN)
        signup = ("https://sd1.org/218/Wet-Weather-Overflow-Notification-Progra" if rid == "ky-sd1"
                  else "https://louisvillemsd.org/" if rid == "ky-louisville-msd" else None)
        aliases = [rid] + [a for p in ps for a in research_ids.get(p, [])]
        new.append({"id": rid, "name": m["name"], "short_name": m["short"] or m["name"], "legal_form": m["lf"],
                    "state": "KY", "kind": kind, "npdes_permit": ps[0], "npdes_permits": list(ps),
                    "receiving_waters": waters, "water_slugs": [],
                    "outfall_count": (len(open_cso) or len(prow)) or None,
                    "outfalls_source": (f"EPA National CSO Inventory (data/outfalls-us.json, {len(open_cso)} open)"
                                        if open_cso else f"EPA ICIS-NPDES discharge points (data/outfalls-plants-us.json, "
                                        f"{len(prow)} rows)" if prow else None),
                    "notification_channel": channel,
                    "notification_feed_machine_readable": rid == "ky-louisville-msd" or bool(reports),
                    "notification_signup_url": signup, "towns": towns, "notes": note.strip(), "verified": "fetched",
                    "checked": CHECKED, "aliases": list(dict.fromkeys(aliases)), "source_areas": ["ky"]})
    ids = Counter(r["id"] for r in keep + new)
    dup = [i for i, n in ids.items() if n > 1]
    if dup:
        raise SystemExit(f"duplicate ids: {dup}")
    stats = {"rows": len(new), "permits": sum(len(r["npdes_permits"]) for r in new),
             "legal_form": dict(Counter(r.get("legal_form") for r in new)), "kind": dict(Counter(r["kind"] for r in new)),
             "permits_with_reports": len([p for p in permits if allr[p]]),
             "held_elsewhere": sorted(p for p in (set(allr) | set(plants)) if p in held_elsewhere),
             "multi_permit_rows": {r["id"]: r["npdes_permits"] for r in new if len(r["npdes_permits"]) > 1}}
    return keep + new, stats


def main(argv: list[str]) -> int:
    dis = json.loads(DIS.read_text())
    out, stats = build(dis)
    print(json.dumps(stats, indent=1, ensure_ascii=False))
    if "--dry-run" not in argv:
        DIS.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
