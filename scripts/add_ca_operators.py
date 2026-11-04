"""California operator rows for data/dischargers.json: one row per operator, every permit and enrollment in one row.

Usage (after pipeline/ingest/ca_swrcb_ciwqs_spills.py has written its events file, for the receiving waters):
    pipeline/.venv/bin/python -I scripts/add_ca_operators.py [--dry-run]

Inputs
  - The State Water Board's enrollee list under the Statewide Sanitary Sewer Systems General Order (Order WQ
    2022-0103-DWQ), Enrollee_Info.txt (https://www.waterboards.ca.gov/water_issues/programs/sso/docs/data_files/
    Enrollee_Info.txt; read from data/raw/ca-swrcb-ciwqs/ or fetched): 1,046 enrollments (WDIDs, one per sewer system;
    "-C" marks a combined system) of 820 agencies, 8 of them historical (terminated). Only the WDID, status, agency,
    collection system, county and dates are read; the address columns are not. Every agency is one row (the
    Department of Parks and Recreation's district offices and the Department of Corrections' two entries are one
    operator each); its WDIDs are its npdes_permits (the WDID is the enrollment's number, not an NPDES permit).
  - research/ca/dischargers.json (14 rows): the CSO permittees (SFPUC's three permits, Sacramento), the largest SSO
    reporters and USIBWC. Each keeps its research id (SFPUC's three permits are one operator, "ca-sfpuc", with the
    research ids as aliases) and joins the agency the enrollee list names for it (RESEARCH_AGENCY).
  - data/outfalls-plants-us.json (EPA ICIS-NPDES sewage plant permits for California, research/ca/federal-seed.json):
    the permit name is the permittee. A permittee whose name key() equals an agency's joins that agency's row
    (ATTACH_BY_HAND for names the key cannot match); permits of one permittee are one row; a joint permit of several
    bodies ("A; B") is its own row under EPA's name.
  - research/ca/private-utilities-candidates.json: PRIVATE below files each candidate with the permittee from EPA's
    record (the Regional Boards' permit orders were not read), legal_form from the controlled list, never an
    individual's name; NOT_SEWAGE names the permit that is no sewer system.

Rules
  - Name: the enrollee list's agency spelled out ("Eureka City" -> "City of Eureka", "Cnty" -> "County"); EPA's
    permit name for a plant-only row.
  - legal_form (form()) from the name, on the controlled list (docs/legal-forms.md); null when the name does not say.
  - notification_channel: the law (HSC 5411.5, Water Code 13271, the General Order's CIWQS reports published nightly);
    a plant operator with no enrollment is told apart: its spills do not reach the CIWQS file.
  - receiving_waters: the receiving waters of the operator's permits only (EPA's for the plant permits, the research
    rows'). The waters the operator's Category 1 spill reports name (the CIWQS events file, most named first) are
    spill_report_waters, kept apart: the status build places a report that names no water on the operator's single
    listed receiving water (build/status.Resolver.by_registry), and an earlier spill's water is no evidence for the
    next one (review 2026-11-04 P2-2). `--split-spill-waters` moves them out of the rows already written.
  - Idempotent: rows with an id or a permit already held are not added again. New rows go after the last California row
    (at the end while there is none).
Writes data/dischargers.json (indent 1) and prints counts.
"""
from __future__ import annotations

import csv
import io
import json
import re
import sys
import urllib.request
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "pipeline"))
from add_federal_operators import title  # noqa: E402

TODAY = date.today().isoformat()
DIS = ROOT / "data" / "dischargers.json"
RESEARCH = ROOT / "research" / "ca" / "dischargers.json"
PLANTS = ROOT / "data" / "outfalls-plants-us.json"
CSO = ROOT / "data" / "outfalls-us.json"
EVENTS = ROOT / "data" / "build" / "events" / "ca-swrcb-ciwqs-spills-flatfile.json"
ENROLLEES = ROOT / "data" / "raw" / "ca-swrcb-ciwqs" / "Enrollee_Info.txt"
ENROLLEES_URL = "https://www.waterboards.ca.gov/water_issues/programs/sso/docs/data_files/Enrollee_Info.txt"
FILE_URL = "https://www.waterboards.ca.gov/water_issues/programs/sso/docs/data_files/Cat1-2-3-Spills.txt"
LAW = ("Notice to the local health officer immediately on knowledge of the discharge (Health and Safety Code 5411.5); "
       "Cal OES within 2 hours for a spill of 1,000 gallons or more to waters of the State (Water Code 13271; Order "
       "WQ 2022-0103-DWQ Att. E1 1.1); a draft spill report in the State Water Board's CIWQS database within 3 "
       "business days of a Category 1 or 2 spill and a certified report within 15 days of its end (Order WQ "
       f"2022-0103-DWQ Att. E1 3.1-3.2), published nightly: {FILE_URL}. The public notice duty falls on the county "
       "health officer (posting and closure, a telephone hotline: HSC 115885). The operator's own pages were not "
       "searched individually.")
