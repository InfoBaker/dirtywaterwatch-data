"""Utah hooks for fetch blocks (docs/generic-ingesters.md; not a feed).

ut_incident_record and ut_incidents_post: the Utah Department of Environmental Quality's Environmental Incidents layer
(data/sources/ut-deq-environmental-incidents.yaml; ArcGIS, services2.arcgis.com/NnxP4LZ3zX8wWmP9 EnvironmentalIncidents
layer 0): the log of the Division of Environmental Response and Remediation's spill hotline and after-hours duty
officers since 1991, one row per incident with a point, edited daily. 8,980 rows on 2026-11-07, every kind of spill.
  - The sewage rows. The layer has no type field: its SITEDESC is the one value "Environmental Incidents" on every row,
    and the incident summary (the only field that says what was released, how much and where it went) carries staff
    names, callers and private addresses and is never requested. A row is a sewage report when its title
    (Title_EventName) names sewage by the words of SEWAGE_WORDS and none of NOT_SEWAGE (the fetch block's filter,
    which keeps the same two lists, so only those rows reach data/raw/). The 2026-11-07 fetch: 8,980 rows; 425 titles
    name sewage words; 385 kept as sewage reports; 40 dropped (NOT_SEWAGE: 29 industrial, process or trade wastewater,
    5 backups inside buildings, 3 drinking-water plants, 3 other materials in a sewer or plant). The counts by reason are
    in the source file. A model pass could later read titles the rules leave unclear ("Waste Water Discharge"); a
    model never supplies a place or a colour.
  - Kind (raw._ut_kind) and event_type: a bypass named in the title -> bypass; a treatment plant, lagoon, effluent or
    reclamation facility -> plant_bypass; the rest -> sso. A title that says only "wastewater" is kept as sewage
    (err on the side of safety; raw._kind_note says the title does not say sewage).
  - Provenance: private dumping, RV and camper dumping, portable toilets and complaints or tips are reports the public
    phoned in (CITIZEN_WORDS): raw.report_provenance "citizen", so the status build shows them with the site's caution
    only (citizen_caution), never as an authority's confirmation. The other rows are DEQ's log of a call whose caller
    the layer does not name (a utility, an agency or a member of the public): raw.report_provenance stays unset.
  - Times. Date_Discovered is the day the incident was discovered (text, MM/DD/YYYY): started_at is that day,
    precision day, read in Mountain time (raw.time_zone America/Denver: Utah keeps one zone). Date_Discovered_For_Filter
    is an epoch the layer keeps for its date filter: until 2023 every value is midnight Eastern time (04:00 or 05:00
    UTC), a date only; since 2024 it carries a time rounded to the quarter hour whose clock the layer does not state
    (read as UTC it puts the American Fork bypass break of 2026-08-17 at 11:00 Mountain time, before the 14:39 start
    the operator reported to EPA; read as Mountain wall-clock time it is 17:00). The time of day is therefore not used:
    it is kept as given in raw._decoded_times and the record is dated to the day. No row gives an end, a report time or
    a volume (the volume is only in the summary): ended_at, reported_at and volume_gal stay null, status unknown, so the
    status build applies its no-end caution from the start of the discovery day. 41 of the kept rows (most of them
    entered before 1995 or migrated without a date) have no date at all: kept, undated, never coloured.
  - Placement: every row carries a point (the layer's geometry, read in WGS 84; DEQ calls the locations approximate),
    so the status build places a row from its point; a water named in the title (WATER_IN_TITLE: "Sewage Release to Bear
    Lake", "Sewage in Gordon Creek") is the row's waterbody_text, matched by name within the status build's distance
    guard. The layer gives no operator or permit; a row is never tied to a plant by its town.
  - Privacy: only the safe fields are requested (Id, DERRID, Title_EventName, Nearest_City, County, Date_Discovered,
    Date_Discovered_For_Filter, SITEDESC, ReportLink, Northing, Easting and the point). Never requested: Responsible_Party
    (businesses and private persons), Address_Location (private addresses), Incident_summary (staff, callers,
    complainants, addresses), Salesforce_Id and Map_Label. The title gets the strict scrub (owners' and residents' names
    and house numbers cut), and a title that is only a person's or a family business's name ("X and Y's Vacuum Truck")
    is cut to the words after it (PERSON_TITLE).
  - ut_incidents_post links a row to EPA's eRule report of the same overflow (the echo-sewer-overflow feed's events
    file, run before the generic blocks): a Utah permit's report that began on the same Mountain-time day, or the day
    before, within ECHO_LINK_M of the row's point. The DEQ row is then duplicate_of EPA's record, which carries the
    operator, the minute and the volume. One such pair on 2026-11-07 (American Fork, 2026-08-17).

ut_rec_record: DWQ's recreational waters layer (data/sources/ut-dwq-recreational-advisories.yaml; AutoMap_Source_Data
layer 0), one row per monitored site with its current advisory as local health departments and DWQ post it:
  - "Warning HAB", "Danger HAB", "HAB HW" (health watch), "Warning Mats": hab_advisory (the bloom category), the
    authority's own advisory, advisory_active while the layer shows it (history.confirm_while_listed).
  - "Warning E coli", "E coli HW": beach_advisory (the bacteria category), advisory_active while listed.
  - "Mats CF": a code whose meaning DWQ does not publish on the layer or its map (raw.code_undecoded): shown with the
    site's caution only, never red.
  - "Looks Good" and an empty advisory are not records (the block's filter): no current advisory, grey, never clean.
  Advisory_Date is the advisory's date, stored as midnight Mountain time: read as that date (precision day).
  Monitored_Date (the latest sample) is kept in raw._last_monitored. Advisory_Picture (photo links) is never requested.
"""
from __future__ import annotations

