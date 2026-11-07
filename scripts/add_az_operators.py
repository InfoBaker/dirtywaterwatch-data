"""Arizona operator rows for data/dischargers.json: one row per operator, every Arizona permit in exactly one row.

Usage (after pipeline/ingest/echo_sewer_overflow_events.py has written its events file, for the report counts):
    pipeline/.venv/bin/python -I scripts/add_az_operators.py [--dry-run]

Inputs
  1. data/outfalls-plants-us.json: EPA's ICIS-NPDES permits with state AZ (133: AZPDES plant permits, the construction
     (AZC...), de minimis (AZDM/AZMS...), pretreatment (AZPT...) and MS4 (AZS...) coverages EPA lists with them, and six
     Navajo Nation permits NN...). permit_name is the owner as EPA records it.
  2. research/az/dischargers.json (75 rows): the 42 permits with reports in EPA's overflow tables and the major permits.
     Each research id stays as an alias of the row that holds its permit, so the overflow module's discharger_id
     (the research id) resolves (common.discharger_alias_map).
  3. The Arizona permits in EPA's overflow tables (data/build/events/echo-sewer-overflow.json and the dropped file) and
     its collection-system table (the saved ZIP when present): a permit no other input names is named by hand (HAND).
  4. research/az/private-utilities-candidates.json (20 private sewage permits, 4 public bodies EPA types private):
     grouped by permittee as EPA ICIS-NPDES records it (ADEQ's permit documents were not read; azdeq.gov refuses
     scripted requests), legal_form from the controlled list (docs/legal-forms.md) by permittee (PRIVATE), never an
     individual's name: the two permits whose permittee the candidates file removed are filed under the facility, or
     under the place where the facility's name was removed too, with legal_form "facility (permittee not named)".
Rules
  - GROUPS joins one owner's permits (Phoenix's four plants and its construction, pretreatment and MS4 coverages are one
    row, City of Phoenix). A construction coverage EPA lists at a plant, held by the contractor, joins the plant owner's
    row with the contractor named in the notes. Every other permit is a row of its own, named from EPA's owner name put
    in order ("WINSLOW, CITY OF" -> "City of Winslow"), legal_form from form().
  - kind: "sso" when a permit of the row has reports in EPA's overflow tables or a collection system in EPA's
    collection-system table; otherwise "plant".
  - notification_channel: what Arizona law requires (a 24-hour report to ADEQ and a five-day written report under
    A.A.C. R18-9-C305(F) and the AZPDES permit; the only public duty a warning sign where more than three reportable
    releases happened at one location in 12 months, R18-9-C305(G)) and where the reports become public (EPA's overflow
    tables). Tribal rows and every Navajo Nation permit (NN...): EPA Region 9 permits in Indian country, outside the
    state rule. notification_signup_url null: no overflow alert list was found from the state or the agencies; the
    operators' own pages were not searched one by one (research/az/report.md).
  - The counts and kind come from git-ignored files (the events and dropped files and the saved all-versions ZIP):
    the script stops when they are absent. The Navajo Nation's reports count when the module placed them in Arizona.
  - Idempotent: a rerun replaces the rows it wrote (state AZ, source_areas ["az"]) and leaves every other row as it is;
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
RESEARCH = ROOT / "research" / "az" / "dischargers.json"
CANDIDATES = ROOT / "research" / "az" / "private-utilities-candidates.json"
EVENTS = ROOT / "data" / "build" / "events" / "echo-sewer-overflow.json"
DROPPED = ROOT / "data" / "build" / "echo-sewer-overflow-dropped.json"
CHECKED = "2026-11-07"
ECHO = "https://echo.epa.gov/tools/data-downloads/sewer-overflow-download-summary"
LAW = ("No Arizona statute or rule requires the public to be told of a sewage release when it happens. A.A.C. "
       "R18-9-C305(F) requires a report to ADEQ within 24 hours of a release that is an imminent and substantial threat "
       "to public health or the environment (over 2,000 gallons, or over 50 gallons reaching a stream, a street, a public "
       "area or a building) and a written report within five business days; AZPDES permits carry the same 24-hour and "
       "five-day noncompliance reports (40 CFR 122.41(l)(6)). The only public duty is a warning sign at a location with "
       "more than three reportable releases in 12 months, kept up until 12 months pass without one (R18-9-C305(G)). "
       f"AZPDES permittees file their reports in ADEQ's myDEQ, and EPA publishes them in its overflow tables ({ECHO}) "
       "a few days later.")
TRIBAL = ("A permit on tribal land, where EPA Region 9, not ADEQ, administers the Clean Water Act permit program and "
          "Arizona's collection-system rule does not apply: the permit's 24-hour and five-day noncompliance reports go "
          f"to EPA (40 CFR 122.41(l)(6)), which publishes the reports filed electronically in its overflow tables ({ECHO}). "
          "No public notice duty was found.")
PRIVATE_NOTE = " The rule and the permit conditions bind a private permittee as they bind a public one."
OWN = " The operator's own pages were not searched individually."

# row id -> (name, short_name, legal_form, permits, note)
GROUPS = {
    "az-city-of-phoenix": ("City of Phoenix Water Services (91st Avenue, 23rd Avenue and Cave Creek plants)",
                           "City of Phoenix", "city",
                           ["AZ0020524", "AZ0020559", "AZ0024465", "AZ0026727", "AZC111068", "AZC111487", "AZC113055",
                            "AZC113158", "AZC113300", "AZPT00006", "AZS000003"],
                           "The 91st Avenue plant is operated by Phoenix for the regional SROG partners."),
    "az-pima-county": ("Pima County (Regional Wastewater Reclamation Department, Tucson area)",
                       "Pima County Regional Wastewater Reclamation", "county",
                       ["AZ0020001", "AZ0020923", "AZ0022250", "AZ0024121", "AZ0024937", "AZ0026107", "AZPT00013",
                        "AZ0025291", "AZ0026093", "AZS000002"],
                       "The Regional Wastewater Reclamation Department runs the Tucson area's sewers and plants (Tres "
                       "Rios, Agua Nueva, Avra Valley, Green Valley, Mount Lemmon). EPA's collection-system table lists "
                       "its systems, but no overflow or bypass report under any of its permits is in EPA's overflow "
                       "tables (2026-11-04 extract). AZ0025291 (the Stadium District's Kino environmental restoration "
                       "project), AZ0026093 (Solid Waste Management) and AZS000002 (the county MS4) are not sewage "
                       "permits."),
    "az-city-of-tucson": ("City of Tucson", "City of Tucson", "city", ["AZ0026417", "AZS000001"],
                          "Tucson's sewers are Pima County's. AZ0026417 is Tucson Water's airport groundwater "
                          "remediation discharge and AZS000001 the city MS4: neither is a sewage permit."),
    "az-city-of-mesa": ("City of Mesa Water Resources (Northwest, Southeast and Greenfield plants)", "City of Mesa",
                        "city", ["AZ0024031", "AZ0024627", "AZ0025151", "AZ0025241", "AZPT00005"], None),
    "az-city-of-buckeye": ("City of Buckeye", "City of Buckeye", "city",
                           ["AZ0025313", "AZ0024881", "AZ0025216", "AZ0026913", "AZ0025127", "AZ0025518", "AZ0025691",
                            "AZPT00002"],
                           "EPA records some of the permits under the Town of Buckeye, the city's earlier form."),
    "az-city-of-goodyear": ("City of Goodyear (157th Avenue, Corgett Wash and Rainbow Valley plants)", "City of Goodyear",
                            "city", ["AZ0022357", "AZ0023582", "AZ0025135", "AZC105576", "AZC106697", "AZC111558",
                                     "AZC111560", "AZDM90319", "AZDM90355", "AZMS92089", "AZMS92107", "AZPT00010"],
                            None),
    "az-city-of-flagstaff": ("City of Flagstaff Utilities (Wildcat Hill and Rio de Flag plants)", "City of Flagstaff",
                             "city", ["AZ0020427", "AZ0023639", "AZPT00007"], None),
    "az-city-of-yuma": ("City of Yuma", "City of Yuma", "city", ["AZ0020443", "AZ0025411", "AZPT00018"], None),
    "az-city-of-peoria": ("City of Peoria", "City of Peoria", "city", ["AZ0025119", "AZ0024945", "AZPT00012"], None),
    "az-city-of-avondale": ("City of Avondale", "City of Avondale", "city", ["AZ0023281", "AZPT00001"], None),
    "az-city-of-casa-grande": ("City of Casa Grande", "City of Casa Grande", "city", ["AZ0025178", "AZPT00003"], None),
    "az-city-of-tolleson": ("City of Tolleson", "City of Tolleson", "city", ["AZ0020338", "AZPT00017"], None),
    "az-city-of-el-mirage": ("City of El Mirage", "City of El Mirage", "city", ["AZ0023272", "AZDM90327"], None),
    "az-apache-junction-sewer-district": ("Apache Junction Sewer District", "Apache Junction Sewer District",
                                          "special district", ["AZ0023931", "AZC111230", "AZC115305"], None),
    "az-town-of-marana": ("Town of Marana", "Town of Marana", "town", ["AZ0024520", "AZC117008"], None),
    "az-town-of-florence": ("Town of Florence (North Florence and South plants)", "Town of Florence", "town",
                            ["AZ0025194", "AZ0025208"], None),
    "az-city-of-winslow": ("City of Winslow", "City of Winslow", "city", ["AZ0023833", "AZ0026310"], None),
    "az-city-of-kingman": ("City of Kingman (Hilltop and Downtown plants)", "City of Kingman", "city",
                           ["AZ0025844", "AZ0026018"], None),
    "az-town-of-wickenburg": ("Town of Wickenburg (Wickenburg and Wickenburg Ranch plants)", "Town of Wickenburg", "town",
                              ["AZ0020044", "AZ0025976"],
                              "EPA types the Wickenburg Ranch plant (AZ0025976) privately owned; the permittee it "
                              "records is the Town."),
    "az-grand-canyon-np": ("National Park Service, Grand Canyon National Park (South Rim and North Rim plants)",
                           "Grand Canyon National Park", "federal facility", ["AZ0022152", "AZ0110426"], None),
    "az-usbr-lower-colorado": ("U.S. Bureau of Reclamation, Lower Colorado Basin (Hoover Dam plant and Yuma Desalting "
                               "Plant)", "U.S. Bureau of Reclamation", "federal facility", ["AZ0025160", "AZ0025348"],
                               "The Hoover Dam plant's permit is an Arizona permit; EPA records the facility's city as "
                               "Boulder City, Nevada. The Yuma Desalting Plant is not a sewage plant."),
    "az-white-mountain-apache-tribe": ("White Mountain Apache Tribe (Whiteriver, Hon-Dah, Sunrise and Cyclone plants)",
                                       "White Mountain Apache Tribe", "tribal",
                                       ["AZ0022829", "AZ0022837", "AZ0024058", "AZ0024571", "AZ0024589"], None),
    "az-navajo-tribal-utility-authority": ("Navajo Tribal Utility Authority (Chinle, Kayenta, Tuba City, Window Rock, "
                                           "Ganado and Twin Arrows plants)", "Navajo Tribal Utility Authority",
                                           "tribal", ["NN0020265", "NN0020281", "NN0020290", "NN0021555", "NN0022195",
                                                      "NN0030344"],
                                           "Navajo Nation permits (NN...) EPA lists in Arizona. A report counts here when its point lies in "
                                           "Arizona (three Window Rock reports lie in New Mexico, two of them at the "
                                           "lift station by Navajo, New Mexico, and are not counted)."),
}
# permits no input names well -> (row id, name, short_name, legal_form, note)
HAND = {
    "AZ0023485": ("az-adcrr-eyman", "Arizona Department of Corrections, Rehabilitation and Reentry (ASPC Eyman, Florence)",
                  "ASPC Eyman", "state facility",
                  "EPA's facility search names the permit ASP - EYMAN PRISON COMPLEX, Florence (NON-POTW), read "
                  "2026-11-07; the plant serves the state prison complex."),
    "AZ0021415": ("az-colorado-river-sewage-system-jv", "Colorado River Sewage System Joint Venture (Parker)",
                  "Colorado River Sewage System Joint Venture", "tribal",
                  "EPA's collection-system table types the owner a tribal government; the joint venture serves Parker "
                  "and the Colorado River Indian Tribes' land."),
    "AZ0024619": ("az-upper-village-of-moenkopi", "Upper Village of Moenkopi (Hopi Tribe)", "Upper Village of Moenkopi",
                  "tribal", None),
    "AZ0024640": ("az-san-carlos-apache-tribe", "San Carlos Apache Tribe (Six Mile lagoon plant)",
                  "San Carlos Apache Tribe", "tribal", None),
    "AZ0025607": ("az-ibwc-nogales", "International Boundary and Water Commission (Nogales International Wastewater "
                  "Treatment Plant)", "International Boundary and Water Commission", "federal facility",
                  "The plant treats sewage from Nogales, Arizona, and Nogales, Sonora."),
    "AZ0025224": ("az-usfs-apache-sitgreaves", "U.S. Forest Service, Apache-Sitgreaves National Forests (Black Mesa "
                  "Ranger District)", "Apache-Sitgreaves National Forests", "federal facility", None),
    "AZ0026620": ("az-arizona-state-parks", "Arizona State Parks and Trails (Patagonia Lake State Park)",
                  "Arizona State Parks and Trails", "state facility", None),
    "AZ0025909": ("az-az0025909", "Miami Wastewater Reclamation Facility", "Miami Wastewater Reclamation Facility", None,
                  "EPA records the plant's name as the permittee; the owner was not read."),
    "AZ0020117": ("az-northern-gila-county-sanitary-district", "Northern Gila County Sanitary District (Payson)",
                  "Northern Gila County Sanitary District", "special district", None),
}
# permittee as EPA records it -> (legal form, note); research/az/private-utilities-candidates.json
PRIVATE = {
    "Epcor Water Arizona Inc.": ("investor-owned utility", "EPCOR Water Arizona, a regulated water and wastewater utility "
                                 "company (the candidates file proposed business or industrial from the name)."),
    "Global Water - Palo Verde Utilities Company, Inc.": ("investor-owned utility", "A wastewater utility company of the "
                                                          "Global Water group."),
    "Global Water - Hassayampa Utilities Company, Inc.": ("investor-owned utility", "A wastewater utility company of the "
                                                          "Global Water group."),
    "Liberty Utilities - Litchfield Park Water & Sewer - Corp.": ("investor-owned utility", "A water and sewer utility "
                                                                  "company of the Liberty Utilities group."),
    "Liberty Utilities - Sub - Corp.": ("investor-owned utility", "A utility company of the Liberty Utilities group."),
    "Utility Source, L.L.C": ("investor-owned utility", "A water and sewer company."),
    "Mountain Pass Utility Company": ("investor-owned utility", "A sewer utility company (SaddleBrooke Ranch)."),
    "Valle Airpark, L.L.C.": ("business or industrial", "A company that holds the airpark plant's permit."),
    "Black Canyon Ranch Rv Resort Llc": ("campground or resort", ""),
    "Frito-Lay North America Inc": ("business or industrial", "A food plant treating its own wastewater."),
    "Trillium Land Company, Llc": ("business or industrial", "A land developer that holds the plant's interim permit."),
    "Bison Ranch Owners Assocation, Inc.": ("homeowners' association", ""),
}
PUBLIC_FORMS = {"city", "town", "county", "authority", "special district", "federal facility", "state facility",
                "tribal"}
# EPA's spellings put right for the row name (the spelling EPA records stays in the notes)
FIXES = {"American Ranch Dwid": "American Ranch Domestic Water Improvement District",
         "PINETOP-LAKESIDE SAN DIST": "Pinetop-Lakeside Sanitary District",
         "CITY OF SHOW LOW - MAIN WWTP": "City of Show Low",
         "Bison Ranch Owners Assocation, Inc.": "Bison Ranch Owners Association",
         "Utility Source, L.L.C": "Utility Source, LLC", "Valle Airpark, L.L.C.": "Valle Airpark, LLC",
         "Black Canyon Ranch Rv Resort Llc": "Black Canyon Ranch RV Resort", "Trillium Land Company, Llc":
         "Trillium Land Company", "Frito-Lay North America Inc": "Frito-Lay North America (Casa Grande plant)",
         "Mountain Pass Utility Company": "Mountain Pass Utility Company (SaddleBrooke Ranch)"}
SHORT = {"Epcor Water Arizona Inc.": "EPCOR Water Arizona",
         "Global Water - Palo Verde Utilities Company, Inc.": "Global Water - Palo Verde Utilities",
         "Global Water - Hassayampa Utilities Company, Inc.": "Global Water - Hassayampa Utilities",
         "Liberty Utilities - Litchfield Park Water & Sewer - Corp.": "Liberty Utilities (Litchfield Park)",
         "Liberty Utilities - Sub - Corp.": "Liberty Utilities (Sarival)"}
PRIVATE_FORMS = {"investor-owned utility", "member-owned utility", "homeowners' association", "mobile-home park",
                 "campground or resort", "private club", "business or industrial", "institution",
                 "facility (permittee not named)"}
ABBR = {"wwtp", "wrf", "wrp", "wwtf", "wwrf", "wpcf", "dwid", "nps", "usdoi", "np", "rv", "llc", "ms4", "ii", "aspc",
        "bnro", "wwmd", "wwts", "uvm"}


def slug(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s.lower())).strip("-")


def smart_title(s: str) -> str:
    out = []
    for w in (s or "").split():
        bare = re.sub(r"[^A-Za-z0-9]", "", w).lower()
        if bare in ABBR:
            out.append(w.upper().replace("LLC", "LLC"))
        elif w.isupper() or w.islower():
            out.append(re.sub(r"(?<=\w)'S\b", "'s", w.title()))
        else:
            out.append(w)
    s = " ".join(out)
    return re.sub(r"(?<=\w )\b(Of|And|The|At)\b", lambda m: m.group(1).lower(), s)


def pretty(owner: str) -> str:
    """'WINSLOW, CITY OF' -> 'City of Winslow'; 'City Of Globe' -> 'City of Globe'; 'MAMMOTH, TOWN OF' -> 'Town of
    Mammoth'."""
    s = " ".join((owner or "").split()).strip(" ,")
    m = re.match(r"^(.*?),?\s+(CITY|TOWN)(?:\s+OF)?$", s, re.I)
    if m and not re.match(r"(?i)^(city|town) of\b", s):
        return f"{m.group(2).title()} of {smart_title(m.group(1))}"
    t = smart_title(s)
    return re.sub(r"^(City|Town) Of\b", lambda m: f"{m.group(1)} of", t)