LAW_PLANT = ("Notice to the local health officer immediately (Health and Safety Code 5411.5) and to Cal OES within 2 "
             "hours for 1,000 gallons or more to waters of the State (Water Code 13271): both bind any person who "
             "causes a sewage discharge, public or private. No enrollment under the Statewide Sanitary Sewer Systems "
             "General Order was found for this operator, so its spills do not reach the State Water Board's CIWQS "
             "spill file; plant discharges are reported under its NPDES permit to the Regional Water Board, not as a "
             "public feed. The operator's own pages were not searched individually.")
CSO_SF = ("San Francisco's combined system: the SFPUC beach map flags each beach station when a combined sewer discharge "
          "has occurred within the last 24-72 hours and signs are posted until it ceases "
          "(https://webapps.sfpuc.org/sapps/beachesandbay.html); hotline 1-877-SFBEACH; e-mail alerts offered (sign-up "
          "link not found). Its separate-system spills follow the General Order: ")
CSO_SAC = ("Sacramento's combined system: under Order R5-2026-0003 (CA0079111) the City notifies the public under its "
           "Spill Emergency Response Plan and Plan of Operations 'in accordance with the U.S. EPA's CSO Control Policy' "
           "and phones the downstream drinking-water agencies within 2 hours; no public web channel was found. Its "
           "separate-system spills follow the General Order: ")
# research id -> the enrollee-list agency it is
RESEARCH_AGENCY = {
    "ca-sfpuc-southeast-northpoint-bayside": "San Francisco Public Utilities Commission",
    "ca-sacramento-css": "Sacramento City",
    "ca-oakland-dpw": "Oakland City DPW",
    "ca-sasd": "Sacramento Area Sewer District (merged)",
    "ca-san-jose": "San Jose City",
    "ca-la-sanitation": "Los Angeles City Bureau of Sanitation",
    "ca-lacsd": "Los Angeles Cnty Sanitation Districts",
    "ca-la-county-dpw": "Los Angeles Cnty DPW",
    "ca-san-diego-pud": "San Diego City Metropolitan Wastewater Dept (Public Utilities)",
    "ca-long-beach": "Long Beach Utilities Department",
    "ca-coronado": "Coronado City",
}
SFPUC_IDS = ("ca-sfpuc-southeast-northpoint-bayside", "ca-sfpuc-oceanside", "ca-sfpuc-bayside-cso")
# agency spellings that are one operator: (regex on the agency, the operator's key and name)
CONSOLIDATE = [
    (re.compile(r"^(ca dept of parks|california state parks|state of california department of parks)", re.I),
     "california department of parks and recreation", "California Department of Parks and Recreation"),
    (re.compile(r"^ca dept of corrections", re.I), "california department of corrections and rehabilitation",
     "California Department of Corrections and Rehabilitation"),
]
# EPA permittee key -> the enrollee-list agency it is, where key() cannot tell
ATTACH_BY_HAND = {
    "joint outfall system": "Los Angeles Cnty Sanitation Districts",          # LACSD's Joint Outfall System permits
    "santa clarita valley sanitary district": "Los Angeles Cnty Sanitation Districts",
    "santa clarita valley sanitary district of los angeles county": "Los Angeles Cnty Sanitation Districts",
    "san francisco city and county of": "San Francisco Public Utilities Commission",
    "san francisco city and county": "San Francisco Public Utilities Commission",
    "los angeles county department of public works": "Los Angeles Cnty DPW",
    "grizzly ranch community servic": "Grizzly Ranch CSD",                    # EPA's name is cut at 30 letters
    # Sacramento Regional County Sanitation District and the Sacramento Area Sewer District merged in 2023 (SacSewer)
    "sacramento regional county sanitary district": "Sacramento Area Sewer District (merged)",
}
# names the rules cannot spell out, and legal forms the name does not say
NAME_FIX = {"PICAYUNE RNCH-CHUKCHANSI INDNS": "Picayune Rancheria of the Chukchansi Indians",
            "SANTA YNEZ BAND OF CHUMASH IND": "Santa Ynez Band of Chumash Indians",
            "Murrieta WMWD": "Western Municipal Water District (Murrieta)",
            "Republic Services of Sonoma County": "Republic Services of Sonoma County (a waste company: the Central "
                                                  "Landfill leachate line)"}
