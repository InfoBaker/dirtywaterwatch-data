"""New Mexico operator rows for data/dischargers.json: one row per operator, every New Mexico permit in exactly one row.

Usage (after pipeline/ingest/echo_sewer_overflow_events.py has written its events and dropped files, with the
all-versions ZIP saved at data/raw/echo-nm/all.zip):
    pipeline/.venv/bin/python -I scripts/add_nm_operators.py [--dry-run]

Inputs
  1. data/outfalls-plants-us.json: EPA's ICIS-NPDES sewage permits with state NM (66: 62 New Mexico permits NM..., and
     four Navajo Nation permits NN... whose plants lie in New Mexico: Shiprock, the Northern Edge Navajo Casino,
     Nenahnezad Community School, Wingate High School). permit_name is the owner as EPA records it.
  2. research/nm/dischargers.json (27 rows, the major permits): each research id stays as an alias of the row that
     holds its permit, so the overflow module's discharger_id (the research id) resolves (common.discharger_alias_map).
  3. research/nm/private-utilities-candidates.json (5 private sewage permits, 2 public bodies EPA types private).
  4. EPA's overflow tables (the events and dropped files, and the collection-system table in the saved ZIP): the reports
     placed in New Mexico and the permits with a collection system. A permit only those tables name gets a row.
Rules
  - OWNERS gives every permit its row: the owner's name put in order and spelled as the body calls itself (EPA's own
    spelling stays in the notes), legal_form from the controlled list (docs/legal-forms.md), never an individual's name:
    a permit whose permittee the candidates file removed is filed under the facility, legal_form "facility (permittee
    not named)". New Mexico's mutual domestic water and sewer associations are filed as special districts (political
    subdivisions under the Sanitary Projects Act, NMSA 1978 Chapter 3 Article 29), public school districts likewise.
    An owner that was not read keeps legal_form null.
  - Permits held by another state's row are left there: Window Rock's NN0021555 is in Arizona's Navajo Tribal Utility
    Authority row although one of its reports lies in New Mexico (it is counted on that row's register entry, here only
    in the notes of the New Mexico row).
  - kind: "sso" when a permit of the row has reports placed in New Mexico or a collection system in EPA's
    collection-system table; otherwise "plant".
  - notification_channel: EPA Region 6 issues New Mexico's permits (the federal 24-hour and five-day reports to EPA,
    published in EPA's overflow tables when filed electronically), and 20.6.2.1203 NMAC requires an oral notice to NMED
    within 24 hours of a discharge that may injure health or property (NMED publishes no list). Tribal and Navajo
    Nation permits (NN..., and the Pueblos' and Apache nations' NM... permits EPA types tribal): EPA's channel only.
    notification_signup_url null: no overflow alert list was found (research/nm/report.md); operators' own pages were
    not searched one by one.
  - The counts and kind come from git-ignored files: the script stops when they are absent.
  - Idempotent: a rerun replaces the rows it wrote (state NM, source_areas ["nm"]) and leaves every other row as it is;
    new rows go after the last row of the file.
Writes data/dischargers.json (indent 1) and prints counts.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIS = ROOT / "data" / "dischargers.json"
PLANTS = ROOT / "data" / "outfalls-plants-us.json"
RESEARCH = ROOT / "research" / "nm" / "dischargers.json"
CANDIDATES = ROOT / "research" / "nm" / "private-utilities-candidates.json"
EVENTS = ROOT / "data" / "build" / "events" / "echo-sewer-overflow.json"
DROPPED = ROOT / "data" / "build" / "echo-sewer-overflow-dropped.json"
ZIP = ROOT / "data" / "raw" / "echo-nm" / "all.zip"
CHECKED = "2026-11-07"
ECHO = "https://echo.epa.gov/tools/data-downloads/sewer-overflow-download-summary"
LAW = ("EPA Region 6 issues New Mexico's NPDES permits: the permit's 24-hour and five-day noncompliance reports go to EPA "
       "(40 CFR 122.41(l)(6)), which publishes those filed electronically in its overflow tables "
       f"({ECHO}). 20.6.2.1203 NMAC also requires the person in charge of a facility to tell NMED orally within 24 hours "
       "of a discharge that may with reasonable probability injure health or property, in writing within a week, with "
       "a corrective-action report in 15 days; NMED publishes no list of these notices. No duty to tell the public was "
       "found.")
TRIBAL = ("A permit on tribal land, where EPA ({region}), not the state, administers the Clean Water Act permit program "
          "and New Mexico's notice rule does not apply: the permit's 24-hour and five-day noncompliance reports go to "
          f"EPA (40 CFR 122.41(l)(6)), which publishes those filed electronically in its overflow tables ({ECHO}). No "
          "public notice duty was found.")
PRIVATE_NOTE = " The permit conditions and the state rule bind a private permittee as they bind a public one."
OWN = " The operator's own pages were not searched individually."
SPA = ("A mutual domestic association: a political subdivision of the state under the Sanitary Projects Act (NMSA "
       "1978, Chapter 3, Article 29), filed as a special district.")

# permit -> (row id, name, short name, legal form, note)
OWNERS = {
    "NM0024830": ("nm-abiquiu-mdwca", "Abiquiu Mutual Domestic Water Consumers and Mutual Sewage Works Association",
                  "Abiquiu MDWCA and MSWA", "special district",
                  SPA + " EPA records the owner as \"ABIQUIU, CITY OF\"; Abiquiu is not incorporated, and EPA's facility "
                        "and collection-system tables name the association."),
    "NM0022250": ("nm-abcwua", "Albuquerque Bernalillo County Water Utility Authority",
                  "Albuquerque Bernalillo County Water Utility Authority", "authority",
                  "Albuquerque's sewers and the Southside Water Reclamation Plant. EPA's collection-system table lists "
                  "the system, but no report under the permit is in EPA's overflow tables (2026-11-04 extract)."),
    "NM0030503": ("nm-village-of-angel-fire", "Village of Angel Fire", "Village of Angel Fire", "town", None),
    "NM0029629": ("nm-anthony-water-and-sanitation-district", "Anthony Water and Sanitation District",
                  "Anthony Water and Sanitation District", "special district", None),
    "NM0022268": ("nm-city-of-artesia", "City of Artesia", "City of Artesia", "city", None),
    "NM0020168": ("nm-city-of-aztec", "City of Aztec", "City of Aztec", "city", None),
    "NM0020150": ("nm-city-of-belen", "City of Belen", "City of Belen", "city", None),
    "NM0023485": ("nm-town-of-bernalillo", "Town of Bernalillo", "Town of Bernalillo", "town",
                  "EPA records the owner as \"BERNALILLO, CITY OF\"; its facility and collection-system tables name the "
                  "Town."),
    "NN0020800": ("nm-bie-nenahnezad-community-school", "Bureau of Indian Education, Nenahnezad Community School",
                  "Nenahnezad Community School", "federal facility",
                  "A Navajo Nation permit (NN...) for a federal school's plant near Fruitland."),
    "NM0020770": ("nm-city-of-bloomfield", "City of Bloomfield", "City of Bloomfield", "city", None),
    "NM0030279": ("nm-village-of-bosque-farms", "Village of Bosque Farms", "Village of Bosque Farms", "town", None),
    "NM0029483": ("nm-camino-real-regional-utility-authority", "Camino Real Regional Utility Authority (Sunland Park "
                  "and North plants)", "Camino Real Regional Utility Authority", "authority", None),
    "NM0031178": ("nm-camino-real-regional-utility-authority", None, None, None, None),
    "NM0026395": ("nm-city-of-carlsbad", "City of Carlsbad", "City of Carlsbad", "city", None),
    "NM0030678": ("nm-casa-blanca-wwtp", "Casa Blanca Wastewater Treatment Plant (Pueblo of Laguna)", "Casa Blanca WWTP",
                  "tribal",
                  "EPA types the owner a tribal government; the plant, on the Pueblo of Laguna's land, serves the "
                  "Dancing Eagle Casino and a small residential area (EPA's 2021 fact sheet; NMED's certification list "
                  "files it under Laguna Pueblo)."),
    "NM0031038": ("nm-village-of-cimarron", "Village of Cimarron", "Village of Cimarron", "town", None),
    "NM0023370": ("nm-village-of-cloudcroft", "Village of Cloudcroft", "Village of Cloudcroft", "town", None),
    "NM0030490": ("nm-dona-ana-county", "Doña Ana County Utilities (South Central Regional plant)", "Doña Ana County",
                  "county", None),
    "NM0030520": ("nm-jicarilla-apache-nation", "Jicarilla Apache Nation (Dulce plant)", "Jicarilla Apache Nation",
                  "tribal", None),
    "NM0031235": ("nm-eastern-new-mexico-rural-water-authority", "Eastern New Mexico Rural Water Authority",
                  "Eastern New Mexico Rural Water Authority", "authority",
                  "EPA records the owner as \"EASTERN NM RURAL WATER SYSTEM\" (Ute Reservoir)."),
    "NM0029351": ("nm-city-of-espanola", "City of Española", "City of Española", "city", None),
    "NM0020583": ("nm-city-of-farmington", "City of Farmington", "City of Farmington", "city", None),
    "NM0023477": ("nm-village-of-fort-sumner", "Village of Fort Sumner", "Village of Fort Sumner", "town",
                  "EPA records the owner as \"FORT SUMNER, TOWN OF\"."),
    "NM0020672": ("nm-city-of-gallup", "City of Gallup", "City of Gallup", "city", None),
    "NM0020010": ("nm-village-of-hatch", "Village of Hatch", "Village of Hatch", "town", None),
    "NM0028011": ("nm-village-of-jemez-springs", "Village of Jemez Springs", "Village of Jemez Springs", "town", None),
    "NM0023311": ("nm-city-of-las-cruces", "City of Las Cruces Utilities (Jacob A. Hands and East Mesa plants)",
                  "City of Las Cruces", "city",
                  "EPA's collection-system table lists the system, but no report under its permits is in EPA's "
                  "overflow tables (2026-11-04 extract)."),
    "NM0030872": ("nm-city-of-las-cruces", None, None, None, None),
    "NM0028827": ("nm-city-of-las-vegas", "City of Las Vegas", "City of Las Vegas", "city", None),
    "NM0020133": ("nm-los-alamos-county", "Los Alamos County Department of Public Utilities (Bayo and White Rock "
                  "plants)", "Los Alamos County", "county", None),
    "NM0020141": ("nm-los-alamos-county", None, None, None, None),
    "NM0020303": ("nm-village-of-los-lunas", "Village of Los Lunas", "Village of Los Lunas", "town", None),
    "NM0029149": ("nm-village-of-maxwell", "Village of Maxwell", "Village of Maxwell", "town", None),
    "NM0030660": ("nm-mescalero-apache-tribe", "Mescalero Apache Tribe", "Mescalero Apache Tribe", "tribal", None),
    "NM0024996": ("nm-mora-mutual-water-and-sewer-works-association", "Mora Mutual Water and Sewer Works Association",
                  "Mora Mutual Water and Sewer Works Association", "special district", SPA),
    "NN0020621": ("nm-navajo-tribal-utility-authority", "Navajo Tribal Utility Authority (Shiprock and Northern Edge "
                  "Navajo Casino plants)", "Navajo Tribal Utility Authority", "tribal",
                  "Navajo Nation permits (NN...) whose plants lie in New Mexico; the Authority's Arizona plants are "
                  "Arizona's row. A report counts here when its point lies in New Mexico. Three reports under Window "
                  "Rock's permit (NN0021555, Arizona's row) lie in New Mexico and are placed there: two at the lift "
                  "station by Navajo, New Mexico (2026-08-10 and 08-11) and a line washed out east of Fort Defiance "
                  "(2026-08-19)."),
    "NN0030343": ("nm-navajo-tribal-utility-authority", None, None, None, None),
    "NM0030813": ("nm-oshara-village-wrf", "Oshara Village Water Reclamation Facility",
                  "Oshara Village Water Reclamation Facility", None,
                  "EPA records the plant's name as the permittee and types it a municipal or water district; the owner "
                  "was not read."),
    "NM0029041": ("nm-village-of-pecos", "Village of Pecos", "Village of Pecos", "town", None),
    "NM0031231": ("nm-pilot-travel-center-305", "Pilot Travel Centers (Travel Center #305, Jamestown)",
                  "Pilot Travel Center #305", "business or industrial",
                  "A truck stop's plant treating its own sewage; the permittee as EPA records it."),
    "NM0023396": ("nm-ramah-water-and-sanitation-district", "Ramah Water and Sanitation District",
                  "Ramah Water and Sanitation District", "special district", None),
    "NM0030368": ("nm-ranchland-utility-company", "Ranchland Utility Company", "Ranchland Utility Company",
                  "investor-owned utility",
                  "A sewer utility company (Santa Fe County); EPA types it a municipal or water district, and its "
                  "collection-system table a municipality."),
    "NM0020273": ("nm-city-of-raton", "City of Raton", "City of Raton", "city", None),
    "NM0024899": ("nm-town-of-red-river", "Town of Red River", "Town of Red River", "town", None),
    "NM0024163": ("nm-reserve-mutual-sewer-association", "Reserve Mutual Sewer Association",
                  "Reserve Mutual Sewer Association", "special district",
                  "EPA records the owner as \"RESERVE MUTUAL SEWER ASSOCIATI\" and names the facility and collection "
                  "system \"RESERVE, VILLAGE OF\". Filed as a mutual domestic association under the Sanitary Projects "
                  "Act (a special district); the permit documents were not read."),
    "NM0027782": ("nm-new-mexico-water-service-company", "New Mexico Water Service Company (Rio Communities and Rio del "
                  "Oro plants)", "New Mexico Water Service Company", "investor-owned utility",
                  "EPA records the owners as \"RIO COMMUNITIES WWTF-NM WATER\" and \"RIO DEL ORO WWTF-NM WATER SERV\" and "
                  "types them municipal or water districts; New Mexico Water Service Company is a regulated water and "
                  "sewer company. The permit documents were not read."),
    "NM0030414": ("nm-new-mexico-water-service-company", None, None, None, None),
    "NM0027987": ("nm-city-of-rio-rancho", "City of Rio Rancho (plants no. 2 and no. 3)", "City of Rio Rancho", "city",
                  None),
    "NM0029602": ("nm-city-of-rio-rancho", None, None, None, None),
    "NM0020311": ("nm-city-of-roswell", "City of Roswell", "City of Roswell", "city", None),
    "NM0029165": ("nm-ruidoso-ruidoso-downs", "Village of Ruidoso and City of Ruidoso Downs (joint plant)",
                  "Ruidoso and Ruidoso Downs", "town",
                  "The regional plant the Village of Ruidoso and the City of Ruidoso Downs share; EPA records it as "
                  "\"RUIDOSO-RUIDOSO DOWNS WWTP-LIN\"."),
    "NM0030457": ("nm-salem-wwtp", "Salem Wastewater Treatment Plant", "Salem Wastewater Treatment Plant", None,
                  "EPA records the plant's name as the permittee and types it a municipal or water district; the owner "
                  "was not read."),
    "NM0031011": ("nm-pueblo-of-san-felipe", "Pueblo of San Felipe", "Pueblo of San Felipe", "tribal", None),
    "NM0022292": ("nm-city-of-santa-fe", "City of Santa Fe (Paseo Real plant)", "City of Santa Fe", "city",
                  "EPA records the plant as \"SANTA FE, CITY OF (AIRPORT RD\". EPA's collection-system table lists the "
                  "system, but no report under the permit is in EPA's overflow tables (2026-11-04 extract)."),
    "NM0024988": ("nm-city-of-santa-rosa", "City of Santa Rosa", "City of Santa Rosa", "city", None),
    "NM0030864": ("nm-sierra-county-regional-wwtp", "Sierra County Regional Wastewater Treatment Plant",
                  "Sierra County Regional WWTP", None,
                  "EPA records the plant's name as the permittee; the owner was not read."),
    "NM0020109": ("nm-town-of-silver-city", "Town of Silver City", "Town of Silver City", "town", None),
    "NM0028835": ("nm-city-of-socorro", "City of Socorro", "City of Socorro", "city", None),
    "NM0030295": ("nm-town-of-springer", "Town of Springer", "Town of Springer", "town",
                  "EPA records the owner as \"SPRINGER, CITY OF\"."),
    "NM0022101": ("nm-village-of-taos-ski-valley", "Village of Taos Ski Valley", "Village of Taos Ski Valley", "town",
                  None),
    "NM0024066": ("nm-town-of-taos", "Town of Taos", "Town of Taos", "town", None),
    "NM0020681": ("nm-city-of-truth-or-consequences", "City of Truth or Consequences", "City of Truth or Consequences",
                  "city", None),
    "NM0020711": ("nm-city-of-tucumcari", "City of Tucumcari", "City of Tucumcari", "city", None),
    "NN0020958": ("nm-bia-wingate-high-school", "Bureau of Indian Affairs, Wingate High School",
                  "Wingate High School", "federal facility",
                  "A Navajo Nation permit (NN...) for a federal school's plant at Fort Wingate."),
    "NM0027731": ("nm-village-of-chama", "Village of Chama", "Village of Chama", "town", None),
    "NM0024848": ("nm-village-of-cuba", "Village of Cuba", "Village of Cuba", "town", None),
    # private candidates and public bodies EPA types private (research/nm/private-utilities-candidates.json)
    "NM0028088": ("nm-nm0028088", "Glorieta Camps Wastewater Treatment Plant (permit NM0028088)",
                  "Glorieta Camps Wastewater Treatment Plant", "facility (permittee not named)",
                  "EPA's permittee name reads as an individual's: not named here; the row names the facility. EPA types "
                  "it privately owned."),
    "NM0029238": ("nm-cds-rainmakers-utilities", "CDS Rainmakers Utilities, LLC", "CDS Rainmakers Utilities",
                  "investor-owned utility", "A sewer utility company (Lincoln County); EPA types it privately owned."),
    "NM0030686": ("nm-rio-puerco-wwtp", "Rio Puerco Wastewater Treatment Plant (Route 66 Casino; a tribal enterprise of "
                  "the Pueblo of Laguna)", "Rio Puerco WWTP (Route 66 Casino)", "tribal",
                  "The applicant in EPA's 2021 fact sheet is Laguna Development Corporation, the Pueblo of Laguna's "
                  "enterprise, and the plant lies on the Pueblo's land at Interstate 40 exit 140, discharging by an "
                  "unnamed arroyo to the Rio Puerco; EPA types it privately owned. Filed as tribal (a tribal "
                  "enterprise)."),
    "NM0031194": ("nm-usbr-cutter-lateral", "U.S. Bureau of Reclamation, Cutter Lateral Water Treatment Plant "
                  "(Navajo-Gallup Water Supply Project)", "Cutter Lateral Water Treatment Plant", "federal facility",
                  "A drinking-water plant of the Navajo-Gallup Water Supply Project (EPA lists a sewage code for it and "
                  "types it privately owned). The permit application names the Bureau of Reclamation (EPA's 2018 fact "
                  "sheet); NMED's 2023 certification notice names the Navajo Tribal Utility Authority, which with the "
                  "Navajo Nation has operated the lateral since June 2024 (Reclamation's project page). Whether the "
                  "permit was reissued to the Authority was not confirmed."),
    "NM0031224": ("nm-tesuque-casino-wwtp", "Tesuque Casino Wastewater Treatment Plant",
                  "Tesuque Casino Wastewater Treatment Plant", "tribal",
                  "EPA's collection-system table types the owner a tribal government (its facility table: privately "
                  "owned); the casino is on the Pueblo of Tesuque's land."),
    "NM0028479": ("nm-jemez-valley-public-schools", "Jemez Valley Public Schools", "Jemez Valley Public Schools",
                  "special district",
                  "A public school district; EPA types the facility privately owned."),
    "NN0030325": ("nm-ramah-navajo-school-board", "Ramah Navajo School Board, Inc. (Pine Hill school plant)",
                  "Ramah Navajo School Board", "institution",
                  "A non-profit corporation that runs the Pine Hill school; a Navajo Nation permit (NN...). EPA types "
                  "it privately owned; its name reads as a public body, but the permittee is the corporation."),
}
PUBLIC_FORMS = {"city", "town", "county", "authority", "special district", "federal facility", "state facility",
                "tribal"}
PRIVATE_FORMS = {"investor-owned utility", "member-owned utility", "homeowners' association", "mobile-home park",
                 "campground or resort", "private club", "business or industrial", "institution",
                 "facility (permittee not named)"}
ABBR = {"wwtp", "wrf", "wwtf", "stp", "nm", "ii", "bie", "bia"}


def smart_title(s: str) -> str:
    out = []
    for w in (s or "").split():
        bare = re.sub(r"[^A-Za-z0-9]", "", w).lower()
        out.append(w.upper() if bare in ABBR else (w.title() if w.isupper() or w.islower() else w))
    return re.sub(r"(?<=\w )\b(Of|And|The|De|Del|La)\b", lambda m: m.group(1).lower(), " ".join(out))


def region(permits: list[str]) -> str:
    return "Region 9, for the Navajo Nation" if any(p.startswith("NN") for p in permits) else "Region 6"


def plants() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for r in json.loads(PLANTS.read_text())["outfalls"]:
        if r.get("state") == "NM" and r.get("npdes_permit"):
            out[r["npdes_permit"].upper()].append(r)
    return out


def placed_nm(r: dict) -> bool:
    return (r.get("state") or (r.get("raw") or {}).get("state") or (r.get("npdes_permit") or r.get("permit"))[:2]) == "NM"


def epa_reports() -> tuple[Counter, Counter]:
    """(permit -> reports placed in New Mexico, permit -> those kept as reaching a water)."""
    allr, kept = Counter(), Counter()
    for r in json.loads(EVENTS.read_text()).get("records", []):
        if placed_nm(r):
            kept[r["npdes_permit"]] += 1
            allr[r["npdes_permit"]] += 1
    for r in json.loads(DROPPED.read_text()).get("dropped", []):
        if placed_nm(r):
            allr[r["permit"]] += 1
    return allr, kept


def collection_systems() -> set[str]:
    sys.path.insert(0, str(ROOT / "pipeline"))
    from ingest import echo_sewer_overflow_events as E
    tables, _ = E.read_zip(ZIP)
    return {s["permit_identifier"] for s in tables.get("systems", [])}


def row(rid, m, permits, towns, waters, notes, kind, outfalls, research_ids):
    tribal = m["lf"] == "tribal" or any(p.startswith("NN") for p in permits)
    private = m["lf"] in PRIVATE_FORMS
    return {"id": rid, "name": m["name"], "short_name": m["short"] or m["name"], "legal_form": m["lf"], "state": "NM",
            "kind": kind, "npdes_permit": permits[0], "npdes_permits": list(permits),
            "receiving_waters": waters, "water_slugs": [], "outfall_count": outfalls or None,
            "outfalls_source": (f"EPA ICIS-NPDES discharge points (data/outfalls-plants-us.json, {outfalls} rows)"
                                if outfalls else None),
            "notification_channel": (TRIBAL.format(region=region(permits)) if tribal
                                     else LAW + (PRIVATE_NOTE if private else "") + OWN),
            "notification_feed_machine_readable": True, "notification_signup_url": None,
            "towns": towns, "notes": notes, "verified": "fetched", "checked": CHECKED,
            "aliases": list(dict.fromkeys([rid] + research_ids)), "source_areas": ["nm"]}


def build(dis: list[dict]) -> tuple[list[dict], dict]:
    missing = [str(p.relative_to(ROOT)) for p in (EVENTS, DROPPED, ZIP) if not p.exists()]
    if missing:   # git-ignored inputs: without them every row would turn "plant" and lose its report counts
        raise SystemExit("run pipeline/ingest/echo_sewer_overflow_events.py first (with the all-versions ZIP saved at "
                         "data/raw/echo-nm/all.zip); missing: " + ", ".join(missing))
    keep = [d for d in dis if not (d.get("state") == "NM" and "nm" in (d.get("source_areas") or []))]
    held_elsewhere = {str(p).upper() for d in keep for p in [d.get("npdes_permit"), *(d.get("npdes_permits") or [])] if p}
    pl = plants()
    research: dict[str, list[dict]] = defaultdict(list)
    for r in json.loads(RESEARCH.read_text()):
        research[r["npdes_permit"]].append(r)
    cand = json.loads(CANDIDATES.read_text())
    cands = {c["npdes_permit"]: c for c in cand["candidates"] + cand["public_by_name"]}
    allr, kept = epa_reports()
    systems = collection_systems()
    nm_systems = {p for p in systems if p.startswith("NM") or (p.startswith("NN") and p in pl) or p in cands}
    permits = sorted((set(pl) | set(research) | set(cands) | set(allr) | nm_systems) - held_elsewhere)
    unknown = [p for p in permits if p not in OWNERS]
    if unknown:
        raise SystemExit(f"permits without an owner in OWNERS: {unknown}")
    clash = sorted(p for p in OWNERS if p in held_elsewhere)
    if clash:
        raise SystemExit(f"permits already held by another row: {clash}")
    meta: dict[str, dict] = {}
    by_row: dict[str, list[str]] = defaultdict(list)
    for p in permits:
        rid, name, short, lf, note = OWNERS[p]
        if name:
            meta[rid] = {"name": name, "short": short, "lf": lf, "note": note}
        by_row[rid].append(p)
    new = []
    for rid, ps in by_row.items():
        m = meta[rid]
        rows = [r for p in ps for r in pl.get(p, [])]
        cities = {smart_title(r["city"]) for r in rows if r.get("city") and r["city"].upper() != "UNKNOWN"}
        cities |= {smart_title(cands[p]["city"]) for p in ps if p in cands and cands[p].get("city")}
        cities = {c for c in cities if not c.lower().endswith(" county")} or cities
        own = re.match(r"^(?:City|Town|Village) of (.+?)(?: \(| -|$)", m["name"])
        if own:
            cities.add(own.group(1))
        towns = sorted(cities)[:1] if m["lf"] == "facility (permittee not named)" else sorted(cities)
        waters = list(dict.fromkeys([r["receiving_water_echo"].strip() for r in rows if r.get("receiving_water_echo")]
                                    + [w for p in ps if p in cands for w in cands[p].get("receiving_waters_echo") or []]))[:8]
        facs = "; ".join(f"{p} {smart_title((pl.get(p) or [{}])[0].get('permittee') or (cands.get(p) or {}).get('facility') or '')}".strip()
                         for p in ps)
        note = (f"EPA ICIS-NPDES: {facs}." if m["lf"] != "facility (permittee not named)"
                else f"EPA ICIS-NPDES: permit {ps[0]}.")
        reports = sum(allr[p] for p in ps)
        if reports:
            note += (f" EPA's overflow tables (2026-11-04 extract): {reports} report(s) placed in New Mexico, "
                     f"{sum(kept[p] for p in ps)} with evidence the discharge reached a water.")
        else:
            note += " No report under these permits is in EPA's overflow tables (2026-11-04 extract)."
        if m.get("note"):
            note += " " + m["note"]
        rids = [r["id"] for p in ps for r in research.get(p, [])]
        kind = "sso" if any(allr[p] or p in systems for p in ps) else "plant"
        new.append(row(rid, m, ps, towns, waters, note.strip(), kind, len(rows), rids))
    new.sort(key=lambda r: r["id"])
    ids = Counter(r["id"] for r in keep + new)
    dup = [i for i, n in ids.items() if n > 1]
    if dup:
        raise SystemExit(f"duplicate ids: {dup}")
    stats = {"rows": len(new), "permits": sum(len(r["npdes_permits"]) for r in new),
             "permits_with_reports": sorted(p for p in permits if allr[p]),
             "held_elsewhere": sorted(p for p in (set(allr) | set(pl)) if p in held_elsewhere),
             "legal_form": dict(Counter(r.get("legal_form") for r in new)), "kind": dict(Counter(r["kind"] for r in new)),
             "private": sorted(r["id"] for r in new if r.get("legal_form") in PRIVATE_FORMS)}
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
