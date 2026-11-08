"""Tennessee hooks for fetch blocks (docs/generic-ingesters.md; not a feed).

tn_tdec_record: TDEC's Division of Water Resources Events Report (data/sources/tn-tdec-events-report.yaml), an Oracle
APEX interactive report at dataviewers.tdec.tn.gov (application 2005, page 34140) of every sewer overflow, release,
bypass, upset and washout a permittee filed through MyTDEC Forms since the municipal systems were onboarded (early 2020
to mid-2021), downloaded whole as CSV. Columns: EFO Name (TDEC's field office), County, Permit Type, Permit No,
Permittee Name, Project Name, Event Type, Estimated Volume[Gal], Date Event Began, Date Event Ended, Duration[hours],
Event Address, Event City. Dates only; no coordinates; no receiving water; no row id.
  - Law: Tenn. Comp. R. & Regs. 0400-40-05-.07(2)(o) (report within 24 hours, in writing within five days) and
    (2)(n)1 (sanitary sewer overflows are prohibited). No duty to tell the public.
  - Zone: dates only; each date is midnight in the zone of the row's county (zones.tennessee_zone: Eastern in the
    thirty East Tennessee counties of 49 CFR 71.5(d), Central in the other sixty-five), and the record says that zone
    (raw.time_zone, raw.timezone_note), so the status build ends a day at that zone's midnight. A row with no county is
    read in Central time, the state's larger part, and says so.
  - Kind (owner default 2026-11-07, docs/state-builder-brief-wave4.md in the site repository: every TDEC event type is
    a sewage report, and every one carries the site's colour, review 2026-11-08 P2-1): "SSO ..." (wet or dry weather,
    0400-40-05-.02(76)), "Unpermitted Discharge" and "Extreme Event Report" are sso; "Release [Sewer] ..." is sso
    with raw.reached_water false, since TDEC's definition is sewage "that does not reach waters" (0400-40-05-.02(75));
    "Bypass" (a diversion of waste streams from a portion of a treatment facility, .02(14)), "Upset" (a treatment
    plant's unintentional noncompliance, .02(88)) and "Washout" are plant_bypass. Every record keeps TDEC's own label in
    raw._source_type and raw._weather.
  - Times: started_at is Date Event Began (day precision); ended_at is Date Event Ended (day precision, an end the
    authority gives: raw.ended_at_precision day). Where the end is blank but TDEC gives a duration in hours, the end is
    the day of the latest end the duration allows (common.end_after: the start day's end plus the duration), at day
    precision, said in raw._basis.ended_at; where neither is given there is no end (status unknown: "end not
    confirmed"). reported_at and published_at stay null: the table gives neither (TDEC receives the written report
    within five days; the rows reach the table about five days after the event began).
  - Placement (owner default 2026-11-07): the table gives no coordinates and no receiving water: every row is kept with
    its county, city and permittee and placed on no water (raw._placement named_water_only, so build/provisional_outfalls
    never stands the plant's point in for it and never geolocates it from the address). A model pass could later read
    the per-event PDF's receiving water; a model never supplies a place or a colour.
  - Operator: npdes_permit is Permit No when it is a federal id (TN plus seven digits); state operating permits (SOP-,
    TNG general permits) stay in raw.state_permit. discharger_id is the data/dischargers.json row holding the permit.
  - Key (the block's template): the table has no id; source_record_id is permit, start day, TDEC's event type and
    the street of the event address after the house-number scrub; repeats are id~2, id~3 (dedupe). A row TDEC corrects (a new address or type)
    and that leaves the table is matched to its replacement by permit, day and type (history.supersede).
  - Privacy: only the thirteen columns are read; the event address and city go through the strict free-text scrub
    (free_text_scrub: strict: every house number, phone, email and person's name cut) before anything is saved, so the
    street stays and the house number never does; a permittee or project name that is only a person's (a small private
    system filed under its owner) becomes "[name removed]" (common.scrub_discharger), the permit staying its identity.

tn_hab_record: TDEC's HAB advisory status layer (data/sources/tn-tdec-hab-advisory-status.yaml), the Survey123 layer
behind the Tennessee HAB Dashboard. Each row is a bloom report (most from the public) with TDEC's follow-up: whether a
bloom was confirmed (hab_confirmed), whether TDEC issued an advisory (advisory_issued: Precautionary Advisory or No
Contact Advisory), and the advisory's dates (HAB_Status_date, HAB_end_date, dates only).
  - A row with an advisory is TDEC's own advisory (hab_advisory, category bloom): advisory_active from its start date;
    advisory_lifted when HAB_end_date is given (the end the authority gives, day precision); the advisory text quotes
    TDEC's level.
  - Every other kept row is a bloom report with no advisory: a bloom TDEC confirmed without issuing one, or a report it
    has not assessed (no finding yet, or "other"). It carries raw._agency_label_only and raw._caution_to_notice_end, and
    the source is in data/rules.json unresolved.sample_caution, so the status build shows the site's caution from the
    report's day (72 hours, or to TDEC's end date when that is later), never TDEC's advisory and never red (review
    2026-11-08 P1-1). A report TDEC found was no bloom, or green algae or plants, is left out by the block's filter.
  - Start: HAB_Status_date (TDEC's date); where TDEC gives none (a report not yet assessed), the date the reporter saw
    the bloom (please_enter_the_date_the_algal, a date stored as an epoch: read as the day in the point's zone), with
    raw._basis.started_at saying so.
  - Zone: the county the point lies in (zones.tennessee_zone), as for the overflow table.
  - Privacy: the layer also holds the reporting person's first and last name, phone number and email, and the
    reporter's own free-text description: none of them is requested (out_fields are the safe fields). The point is
    the reporter's: rounded to 0.001 degree (about 100 m; coord_precision_m 150) in the record and in raw.row and
    data/raw (the block's round_coords). Where TDEC's private_property code says "No, private residence, or farm pond"
    the record keeps only the county the point lies in: no point in the record or in raw.row (review 2026-11-08 P2-3),
    and no water text either: the reporter's words may name the home's street (final audit 2026-11-08 P2-4); the
    record says "a private pond" (raw._water_text_withheld) and is placed on no water.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

import zones
from common import DATA_DIR, NAME_REMOVED, end_after, scrub_discharger
from ingest.generic import fieldmap as F

ZONE_NOTE = "{zone} time ({county}; 49 CFR 71.5(d)); dates only"
PLACEMENT = ("TDEC's table gives no coordinates and no receiving water: every report is listed with its county, city "
             "and permittee and placed on no water; it is never placed at the plant or geolocated from its address")
FEDERAL = re.compile(r"^TN\d{7}$")
# TDEC's event types (the Event Type column) -> (event_type, weather)
KINDS = [
    (re.compile(r"^\s*SSO\b", re.I), "sso"),
    (re.compile(r"^\s*Release\b", re.I), "sso"),
    (re.compile(r"^\s*(Bypass|Upset|Washout)\b", re.I), "plant_bypass"),
    (re.compile(r"^\s*(Extreme\s+Event|Unpermitted)\b", re.I), "sso"),
]
RELEASE = re.compile(r"^\s*Release\b", re.I)
RELEASE_DEF = ("TDEC's \u201cRelease\u201d: \u201cthe flow of sewage from any portion of the collection or transmission "
               "system ... other than through permitted outfalls, that does not reach waters\u201d, including a backup "
               "into a building (Tenn. Comp. R. & Regs. 0400-40-05-.02(75))")
WEATHER = re.compile(r"\b(wet|dry)\s+weather\b", re.I)
ROW_IN_RECORD = {"date_event_began", "date_event_ended", "estimated_volume_gal", "duration_hours", "event_type"}


def county_name(raw) -> str | None:
    c = F.clean(raw)
    if not c:
        return None
    c = re.sub(r"\s+county\s*$", "", c, flags=re.I)
    words = []
    for w in c.lower().split():
        w = w.capitalize()
        if w.startswith("Mc") and len(w) > 2:
            w = "Mc" + w[2:].capitalize()
        words.append(w)
    return " ".join(words).replace("Dekalb", "DeKalb") + " County"


def tdec_kind(label) -> str:
    t = F.clean(label)
    for rx, kind in KINDS:
        if rx.search(t):
            return kind
    return "sso"           # a type TDEC adds later: a sewage report of the table, never an uncoloured one


def _operators(ctx: F.Ctx) -> dict:
    if "tn" not in ctx.extra:
        by_permit, names = {}, {}
        dis = DATA_DIR / "dischargers.json"
        for r in json.loads(dis.read_text()) if dis.exists() else []:
            if r.get("state") != "TN":
                continue
            names[r["id"]] = r.get("name")
            for p in [r.get("npdes_permit"), *(r.get("npdes_permits") or [])]:
                if p:
                    by_permit.setdefault(p, r["id"])
        ctx.extra["tn"] = {"by_permit": by_permit, "names": names}
    return ctx.extra["tn"]


def _local_midnights(rec: dict, tz: ZoneInfo) -> None:
    for k in ("started_at", "ended_at"):
        v = rec.get(k)
        if isinstance(v, str) and re.match(r"\d{4}-\d{2}-\d{2}", v):
            rec[k] = datetime(int(v[:4]), int(v[5:7]), int(v[8:10]), tzinfo=tz).isoformat()


@F.hook
def tn_tdec_record(row: dict, rec: dict, notes: dict, ctx: F.Ctx) -> None:
    county = county_name(row.get("county"))
    zone = zones.tennessee_zone(county) if county else zones.CENTRAL
    notes["state"] = "TN"
    if county:
        notes["county"] = county
    city = F.clean(row.get("event_city"))
    if city:
        notes["city"] = city
    notes["time_zone"] = zone
    tz = ZoneInfo(zone)
    _local_midnights(rec, tz)
    notes["timezone_note"] = ZONE_NOTE.format(zone="Eastern" if zone == zones.EASTERN else "Central",
                                              county=county or "county not given: the state's larger part")
    # the kind: TDEC's own label kept
    label = F.clean(row.get("event_type"))
    rec["event_type"] = tdec_kind(label)
    notes["_source_type"] = label or None
    if RELEASE.search(label):
        # by TDEC's definition a release reached no water: never placed on one (review 2026-11-08 P2-6)
        notes["reached_water"] = False
        notes["_no_water_reason"] = RELEASE_DEF
    w = WEATHER.search(label)
    if w:
        notes["_weather"] = f"{w.group(1).lower()} weather (TDEC's event type)"
    # the end: TDEC's own date, else the latest day its duration allows, else none
    dur = F.clean(row.get("duration_hours"))
    if dur:
        notes["_duration_hours"] = dur
    if rec.get("started_at") and re.fullmatch(r"\d+(?:\.\d+)?", dur or "") and float(dur) > 0:
        start = datetime.fromisoformat(rec["started_at"])
        bound, basis = end_after(start, timedelta(hours=float(dur)), "day")
        given = datetime.fromisoformat(rec["ended_at"]) if rec.get("ended_at") else None
        if given is None or bound > given:
            # no end date, or one earlier than the duration allows: the later of the two (review 2026-11-08 P3-8)
            if given is not None:
                notes["_end_as_given"] = rec["ended_at"]
            rec["ended_at"] = bound.isoformat()
            notes.setdefault("_basis", {})["ended_at"] = f"{basis} (Duration[hours] {dur})"
    if rec.get("ended_at"):
        notes["ended_at_precision"] = "day"
    rec["status"] = "ended" if rec.get("ended_at") else "unknown"
    permit = F.clean(row.get("permit_no")).upper()
    # the operator
    rec["npdes_permit"] = permit if FEDERAL.match(permit) else None
    if permit and not FEDERAL.match(permit):
        notes["state_permit"] = permit
    look = _operators(ctx)
    did = look["by_permit"].get(permit) if permit else None
    rec["discharger_id"] = did
    if did and look["names"].get(did):
        notes["_discharger_basis"] = "the operator row holding its permit"
    # a permittee or project name that is only a person's leaves raw.row too
    row_out = {k: v for k, v in row.items() if k not in ROW_IN_RECORD}
    for k in ("permittee_name", "project_name"):
        v = F.clean(row.get(k))
        if v and scrub_discharger({"discharger_name": v})["discharger_name"] == NAME_REMOVED:
            row_out[k] = NAME_REMOVED
            notes["_name_removed"] = "a permittee or project name read as a person's"
            if rec.get("discharger_name") == v:
                rec["discharger_name"] = NAME_REMOVED
    notes["row"] = row_out
    notes["_placement"] = "named_water_only"
    # where the event was: the street (house number scrubbed) and city, else the permitted facility (project name)
    street = F.clean(row.get("event_address"))
    loc = ", ".join(x for x in (street, city) if x)
    if street:
        rec["outfall_name"] = loc
        notes["_outfall_name_basis"] = "Event Address and Event City (the house number removed)"


# ---------------------------------------------------------------- HAB advisory layer

ADVISORY_LEVELS = {"precautionary advisory": "Precautionary Advisory", "no contact advisory": "No Contact Advisory"}
WINDOW_BASIS = ("TDEC's harmful algal bloom advisory: in effect from the date TDEC gives until the end date it gives; "
                "TDEC sets no fixed period")


PRIVATE_WATER_TEXT = "a private pond (TDEC: private residence or farm pond; its name is not published)"
PRIVATE_RESIDENCE = re.compile(r"private\s+residence|farm\s+pond", re.I)


@lru_cache(maxsize=1)
def _tn_counties():
    from shapely.geometry import shape
    from shapely.validation import make_valid
    doc = json.loads((DATA_DIR / "reference" / "tn-counties.json").read_text())
    return [(c["county"], make_valid(shape(c["geometry"]))) for c in doc["counties"]]


def point_county(lat, lon) -> str | None:
    """The Tennessee county a point lies in ('Davidson County'), or None."""
    if lat is None or lon is None:
        return None
    from shapely.geometry import Point
    p = Point(float(lon), float(lat))
    return next((n for n, g in _tn_counties() if g.covers(p)), None)


@F.hook
def tn_hab_record(row: dict, rec: dict, notes: dict, ctx: F.Ctx) -> None:
    lat, lon = rec.get("lat"), rec.get("lon")
    county = point_county(lat, lon)
    zone = zones.tennessee_zone(county, lat, lon) if county else zones.tennessee_zone(lat=lat, lon=lon)
    if county:
        notes["county"] = county
    if lat is not None and lon is not None:
        if PRIVATE_RESIDENCE.search(F.clean(row.get("private_property"))):
            rec["lat"] = rec["lon"] = None
            rec["coord_source"] = None
            notes["row"] = {k: v for k, v in (notes.get("row") or row).items() if k not in ("_x", "_y")}
            notes["_point_withheld"] = ("TDEC marks this water a private residence or farm pond: only its county is "
                                        "published")
            # the reporter's words for the water may name the home's street ("pond located near ... block of ..."):
            # a generic text with the county, never the words (final audit 2026-11-08 P2-4)
            if rec.get("waterbody_text"):
                notes["row"] = {**notes["row"], "name_of_the_waterbody": PRIVATE_WATER_TEXT}
                rec["waterbody_text"] = None
                notes["_water_text_withheld"] = PRIVATE_WATER_TEXT
        else:
            rec["lat"], rec["lon"] = round(float(lat), 3), round(float(lon), 3)
            rec["coord_precision_m"] = 150
            notes["_coords_rounded"] = "the reporter's point, rounded to 0.001 degree (a pond may be at a home)"
    notes["state"] = "TN"
    notes["time_zone"] = zone
    notes["timezone_note"] = (f"{'Eastern' if zone == zones.EASTERN else 'Central'} time "
                              f"({county or 'no county: the state\'s larger part'}; 49 CFR 71.5(d)); dates only")
    tz = ZoneInfo(zone)
    _local_midnights(rec, tz)
    obs = row.get("please_enter_the_date_the_algal")
    if not rec.get("started_at") and isinstance(obs, (int, float)):
        d = datetime.fromtimestamp(obs / 1000, tz).date()
        rec["started_at"] = datetime(d.year, d.month, d.day, tzinfo=tz).isoformat()
        rec["time_precision"] = "day"
        notes.setdefault("_basis", {})["started_at"] = (
            "please_enter_the_date_the_algal (the date the reporter saw the bloom): TDEC gives no status date for "
            "this report")
    level = ADVISORY_LEVELS.get(F.clean(row.get("advisory_issued")).lower())
    confirmed = F.clean(row.get("hab_confirmed")).lower() == "yes"
    if level:
        rec["advice_text"] = f"TDEC harmful algal bloom {level}."
        rec["advice_window_basis"] = WINDOW_BASIS
        rec["status"] = "advisory_lifted" if rec.get("ended_at") else "advisory_active"
        if rec.get("ended_at"):
            notes["ended_at_precision"] = "day"
        notes["_hab_level"] = level
    else:
        # a bloom report with no advisory: the site's caution (unresolved.sample_caution), never TDEC's advisory
        rec["status"] = "ended" if rec.get("ended_at") else "unknown"
        notes["_agency_label_only"] = ("TDEC confirmed a bloom and issued no advisory" if confirmed
                                       else "a bloom report TDEC has not assessed, with no advisory")
        notes["_agency_label"] = ("Bloom confirmed by TDEC; no advisory issued" if confirmed
                                  else "Bloom reported to TDEC; not yet assessed")
        notes["_caution_to_notice_end"] = True
        if rec.get("ended_at"):
            notes["ended_at_precision"] = "day"
            notes["_notice_end_basis"] = "TDEC's end date for this bloom (HAB_end_date)"
    notes["_confirmed"] = F.clean(row.get("hab_confirmed")) or None