FORM_FIX = {
    "California American Water": "investor-owned utility", "California Utilities Service": "investor-owned utility",
    "Cachuma Lake Recreation Area": "county", "Delta Diablo": "special district", "Montara": "special district",
    "Monterey One Water": "authority", "Silicon Valley Clean Water": "authority", "Scotts Valley": "city",
    "Woodside": "town", "Los Banos Urban Area SW System": "city", "Olympic Valley PSD": "special district",
    "Calaveras County Water District and Saddle Creek Golf Club, LLC": "special district",
    "River Highlands CSD, County of Yuba, and Gold Village Land Development LLC": "special district",
    "San Jose and Santa Clara, Cities of; and San Jose/Santa Clara WPCP": "city",
    "South San Francisco and San Bruno, Cities of & North Bayside System Unit (NBSU)": "city",
    "San Francisco, City and County of; North Bayside System Unit": "city",
    "MORRO BAY, CITY OF AND CAYUCOS SANITARY DISTRICT": "city",
}
NOT_SEWAGE = {"CA0000018": "a pilot ocean desalination vessel test (EPA lists a POTW component; the permittee of record "
                           "is not named)"}
# EPA's private sewage permits (research/ca/private-utilities-candidates.json): permit -> (name, legal_form, towns, note)
PRIVATE = {
    "CA0104841": ("Date Gardens Mobile Home Park wastewater plant (El Centro)", "facility (permittee not named)",
                  ["El Centro"], "EPA's permittee of record reads as an individual's name: not named here; the row "
                                 "names the facility (a mobile-home park's plant, EPA SIC 4952)."),
    "CA0006017": ("Town of Scotia Company LLC (Scotia WWTF)", "business or industrial", ["Scotia"],
                  "EPA records a company, the Town of Scotia Company LLC, as permittee despite the words 'Town of' in "
                  "its name; whether a public district has since taken the plant over was not checked."),
    "CA0084280": ("Table Mountain Rancheria (wastewater treatment facility)", "tribal", ["Friant"],
                  "A tribal government's plant; EPA types the facility privately owned."),
}
CITY_WITH_CITY = {"crescent city", "yuba city", "national city", "california city", "nevada city", "union city",
                  "daly city", "foster city", "culver city", "suisun city", "cathedral city", "big bear city",
                  "marin city", "mendocino city", "redwood city", "commerce city"}
DEPT_WORDS = set("""dept department bureau division services service dpw pwd mud dwp public works utilities utility water
wastewater sewer sanitation environmental metropolitan municipal administration resources of and facility facilities
regional parks rec recreation airport airports system systems cs pw environmental corporation pollution control plant
treatment wetland wpcp wpcf sso power""".split())


def slug(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s.lower())).strip("-")


def _strip_dept(s: str) -> str:
    words = s.split()
    while words and words[-1] in DEPT_WORDS:
        words.pop()
    return " ".join(words)