import json
import math
import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from common import EVENTS_DIR
from ingest.generic import fieldmap as F

ZONE = "America/Denver"
TZ = ZoneInfo(ZONE)
ZONE_NOTE = "Mountain time (Utah keeps one zone); dates only"

# the sewage words of a title (the fetch block's include filter is this pattern)
SEWAGE_WORDS = (r"\bsew(?:age|er|ers)\b|\bSSOs?\b|\bseptic\b|\bwaste\s*-?\s*water\b|\blift\s+station|\bmanhole|"
                r"\beffluent\b|\bbypass\b|\bblack\s*water\b|\bmotorhome\b|\bcamper\b|\bRV\b|"
                r"\bport(?:a|able)[\s-]*(?:pott\w*|john|toilet)|\bhoney\s*bucket|\bchemical\s+toilet|\bbiosolids?\b|"
                r"\blagoons?\b|\bWWTP\b|\bPOTW\b|\btreatment\s+plant|\bwater\s+reclamation|\breclamation\s+facility|"
                r"\bfecal\b|\bsanitary\b|\bsanitized\s+sewer")
# the titles that name sewage words but report something else (the fetch block's exclude filters), by reason
NOT_SEWAGE = {
    "industrial, process or trade wastewater": (
        r"\bindustrial\b|\bprocess(?:ed)?\b|\bcarpet\s+clean|\bconcrete\b|\bcement\b|\bcar\s+wash|\bdairy\b|"
        r"\bacidic\b|\balkaline\b|\blow\s+ph\b|\bhydrocarbon\b|\breverse\s+osmosis\b|\bIWWTP\b|\btoxicity\b|"
        r"\bfood\s+truck\b|\bgr[ae]y\s*water\b|\bdumpsters?\b"),
    "a drinking-water plant": r"(?<!waste )(?<!waste)\bwater\s+treatment\s+plant\b",
    "another material in a sewer, drain or plant": (
        r"\bdiesel\b|\bfuel\b|\boil\b|\bsheen\b|\bfirefighting\s+foam\b|\bchemicals?\b(?!\s+toilet)|\bethylene\b|"
        r"\bhydraulic\b|\bbird\s+deaths\b|\bliquid\s+from\s+sewer\s+drain\b|\bstorm\s+sewer\s+dumping\b|\bfire\b"),
    "a backup inside a building (basement or home)": r"\bbasements?\b|\bin(?:to)?\s+homes?\b|\b\d+\s+residences\b",
}
SEWAGE_RE = re.compile(SEWAGE_WORDS, re.I)
NOT_SEWAGE_RE = {k: re.compile(v, re.I) for k, v in NOT_SEWAGE.items()}
BYPASS = re.compile(r"\bbypass\b", re.I)
PLANT = re.compile(r"\btreatment\s+(?:plant|facility)|\bWWTP\b|\bWWTF\b|\bPOTW\b|\blagoons?\b|\beffluent\b|"
                   r"\breclamation\b|\bplant\b", re.I)