def form(name: str | None) -> str | None:
    n = (name or "").lower()
    if re.search(r"\b(tribe|tribal|nation|indian|apache|navajo|hopi|moenkopi)\b", n):
        return "tribal"
    if re.search(r"\b(national park|usdoi|usda|u\.?s\.? |forest service|reclamation|army|air force|boundary and water)\b",
                 n):
        return "federal facility"
    if re.search(r"\b(sanitary district|sewer district|improvement district|dwid|wastewater improvement district|"
                 r"water improvement district|san dist)\b", n):
        return "special district"
    if re.search(r"\bcounty\b", n):
        return "county"
    if re.search(r"^town of\b|\btown of\b", n):
        return "town"
    if re.search(r"^city of\b|\bcity of\b", n):
        return "city"
    return None


WBIDS = ROOT / "data" / "reference" / "az-adeq-wbids.json"


def wbid_name(w: str) -> str:
    """An ADEQ waterbody identifier as ADEQ names it (scripts/az_adeq_wbids.py); any other text as it is."""
    global _WB
    if "_WB" not in globals():
        _WB = json.loads(WBIDS.read_text())["wbids"] if WBIDS.exists() else {}
    hit = _WB.get((w or "").strip())
    return hit["name"] if hit and hit.get("name") else w


def plants() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for r in json.loads(PLANTS.read_text())["outfalls"]:
        if r.get("state") == "AZ" and r.get("npdes_permit"):
            out[r["npdes_permit"].upper()].append(r)
        elif str(r.get("npdes_permit") or "").upper() == "AZ0025160":   # Hoover Dam: an Arizona permit, NV city
            out["AZ0025160"].append(r)
    return out