def key(name: str | None) -> str | None:
    """A comparable owner key: 'Arcata, City of' and 'Arcata City' -> 'arcata'; 'Los Angeles City Bureau of
    Sanitation' and 'Los Angeles, City of' -> 'los angeles'; districts spelled out ('SD', 'CSD', 'PUD', 'MWD', 'Dist')."""
    s = re.sub(r"\([^)]*\)", " ", (name or "").lower()).replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = " ".join(s.split())
    s = re.sub(r"\bcnty\b|\bco\b", "county", s)
    s = re.sub(r"\bdist\b|\bdistr\b", "district", s)
    s = re.sub(r"\bcsd\b|\bcommunity service district\b", "community services district", s)
    s = re.sub(r"\bpud\b|\bp u d\b", "public utility district", s)
    s = re.sub(r"\bpublic utilities district\b", "public utility district", s)
    s = re.sub(r"\bmwd\b", "municipal water district", s)
    s = re.sub(r"\bsd\b|\bsanitation district\b|\bsanitatary district\b", "sanitary district", s)
    s = re.sub(r"\bwd\b", "water district", s)
    s = re.sub(r"\b(the|merged)\b", " ", s)
    s = " ".join(s.split())
    if re.search(r"\b(district|authority|agency|commission|county|cities)\b", s):
        return s or None
    m = re.match(r"^city of (.+)$", s)
    if m:
        base_ = _strip_dept(m.group(1))
        return base_ or s
    m = re.match(r"^(.+?) city(?: of)?(?: (.*))?$", s)
    if m:
        base_, rest = m.group(1), _strip_dept(m.group(2) or "")
        if f"{base_} city" in CITY_WITH_CITY:
            m2 = re.match(r"^city(?: of)?(?: (.*))?$", rest)
            if not rest or (m2 and not _strip_dept(m2.group(1) or "")):
                return f"{base_} city"
            return s
        if not rest:
            return base_
    return s or None


def public_name(agency: str) -> str:
    """'Eureka City' -> 'City of Eureka'; 'Arcata, City of' -> 'City of Arcata'; 'Cnty' -> 'County'."""
    s = " ".join(agency.split())
    s = re.sub(r"\bCnty\b", "County", s)
    m = re.match(r"^(.+?),\s*City of$", s, re.I)
    if m:
        return f"City of {m.group(1)}"
    m = re.match(r"^(.+?) City$", s)
    if m and f"{m.group(1).lower()} city" not in CITY_WITH_CITY and not re.search(r"\b(District|Authority)\b", s):
        return f"City of {m.group(1)}"
    m = re.match(r"^(.+?) City(?: of)? \(?(.+?)\)?$", s)
    if m and f"{m.group(1).lower()} city" not in CITY_WITH_CITY and \
            all(w in DEPT_WORDS for w in re.sub(r"[^a-z ]+", " ", m.group(2).lower()).split()):
        rest = m.group(2).strip(" -\u2013")
        return f"City of {m.group(1)}" + (f" ({rest})" if rest.upper() != "SSO" else "")
    return NAME_FIX.get(s, s)


def form(name: str) -> str | None:
    if name in FORM_FIX:
        return FORM_FIX[name]
    n = (name or "").lower()
    if re.search(r"\b(rancheria|tribe|tribal|band of|indians?|indns|indian community|reservation)\b", n):
        return "tribal"
    if re.search(r"\b(u\.?s\.?|united states|usdi|usda|national park|national lab|national laboratories|army|navy|"
                 r"marine corps|air force|veterans affairs|bureau of reclamation|forest service|dept of energy|"
                 r"boundary and water commission|usibwc|corps of engineers|federal)\b", n):
        return "federal facility"
    if re.search(r"\b(ca dept|california department|state parks|dept\.? of state hospitals|state hospital|csu|"
                 r"california state university|state university|uc|university of california|regents|polytechnic|"
                 r"caltrans|corrections|developmental center|veteran'?s home|district agricultural association|"
                 r"state water resources|state of california)\b", n):
        return "state facility"
    if re.search(r"\b(mutual water company)\b", n):
        return "member-owned utility"
    if re.search(r"\b(llc|inc|corp|ranchcorp|company|services of)\b", n) and not re.search(r"\btown of\b", n):
        if re.search(r"\b(water|utilit|sewer)\b", n):
            return "investor-owned utility"
        return "business or industrial"
    if re.search(r"\b(authority|joint powers|jpa|agency|commission|wma|management agency)\b", n):
        return "authority"
    if re.search(r"\b(district|dist\.?|sd|csd|pud|p\.u\.d|mud|mwd|psd|wd|cwd|usd|csa|service area|improvement|sanitary|sanitation|"
                 r"college|unified school|port of)\b", n):
        return "special district"
    if re.search(r"\b(county|cnty|co)\b", n):
        return "county"
    if re.search(r"\btown of\b|\btown$", n):
        return "town"
    if re.search(r"\bcity\b|\bccsf\b|public utilities commission|utilities department|public works", n):
        return "city"
    return None


