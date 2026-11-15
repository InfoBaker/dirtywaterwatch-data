"""Indiana operator rows for data/dischargers.json: one row per operator, every Indiana permit in exactly one row.

Usage: pipeline/.venv/bin/python -I scripts/add_in_operators.py [--dry-run]

Inputs
  1. data/outfalls-plants-us.json: EPA's ICIS-NPDES sewage permits with state IN (758 permits). EPA's permit_name is
     mostly the plant's ("SHELBYVILLE WWTP, CITY OF", "ARGOS WASTEWATER TREATMENT PLANT"), so the owner is read by
     the rules below.
  2. The combined sewer permits: data/outfalls-us.json (EPA's inventory, 138 Indiana permits) and data/outfalls-in.json
     (IDEM's CSO outfall layer, 106 permits); a permit with an open combined sewer outfall in either is kind cso.
  3. research/in/dischargers.json (139 rows: the 138 CSO permits and Highland's sewer overflow reports): each research
     id stays an alias of the row holding its permit (Highland's, which names no permit, of the Town of Highland row).
  4. research/in/private-utilities-candidates.json (126 private sewage permits), with their proposed legal forms.
  5. EPA's overflow tables (data/build/events/echo-sewer-overflow.json): a permit with an Indiana report there.
Rules
  - OWNERS: the operators whose names EPA's rows do not give, by permit (Citizens Energy Group's CWA Authority in
    Indianapolis, Evansville's water and sewer utility, the Gary and Hammond sanitary districts, the collection-system
    permits INM020346 and INM022560 filed under their cities).
  - A plant EPA names "<Place> WWTP, CITY OF" / "TOWN OF", "TOWN OF <Place>", or "<Place> WWTP" (and the like) with an
    owner typed a municipality, where <Place> is an Indiana incorporated place (data/reference/in-census-places.json,
    the Census Bureau's list with each place's legal description), is "City of <Place>" or "Town of <Place>" as the
    Census lists it, legal_form city or town (an operator is never named after a plant; a place the Census does not
    list keeps EPA's plant name and legal_form null).
  - Sanitary, conservancy, regional sewer or water districts (RSD, CD): special district; a public school corporation's
    plant: special district; an owner typed State Government: state facility; Federal: federal facility; a mobile-home
    park or community: mobile-home park; a campground: campground or resort; a company (LLC, Inc, Utilities): business
    or industrial, or the candidate file's proposed form when it gives one (investor-owned utility, homeowners'
    association ...).
  - Never an individual's name: a permittee that reads as a person's (common.scrub_discharger) is filed as "Holder of
    permit <permit>", legal_form "facility (permittee not named)".
  - kind: "cso" for a permit with an open combined sewer outfall, "sso" for a permit with reports in EPA's overflow
    tables, else "plant".
  - notification_channel: 327 IAC 5-2.1 for a combined sewer permittee (notice to the affected public and to those who
    ask after the March newspaper notice, signs at access points; no web channel and no clock); 327 IAC 5-2.2 and 40 CFR
    122.38 (notice within four hours) for one in the Lake Michigan or Lake Erie basin (IDEM's layer's Basin); the
    24-hour report of an overflow or bypass to IDEM on State Form 48373 for every permittee (no public notice duty;
    IDEM files the reports in its Virtual File Cabinet); the operator's own channel where the research found one.
  - Idempotent: a rerun replaces the rows it wrote (state IN, source_areas ["in"]) and leaves every other row as it is.
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
CSO_IN = ROOT / "data" / "outfalls-in.json"
RESEARCH = ROOT / "research" / "in" / "dischargers.json"
CANDIDATES = ROOT / "research" / "in" / "private-utilities-candidates.json"
EVENTS = ROOT / "data" / "build" / "events" / "echo-sewer-overflow.json"
PLACES_FILE = ROOT / "data" / "reference" / "in-census-places.json"
CHECKED = "2026-11-14"
GREAT_LAKES_BASINS = {"Southeastern Lake Michigan", "Southwestern Lake Michigan", "Western Lake Erie"}
VFC = "https://www.in.gov/idem/legal/public-records/virtual-file-cabinet"
SSO_LAW = ("Every overflow, bypass and sewage basement backup must be reported to the Indiana Department of "
           "Environmental Management within 24 hours on State Form 48373 (IDEM's sewer bypass/overflow reporting page, "
           "https://www.in.gov/idem/cleanwater/wastewater-compliance/sewer-bypassoverflow-incident-reporting/); IDEM "
           f"files the reports in its Virtual File Cabinet ({VFC}) and publishes no list of them. No duty to tell the "
           "public of a sanitary sewer overflow or bypass was found.")
CSO_LAW = ("327 IAC 5-2.1 requires a combined sewer community to notify the affected public, local health departments, "
           "drinking water suppliers with intakes within ten river miles downstream, and anyone who asks after its "
           "annual March newspaper notice, whenever an overflow is occurring or is imminent, in a manner agreed with "
           "each recipient, and to post signs at public access points; it names no web channel and no deadline. Each "
           "outfall's monthly totals are filed on a discharge monitoring report (published by EPA weeks later). ")
GL_LAW = ("In the Lake Michigan or Lake Erie basin, 327 IAC 5-2.2 applies 40 CFR 122.38: a public notice within four "
          "hours of becoming aware of an overflow, a supplemental notice within seven days, and an annual notice. ")
PRIVATE_NOTE = " The permit conditions and the state rule bind a private permittee as they bind a public one."
OWN = " The operator's own pages were not searched individually."

# operator channels the research and this build read (2026-11-03 and 2026-11-14); each states its barrier
CHANNELS = {
    "in-citizens-energy-group-cwa-authority": (
        "Citizens Energy Group issues CSO warnings by e-mail when about a quarter inch of rain or more is forecast "
        "(Citizens' 2018 post); no sign-up page or public list of the warnings was found, and the old CSO page "
        "answers 404. ", None),
    "in-city-of-fort-wayne": (
        "Fort Wayne City Utilities' CSO notifications page (https://utilities.cityoffortwayne.org/sewer-system/"
        "cso-notifications) posts a summary of the past seven days' overflows each Wednesday as a PDF, and a yearly "
        "report; the site answered this build's client with a bot check (HTTP 403, 2026-11-14). ",
        "https://utilities.cityoffortwayne.org/sewer-system/cso-notifications"),
    "in-city-of-south-bend": (
        "South Bend sends e-mail CSO notifications to people who sign up by telephone and posts its "
        "public notification plan, a yearly CSO notice and its monthly reports of operation as PDFs "
        "(https://southbendin.gov/department/public-works/utilities-division/waste-water/). ",
        "https://southbendin.gov/department/public-works/utilities-division/waste-water/"),
    "in-sanitary-district-of-hammond": (
        "The Hammond Sanitary District sends e-mail notice when its combined sewers discharge to anyone who requests "
        "it by post, and posts a yearly CSO notice (https://www.hammondsd.com/cso-notification-plan/). ",
        "https://www.hammondsd.com/cso-notification-plan/"),
    "in-city-of-mishawaka": (
        "Mishawaka Utilities posts its CSO alerts on an X account (@CSOAlerts), which can be read only when signed in, "
        "and its yearly CSO report and outfall map as PDFs (https://mishawaka.in.gov/government/departments/"
        "mishawaka-utilities/wastewater/cso-information/). ",
        "https://mishawaka.in.gov/government/departments/mishawaka-utilities/wastewater/cso-information/"),
    "in-city-of-la-porte": (
        "La Porte posts its combined sewer overflow status and a list of past overflows with volumes "
        "(https://www.cityoflaporte.com/departments/laporte-utilties/wastewater-division/combined-sewer-overflow-"
        "status); the host did not accept a connection from this build on 2026-11-14 (two tries). ",
        "https://www.cityoflaporte.com/departments/laporte-utilties/wastewater-division/combined-sewer-overflow-status"),
    "in-town-of-waterloo": (
        "Waterloo posts each overflow's start and end notice as a PDF on its CSO policy page "
        "(https://waterlooin.gov/cso-policy/: three pairs in 2026, March and April), with its yearly notice and "
        "monthly reports of operation. ", "https://waterlooin.gov/cso-policy/"),
    "in-city-of-goshen": (
        "Goshen has posted dated CSO public notices naming the permit and outfall (seen 2018, research of "
        "2026-11-03). ", None),
    "in-city-of-evansville": (
        "Evansville Water and Sewer Utility's Clear Path program has a combined sewer overflow page "
        "(https://www.ewsu.com/); its notification channel was not traced. ", None),
}

# permit -> (row id, name, short name, legal form, note); a later permit of the same row repeats the id with None
OWNERS = {
    "IN0023183": ("in-citizens-energy-group-cwa-authority", "CWA Authority, Inc. (Citizens Energy Group), Indianapolis",
                  "Citizens Energy Group", None,
                  "Indianapolis's wastewater utility, CWA Authority, Inc., operated by Citizens Energy Group since 2011: "
                  "the Belmont and Southport plants and the combined sewer system (131 open outfalls in EPA's "
                  "inventory). Its legal form (a nonprofit corporation of a public charitable trust) is not one of the "
                  "list's values and is left blank."),
    "IN0031950": ("in-citizens-energy-group-cwa-authority", None, None, None, None),
    "IN0055824": ("in-hidden-falls-camp", "Hidden Falls Camp", "Hidden Falls Camp", "institution",
                  "A charity's camp (EPA: \"Salvation Army Hidden Falls Camp\"), named for the camp."),
    "IN0032956": ("in-city-of-evansville", "City of Evansville (Evansville Water and Sewer Utility)",
                  "Evansville Water and Sewer Utility", "city", "The Westside and Eastside plants."),
    "IN0033073": ("in-city-of-evansville", None, None, None, None),
    "IN0022977": ("in-gary-sanitary-district", "Gary Sanitary District", "Gary Sanitary District", "special district",
                  "A sanitary district (IC 36-9-25)."),
    "IN0023060": ("in-sanitary-district-of-hammond", "Sanitary District of Hammond", "Hammond Sanitary District",
                  "special district", "A sanitary district (IC 36-9-25)."),
    "INM020346": ("in-city-of-new-haven", None, None, None, None),
    "INM022560": ("in-town-of-chesterfield", None, None, None, None),
    "INM024520": ("in-city-of-south-bend", None, None, None, None),
}
EXTRA_ROWS = {   # rows OWNERS names that the place rule writes too; their metadata when no plant gives it
    "in-city-of-new-haven": ("City of New Haven", "city"),
    "in-town-of-chesterfield": ("Town of Chesterfield", "town"),
    "in-city-of-south-bend": ("City of South Bend", "city"),
}
PLANT_WORDS = re.compile(r"\s+(?:WWTP|WWTF|WPCF|WPC|STP|WRF|WRRF|MUNICIPAL WWTP|MUNICIPAL|WASTEWATER TREATMENT PLANT|"
                         r"WASTEWATER TREATMENT FACILITY|WASTEWATER PLANT|WASTEWATER TREATMENT|WATER POLLUTION CONTROL"
                         r"(?: FACILITY| PLANT)?|SANITARY SYSTEM|SANITARY SEWER SYSTEM|SEWAGE TREATMENT PLANT|"
                         r"UTILITIES|UTILITY|COMBINED SEWER SYSTEM|COMBINED SEWER SYS|COMBINED COLLECTION SYSTEM|CSS|CSO|"
                         r"WATER RECLAMATION FACILITY|WATER RESOURCE RECOVERY FACILITY)\b.*$", re.I)
DISTRICT = re.compile(r"\b(sanitary district|conservancy district|regional sewer district|regional sewage district|"
                      r"regional waste district|regional water (?:&|and) sewer district|regional water district|"
                      r"water district|sewer district|utility district|reg utility district|reg\.? ?sew(?:er)?\.? dist|rsd|hcrsd|"
                      r"rwsd|rwd|cd|c d)\b", re.I)
INSTITUTION = re.compile(r"\b(salvation army|school,? inc|convent|archabbey|abbey|christian|parish|church|assembly|asembly|conference center|"
                         r"hope center|health care|community health|family serv|retreat|camp \w+ (?:ministr|bible))", re.I)
STORE = re.compile(r"\b(store|travel stops?|travel center|traveler'?s mall|mall|lumber|restaurant|motel|hotel|"
                   r"truck stop|plaza)\b", re.I)
COUNTY_BODY = re.compile(r"\bcounty (?:home|wwtp|water pollution control|sewer|commissioners)\b|^\w+ county wwtp$", re.I)
# a plant's name that carries a person's name ('J.B. Gifford', '(Blucher Poole)'): the notes give its permit only
PERSON_PLANT = re.compile(r"\b[A-Z]\.\s?[A-Z]\.?\s+[A-Z][a-z]+\b|\([A-Z][a-z]+ [A-Z][a-z]+\)", re.I)
# EPA plant names whose permits join one operator row, by name: (pattern, (id, name, legal form, note))
NAME_ROWS = [
    (re.compile(r"^AQUA INDIANA\b", re.I), ("in-aqua-indiana", "Aqua Indiana, Inc.", "investor-owned utility",
                                             "A regulated water and sewer company (Essential Utilities); EPA records "
                                             "its plants by division.")),
    (re.compile(r"^(INDIANA AMERICAN WATER|IAW)\b", re.I), ("in-indiana-american-water", "Indiana-American Water "
                                                             "Company", "investor-owned utility",
                                                             "A regulated water and sewer company (American Water).")),
    (re.compile(r"^NINESTAR CONNECT\b", re.I), ("in-ninestar-connect", "NineStar Connect", "member-owned utility",
                                                 "A member-owned cooperative utility (Hancock County).")),
    (re.compile(r"^WHITE LICK SEWER", re.I), ("in-white-lick-sewer", "White Lick Sewer, Inc.", "investor-owned utility",
                                              None)),
]
SCHOOL = re.compile(r"\b(school|schools|elementary|jr/sr|jr\.?-sr|h\.?\s?s\.?|high sch|high school|middle school|"
                    r"school corp)\b", re.I)
MHP = re.compile(r"\b(mobile home|mobile home park|mhp|mhc|manufactured home|trailer (?:park|court)|estates mhp)\b", re.I)
CAMP = re.compile(r"\b(campground|kampground|camp|rv park|resort|marina)\b", re.I)
COMPANY = re.compile(r"\b(llc|inc|corp|co\.?|company|l\.?p\.?|ltd)\b\.?$|\butilities\b|\butility\b", re.I)
PUBLIC_FORMS = {"city", "town", "county", "authority", "special district", "federal facility", "state facility",
                "tribal"}
PRIVATE_FORMS = {"investor-owned utility", "member-owned utility", "homeowners' association", "mobile-home park",
                 "campground or resort", "private club", "business or industrial", "institution",
                 "facility (permittee not named)"}
ABBR = {"wwtp", "wwtf", "wpcf", "stp", "rsd", "cd", "mhp", "mhc", "llc", "rv", "sr", "jr", "ii", "iii", "cwa"}


def smart_title(s: str) -> str:
    out = []
    for i, w in enumerate((s or "").split()):
        bare = re.sub(r"[^A-Za-z0-9]", "", w).lower()
        if bare in ABBR:
            out.append(w.upper())
        elif bare in ("of", "and", "the", "at") and i:
            out.append(w.lower())
        else:
            out.append(w.capitalize() if w.isupper() or w.islower() else w)
    return " ".join(out)


def slug(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", (s or "").lower())).strip("-")


def person(name: str) -> bool:
    return bool(name) and scrub_discharger({"discharger_name": name})["discharger_name"] == NAME_REMOVED


_PLACES: dict[str, tuple[str, str]] | None = None


def places() -> dict[str, tuple[str, str]]:
    """compact name -> (the Census spelling, 'city' or 'town') of each Indiana incorporated place."""
    global _PLACES
    if _PLACES is None:
        doc = json.loads(PLACES_FILE.read_text())
        _PLACES = {re.sub(r"[^a-z]", "", k.lower()): (k, v) for k, v in doc["places"].items()}
    return _PLACES


def place(town: str) -> tuple[str, str] | None:
    """The Indiana incorporated place a plant's stem names ('LAPORTE' -> ('La Porte', 'city')), or None. The whole stem
    must be the place: 'Brown County State Park' is no place, and a county's name is never a city's."""
    t = re.sub(r"[^a-z]", "", (town or "").lower())
    if not t or re.search(r"\bcounty\b|\btownship\b", town or "", re.I):
        return None
    return places().get(t) or places().get(re.sub(r"^saint", "st", t)) or places().get(re.sub(r"^st", "saint", t))


def place_prefix(stem: str) -> tuple[str, str] | None:
    """The longest leading run of words of a plant's stem that is an Indiana incorporated place ('JEFFERSONVILLE
    DOWNTOWN' -> Jeffersonville, 'MICHIGAN CITY - J.B. GIFFORD' -> Michigan City), never a county's name; None
    otherwise (an operator is never named after a plant)."""
    if re.search(r"\bcounty\b|\bco\.?\s|\btownship\b|\btwp\b", stem or "", re.I):
        return None
    words = re.sub(r"[-#(/,].*$", "", stem or "").split()
    for n in range(len(words), 0, -1):
        hit = place(" ".join(words[:n]))
        if hit:
            return hit
    return None


def bare(pn: str) -> str:
    """A plant name without its plant words ('Lake Bruce CD WWTP' -> 'Lake Bruce CD'): an operator is never named
    after a plant (review 2026-11-14 P2-7)."""
    out = PLANT_WORDS.sub("", " " + (pn or "")).strip(" -#,")
    return out or pn


PERMIT_ONLY = "facility (permittee not named)"
UNESTABLISHED = ("EPA records the permittee as the plant ({kind}; owner typed \"{t}\"); the plant's name does not "
                 "establish who holds the permit, so the row names the permit's holder, not the plant, and is not "
                 "counted as a named operator.")


def owner_of_plant(pn: str, ftype: str | None) -> tuple[str | None, str | None, str | None, str | None]:
    """(id, name, legal form, note) for a plant EPA names (module docstring); (None, None, None, note) when the owner
    cannot be read from the name, so the row is the permit's holder, unnamed."""
    pn = " ".join((pn or "").split())
    flat = pn.replace(".", "")
    t = ftype or ""
    for pat, (rid, name, lf, note) in NAME_ROWS:
        if pat.search(pn):
            return rid, name, lf, note
    m = re.match(r"^(.+?),\s*(CITY|TOWN) OF$", pn, re.I) or re.match(r"^(?:TOWN COUNCIL OF|(?:CITY|TOWN) OF)\s+(.+)$", pn, re.I)
    if m:
        hit = place_prefix(PLANT_WORDS.sub("", " " + m.group(1)).strip())
        if hit:
            return f"in-{hit[1]}-of-{slug(hit[0])}", f"{hit[1].capitalize()} of {hit[0]}", hit[1], None
    if DISTRICT.search(flat):
        name = smart_title(bare(pn))
        return f"in-{slug(name)}", name, "special district", None
    if t.startswith("State"):
        return None, None, PERMIT_ONLY, UNESTABLISHED.format(kind="a state facility", t=t)
    if t.startswith("Federal"):
        return None, None, PERMIT_ONLY, UNESTABLISHED.format(kind="a federal facility", t=t)
    if re.search(r"\breuse authority\b|\bauthority\b", pn, re.I):
        name = smart_title(bare(pn))
        return f"in-{slug(name)}", name, "authority", None
    if re.search(r"\bschool corp(?:oration)?\b", pn, re.I) and not INSTITUTION.search(pn):
        name = smart_title(bare(pn))
        return f"in-{slug(name)}", name, "special district", "A public school corporation's plant."
    # a facility's own name (an institution, a school building, a park, a campground) does not establish who holds
    # its permit (re-review 2026-11-14 P2-6): the row is the permit's holder, unnamed, the facility kept in the notes
    if COMPANY.search(pn) and (INSTITUTION.search(pn) or MHP.search(pn) or CAMP.search(pn)) \
            and not t.startswith(("State", "Federal")):
        name = smart_title(bare(pn))
        lf = ("mobile-home park" if MHP.search(pn) else "campground or resort" if CAMP.search(pn) else "institution")
        return f"in-{slug(name)}", name, lf, None
    if INSTITUTION.search(pn):
        return None, None, PERMIT_ONLY, UNESTABLISHED.format(kind="an institution's plant", t=t or "not given")
    if SCHOOL.search(pn) or re.search(r"\beducational center\b", pn, re.I):
        return None, None, PERMIT_ONLY, UNESTABLISHED.format(kind="a school's plant", t=t or "not given")
    if MHP.search(pn):
        return None, None, PERMIT_ONLY, UNESTABLISHED.format(kind="a mobile-home park's plant", t=t or "not given")
    if CAMP.search(pn) or re.search(r"\bjellystone\b|\bwater park\b", pn, re.I):
        return None, None, PERMIT_ONLY, UNESTABLISHED.format(kind="a campground's or resort's plant", t=t or "not given")
    if COUNTY_BODY.search(pn):
        name = smart_title(bare(pn))
        return f"in-{slug(name)}", name, "county", None
    if STORE.search(pn) and not COMPANY.search(pn):
        return None, None, PERMIT_ONLY, UNESTABLISHED.format(kind="a business's plant", t=t or "not given")
    stem = PLANT_WORDS.sub("", " " + pn).strip(" -#0123456789")
    hit = place_prefix(stem) if (t.startswith("Municipal") or t == "POTW" or not t) else None
    if hit:
        return (f"in-{hit[1]}-of-{slug(hit[0])}", f"{hit[1].capitalize()} of {hit[0]}", hit[1],
                f"EPA records the plant under the {hit[1]}'s name and types its owner a municipality: filed under the "
                f"{hit[1]} (an incorporated place in the Census Bureau's list).")
    if COMPANY.search(pn):
        name = smart_title(bare(pn))
        return f"in-{slug(name)}", name, "business or industrial", None
    return (None, None, None,
            f"EPA records the permittee as the plant and types the owner \"{t or 'not given'}\"; the owner was not "
            "read, so the row names the permit's holder, not the plant.")