WASTEWATER_ONLY = re.compile(r"\bwaste\s*-?\s*water\b", re.I)
SEWAGE_NAMED = re.compile(r"\bsew(?:age|er)|\bSSOs?\b|\bseptic\b|\bsanitary\b|\bmanhole|\blift\s+station|\bblack\s*water|"
                          r"\bport(?:a|able)|\bhoney\s*bucket|\bchemical\s+toilet|\bRV\b|\bcamper\b|\bmotorhome\b|"
                          r"\bbiosolids?\b|\bfecal\b", re.I)
CITIZEN_WORDS = re.compile(r"\bcomp(?:laint|\.)|\btip\b|\balleged\b|\bdump(?:s|ed|ing)?\b|\billegal\b|\billicit\b|"
                           r"\bimproper\b|\bunpermitted\b|\bRV\b|\bcamper\b|\bmotorhome\b|\bhouseboat\b|"
                           r"\bport(?:a|able)[\s-]*(?:pott\w*|john|toilet)|\bhoney\s*bucket|\bchemical\s+toilet|"
                           r"\bvacuum\s+truck\b|\bon\s+(?:private\s+)?property\b|\bresidence\b", re.I)
CITIZEN_NOTE = ("phoned in to DEQ's spill hotline as a dumping, a private system's release or a complaint; no authority "
                "has confirmed the discharge")
# a water named in the title: up to three capitalised words before a water noun, or "Lake <Name>"
WATER_IN_TITLE = re.compile(
    r"\b((?:[A-Z][A-Za-z.']*\s+){1,3}(?i:river|creek|lake|reservoir|slough|canal|wash|pond))\b"
    r"(?!\s+(?:City|County|Sewer|Water|Improvement|District|Lift|Special|Town))|"
    r"\b(Lake\s+Powell)\b")
NOT_A_WATER = re.compile(r"^(?:(?:north|south|west|[nsw]\.?)\s+)?salt\s+lake$|^lake\s+point$", re.I)
PLACE_WATERS = {"salt lake", "north salt lake", "south salt lake", "west salt lake"}
# a title that is a person's or family business's name: "First and First's ..." (pre-2013 rows title the party)
PERSON_TITLE = re.compile(r"^\s*[A-Z][a-z]+(?:\s+(?:and|&)\s+[A-Z][a-z]+)?'s\s+", re.U)
FILTER_TIME_NOTE = ("the layer's filter time as stored (epoch read as UTC): midnight Eastern time on rows before 2024 (a date "
                    "only); since 2024 a time rounded to the quarter hour whose clock the layer does not state; not used")
ECHO_FILE = EVENTS_DIR / "echo-sewer-overflow.json"
ECHO_LINK_M = 10_000
STARTED_BASIS = ("started_at is the day DEQ logged the incident as discovered (Date_Discovered), in Mountain time; the "
                 "layer's filter time is not used (its clock is not stated)")


def county_name(raw) -> str | None:
    c = F.clean(raw)
    if not c or c.lower() == "none":
        return None
    return " ".join(w.capitalize() for w in c.lower().split()) + " County"