def read_enrollees() -> list[dict]:
    if ENROLLEES.exists():
        content = ENROLLEES.read_bytes()
    else:
        req = urllib.request.Request(ENROLLEES_URL, headers={"User-Agent": "DirtyWaterWatch/0.1 (+https://dirtywaterwatch.org)"})
        content = urllib.request.urlopen(req, timeout=120).read()
        ENROLLEES.parent.mkdir(parents=True, exist_ok=True)
        ENROLLEES.write_bytes(content)
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        text = content.decode("cp1252", errors="replace")
    out = []
    for r in csv.DictReader(io.StringIO(text), delimiter="\t"):
        wdid = (r.get("WDID") or "").strip().upper()
        if not wdid:
            continue
        out.append({"wdid": wdid, "status": (r.get("Status") or "").strip(), "agency": " ".join((r.get("Agency") or "").split()),
                    "system": " ".join((r.get("Collection System") or "").split()),
                    "county": (r.get("County") or "").strip(), "terminated": (r.get("Termination Date") or "").strip()})
    return out


WATER_WORD = re.compile(r"(?i)\b(creek|river|bay|ocean|lake|slough|channel|canal|wash|lagoon|harbou?r|estuary|reservoir|"
                        r"pond|marsh|inlet|beach|cove|arroyo|sea|stream|strait|straits|gulch|ditch|delta|wetlands?|"
                        r"tributary|drain|marina|basin)\b")


def spill_waters() -> dict[str, Counter]:
    """WDID -> Counter of the receiving waters its Category 1 spill reports name."""
    out: dict[str, Counter] = defaultdict(Counter)
    if not EVENTS.exists():
        return out
    for r in json.loads(EVENTS.read_text()).get("records", []):
        raw = r.get("raw") or {}
        if r.get("npdes_permit") and r.get("waterbody_text") and raw.get("spill_category") == "1" and \
                len(r["waterbody_text"]) <= 60 and "[" not in r["waterbody_text"] and WATER_WORD.search(r["waterbody_text"]):
            out[r["npdes_permit"].upper()][" ".join(r["waterbody_text"].split())] += 1
    return out


def plants() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for r in json.loads(PLANTS.read_text())["outfalls"]:
        if r.get("state") == "CA" and r.get("npdes_permit"):
            out[r["npdes_permit"].upper()].append(r)
    return out


def cso_rows() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for r in json.loads(CSO.read_text())["outfalls"]:
        if r.get("state") == "CA" and r.get("npdes_permit"):
            out[r["npdes_permit"].upper()].append(r)
    return out


def base_row(rid, name, kind, permits, towns, waters, notes, legal_form=None, short=None, outfalls_source=None,
             outfall_count=None, verified="fetched", channel=LAW, machine=True, spill_waters=None):
    return {"id": rid, "name": name, "short_name": short or name, "legal_form": legal_form, "state": "CA",
            "kind": kind, "npdes_permit": permits[0] if permits else None, "npdes_permits": list(permits),
            "receiving_waters": waters, "spill_report_waters": list(spill_waters or []), "water_slugs": [],
            "outfall_count": outfall_count,
            "outfalls_source": outfalls_source, "notification_channel": channel,
            "notification_feed_machine_readable": machine, "notification_signup_url": None,
            "towns": towns, "notes": notes, "verified": verified, "checked": TODAY, "aliases": [rid],
            "source_areas": ["ca"]}


def permit_waters(row: dict, pl: dict[str, list[dict]], research: dict[str, dict]) -> set[str]:
    """The receiving waters a row's permits name: EPA's for its plant permits, the research rows' it was built from."""
    out = {r["receiving_water_echo"] for p in row.get("npdes_permits") or [] for r in pl.get(str(p).upper(), [])
           if r.get("receiving_water_echo")}
    for rid in row.get("aliases") or []:
        out.update((research.get(rid) or {}).get("receiving_waters") or [])
    return out


def split_spill_waters(dis: list[dict], pl: dict[str, list[dict]], research: dict[str, dict]) -> int:
    """California rows: receiving_waters keeps the waters the permits name; the others (named in the operator's spill
    reports) move to spill_report_waters. Returns the number of rows changed."""
    n = 0
    for r in dis:
        if r.get("state") != "CA" or "spill_report_waters" in r and not r.get("receiving_waters"):
            continue
        own = permit_waters(r, pl, research)
        keep = [w for w in r.get("receiving_waters") or [] if w in own]
        moved = [w for w in r.get("receiving_waters") or [] if w not in own]
        before = (list(r.get("receiving_waters") or []), r.get("spill_report_waters"))
        spill = list(dict.fromkeys((r.get("spill_report_waters") or []) + moved))
        items = [(k, v) for k, v in r.items() if k != "spill_report_waters"]
        r.clear()
        for k, v in items:
            r[k] = keep if k == "receiving_waters" else v
            if k == "receiving_waters":
                r["spill_report_waters"] = spill
        n += (keep, spill) != before
    return n


