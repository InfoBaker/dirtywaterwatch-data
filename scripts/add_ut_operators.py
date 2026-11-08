"""Utah operator rows for data/dischargers.json: one row per operator, every Utah permit in exactly one row.

Usage (with EPA's all-versions overflow ZIP saved at data/raw/ut-epa-sobe/all.zip, and after
pipeline/ingest/echo_sewer_overflow_events.py has written its events file):
    pipeline/.venv/bin/python -I scripts/add_ut_operators.py [--dry-run]

Inputs
  1. data/outfalls-plants-us.json: EPA ICIS-NPDES's sewage permits with state UT (93: 74 UPDES individual permits UT...,
     8 land-application permits UTL... held by the same districts and cities, 9 general-permit coverages UTG... (six
     lagoons of the Ute Indian Tribe, three construction dewatering coverages at sewer projects), White Mesa's lagoons
     (COG587102) and two Navajo Nation permits NN...).
  2. EPA's collection-system table (collection_system_permit.csv in the saved ZIP): 188 Utah permits, 126 of them
     coverages under Utah's general permit for sewer collection systems (UTG58....) that hold no treatment plant. Each
     gets a row; its owner is read from EPA's system name and owner type (collection_owner()).
  3. research/ut/dischargers.json (36 rows, the major permits): each research id stays as an alias of the row that holds
     its permit, so the overflow module's discharger_id (the research id) resolves (common.discharger_alias_map).
  4. research/ut/private-utilities-candidates.json (3 private permits with a sewage code: an oil-field lease on the
     Navajo Nation, a steel plant's treatment unit, a coal mine).
Rules
  - OWNERS gives every plant permit its row: the owner's name as the body calls itself (EPA's spelling in the notes
    where it differs), legal_form from the controlled list (docs/legal-forms.md), never an individual's name. Utah's
    special service districts, improvement districts, sewer districts and county service areas are local districts
    (Utah Code Title 17B and 17D): "special district". The water reclamation boards that cities and districts run
    together (Central Valley, South Valley) are interlocal entities: "authority". An owner that was not read keeps
    legal_form null.
  - kind: "sso" when a permit of the row has a collection system in EPA's table or a report in EPA's overflow tables;
    otherwise "plant".
  - notification_channel: R317-801-4 (Class 1 overflows to DWQ by telephone within 24 hours, in writing within five
    days; DWQ publishes no list), where a few become public (DEQ's spill hotline log, EPA's tables), and that no duty to
    tell the public was found. Tribal permits (NN..., COG..., the Ute Indian Tribe's UTG5894..): EPA Region 8's
    channel. notification_signup_url null: no overflow alert list was found; operators' own pages were not searched one
    by one (research/ut/report.md section 2.3).
  - Idempotent: a rerun replaces the rows it wrote (state UT, source_areas ["ut"]) and leaves every other row as it
    is; new rows go after the last row of the file.
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
RESEARCH = ROOT / "research" / "ut" / "dischargers.json"
CANDIDATES = ROOT / "research" / "ut" / "private-utilities-candidates.json"
EVENTS = ROOT / "data" / "build" / "events" / "echo-sewer-overflow.json"
ZIP = ROOT / "data" / "raw" / "ut-epa-sobe" / "all.zip"
CHECKED = "2026-11-07"
ECHO = "https://echo.epa.gov/tools/data-downloads/sewer-overflow-download-summary"
LAW = ("Utah Admin. Code R317-801-4: a Class 1 sanitary sewer overflow (one that reaches waters of the state, exceeds "
       "5,000 gallons, affects more than five private structures or any public, commercial or industrial building, or "
       "may be a risk to public health; R317-801-1(13)) is reported to the Division of Water Quality orally within 24 "
       "hours and in writing within five calendar days; Class 2 overflows go only in the annual sewer management report. "
       "DWQ publishes no list of the reports. An overflow becomes public when someone also calls DEQ's spill hotline (the "
       "Environmental Incidents layer) or the permittee files it electronically with EPA (its overflow tables, "
       f"{ECHO}). No duty to tell the public was found.")
TRIBAL = ("A permit on tribal land, where EPA Region 8 administers the Clean Water Act permit program and Utah's rule "
          "does not apply: the permit's 24-hour and five-day noncompliance reports go to EPA (40 CFR 122.41(l)(6)), "
          f"which publishes those filed electronically in its overflow tables ({ECHO}). No public notice duty was found.")
PRIVATE_NOTE = " The rule and the permit bind a private permittee as they bind a public one."
OWN = " The operator's own pages were not searched individually."
SD = "special district"

# permit -> (row id, name, short name, legal form, note); a row's name, short name and form are given once
OWNERS = {
    "UT0020001": ("ut-snyderville-basin-wrd", "Snyderville Basin Water Reclamation District",
                  "Snyderville Basin Water Reclamation District", SD,
                  "East Canyon and Silver Creek plants (Park City area)."),
    "UT0024414": ("ut-snyderville-basin-wrd", None, None, None, None),
    "UTL020001": ("ut-snyderville-basin-wrd", None, None, None, None),
    "UT0020052": ("ut-castle-valley-ssd", "Castle Valley Special Service District", "Castle Valley SSD", SD,
                  "The Ferron, Huntington and Castle Dale plants and the Elmo, Emery, Cleveland and Clawson collection "
                  "systems (Emery County). EPA records Ferron's plant permittee as \"FERRON- CITY OF\"; its collection-"
                  "system table names the district."),
    "UT0021296": ("ut-castle-valley-ssd", None, None, None, None),
    "UT0023663": ("ut-castle-valley-ssd", None, None, None, None),
    "UT0020061": ("ut-oakley-city", "Oakley City", "Oakley City", "city", None),
    "UT0020095": ("ut-duchesne-city", "Duchesne City", "Duchesne City", "city",
                  "EPA's collection-system table gives this permit the name \"Spanish Fork City SSCS\" and Spanish "
                  "Fork's permit (UT0020109) the name \"Duchesne City WWTF SSCS\": the two names are swapped there."),
    "UT0020109": ("ut-spanish-fork-city", "Spanish Fork City", "Spanish Fork City", "city", None),
    "UT0020192": ("ut-henefer-town", "Henefer Town", "Henefer Town", "town", None),
    "UT0020214": ("ut-lewiston-city", "Lewiston City", "Lewiston City", "city", None),
    "UT0020222": ("ut-moroni-plant", "Moroni wastewater treatment plant (permittee as EPA records it: Pitman Family "
                  "Farms, Inc.)", "Moroni wastewater treatment plant", "business or industrial",
                  "EPA names the facility \"MORONI CITY WASTE WATER TREATMENT PLANT\" and the permittee Pitman Family "
                  "Farms, Inc., a poultry company; the plant treats the town's sewage and the processing plant's "
                  "wastewater. Filed under the permittee EPA records; the permit documents were not read."),
    "UT0020231": ("ut-lake-point-id", "Lake Point Improvement District", "Lake Point Improvement District", SD, None),
    "UT0020303": ("ut-tremonton-city", "Tremonton City", "Tremonton City", "city", None),
    "UT0020311": ("ut-bear-river-city", "Bear River City", "Bear River City", "city",
                  "EPA records the owner as \"BEAR RIVER- TOWN OF\"."),
    "UT0020338": ("ut-usbr-flaming-gorge-dam", "U.S. Bureau of Reclamation, Flaming Gorge Dam",
                  "Flaming Gorge Dam", "federal facility", None),
    "UT0020371": ("ut-wellsville-city", "Wellsville City", "Wellsville City", "city", None),
    "UT0020419": ("ut-moab-city", "City of Moab", "City of Moab", "city", None),
    "UTL020419": ("ut-moab-city", None, None, None, None),
    "UT0020427": ("ut-payson-city", "Payson City", "Payson City", "city", None),
    "UT0020834": ("ut-springville-city", "Springville City", "Springville City", "city", None),
    "UT0020893": ("ut-morgan-city", "Morgan City", "Morgan City", "city", None),
    "UT0020907": ("ut-richmond-city", "Richmond City", "Richmond City", "city", None),
    "UT0020915": ("ut-orem-city", "Orem City", "Orem City", "city", None),
    "UT0020931": ("ut-corinne-city", "Corinne City", "Corinne City", "city", None),
    "UT0020966": ("ut-kamas-city", "Kamas City", "Kamas City", "city", None),
    "UT0020974": ("ut-central-davis-sewer-district", "Central Davis Sewer District", "Central Davis Sewer District", SD,
                  None),
    "UT0021130": ("ut-grantsville-city", "Grantsville City", "Grantsville City", "city", None),
    "UT0021148": ("ut-perry-city", "Perry City", "Perry City", "city",
                  "Perry's former plant permit (UT0021148, expired), the Perry/Willard Regional Water Reclamation "
                  "Facility (UT0025721) and the city's collection system."),
    "UT0025721": ("ut-perry-city", None, None, None, None),
    "UT0021288": ("ut-coalville-city", "Coalville City", "Coalville City", "city", None),
    "UT0025976": ("ut-coalville-city", None, None, None, None),
    "UT0021326": ("ut-plain-city", "Plain City", "Plain City", "city", None),
    "UT0021440": ("ut-magna-water-district", "Magna Water District", "Magna Water District", SD,
                  "EPA records the owner as \"MAGNA WATER & SEWER DIST\"."),
    "UT0021628": ("ut-south-davis-sewer-district", "South Davis Sewer District", "South Davis Sewer District", SD,
                  "South and North plants."),
    "UT0021636": ("ut-south-davis-sewer-district", None, None, None, None),
    "UTL021636": ("ut-south-davis-sewer-district", None, None, None, None),
    "UT0021717": ("ut-provo-city", "Provo City", "Provo City", "city", None),
    "UT0021725": ("ut-salt-lake-city", "Salt Lake City Department of Public Utilities (Water Reclamation Facility)",
                  "Salt Lake City", "city", None),
    "UT0021741": ("ut-north-davis-sewer-district", "North Davis Sewer District", "North Davis Sewer District", SD,
                  None),
    "UT0021814": ("ut-price-river-wid", "Price River Water Improvement District", "Price River WID", SD, None),
    "UTL021814": ("ut-price-river-wid", None, None, None, None),
    "UT0021911": ("ut-central-weber-sid", "Central Weber Sewer Improvement District",
                  "Central Weber Sewer Improvement District", SD, None),
    "UT0021920": ("ut-logan-city", "Logan City", "Logan City", "city", None),
    "UT0022365": ("ut-brigham-city", "Brigham City", "Brigham City", "city", None),
    "UTL022365": ("ut-brigham-city", None, None, None, None),
    "UT0023001": ("ut-neola-water-and-sewer-district", "Neola Water and Sewer District",
                  "Neola Water and Sewer District", SD,
                  "EPA records the owner as \"NEOLA TOWN WATER AND SEWER ASSOC\"; its collection-system table names "
                  "the district."),
    "UT0023205": ("ut-hyrum-city", "Hyrum City", "Hyrum City", "city", None),
    "UT0023639": ("ut-timpanogos-ssd", "Timpanogos Special Service District", "Timpanogos SSD", SD,
                  "EPA records the owner as \"TIMPANOGOS SANITARY SEWER DISTRICT\" (American Fork)."),
    "UTL023639": ("ut-timpanogos-ssd", None, None, None, None),
    "UT0024384": ("ut-south-valley-wrf", "South Valley Water Reclamation Facility", "South Valley WRF", "authority",
                  "The plant the cities and districts of the southern Salt Lake Valley run together (West Jordan)."),
    "UT0024392": ("ut-central-valley-wrf", "Central Valley Water Reclamation Facility",
                  "Central Valley Water Reclamation Facility", "authority",
                  "The plant the Salt Lake Valley's sewer districts and cities run together (South Salt Lake)."),
    "UT0024503": ("ut-monticello-city", "Monticello City", "Monticello City", "city", None),
    "UT0024601": ("ut-eureka-city", "Eureka City", "Eureka City", "city", None),
    "UT0024686": ("ut-st-george-city", "City of St. George", "City of St. George", "city", None),
    "UTL024686": ("ut-st-george-city", None, None, None, None),
    "UT0024732": ("ut-mountain-green-sid", "Mountain Green Sewer Improvement District",
                  "Mountain Green Sewer Improvement District", SD, None),
    "UT0024970": ("ut-cedar-city", "Cedar City", "Cedar City", "city", None),
    "UT0025216": ("ut-spring-city", "Spring City", "Spring City", "city", None),
    "UT0025224": ("ut-springdale-town", "Town of Springdale", "Town of Springdale", "town", None),
    "UT0025241": ("ut-stansbury-park-id", "Stansbury Park Improvement District", "Stansbury Park Improvement District",
                  SD, None),
    "UT0025291": ("ut-salina-city", "Salina City", "Salina City", "city", None),
    "UT0025330": ("ut-enterprise-city", "Enterprise City", "Enterprise City", "city", None),
    "UT0025348": ("ut-ashley-valley-wrf", "Ashley Valley Water Reclamation Facility",
                  "Ashley Valley Water Reclamation Facility", None,
                  "The Vernal area's plant; EPA records it as \"ASHLEY VALLEY WATER REC. FACIL\". The owner was not "
                  "read."),
    "UT0025445": ("ut-tooele-city", "Tooele City", "Tooele City", "city", None),
    "UTL022217": ("ut-tooele-city", None, None, None, None),
    "UT0025542": ("ut-fairview-city", "Fairview City", "Fairview City", "city", None),
    "UT0025569": ("ut-little-mountain-service-area", "Little Mountain Service Area", "Little Mountain Service Area", SD,
                  "A Weber County service area (west of Ogden)."),
    "UT0025747": ("ut-jordanelle-ssd", "Jordanelle Special Service District", "Jordanelle SSD", SD, None),
    "UT0025771": ("ut-green-river-city", "Green River City", "Green River City", "city",
                  "EPA records the permittee as \"Green River Wastewater Treatment Plant\"."),
    "UT0025828": ("ut-arches-ssd", "Arches Special Service District", "Arches SSD", SD,
                  "The Courthouse Wash plant (Moab)."),
    "UT0025852": ("ut-jordan-basin-id", "Jordan Basin Improvement District", "Jordan Basin Improvement District", SD,
                  None),
    "UT0025950": ("ut-mona-city", "Mona City", "Mona City", "city",
                  "EPA records the permittee as \"Mona Wastewater Treatment Plant\"."),
    "UT0025984": ("ut-ephraim-city", "Ephraim City", "Ephraim City", "city", None),
    "UT0026000": ("ut-santaquin-city", "Santaquin City", "Santaquin City", "city",
                  "EPA records the permittee as \"Santaquin Water Reclamation Facility\"."),
    "UT0026026": ("ut-manti-city", "Manti City", "Manti City", "city", None),
    "UT0026034": ("ut-garland-city", "Garland City", "Garland City", "city", None),
    "UT0026085": ("ut-salem-city", "Salem City", "Salem City", "city", None),
    "UT0026158": ("ut-parowan-city", "Parowan City", "Parowan City", "city", None),
    "UT0026204": ("ut-kane-springs-id", "Kane Springs Improvement District", "Kane Springs Improvement District", SD,
                  None),
    "UT0026301": ("ut-ash-creek-ssd", "Ash Creek Special Service District", "Ash Creek SSD", SD,
                  "The Confluence Park plant (La Verkin) and the district's collection system."),
    "UTG071774": ("ut-alder-construction", "Alder Construction", "Alder Construction", "business or industrial",
                  "A construction dewatering coverage (general permit UTG07) at the Payson wastewater plant's project; "
                  "not a sewer operator."),
    "UTG072162": ("ut-whitaker-construction", "Whitaker Construction Co., Inc.", "Whitaker Construction",
                  "business or industrial",
                  "A construction dewatering coverage (general permit UTG07) at a sewer reroute in Provo; not a sewer "
                  "operator."),
    "UTG072174": ("ut-fx-construction", "FX Construction", "FX Construction", "business or industrial",
                  "A construction dewatering coverage (general permit UTG07) at a sewer lift station project; not a "
                  "sewer operator."),
    "UTG589401": ("ut-ute-indian-tribe", "Ute Indian Tribe of the Uintah and Ouray Reservation (Environmental Health "
                  "and Sanitation)", "Ute Indian Tribe", "tribal",
                  "The Fort Duchesne plant and the Yellowstone, Sunshine, Hilltop, Whiterocks and Randlett lagoons, "
                  "under EPA's general permit for lagoons on tribal land (UTG5894..)."),
    "UTG589402": ("ut-ute-indian-tribe", None, None, None, None),
    "UTG589403": ("ut-ute-indian-tribe", None, None, None, None),
    "UTG589404": ("ut-ute-indian-tribe", None, None, None, None),
    "UTG589405": ("ut-ute-indian-tribe", None, None, None, None),
    "UTG589406": ("ut-ute-indian-tribe", None, None, None, None),
    "COG587102": ("ut-white-mesa-lagoons", "White Mesa Lagoons (Ute Mountain Ute Tribe)", "White Mesa Lagoons",
                  "tribal",
                  "A Colorado general-permit coverage (COG58) EPA issues for the Ute Mountain Ute Tribe's White Mesa "
                  "community in San Juan County, Utah."),
    "NN0025178": ("ut-goulding-lodge-wwtf", "Navajo Nation Hospitality Enterprise (Monument Valley lodge plant)",
                  "Navajo Nation Hospitality Enterprise", "tribal",
                  "A Navajo Nation permit (NN...) for a lodge's plant at Monument Valley; EPA types the owner a "
                  "tribal government."),
    "NN0020133": ("ut-boundary-butte-lease", "Boundary Butte oil lease plant (Navajo Nation permit NN0020133)",
                  "Boundary Butte lease plant", "business or industrial",
                  "An oil-field lease's sewage system on the Navajo Nation (San Juan County); EPA types it privately "
                  "owned. The facility's name as EPA records it is not used."),
    "UT0000361": ("ut-us-steel-treatment-unit", "U.S. Steel Corporation (treatment unit, Vineyard)",
                  "U.S. Steel treatment unit", "business or industrial",
                  "An industrial permit with a sewage code at the former Geneva works; EPA types it privately owned."),
    "UT0026018": ("ut-lila-canyon-mine", "Lila Canyon Mine", "Lila Canyon Mine", "business or industrial",
                  "A coal mine's permit with a sewage code (Emery County); EPA types it privately owned."),
}
# collection-system permits that belong to a plant permit's operator (read from EPA's system names, 2026-11-07)
JOIN = {"UTG580065": "UT0021148", "UTG580120": "UT0024503", "UTG580204": "UT0025291", "UTG580168": "UT0025216",
        "UTG580047": "UT0026301", "UTG580130": "UT0020052", "UTG580131": "UT0020052", "UTG580133": "UT0020052",
        "UTG580155": "UT0020052"}
# collection-system owners whose name or form EPA's table does not give plainly
HAND = {
    "UTG580024": ("Town of Alta", "town", None),
    "UTG580092": ("Manila Town", "town", None),
    "UTG580134": ("Vineyard City", "city", "EPA's table names it \"Vineyard Town\"."),
    "UTG580162": ("Ruby's Inn", "campground or resort",
                  "A resort's collection system near Bryce Canyon; EPA's table types the owner a municipality."),
    "UTG580201": ("Cloaca Maxima Treatment and Collection (Canyon Lands)", None,
                  "EPA's table types the owner a water district; the owner was not read."),
    "UTG580148": ("Columbia (Carbon County)", None, "An unincorporated town; the owner was not read."),
    "UTG580205": ("Woodland (collection system)", None,
                  "EPA's table types the owner a municipality; which Woodland was not read."),
    "UTG580143": ("National Park Service (permit UTG580143)", "federal facility",
                  "EPA's table names the system only \"National Park Service SSCS\"."),
    "UTG580159": ("National Park Service, Glen Canyon National Recreation Area (Halls Crossing)", "federal facility",
                  None),
    "UTG580160": ("National Park Service, Glen Canyon National Recreation Area (Hite Marina)", "federal facility", None),
    "UTG580170": ("U.S. Army, Deseret Chemical Depot", "federal facility", None),
    "UTG580208": ("U.S. Air Force, Hill Air Force Base", "federal facility", None),
    "UTG580042": ("National Park Service, Dinosaur National Monument", "federal facility", None),
    "UTG580112": ("National Park Service, Bryce Canyon National Park", "federal facility", None),
    "UTG580126": ("National Park Service, Capitol Reef National Park", "federal facility", None),
    "UTG580150": ("National Park Service, Zion National Park", "federal facility", None),
    "UTG580100": ("Daggett County", "county", None),
    "UTG580203": ("Kane County Water Conservancy District", SD, None),
    "UTG580026": ("Salt Lake County Service Area No. 3", SD, "A county service area (Snowbird and Alta area)."),
    "UTG580209": ("Powder Mountain Water and Sewer Improvement District", SD, None),
    "UTG580114": ("Price City", "city", "EPA's table names it \"Price Muncipal Corp\"."),
    "UTG580172": ("Altamont Town", "town", None),
    "UTG580207": ("Elwood Town", "town", None),
    "UTG580043": ("Mantua Town", "town", None),
    "UTG580015": ("City of South Salt Lake", "city", None),
}
ABBREV = [(r"\bDist\b|\bDistict\b", "District"), (r"\bImprov\b|\bImpr\b|\bImp\b", "Improvement"), (r"\bWtr\b", "Water"),
          (r"\bSpec Serv\b", "Special Service"), (r"\bSSD\b", "Special Service District"), (r"\bMt\b", "Mount"),
          (r"\s*&\s*", " and ")]
PUBLIC_FORMS = {"city", "town", "county", "authority", "special district", "federal facility", "state facility",
                "tribal"}
PRIVATE_FORMS = {"investor-owned utility", "member-owned utility", "homeowners' association", "mobile-home park",
                 "campground or resort", "private club", "business or industrial", "institution",
                 "facility (permittee not named)"}
TRIBAL_PERMITS = re.compile(r"^(NN|COG|UTG5894)")


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower().replace("'", "")).strip("-")


def smart_title(s: str) -> str:
    return " ".join(w.title() if w.isupper() or w.islower() else w for w in (s or "").split())


def collection_owner(p: str, sysrow: dict) -> tuple[str, str | None, str | None]:
    """(owner name, legal form, note) of a collection-system-only permit from EPA's system name and owner type."""
    if p in HAND:
        return HAND[p]
    n = re.sub(r"\s+SSCS\s*$", "", sysrow["collection_system_name"].strip())
    n = re.sub(r"\s+(?:Corp(?:oration)?|Inc)\b\.?", "", n)
    for pat, rep in ABBREV:
        n = re.sub(pat, rep, n)
    n = re.sub(r"\s+", " ", n).strip()
    kind = sysrow.get("collection_system_owner_type_desc") or ""
    if kind.startswith("Water District"):
        return n, SD, None
    if kind.startswith("County"):
        return n, "county", None
    if kind.startswith("Federal"):
        return n, "federal facility", None
    if re.search(r"\bTown\b", n):
        return n, "town", None
    if not re.search(r"\bCity\b", n):
        n = f"{n} City"
    return n, "city", None