def outfall_counts(r: dict) -> bool:
    """A plant row that is a sewage discharge point: it names an outfall and is no groundwater or dewatering outlet
    (review 2026-11-14 P2-7: a collection-system row with no outfall number, Loogootee's dewatering outlet)."""
    if not str(r.get("outfall") or "").strip():
        return False
    sets = " ".join(str(x) for x in r.get("limit_set_names") or [])
    return not re.search(r"\bgroundwater\b|\bdewater", sets, re.I)


def build(dis: list[dict]) -> tuple[list[dict], dict]:
    keep = [d for d in dis if not (d.get("state") == "IN" and "in" in (d.get("source_areas") or []))]
    held_elsewhere = {str(p).upper() for d in keep for p in [d.get("npdes_permit"), *(d.get("npdes_permits") or [])] if p}
    plants: dict[str, list[dict]] = defaultdict(list)
    for r in json.loads(PLANTS.read_text())["outfalls"]:
        if r.get("state") == "IN" and str(r.get("npdes_permit") or "").startswith("IN"):
            plants[r["npdes_permit"]].append(r)
    cso: dict[str, list[dict]] = defaultdict(list)
    for r in json.loads(CSO.read_text())["outfalls"]:
        if r.get("state") == "IN":
            cso[r["npdes_permit"]].append(r)
    idem: dict[str, list[dict]] = defaultdict(list)
    for r in json.loads(CSO_IN.read_text())["outfalls"]:
        idem[r["npdes_permit"]].append(r)
    research: dict[str, list[dict]] = defaultdict(list)
    for r in json.loads(RESEARCH.read_text()):
        research[r.get("npdes_permit") or "HIGHLAND"].append(r)
    cand = json.loads(CANDIDATES.read_text())
    cands = {c["npdes_permit"]: c for c in cand["candidates"] + cand.get("public_by_name", [])}
    reports = Counter(r["npdes_permit"] for r in (json.loads(EVENTS.read_text()).get("records", [])
                                                  if EVENTS.exists() else [])
                      if str(r.get("npdes_permit") or "").startswith("IN"))
    permits = sorted((set(plants) | set(cso) | set(idem) | (set(research) - {"HIGHLAND"}) | set(cands) | set(reports))
                     - held_elsewhere)

    meta: dict[str, dict] = {}
    for p, (rid, name, short, lf, note) in OWNERS.items():
        if name:
            meta[rid] = {"name": name, "short": short, "lf": lf, "note": note}
    for rid, (name, lf) in EXTRA_ROWS.items():
        meta.setdefault(rid, {"name": name, "short": name, "lf": lf, "note": None})
    by_row: dict[str, list[str]] = defaultdict(list)
    for p in permits:
        rows = plants.get(p) or cso.get(p) or []
        pn = (rows[0].get("permit_name") or rows[0].get("permittee") or "") if rows else ""
        ftype = (plants.get(p) or [{}])[0].get("facility_type")
        c = cands.get(p)
        if p in OWNERS:
            rid = OWNERS[p][0]
        elif c and (NAME_REMOVED in (c.get("permittee_as_recorded") or "") or person(c.get("permittee_as_recorded"))):
            fac = c.get("facility") or ""
            name = (f"{smart_title(bare(fac))} (permit {p})" if fac and NAME_REMOVED not in fac and not person(fac)
                    else f"Holder of permit {p}")
            rid = f"in-{p.lower()}"
            meta.setdefault(rid, {"name": name, "short": name, "lf": "facility (permittee not named)",
                                  "note": "EPA's permittee name reads as an individual's: not named here.",
                                  "person": True})
        elif pn and person(pn):
            rid = f"in-{p.lower()}"
            meta.setdefault(rid, {"name": f"Holder of permit {p}", "short": f"Holder of permit {p}",
                                  "lf": "facility (permittee not named)", "note": None, "person": True})
        elif pn:
            if (p in cso or p in idem) and (ftype or "").startswith("Mixed"):
                ftype = "Municipal or Water District"   # a combined sewer is a city's or town's old system
            rid, name, lf, note = owner_of_plant(pn, ftype)
            if rid is None:
                rid, name, lf = f"in-{p.lower()}", f"Holder of permit {p}", PERMIT_ONLY
            if c and c.get("legal_form_proposed") and lf in (None, "business or industrial") and rid != f"in-{p.lower()}":
                lf = c["legal_form_proposed"]
            meta.setdefault(rid, {"name": name, "short": name, "lf": lf, "note": note})
        elif c:
            name = smart_title(c.get("facility") or "") or f"Holder of permit {p}"
            rid = f"in-{slug(name)}"
            meta.setdefault(rid, {"name": name, "short": name, "lf": c.get("legal_form_proposed"),
                                  "note": "EPA types it privately owned."})
        else:
            rid = f"in-{p.lower()}"
            meta.setdefault(rid, {"name": f"Holder of permit {p}", "short": f"Holder of permit {p}", "lf": PERMIT_ONLY,
                                  "note": "The permit's record was not read, so the holder is not named here."})
        by_row[rid].append(p)
    by_row["in-town-of-highland"]   # Highland's sewer overflow reports (research), no permit in EPA's lists
    meta.setdefault("in-town-of-highland", {"name": "Town of Highland", "short": "Town of Highland", "lf": "town",
                                            "note": "The town posts its State Form 48373 overflow reports as PDFs "
                                                    "(research of 2026-11-03)."})
    research_ids = {p: [r["id"] for r in rs] for p, rs in research.items()}
    research_channel = {p: rs[0].get("notification_channel") for p, rs in research.items()
                        if rs and rs[0].get("verified") in ("fetched", "search_only")}

    new = []
    for rid, ps in sorted(by_row.items()):
        m = meta[rid]
        prow = [r for p in ps for r in plants.get(p, []) if outfall_counts(r)]
        crow = [r for p in ps for r in idem.get(p, [])] or [r for p in ps for r in cso.get(p, [])]
        if [p for p in ps if p in idem]:
            crow = [r for p in ps for r in (idem.get(p) or cso.get(p, []))]
        open_cso = [r for r in crow if not str(r.get("outfall_status") or "").upper().startswith("CLS")
                    and r.get("outfall_kind", "cso") == "cso"]
        towns = sorted({smart_title(r["city"]) for r in prow + crow if r.get("city")
                        and "COUNTY" not in str(r["city"]).upper() and str(r["city"]).upper() != "UNKNOWN"}
                       | {smart_title(cands[p]["city"]) for p in ps if p in cands and cands[p].get("city")})
        own = re.match(r"^(?:City|Town) of ([^(,]+?)(?: \(|$)", m["name"])
        if own and own.group(1) not in towns:
            towns.append(own.group(1))
        waters = list(dict.fromkeys([str(r["receiving_water_echo"]).strip() for r in crow + prow
                                     if r.get("receiving_water_echo")]))[:10]
        basins = {r.get("basin") for r in crow if r.get("basin")}
        great_lakes = bool(basins & GREAT_LAKES_BASINS)
        def fac(p):
            r0 = (plants.get(p) or cso.get(p) or [{}])[0]
            n = smart_title(r0.get("permit_name") or r0.get("permittee") or "")
            return p if not n or PERSON_PLANT.search(n) else f"{p} {n}"
        # the plant's name is kept in the notes, except where it is a person's (the permittee read as an individual)
        facs = "; ".join(fac(p) for p in ps) if not m.get("person") else ps[0]
        note = f"EPA ICIS-NPDES: {facs}." if ps else ""
        n_reports = sum(reports[p] for p in ps)
        if n_reports:
            note += f" EPA's overflow tables (2026-11-12 extract): {n_reports} Indiana report(s)."
        if open_cso:
            src = "IDEM's CSO outfall layer" if any(p in idem for p in ps) else "EPA's national CSO inventory"
            note += f" {len(open_cso)} open combined sewer outfall(s) in {src}."
            if great_lakes:
                note += " Great Lakes basin (" + ", ".join(sorted(basins & GREAT_LAKES_BASINS)) + ")."
        if m.get("note"):
            note += " " + m["note"]
        kind = "cso" if open_cso else ("sso" if n_reports else "plant")
        private = m["lf"] in PRIVATE_FORMS
        own_channel, signup = CHANNELS.get(rid, ("", None))
        if not own_channel:
            rc = next((research_channel[p] for p in ps if p in research_channel), None)
            if rc:
                own_channel = f"Research of 2026-11-03: {rc.rstrip('.')}. "
        channel = own_channel + (CSO_LAW + (GL_LAW if great_lakes else "") if open_cso else "") + SSO_LAW \
            + (PRIVATE_NOTE if private else "") + ("" if own_channel else OWN)
        aliases = [rid] + [a for p in ps for a in research_ids.get(p, [])]
        if rid == "in-town-of-highland":
            aliases += research_ids.get("HIGHLAND", [])
        new.append({"id": rid, "name": m["name"], "short_name": m["short"] or m["name"], "legal_form": m["lf"],
                    "state": "IN", "kind": kind, "npdes_permit": ps[0] if ps else None, "npdes_permits": list(ps),
                    "receiving_waters": waters, "water_slugs": [],
                    "outfall_count": (len(open_cso) or len(prow)) or None,
                    "outfalls_source": ((f"IDEM's CSO outfall layer (data/outfalls-in.json, {len(open_cso)} open)"
                                         if any(p in idem for p in ps) else
                                         f"EPA National CSO Inventory (data/outfalls-us.json, {len(open_cso)} open)")
                                        if open_cso else f"EPA ICIS-NPDES discharge points (data/outfalls-plants-us.json, "
                                        f"{len(prow)} rows)" if prow else None),
                    "notification_channel": channel,
                    "notification_feed_machine_readable": bool(open_cso or n_reports),
                    "notification_signup_url": signup, "towns": towns, "notes": note.strip(), "verified": "fetched",
                    "checked": CHECKED, "aliases": list(dict.fromkeys(aliases)), "source_areas": ["in"]})
    ids = Counter(r["id"] for r in keep + new)
    dup = [i for i, n in ids.items() if n > 1]
    if dup:
        raise SystemExit(f"duplicate ids: {dup}")
    stats = {"rows": len(new), "permits": sum(len(r["npdes_permits"]) for r in new),
             # permit-only rows (the responsible body not established) are not counted as named operators
             "named_operators": sum(1 for r in new if r.get("legal_form") != PERMIT_ONLY),
             "permit_only_rows": sum(1 for r in new if r.get("legal_form") == PERMIT_ONLY),
             "legal_form": dict(Counter(r.get("legal_form") for r in new)), "kind": dict(Counter(r["kind"] for r in new)),
             "held_elsewhere": sorted(p for p in set(plants) if p in held_elsewhere),
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