def main(argv) -> int:
    dry = "--dry-run" in argv
    if "--split-spill-waters" in argv:
        dis = json.loads(DIS.read_text())
        research = {r["id"]: r for r in json.loads(RESEARCH.read_text())}
        n = split_spill_waters(dis, plants(), research)
        print(f"{n} California rows: spill-report waters moved out of receiving_waters")
        if not dry:
            DIS.write_text(json.dumps(dis, indent=1, ensure_ascii=False) + "\n")
        return 0
    dis = json.loads(DIS.read_text())
    have_ids = {d["id"] for d in dis}
    held = {str(p).strip().upper() for d in dis for p in [d.get("npdes_permit"), *(d.get("npdes_permits") or [])] if p}
    enr = read_enrollees()
    waters_by_wdid = spill_waters()
    pl = plants()
    cso = cso_rows()
    research = {r["id"]: r for r in json.loads(RESEARCH.read_text())}
    counts = Counter()

    # 1. agencies of the enrollee list
    agencies: dict[str, dict] = {}
    for e in enr:
        k, name = None, None
        for rx, ck, cn in CONSOLIDATE:
            if rx.search(e["agency"]):
                k, name = ck, cn
        k = k or key(e["agency"]) or e["wdid"].lower()
        a = agencies.setdefault(k, {"key": k, "agency": e["agency"], "name": name or public_name(e["agency"]),
                                    "enrollments": [], "spellings": set()})
        a["enrollments"].append(e)
        a["spellings"].add(e["agency"])
    by_agency = {sp: a for a in agencies.values() for sp in a["spellings"]}

    rows: dict[str, dict] = {}            # agency key -> row
    new: list[dict] = []

    def wdid_waters(wdids) -> list[str]:
        c = Counter()
        for w in wdids:
            c.update(waters_by_wdid.get(w, Counter()))
        return [w for w, _ in c.most_common(8)]

    for k, a in sorted(agencies.items()):
        wdids = [e["wdid"] for e in a["enrollments"]]
        if any(w in held for w in wdids):
            counts["agency already held"] += 1
            continue
        lf = form(a["agency"]) or form(a["name"])
        towns = [re.sub(r"^City of ", "", a["name"]).split(" (")[0]] if lf == "city" and a["name"].startswith("City of") \
            else []
        systems = "; ".join(f"{e['system']} ({e['wdid']}{', enrollment terminated ' + e['terminated'] if e['terminated'] else ''})"
                            for e in a["enrollments"])
        counties = sorted({e["county"] for e in a["enrollments"] if e["county"]})
        notes = (f"Enrolled under the Statewide Sanitary Sewer Systems General Order (State Water Board enrollee list, "
                 f"Enrollee_Info.txt): {systems}" + (f"; {', '.join(counties)} County" + ("ies" if len(counties) > 1 else "")
                                                     if counties else "") + ".")
        if len(a["spellings"]) > 1:
            notes += f" The list names it {len(a['spellings'])} ways (district offices); one operator here."
        hist = all(e["status"].lower() == "historical" for e in a["enrollments"])
        if hist:
            notes += " Every enrollment is historical (terminated)."
        rid = f"ca-{slug(k)}"
        if rid in have_ids:
            rid = f"ca-{slug(k)}-{wdids[0].lower()}"
        row = base_row(rid, a["name"], "sso", wdids, towns, [], notes, legal_form=lf, spill_waters=wdid_waters(wdids))
        rows[k] = row
        counts["agency rows"] += 1

    # 2. research rows: the research id and name, joined to their agency
    sf = rows.get(key("San Francisco Public Utilities Commission"))
    for rid, r in research.items():
        if rid in have_ids:
            counts["research row already held"] += 1
            continue
        agency = RESEARCH_AGENCY.get(rid)
        if rid in SFPUC_IDS:
            continue
        if agency:
            row = rows.get(by_agency[agency]["key"])
            old = row["id"]
            row["id"], row["aliases"] = rid, [rid, old]
            row["name"] = r["name"]
            row["short_name"] = r["name"]
            if r.get("towns"):
                row["towns"] = [t for t in r["towns"] if not t.endswith(" County")] or row["towns"]
            if r.get("receiving_waters") and not row["receiving_waters"]:
                row["receiving_waters"] = list(r["receiving_waters"])
            if r.get("kind") == "cso":
                row["kind"] = "cso"
                p = r["npdes_permit"]
                row["npdes_permits"] = [p] + row["npdes_permits"]
                row["npdes_permit"] = p
                row["outfall_count"] = r.get("outfall_count")
                row["outfalls_source"] = r.get("outfalls_source")
                row["receiving_waters"] = list(dict.fromkeys((r.get("receiving_waters") or []) + row["receiving_waters"]))
                row["notification_channel"] = CSO_SAC + LAW
                row["legal_form"] = "city"
            row["notes"] = (r.get("notes") or "").strip() + " " + row["notes"]
            row["verified"] = r.get("verified") or "fetched"
            counts["research rows joined to an agency"] += 1
            continue
        # USIBWC: an NPDES plant with no enrollment
        p = r.get("npdes_permit")
        prow = pl.get(p) or []
        notes = (r.get("notes") or "") + (" Permit confirmed in EPA ICIS-NPDES (data/outfalls-plants-us.json): "
                                          f"{prow[0].get('permit_name')}." if prow else "")
        row = base_row(rid, r["name"], r.get("kind") or "plant", [p] if p else [], r.get("towns") or [],
                       r.get("receiving_waters") or [], notes.strip(), legal_form=form(r["name"]) or "federal facility",
                       outfalls_source=f"EPA ICIS-NPDES Discharge Points (data/outfalls-plants-us.json, {len(prow)} rows)"
                       if prow else None, outfall_count=len(prow) or None, channel=LAW_PLANT, machine=False,
                       verified=r.get("verified") or "fetched")
        rows[f"research:{rid}"] = row
        counts["research rows on their own"] += 1
    if sf is not None:
        rs = [research[i] for i in SFPUC_IDS if i in research]
        old = sf["id"]
        sf.update(id="ca-sfpuc", name="San Francisco Public Utilities Commission",
                  short_name="San Francisco Public Utilities Commission (SFPUC)", kind="cso", legal_form="city",
                  towns=["San Francisco"], notification_channel=CSO_SF + LAW,
                  outfall_count=sum(r.get("outfall_count") or 0 for r in rs) or None,
                  outfalls_source="EPA National CSO Inventory (data/outfalls-us.json)")
        sf["aliases"] = ["ca-sfpuc", old, *SFPUC_IDS]
        perms = [r["npdes_permit"] for r in rs if r.get("npdes_permit")]
        sf["npdes_permits"] = perms + sf["npdes_permits"]
        sf["npdes_permit"] = perms[0] if perms else sf["npdes_permit"]
        sf["receiving_waters"] = list(dict.fromkeys([w for r in rs for w in r.get("receiving_waters") or []]
                                                    + sf["receiving_waters"]))
        sf["notes"] = ("The City and County of San Francisco's sewer utility: combined system (NPDES CA0037664 for "
                       "the Southeast WPCP, North Point and Bayside wet-weather facilities; CA0037681 for the Oceanside "
                       "WPCP and Westside; CA0038610 is an EPA inventory record of the Bayside CSO, probably part of "
                       "CA0037664) and separate systems enrolled under the General Order. " + sf["notes"])
        counts["research SFPUC rows folded into one"] += len(rs)

    # 3. EPA plant permits, grouped by owner, joined to an agency when the name says so
    groups: dict[str, list[str]] = defaultdict(list)
    for p, prs in sorted(pl.items()):
        if p in held or p in NOT_SEWAGE or p in PRIVATE:
            continue
        if any(p in r["npdes_permits"] for r in rows.values()):
            continue
        owner = prs[0].get("permit_name") or prs[0].get("permittee")
        k = key(owner) or p
        if k in ATTACH_BY_HAND:
            k = by_agency[ATTACH_BY_HAND[k]]["key"]
        groups[k].append(p)
    for k, perms in groups.items():
        prs = [r for p in perms for r in pl[p]]
        owner = prs[0].get("permit_name") or prs[0].get("permittee")
        waters = list(dict.fromkeys(r["receiving_water_echo"] for r in prs if r.get("receiving_water_echo")))[:8]
        target = rows.get(k)
        if target is None and k in by_agency:
            target = rows.get(by_agency[k]["key"])
        if target is not None:
            target["npdes_permits"] += perms
            target["receiving_waters"] = list(dict.fromkeys(target["receiving_waters"] + waters))
            target["notes"] += (f" NPDES plant permits {', '.join(perms)} (EPA ICIS-NPDES permittee {owner!r}; "
                                f"data/outfalls-plants-us.json, {len(prs)} outfall rows).")
            target["outfall_count"] = (target.get("outfall_count") or 0) + len(prs)
            target["outfalls_source"] = target.get("outfalls_source") or \
                "EPA ICIS-NPDES Discharge Points (data/outfalls-plants-us.json)"
            counts["plant permits joined to an agency"] += len(perms)
            continue
        rid = f"ca-{slug(k)}"
        if rid in have_ids or any(r["id"] == rid for r in rows.values()):
            rid = f"ca-{slug(k)}-{perms[0].lower()}"
        towns = sorted({title(r.get("city")) for r in prs if r.get("city")})
        facs = ", ".join(sorted({f"{r.get('permittee')} ({r['npdes_permit']})" for r in prs}))
        name = public_name(owner)
        row = base_row(rid, name, "plant", perms, towns, waters,
                       f"Permittee as EPA ICIS-NPDES names it ({owner}); plants: {facs}. Added from "
                       "data/outfalls-plants-us.json; no enrollment under the General Order matched by name.",
                       legal_form=form(owner), outfalls_source=f"EPA ICIS-NPDES Discharge Points "
                       f"(data/outfalls-plants-us.json, {len(prs)} rows)", outfall_count=len(prs),
                       channel=LAW_PLANT, machine=False)
        rows[f"plant:{k}"] = row
        counts["plant rows"] += 1

    # 4. private sewage permits
    for p, (name, lf, towns, note) in PRIVATE.items():
        if p in held:
            continue
        prs = pl.get(p) or []
        rid = f"ca-{p.lower()}" if lf == "facility (permittee not named)" else f"ca-{slug(name.split(' (')[0])}"
        waters = list(dict.fromkeys(r["receiving_water_echo"] for r in prs if r.get("receiving_water_echo")))
        row = base_row(rid, name, "plant", [p], towns, waters,
                       note + " Covered like any other operator: Health and Safety Code 5411.5 and Water Code 13271 "
                       "bind any person who causes a sewage discharge. Permittee as EPA ICIS-NPDES records it "
                       "(research/ca/private-utilities-candidates.json); the Regional Board's permit order was not read.",
                       legal_form=lf, verified=False, channel=LAW_PLANT, machine=False,
                       outfalls_source=f"EPA ICIS-NPDES Discharge Points (data/outfalls-plants-us.json, {len(prs)} rows)"
                       if prs else None, outfall_count=len(prs) or None)
        rows[f"private:{p}"] = row
        counts["private rows"] += 1

    for r in rows.values():
        r["npdes_permits"] = list(dict.fromkeys(r["npdes_permits"]))
        r["npdes_permit"] = r["npdes_permit"] if r["npdes_permit"] in r["npdes_permits"] else \
            (r["npdes_permits"][0] if r["npdes_permits"] else None)
        r["aliases"] = list(dict.fromkeys(r["aliases"]))
        r["notes"] = " ".join(r["notes"].split())
        r["receiving_waters"] = list(dict.fromkeys(r["receiving_waters"]))[:12]
        new.append(r)
    ids = Counter(r["id"] for r in new)
    dupe_ids = [i for i, n in ids.items() if n > 1]
    perms = Counter(p for r in new for p in r["npdes_permits"])
    dupe_perms = [p for p, n in perms.items() if n > 1]
    if dupe_ids or dupe_perms:
        raise SystemExit(f"duplicate ids {dupe_ids} or permits {dupe_perms}")
    new.sort(key=lambda r: r["id"])
    last = max((i for i, d in enumerate(dis) if d.get("state") == "CA"), default=len(dis) - 1)
    out = dis[:last + 1] + new + dis[last + 1:]
    print(json.dumps(dict(counts), indent=1), f"\nnew rows {len(new)}; not sewage: {sorted(NOT_SEWAGE)}")
    print("legal_form:", dict(Counter(r.get("legal_form") for r in new)))
    print("kind:", dict(Counter(r.get("kind") for r in new)))
    if not dry:
        DIS.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