def plants() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for r in json.loads(PLANTS.read_text())["outfalls"]:
        if r.get("state") == "UT" and r.get("npdes_permit"):
            out[r["npdes_permit"].upper()].append(r)
    return out


def systems() -> dict[str, dict]:
    sys.path.insert(0, str(ROOT / "pipeline"))
    from ingest import echo_sewer_overflow_events as E
    tables, _ = E.read_zip(ZIP)
    return {s["permit_identifier"]: s for s in tables.get("systems", []) if s["permit_identifier"].startswith("UT")}


def epa_reports() -> Counter:
    n = Counter()
    for r in json.loads(EVENTS.read_text()).get("records", []):
        if str(r.get("npdes_permit") or "").startswith("UT"):
            n[r["npdes_permit"]] += 1
    return n


def build(dis: list[dict]) -> tuple[list[dict], dict]:
    missing = [str(p.relative_to(ROOT)) for p in (EVENTS, ZIP) if not p.exists()]
    if missing:
        raise SystemExit("save EPA's all-versions ZIP at data/raw/ut-epa-sobe/all.zip and run "
                         "pipeline/ingest/echo_sewer_overflow_events.py first; missing: " + ", ".join(missing))
    keep = [d for d in dis if not (d.get("state") == "UT" and "ut" in (d.get("source_areas") or []))]
    held_elsewhere = {str(p).upper() for d in keep for p in [d.get("npdes_permit"), *(d.get("npdes_permits") or [])] if p}
    pl = plants()
    sy = systems()
    research: dict[str, list[dict]] = defaultdict(list)
    for r in json.loads(RESEARCH.read_text()):
        research[r["npdes_permit"]].append(r)
    cand = json.loads(CANDIDATES.read_text())
    cands = {c["npdes_permit"]: c for c in cand["candidates"] + cand.get("public_by_name", [])}
    reports = epa_reports()
    owners = dict(OWNERS)
    for p, s in sy.items():
        if p in owners:
            continue
        if p in JOIN:
            owners[p] = (owners[JOIN[p]][0], None, None, None, None)
            continue
        name, lf, note = collection_owner(p, s)
        owners[p] = ("ut-" + slug(name), name, name, lf, note)
    permits = sorted((set(pl) | set(research) | set(cands) | set(sy) | set(reports)) - held_elsewhere)
    unknown = [p for p in permits if p not in owners]
    if unknown:
        raise SystemExit(f"permits without an owner: {unknown}")
    meta: dict[str, dict] = {}
    by_row: dict[str, list[str]] = defaultdict(list)
    for p in permits:
        rid, name, short, lf, note = owners[p]
        if name:
            if rid in meta:
                raise SystemExit(f"two owners named for {rid}")
            meta[rid] = {"name": name, "short": short, "lf": lf, "note": note}
        by_row[rid].append(p)
    new = []
    for rid, ps in by_row.items():
        m = meta[rid]
        rows = [r for p in ps for r in pl.get(p, [])]
        towns = sorted({smart_title(r["city"]) for r in rows if r.get("city") and r["city"].upper() != "UNKNOWN"
                        and not r["city"].upper().endswith("COUNTY")})
        own = re.match(r"^(?:City of |Town of )?(.+?) (?:City|Town)$", m["name"]) or \
            re.match(r"^(?:City|Town) of (.+?)$", m["name"])
        if own and m["lf"] in ("city", "town"):
            towns = sorted(set(towns) | {own.group(1).replace("St.", "St.")})
        waters = list(dict.fromkeys(r["receiving_water_echo"].strip() for r in rows if r.get("receiving_water_echo")))[:8]
        parts = []
        if rows:
            facs = "; ".join(f"{p} {smart_title((pl.get(p) or [{}])[0].get('permittee') or '')}".strip()
                             for p in ps if p in pl)
            parts.append(f"EPA ICIS-NPDES: {facs}.")
        sys_ps = [p for p in ps if p in sy]
        if sys_ps:
            parts.append("EPA's collection-system table: " + "; ".join(
                f"{p} {sy[p]['collection_system_name'].strip()} ({sy[p]['collection_system_owner_type_desc']})"
                for p in sys_ps) + ".")
        n = sum(reports[p] for p in ps)
        if n:
            parts.append(f"EPA's overflow tables (2026-11-04 extract): {n} report(s).")
        elif sys_ps:
            parts.append("No report under these permits is in EPA's overflow tables (2026-11-04 extract).")
        if m.get("note"):
            parts.append(m["note"])
        tribal = m["lf"] == "tribal" or any(TRIBAL_PERMITS.match(p) for p in ps)
        private = m["lf"] in PRIVATE_FORMS
        rids = list(dict.fromkeys(r["id"] for p in ps for r in research.get(p, [])))
        kind = "sso" if any(p in sy or reports[p] for p in ps) else "plant"
        new.append({"id": rid, "name": m["name"], "short_name": m["short"] or m["name"], "legal_form": m["lf"],
                    "state": "UT", "kind": kind, "npdes_permit": ps[0], "npdes_permits": list(ps),
                    "receiving_waters": waters, "water_slugs": [], "outfall_count": len(rows) or None,
                    "outfalls_source": (f"EPA ICIS-NPDES discharge points (data/outfalls-plants-us.json, {len(rows)} rows)"
                                        if rows else None),
                    "notification_channel": TRIBAL if tribal else LAW + (PRIVATE_NOTE if private else "") + OWN,
                    "notification_feed_machine_readable": True, "notification_signup_url": None,
                    "towns": towns, "notes": " ".join(parts).strip(), "verified": "fetched", "checked": CHECKED,
                    "aliases": list(dict.fromkeys([rid] + rids)), "source_areas": ["ut"]})
    new.sort(key=lambda r: r["id"])
    ids = Counter(r["id"] for r in keep + new)
    dup = [i for i, k in ids.items() if k > 1]
    if dup:
        raise SystemExit(f"duplicate ids: {dup}")
    stats = {"rows": len(new), "permits": sum(len(r["npdes_permits"]) for r in new),
             "collection_only_rows": sum(1 for r in new if not r["outfall_count"]),
             "permits_with_reports": sorted(p for p in permits if reports[p]),
             "held_elsewhere": sorted(p for p in (set(pl) | set(sy)) if p in held_elsewhere),
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
