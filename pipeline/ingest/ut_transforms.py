"""Utah hooks for fetch blocks (docs/generic-ingesters.md; not a feed).

ut_incident_record and ut_incidents_post: the Utah Department of Environmental Quality's Environmental Incidents layer
(data/sources/ut-deq-environmental-incidents.yaml; ArcGIS, services2.arcgis.com/NnxP4LZ3zX8wWmP9 EnvironmentalIncidents
layer 0): the log of the Division of Environmental Response and Remediation's spill hotline and after-hours duty
officers since 1991, one row per incident with a point, edited daily. 8,980 rows on 2026-11-07, every kind of spill.
  - The sewage rows. The layer has no type field: its SITEDESC is the one value "Environmental Incidents" on every row,
    and the incident summary (the only field that says what was released, how much and where it went) carries staff
    names, callers and private addresses and is never requested. A row is a sewage report when its title
    (Title_EventName) names sewage by the words of SEWAGE_WORDS and none of NOT_SEWAGE (the fetch block's filter,
    which keeps the same two lists, so only those rows reach data/raw/). The 2026-11-08 fetch: 8,980 rows; 435 titles
    name sewage words; 387 kept as sewage reports; 48 dropped (NOT_SEWAGE: 30 industrial, process or trade wastewater,
    11 other materials in a sewer, drain or plant, 5 backups inside buildings, 2 drinking-water plants). Before 2013 the
    log titles an incident by the party involved: a kept title from then that names no event (EVENT_WORDS) carries
    material "not stated in the title" (9 rows). The counts by reason are
    in the source file. A model pass could later read titles the rules leave unclear ("Waste Water Discharge"); a
    model never supplies a place or a colour.
  - Kind (raw._ut_kind) and event_type: a bypass named in the title -> bypass; a treatment plant, lagoon, effluent or
    reclamation facility -> plant_bypass; the rest -> sso. A title that says only "wastewater" is kept as sewage
    (err on the side of safety; raw._kind_note says the title does not say sewage).
  - Provenance: private dumping, RV and camper dumping, portable toilets and complaints or tips are reports the public
    phoned in (CITIZEN_WORDS): raw.report_provenance "citizen", so the status build shows them with the site's caution
    only (citizen_caution), never as an authority's confirmation. The other rows are DEQ's log of a call whose caller
    the layer does not name (a utility, an agency or a member of the public): raw.report_provenance stays unset.
  - Times. Date_Discovered_For_Filter is the discovery time stored in UTC: until 2023 every value is midnight Eastern
    time (04:00 or 05:00 UTC), a date only; since 2024 a time rounded to the quarter hour, whose hours fall to a low at
    01:00 to 03:00 Mountain time and peak at 13:00 only when read as UTC. Date_Discovered (text, MM/DD/YYYY) is that
    time's UTC date, so a discovery after 17:00 or 18:00 Mountain time carries the next day (14 of the 83 kept rows
    since 2024). started_at is 00:00 Mountain time of the earlier of the two days (discovery_day), precision day, with
    the basis in raw._day_basis; the earlier day is right under either reading of the clock. (One row reads oddly as
    UTC: the American Fork bypass break of 2026-08-17 at 11:00 Mountain, before the 14:39 start the operator gave EPA.)
    The filter time stays as given in raw._filter_time_as_given. No row gives an end, a report time or a volume (the
    volume is only in the summary): ended_at, reported_at and volume_gal stay null, status unknown, so the status build
    applies its no-end caution from the start of the discovery day. 39 of the kept rows (most entered before 2014 or
    migrated without a date) have no date at all: kept, undated, never coloured.
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
    before, within ECHO_LINK_M (2 km) of the row's point, unless the row is the public's report (which never absorbs nor
    is absorbed by an operator's, as in status.find_duplicates) or the two name different particular waters
    (status.waters_differ). The DEQ row is then duplicate_of EPA's record, which carries the operator, the minute and the
    volume. One such pair on 2026-11-08 (American Fork, 2026-08-17, about 1 m apart).

ut_rec_record: DWQ's recreational waters layer (data/sources/ut-dwq-recreational-advisories.yaml; AutoMap_Source_Data
layer 0), one row per monitored site with its current advisory as local health departments and DWQ post it:
  - "Warning HAB", "Danger HAB", "HAB HW" (health watch), "Warning Mats": hab_advisory (the bloom category), the
    authority's own advisory, advisory_active while the layer shows it (history.confirm_while_listed).
  - "Warning E coli", "E coli HW": beach_advisory (the bacteria category), advisory_active while listed. Labels are read
    without case, spaces or dots (advisory_key: DWQ writes both "E coli" and "Ecoli"); a label the hook does not know
    is kept by its words (bloom words -> hab_advisory, else beach_advisory) with raw.code_undecoded, the site's caution,
    never grey.
  - "Mats CF": by DWQ's web map (item 213cdc781ebd4faf97e0d4af5a79c5fa, the "Mats CF" layer's pop-up), a few harmful
    algae mats observed by DWQ's monitoring team, with the date last monitored; not one of the advisory levels (Health
    Watch, Warning, Danger) DEQ's page names. Shown with the site's caution only (raw.code_undecoded carries that basis).
  - "Looks Good" and an empty advisory are not records (the block's filter): no current advisory, grey, never clean.
  Advisory_Date is the advisory's date, stored as midnight Mountain time: read as that date (precision day); a row
  without one is dated by its latest sample (Monitored_Date). DWQ's own note on a site is quoted as "DWQ's note".
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
                r"\beffluent\b|\bbypass\b|\bblack\s*water\b|\bmotorhomes?\b|\bcampers?\b|\bRVs?\b|"
                r"\bport(?:a|able)[\s-]*(?:pott\w*|john|toilet)|\bport(?:a|o)[\s-]*j|\bhoney\s*bucket|\bchemical\s+toilet|"
                r"\bbiosolids?\b|\blagoons?\b|\bWWTP\b|\bPOTW\b|\btreatment\s+plant|\breclamation\b|\bfecal\b|"
                r"\bsanitary\b|\bsanitized\s+sewer|\bhuman\s+waste\b|\bseptage\b|\bactivated\s+sludge\b")
# the titles that name sewage words but report something else (the fetch block's exclude filters), by reason
NOT_SEWAGE = {
    "industrial, process or trade wastewater": (
        r"\bindustrial\b|\bprocess(?:ed)?\b|\bcarpet\s+clean|\bconcrete\b|\bcement\b|\bcar\s+wash|\bdairy\b|"
        r"\bacidic\b|\balkaline\b|\blow\s+ph\b|\bhydrocarbon\b|\breverse\s+osmosis\b|\bIWWTP\b|\btoxicity\b|"
        r"\bfood\s+truck\b|\bgr[ae]y\s*water\b|\bdumpsters?\b|\brefinery\b"),
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
                   r"\breclamation\b|\bplant\b|\bpartially\s+treated\b|\bactivated\s+sludge\b", re.I)
WASTEWATER_ONLY = re.compile(r"\bwaste\s*-?\s*water\b", re.I)
SEWAGE_NAMED = re.compile(r"\bsew(?:age|er)|\bSSOs?\b|\bseptic\b|\bsanitary\b|\bmanhole|\blift\s+station|\bblack\s*water|"
                          r"\bport(?:a|able|o)|\bhoney\s*bucket|\bchemical\s+toilet|\bRVs?\b|\bcampers?\b|\bmotorhomes?\b|"
                          r"\bbiosolids?\b|\bfecal\b|\bhuman\s+waste\b|\bseptage\b", re.I)
CITIZEN_WORDS = re.compile(r"\bcomp(?:laint|\.)|\btip\b|\balleged\b|\bdump(?:s|ed|ing)?\b|\billegal\b|\billicit\b|"
                           r"\bimproper\b|\bunpermitted\b|\bRVs?\b|\bcampers?\b|\bmotorhomes?\b|\bhouseboats?\b|"
                           r"\bport(?:a|able)[\s-]*(?:pott\w*|john|toilet)|\bport(?:a|o)[\s-]*j|\bhoney\s*bucket|"
                           r"\bchemical\s+toilet|\bhuman\s+waste\b|\bseptage\b|"
                           r"\bvacuum\s+truck\b|\bon\s+(?:private\s+)?property\b|\bresidence\b", re.I)
CITIZEN_NOTE = ("the hotline log's title reads as a dumping, a private system's release or a complaint; the log does not "
                "say who reported it or whether an authority confirmed it")
# a water named in the title: up to three capitalised words before a water noun, or "Lake <Name>"
WATER_IN_TITLE = re.compile(
    r"\b((?:[A-Z][A-Za-z.']*\s+){1,3}(?i:river|creek|lake|reservoir|slough|canal|wash|pond))\b"
    r"(?!\s+(?:City|County|Sewer|Water|Improvement|District|Lift|Special|Town))|"
    r"\b(Lake\s+Powell)\b")
NOT_A_WATER = re.compile(r"^(?:(?:north|south|west|[nsw]\.?)\s+)?salt\s+lake$|^lake\s+point$", re.I)
PLACE_WATERS = {"salt lake", "north salt lake", "south salt lake", "west salt lake"}
# a title that is a person's or family business's name: "First and First's ..." (pre-2013 rows title the party)
PERSON_TITLE = re.compile(r"^\s*[A-Z][a-z]+(?:\s+(?:and|&)\s+[A-Z][a-z]+)?'s\s+", re.U)
FILTER_TIME_NOTE = ("the layer's filter time as stored (an epoch, UTC): midnight Eastern time on rows before 2024 (a date "
                    "only); since 2024 the discovery time rounded to the quarter hour, whose UTC date is the layer's "
                    "Date_Discovered")
ECHO_FILE = EVENTS_DIR / "echo-sewer-overflow.json"
ECHO_LINK_M = 2_000
STARTED_BASIS = ("started_at is the Mountain-time day the incident was discovered: the earlier of the layer's "
                 "Date_Discovered (the UTC date of its filter time) and the Mountain date of the filter time read as UTC; "
                 "day precision")
ET = ZoneInfo("America/New_York")
EVENT_WORDS = re.compile(r"\b(?:releases?|spills?|overflows?|over-flow|dump\w*|leaks?|discharges?|breaks?|backups?|"
                         r"bypass|SSO|sewage|disposal|upset|inundated)\b", re.I)


def discovery_day(date_text: str | None, epoch_ms) -> tuple[date | None, str]:
    """(the Mountain-time day of discovery, how it was read). Date_Discovered is the UTC date of the filter time, so an
    evening discovery (after 17:00 or 18:00 Mountain) carries the next day; the earlier of the two days is used. A filter
    time at midnight Eastern (rows before 2024) is a date only and leaves Date_Discovered as it is."""
    try:
        d = datetime.strptime(F.clean(date_text), "%m/%d/%Y").date() if F.clean(date_text) else None
    except ValueError:
        d = None
    if not isinstance(epoch_ms, (int, float)):
        return d, "Date_Discovered (no filter time)"
    u = datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc)
    e = u.astimezone(ET)
    if (e.hour, e.minute, e.second) == (0, 0, 0):
        return (d or e.date()), "Date_Discovered (the filter time is midnight Eastern: a date only)"
    m = u.astimezone(TZ).date()
    if d is None or m < d:
        return m, "the Mountain date of the filter time read as UTC (earlier than Date_Discovered, its UTC date)"
    return d, "Date_Discovered (the same day as the filter time in Mountain time)"


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
        notes["row"] = {**row, "Title_EventName": title}       # raw.row keeps the cut title, never the name
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
    day, how = discovery_day(row.get("Date_Discovered"), row.get("Date_Discovered_For_Filter"))
    if day is not None:
        rec["started_at"] = datetime(day.year, day.month, day.day, tzinfo=TZ).isoformat()
        rec["time_precision"] = "day"
        notes["_day_basis"] = how
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
    if day is not None and day.year < 2013 and not EVENT_WORDS.search(title):
        rec["material"] = "not stated in the title"
        notes["_kind_note"] = ("before 2013 the log titles an incident by the party involved; this title names a sewer "
                               "body or business, not what was released")
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
    from build.status import waters_differ
    n = {"linked_to_epa": 0}
    for r in records:
        if r.get("event_type") not in ("sso", "bypass", "plant_bypass") or r.get("lat") is None:
            continue
        if (r.get("raw") or {}).get("report_provenance") == "citizen":
            continue        # the public's report never absorbs nor is absorbed by an operator's (status.find_duplicates)
        d = _day(r.get("started_at"))
        if d is None:
            continue
        cands = []
        for e in echo:
            ed = _local_day(e["started_at"])
            if ed is None or not (d - timedelta(days=1) <= ed <= d):
                continue
            if waters_differ(r, e):
                continue    # two reports naming different particular waters are not linked
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
    "WARNINGHAB": ("hab_advisory", "Warning advisory: harmful algal bloom"),
    "DANGERHAB": ("hab_advisory", "Danger advisory: harmful algal bloom"),
    "HABHW": ("hab_advisory", "Health watch: harmful algal bloom"),
    "WARNINGMATS": ("hab_advisory", "Warning advisory: harmful algae mats (benthic cyanobacteria)"),
    "MATSCF": ("hab_advisory", "Harmful algae mats observed by DWQ's monitoring team (DWQ's map code \"Mats CF\"); "
                               "not one of DWQ's advisory levels"),
    "WARNINGECOLI": ("beach_advisory", "Warning advisory: E. coli"),
    "ECOLIHW": ("beach_advisory", "Health watch: E. coli"),
}
# caution only (raw.code_undecoded, the status build's code_caution): never shown as the authority's advisory
OBSERVATION = {"MATSCF": ("DWQ's map describes \"Mats CF\" as a few harmful algae mats observed by its monitoring team, "
                          "not an advisory level: shown with the site's caution only")}
NOT_ADVISORY = re.compile(r"^(?:LOOKSGOOD|NONE|NULL|)$")
REC_WINDOW_BASIS = ("Utah's recreational water advisories: issued by the local health department with DWQ and shown "
                    "while DWQ's map lists them")


def advisory_key(label) -> str:
    """DWQ's label normalised: upper case, no spaces or dots ("E coli", "Ecoli" and "E. coli" alike)."""
    return re.sub(r"[\s.\-_]", "", F.clean(label).upper())


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
    given = F.clean(row.get("Advisory"))
    level = advisory_key(given)
    notes["_advisory_label"] = given
    if level in ADVISORY:
        et, label = ADVISORY[level]
        if level in OBSERVATION:
            notes["code_undecoded"] = OBSERVATION[level]
    elif not NOT_ADVISORY.match(level):
        # a label DWQ adds or respells: kept by its words, with the site's caution, never grey
        et = "hab_advisory" if re.search(r"HAB|MAT|ALGA|CYANO|TOXIN", level) else "beach_advisory"
        label = f"DWQ's map label \"{given}\""
        notes["code_undecoded"] = f"DWQ's map label \"{given}\" is not one this site reads: shown with the site's caution"
    else:
        et, label = "unknown", None
    rec["event_type"] = et
    rec["status"] = "advisory_active" if et != "unknown" else "unknown"
    extra = F.clean(row.get("Additional_Advisory_Notes"))
    if label:
        rec["advice_text"] = label + (f". DWQ's note: {extra}" if extra else "")
        rec["advice_window_basis"] = REC_WINDOW_BASIS
    mon = F.clean(row.get("Monitored_Date"))
    if mon:
        notes["_last_monitored"] = mon
        if not rec.get("started_at") and re.fullmatch(r"\d{4}-\d{2}-\d{2}", mon[:10]):
            rec["started_at"] = datetime(int(mon[:4]), int(mon[5:7]), int(mon[8:10]), tzinfo=TZ).isoformat()
            rec["time_precision"] = "day"
            notes["_date_basis"] = "no Advisory_Date: dated by the site's latest sample (Monitored_Date)"