def epa_reports() -> tuple[Counter, Counter]:
    """(permit -> reports in EPA's overflow tables, permit -> reports kept as reaching a water), Arizona only."""
    allr, kept = Counter(), Counter()
    ev = json.loads(EVENTS.read_text()) if EVENTS.exists() else {}
    for r in ev.get("records", []):
        if (r.get("npdes_permit") or "")[:2] in ("AZ", "NN") and (r.get("raw") or {}).get("state", "AZ") == "AZ":
            kept[r["npdes_permit"]] += 1
            allr[r["npdes_permit"]] += 1
    dr = json.loads(DROPPED.read_text()) if DROPPED.exists() else {}
    for r in dr.get("dropped", []):
        if (r.get("permit") or "")[:2] in ("AZ", "NN") and r.get("state", "AZ") == "AZ":   # NN placed in AZ
            allr[r["permit"]] += 1
    return allr, kept


def collection_systems() -> set[str]:
    """Permits EPA's collection-system table lists for Arizona (the saved all-versions ZIP, when present)."""
    z = ROOT / "data" / "raw" / "echo-az" / "all.zip"
    if not z.exists():
        return set()
    sys.path.insert(0, str(ROOT / "pipeline"))
    from ingest import echo_sewer_overflow_events as E
    tables, _ = E.read_zip(z)
    return {s["permit_identifier"] for s in tables.get("systems", []) if s["permit_identifier"][:2] in ("AZ", "NN")}