def classify(title: str) -> tuple[str | None, str]:
    """(None, why) when the title is not a sewage report; else (event_type, kind)."""
    t = F.clean(title)
    if not SEWAGE_RE.search(t):
        return None, "no sewage word in the title"
    for why, rx in NOT_SEWAGE_RE.items():
        if rx.search(t):
            return None, why
    if BYPASS.search(t):
        return "bypass", "bypass"
    if PLANT.search(t):
        return "plant_bypass", "treatment plant or lagoon release"
    return "sso", "sewer or septic release"


def water_in_title(title: str) -> str | None:
    for m in WATER_IN_TITLE.finditer(F.clean(title)):
        name = re.sub(r"\s+", " ", (m.group(1) or m.group(2) or "")).strip()
        name = re.sub(r"^(?:Release|Sewage|Spill|Discharge|Overflow|Update|UPDATE)\s+", "", name)
        if not name or name.lower() in PLACE_WATERS or NOT_A_WATER.match(name):
            continue
        return " ".join(w if w.isupper() and len(w) <= 3 else w[:1].upper() + w[1:].lower() for w in name.split())
    return None


def _day(v) -> date | None:
    try:
        return date.fromisoformat(str(v or "")[:10])
    except ValueError:
        return None


@F.hook
def ut_incident_record(row: dict, rec: dict, notes: dict, ctx: F.Ctx) -> None:
    title = F.clean(rec.get("outfall_name") or row.get("Title_EventName"))
    m = PERSON_TITLE.match(title)
    if m:
        title = title[m.end():].strip()
        notes["_title_basis"] = "the title began with a person's or family business's name: cut"
    rec["outfall_name"] = title or None
    notes["state"] = "UT"
    notes["time_zone"] = ZONE
    notes["timezone_note"] = ZONE_NOTE
    county = county_name(row.get("County"))
    if county:
        notes["county"] = county
    city = F.clean(row.get("Nearest_City"))
    if city and city.lower() != "none":
        notes["nearest_city"] = city.title()
    st = rec.get("started_at")
    if isinstance(st, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", st):
        rec["started_at"] = datetime(int(st[:4]), int(st[5:7]), int(st[8:10]), tzinfo=TZ).isoformat()
        rec["time_precision"] = "day"
    if not rec.get("started_at"):
        notes["_undated"] = "the layer gives no discovery date for this incident"
    notes["_started_basis"] = STARTED_BASIS
    ft = row.get("Date_Discovered_For_Filter")
    if isinstance(ft, (int, float)):
        notes["_filter_time_as_given"] = datetime.fromtimestamp(ft / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        notes["_filter_time_note"] = FILTER_TIME_NOTE
    et, kind = classify(title)
    if et is None:              # the block's filter keeps only sewage titles; a row reaching here is kept, unknown
        rec["event_type"] = "unknown"
        notes["_ut_kind"] = f"not a sewage report: {kind}"
        return
    rec["event_type"], rec["status"] = et, "unknown"
    notes["_ut_kind"] = kind
    rec["material"] = ("wastewater (type not stated)" if WASTEWATER_ONLY.search(title) and not SEWAGE_NAMED.search(title)
                       else "sewage")
    if rec["material"].startswith("wastewater"):
        notes["_kind_note"] = "the title says wastewater without saying sewage; it is shown as sewage"
    if CITIZEN_WORDS.search(title):
        notes["report_provenance"] = "citizen"
        notes["_provenance_note"] = CITIZEN_NOTE
    w = water_in_title(title)
    if w:
        rec["waterbody_text"] = w
        notes["_water_basis"] = "the water the incident's title names"
    did = F.clean(row.get("DERRID"))
    if did and did.lower() != "none":
        notes["derr_id"] = did
    notes["_coord_note"] = "DEQ: incident locations on the map are approximate"


def _echo_ut(path=None) -> list[dict]:
    p = path or ECHO_FILE
    try:
        d = json.loads(p.read_text())
    except (OSError, ValueError):
        return []
    return [r for r in d.get("records", []) if str(r.get("npdes_permit") or "").startswith("UT") and r.get("started_at")
            and r.get("lat") is not None and r.get("lon") is not None]


def _metres(a_lat, a_lon, b_lat, b_lon) -> float:
    k = math.pi / 180
    x = (b_lon - a_lon) * k * math.cos((a_lat + b_lat) * k / 2)
    return 6_371_000 * math.hypot(x, (b_lat - a_lat) * k)


def _local_day(ts) -> date | None:
    try:
        t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (t.astimezone(TZ) if t.tzinfo else t).date()


@F.hook
def ut_incidents_post(records: list[dict], ctx: F.Ctx) -> dict:
    """Link a row to EPA's eRule report of the same overflow (module docstring)."""
    echo = ctx.extra.get("ut_echo_records")
    if echo is None:
        echo = _echo_ut()
    n = {"linked_to_epa": 0}
    for r in records:
        if r.get("event_type") not in ("sso", "bypass", "plant_bypass") or r.get("lat") is None:
            continue
        d = _day(r.get("started_at"))
        if d is None:
            continue
        cands = []
        for e in echo:
            ed = _local_day(e["started_at"])
            if ed is None or not (d - timedelta(days=1) <= ed <= d):
                continue
            m = _metres(r["lat"], r["lon"], float(e["lat"]), float(e["lon"]))
            if m <= ECHO_LINK_M:
                cands.append((m, e["event_id"]))
        if cands:
            m, eid = min(cands)
            r["duplicate_of"] = eid
            r["raw"]["_duplicate_basis"] = (f"EPA's eRule report {eid}: a Utah permit's report that began the same day "
                                            f"or the day before, {round(m)} m from this row's point")
            n["linked_to_epa"] += 1
    return n


ADVISORY = {
    "WARNING HAB": ("hab_advisory", "Warning advisory: harmful algal bloom"),
    "DANGER HAB": ("hab_advisory", "Danger advisory: harmful algal bloom"),
    "HAB HW": ("hab_advisory", "Health watch: harmful algal bloom"),
    "WARNING MATS": ("hab_advisory", "Warning advisory: harmful algae mats (benthic cyanobacteria)"),
    "MATS CF": ("hab_advisory", "Harmful algae mats (DWQ's code \"Mats CF\")"),
    "WARNING E COLI": ("beach_advisory", "Warning advisory: E. coli"),
    "E COLI HW": ("beach_advisory", "Health watch: E. coli"),
}
UNDECODED = {"MATS CF": "DWQ's layer and map do not say what the code \"Mats CF\" means"}
REC_WINDOW_BASIS = ("Utah's recreational water advisories: posted by the local health department with DWQ and in effect "
                    "while DWQ's map shows them; DWQ's guidance lifts one after results stay below its thresholds for "
                    "two weeks")


@F.hook
def ut_rec_record(row: dict, rec: dict, notes: dict, ctx: F.Ctx) -> None:
    notes["state"] = "UT"
    notes["time_zone"] = ZONE
    st = rec.get("started_at") or ""
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})", st):
        t = datetime.fromisoformat(st.replace("Z", "+00:00")).astimezone(TZ)
        if (t.hour, t.minute, t.second) == (0, 0, 0):
            rec["started_at"] = datetime(t.year, t.month, t.day, tzinfo=TZ).isoformat()
            rec["time_precision"] = "day"
            notes["_date_basis"] = "Advisory_Date is stored as midnight Mountain time: read as the advisory's date"
    level = F.clean(row.get("Advisory")).upper()
    et, label = ADVISORY.get(level, ("unknown", None))
    rec["event_type"] = et
    rec["status"] = "advisory_active" if et != "unknown" else "unknown"
    notes["_advisory_label"] = F.clean(row.get("Advisory"))
    extra = F.clean(row.get("Additional_Advisory_Notes"))
    if label:
        rec["advice_text"] = label + (f". {extra}" if extra else "")
        rec["advice_window_basis"] = REC_WINDOW_BASIS
    if level in UNDECODED:
        notes["code_undecoded"] = UNDECODED[level]
    mon = F.clean(row.get("Monitored_Date"))
    if mon:
        notes["_last_monitored"] = mon