def row(rid, name, short, legal_form, permits, towns, waters, notes, kind, outfalls, research_ids, verified="fetched"):
    tribal = legal_form == "tribal" or any(p.startswith("NN") for p in permits)   # EPA's permits in Indian country
    private = legal_form in PRIVATE_FORMS
    return {"id": rid, "name": name, "short_name": short or name, "legal_form": legal_form, "state": "AZ",
            "kind": kind, "npdes_permit": permits[0] if permits else None, "npdes_permits": list(permits),
            "receiving_waters": waters, "water_slugs": [], "outfall_count": outfalls or None,
            "outfalls_source": (f"EPA ICIS-NPDES discharge points (data/outfalls-plants-us.json, {outfalls} rows)"
                                if outfalls else None),
            "notification_channel": (TRIBAL if tribal else LAW + (PRIVATE_NOTE if private else "") + OWN),
            "notification_feed_machine_readable": True, "notification_signup_url": None,
            "towns": towns, "notes": notes, "verified": verified, "checked": CHECKED,
            "aliases": list(dict.fromkeys([rid] + research_ids)), "source_areas": ["az"]}


def build(dis: list[dict]) -> tuple[list[dict], dict]:
    missing = [str(p.relative_to(ROOT)) for p in (EVENTS, DROPPED, ROOT / "data" / "raw" / "echo-az" / "all.zip")
               if not p.exists()]
    if missing:   # git-ignored inputs: without them every row would turn "plant" and lose its report counts
        raise SystemExit("run pipeline/ingest/echo_sewer_overflow_events.py first (with the all-versions ZIP saved at "
                         "data/raw/echo-az/all.zip); missing: " + ", ".join(missing))
    keep = [d for d in dis if not (d.get("state") == "AZ" and "az" in (d.get("source_areas") or []))]
    held_elsewhere = {str(p).upper() for d in keep for p in [d.get("npdes_permit"), *(d.get("npdes_permits") or [])] if p}
    pl = plants()
    research = {r["npdes_permit"]: r for r in json.loads(RESEARCH.read_text())}
    cand = json.loads(CANDIDATES.read_text())
    cands = {c["npdes_permit"]: c for c in cand["candidates"]}
    public_by_name = {c["npdes_permit"]: c for c in cand["public_by_name"]}
    allr, kept = epa_reports()
    systems = collection_systems()
    permits = sorted(set(pl) | set(research) | set(cands) | set(public_by_name) | set(allr))
    clash = sorted(p for p in permits if p in held_elsewhere)
    if clash:
        raise SystemExit(f"permits already held by another row: {clash}")
    owner_of: dict[str, str] = {}
    meta: dict[str, dict] = {}
    for rid, (name, short, lf, ps, note) in GROUPS.items():
        meta[rid] = {"name": name, "short": short, "lf": lf, "note": note}
        for p in ps:
            if p in owner_of:
                raise SystemExit(f"{p} in two groups")
            owner_of[p] = rid
    for p, (rid, name, short, lf, note) in HAND.items():
        owner_of[p] = rid
        meta[rid] = {"name": name, "short": short, "lf": lf, "note": note}
    # private candidates by permittee
    for p, c in cands.items():
        who = c["permittee_as_recorded"]
        if who == "[name removed]":
            fac = c.get("facility") or ""
            if fac and fac != "[name removed]":
                name = f"{smart_title(fac).replace(' @ ', ' at ')} (permit {p})"
            else:
                name = f"Sewage plant near {smart_title(c.get('city') or '')} (permit {p})"
            rid = f"az-{p.lower()}"
            meta[rid] = {"name": name, "short": name, "lf": "facility (permittee not named)",
                         "note": "EPA's permittee name reads as an individual's: not named here; the row names the "
                                 "facility" + (" (EPA's facility name was removed too: the place is given)."
                                               if fac in ("", "[name removed]") else ".")}
        elif who not in PRIVATE and form(who) in PUBLIC_FORMS:   # a district EPA types private: a public body
            name = FIXES.get(who, smart_title(who))
            rid = f"az-{slug(name)}"
            meta.setdefault(rid, {"name": name, "short": name, "lf": form(who),
                                  "note": "EPA types the facility privately owned, but the permittee it records reads "
                                          f"as a public body ({who}): filed as one."})
        else:
            lf, note = PRIVATE.get(who, (c.get("legal_form_proposed"), "The legal form is the candidates file's proposal."))
            name = SHORT.get(who) or FIXES.get(who) or smart_title(who)
            rid = f"az-{slug(name)}"
            meta.setdefault(rid, {"name": name, "short": name, "lf": lf,
                                  "note": (note + " " if note else "") + f"Privately owned; permittee as EPA ICIS-NPDES "
                                          f"records it: {who} (research/az/private-utilities-candidates.json); ADEQ's "
                                          "permit documents were not read."})
        owner_of[p] = rid
    # every other permit: a row of its own, named from EPA's owner name
    for p in permits:
        if p in owner_of:
            continue
        rows = pl.get(p) or []
        owner = (rows[0].get("permit_name") if rows else None) or (public_by_name.get(p) or {}).get(
            "permittee_as_recorded") or (research.get(p) or {}).get("name") or p
        name = FIXES.get(owner) or pretty(owner)
        rid = f"az-{slug(name)}"
        if rid in meta and owner_of.get(p) != rid and rid not in GROUPS:
            if meta[rid]["name"] == name:          # one owner, two permits
                owner_of[p] = rid
                continue
            rid = f"{rid}-{p.lower()}"
        note = None
        if p in public_by_name:
            note = ("EPA types the facility privately owned, but the permittee it records is a public body "
                    f"({public_by_name[p]['permittee_as_recorded']}).")
        meta[rid] = {"name": name, "short": name, "lf": form(owner) or form(name), "note": note}
        owner_of[p] = rid
    by_row: dict[str, list[str]] = defaultdict(list)
    for p in permits:
        by_row[owner_of[p]].append(p)
    new = []
    for rid, ps in by_row.items():
        m = meta[rid]
        rows = [r for p in ps for r in pl.get(p, [])]
        cities = sorted({smart_title(r["city"]) for r in rows if r.get("city") and r["city"].upper() != "UNKNOWN"}
                        | {smart_title(cands[p]["city"]) for p in ps if p in cands and cands[p].get("city")
                           and cands[p]["city"].upper() != "UNKNOWN"})
        cities = sorted(set(cities) | {smart_title(public_by_name[p]["city"]) for p in ps if p in public_by_name
                                       and public_by_name[p].get("city")})
        own = re.match(r"^(?:City|Town) of (.+?)(?: \(| -|$)", m["name"])
        if own and own.group(1) not in cities:
            cities = sorted(cities + [own.group(1)])
        if m["lf"] == "facility (permittee not named)":
            cities = cities[:1]
        elif rid == "az-adcrr-eyman":
            cities = ["Florence"]
        waters = list(dict.fromkeys([wbid_name(w) for p in ps for w in (research.get(p) or {}).get("receiving_waters")
                                     or []] + [r["receiving_water_echo"] for r in rows if r.get("receiving_water_echo")]))[:8]
        facs = "; ".join(f"{p} {smart_title((pl.get(p) or [{}])[0].get('permittee') or (cands.get(p) or {}).get('facility') or '')}".strip()
                         for p in ps)
        contractors = sorted({(pl.get(p) or [{}])[0].get("permit_name") for p in ps if p.startswith("AZC")
                              and (pl.get(p) or [{}])[0].get("permit_name") and "City" not in (pl[p][0]["permit_name"] or "")})
        reports = sum(allr[p] for p in ps)
        note = f"EPA ICIS-NPDES: {facs}." if m["lf"] != "facility (permittee not named)" else f"EPA ICIS-NPDES: permit {ps[0]}."
        if contractors:
            note += (" The construction coverages (AZC...) at the plants are held by the contractors EPA records: "
                     + ", ".join(contractors) + ".")
        if reports:
            note += (f" EPA's overflow tables (2026-11-04 extract): {reports} report(s), {sum(kept[p] for p in ps)} "
                     "with evidence the discharge reached a water.")
        else:
            note += " No report under these permits is in EPA's overflow tables (2026-11-04 extract)."
        if m.get("note"):
            note += " " + m["note"]
        rids = [research[p]["id"] for p in ps if p in research]
        kind = "sso" if any(allr[p] or p in systems for p in ps) else "plant"
        new.append(row(rid, m["name"], m["short"], m["lf"], ps, cities, waters, note.strip(), kind, len(rows), rids))
    new.sort(key=lambda r: r["id"])
    ids = Counter(r["id"] for r in keep + new)
    dup = [i for i, n in ids.items() if n > 1]
    if dup:
        raise SystemExit(f"duplicate ids: {dup}")
    stats = {"rows": len(new), "permits": sum(len(r["npdes_permits"]) for r in new),
             "permits_with_reports": sum(1 for p in permits if allr[p]),
             "legal_form": dict(Counter(r.get("legal_form") for r in new)), "kind": dict(Counter(r["kind"] for r in new)),
             "private": sorted(r["id"] for r in new if r.get("legal_form") in PRIVATE_FORMS)}
    return keep + new, stats


def main(argv: list[str]) -> int:
    dis = json.loads(DIS.read_text())
    out, stats = build(dis)
    print(json.dumps(stats, indent=1))
    if "--dry-run" not in argv:
        DIS.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
