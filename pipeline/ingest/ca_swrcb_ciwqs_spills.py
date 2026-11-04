"""California State Water Board CIWQS sanitary sewer spill file -> data/build/events/ca-swrcb-ciwqs-spills-flatfile.json

Source
  State Water Resources Control Board, Sanitary Sewer Systems program: the nightly flat file of every Category 1, 2
  and 3 spill reported to the CIWQS Sanitary Sewer System Database under the Statewide Sanitary Sewer Systems General
  Order (Order WQ 2022-0103-DWQ, effective 2023-06-05),
  https://www.waterboards.ca.gov/water_issues/programs/sso/docs/data_files/Cat1-2-3-Spills.txt
  (index: https://www.waterboards.ca.gov/water_issues/programs/sso/docs/index.php). Tab-delimited, 95 columns,
  Windows-1252 text, one row per spill report version; the Board regenerates it once a day (Last-Modified about
  06:00 Pacific). No key, no licence statement. Credit "California State Water Resources Control Board, CIWQS
  Sanitary Sewer System Database (Cat1-2-3-Spills.txt)".
  Law (the rule this feed follows; data/rules.json red.by_state.CA quotes it):
  - Order WQ 2022-0103-DWQ 5.13.1: a Category 1 spill is "a spill of any volume of sewage ... that results in a
    discharge to: A surface water ... or A drainage conveyance system that discharges to surface waters when the sewage
    is not fully captured and returned"; Category 2 is "1,000 gallons or greater ... that does not discharge to a
    surface water"; Category 3 is 50 to 999 gallons that does not; Category 4 (under 50 gallons, no surface water) is
    reported only as a monthly count and is not in this file.
  - Attachment E1 1.1 (Water Code 13271): the California Office of Emergency Services is notified "no later than two
    (2) hours after" knowledge of a spill of 1,000 gallons or more to waters of the State; E1 3.1.1 / 3.2.1: a Draft
    Spill Report in CIWQS "Within three (3) business days" of knowledge of a Category 1 or 2 spill; 3.1.2 / 3.2.2: a
    Certified Spill Report "Within 15 calendar days of the spill end date" (the spill end is required only there);
    3.3: Category 3 spills are certified monthly, within 30 days after the month's end.
  - Spills from privately owned laterals are reported voluntarily (5.15) to a separate file (plps_spills.txt), not
    read here.

What is read (privacy)
  Only the columns in COLUMNS are read; every other column is never parsed into a record or saved: the certifier's
  name and title (CERTIFIED_BY, CERTIFIER_TITLE) and every narrative written by the operator (descriptions of the
  location, extent, drainage system, discharge points, destinations, volume estimates, cause, impacts, response,
  corrective actions, investigation, water body, samples, and every "if other, describe" field), which can name
  staff, residents and private addresses (raw._withheld says so; the source file has them). The kept columns are
  renamed to short keys (a column such as NAME_OF_RECEIVING_WATER_BODY(S) would read as a personal key).
  The free text kept is scrubbed: the spill location name (typed by the operator, very often a street address of a
  home) loses every street address's house number (common.strip_house_numbers) after common.scrub_text; the receiving
  water name and the entity that closed or restricted a water pass common.scrub_text, and a value that is only a
  person's name becomes "[name removed]". When the spill appeared only on private property (a private lateral
  clean-out or inside a building) its origin point is rounded to three decimals (about 100 m) so it does not mark a
  home; coord_precision_m says so. common.strip_personal runs on every raw (in event()) and build.redact over the
  records last. The saved raw page (data/raw/<source>/) holds only the scrubbed short-key rows, never the file.
  tests/test_ca_swrcb_ciwqs.py proves that the certifier, the narratives and the placeholder house number never reach
  a record or the saved page.

Which reports are shown
  Every spill in the file becomes a record (event_type sso, raw.spill_category "1", "2" or "3"). Category 1 spills are
  the reports shown: raw.reached_water true (the Order's own category says the sewage reached surface water or a
  drainage system that discharges to one and was not recovered). Category 2 and 3 spills did not reach surface water
  by the Order's definition: raw.reached_water false, so the status build keeps them on the record and counts them
  with no_receiving_water, never colouring a water. meta.by_category counts each.

Record rules
  - Key: SPILL_EVENT_ID; the file repeats a spill once per report version (an amended report keeps its earlier
    versions as rows with status Amended): the highest SPILL_REPORT_VERSION is the record, the others are listed in
    raw._versions. Across runs a change of the tracked fields is kept in raw._revisions.
  - Times are Pacific local time as typed ("MM/DD/YYYY HH:MM"), written with their offset, time_precision "minute"
    (a start typed as midnight with no end, or with an end also at midnight, is read at day precision). A local time
    that happened twice or not at all at a clock change is noted (raw._time_notes).
    started_at = ESTIMATED_SPILL_START_DATE_AND_TIME; ended_at = SPILL_END_DATE_AND_TIME.
  - Status: an end at or after the start -> ended (a report not yet certified says in raw._end_basis that the end is
    the operator's draft); no end -> unknown with no end (the draft report form has no end: the Order requires it only
    in the certified report), so the status build gives the plan's unknown-status caution and then "end not
    reported"; an end before the start, or a time more than a day after the read, is not used and the record says why.
  - reported_at: the time the operator told Cal OES (DATE_TIME_ENROLLEE_NOTIFIED_CALOES) when given, else the draft
    report's date, else the first certification date (raw._reported_basis says which). published_at is null (the file
    gives no posting time; raw._first_seen_in_file is the file's Last-Modified when the spill was first seen).
    source_updated_at is the latest of the report's own dates (draft, first and final certification), a date.
  - Water: waterbody_text is the receiving water as named in the certified report; a name that names none ("N/A",
    "None") is not used as a water (raw.receiving_water keeps it). TYPE, public access impact, days closed and the
    closing entity are kept in raw.
  - Operator: npdes_permit is the enrollee's WDID (the General Order is not an NPDES permit: the WDID is the
    enrollment's number); discharger_id is the data/dischargers.json California row that holds the WDID. discharger_name
    is the agency as the file names it.
  - Point: LATITUDE / LONGITUDE (the spill's origin); a longitude typed without its minus sign inside California is
    repaired (raw._coords_repaired); a point outside California is not used. The up to four destination points stay
    in raw.destination_points.
  - Volume: volume_gal is the estimated total spill volume exiting the system; volume_text adds the volume that
    reached surface water and the volume recovered, as estimated by the operator (estimate_flag "estimated").

Reading (what each run costs)
  Each run asks for the file with If-Modified-Since: the Board rebuilds it once a day, so 23 runs of 24 get a 304
  with no body and rebuild nothing; the first run after the rebuild downloads it (about 11 MB, 2.8 MB gzip-encoded)
  and parses it in about a second. A run takes into records the spills whose start, draft or certification date lies
  in the last WINDOW_DAYS (60) days and every spill already on record (so a late certification of an older spill is
  read); `--backfill` takes every spill in the file (since June 2023, about 3,700 reports). A spill on record that
  leaves the file keeps its record with raw._missing_from_file_since. A file not rebuilt for more than STALE_DAYS is
  an outage (ok false, the records kept).

Run from pipeline/:  python -m ingest.ca_swrcb_ciwqs_spills [--file Cat1-2-3-Spills.txt] [--backfill]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import string
import sys
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from common import (BUILD_DIR, DATA_DIR, EVENTS_DIR, HEADERS, NAME_REMOVED, OPERATOR_WORDS, ROOT, event, now_iso,
                    path_notes_to_meta, read_json, save_raw, scrub_text, strip_house_numbers, write_events, write_json)

SOURCE_ID = "ca-swrcb-ciwqs-spills-flatfile"
FILE_URL = "https://www.waterboards.ca.gov/water_issues/programs/sso/docs/data_files/Cat1-2-3-Spills.txt"
INDEX_URL = "https://www.waterboards.ca.gov/water_issues/programs/sso/docs/index.php"
STATE_FILE = BUILD_DIR / "ca-swrcb-ciwqs-state.json"
AUTHORITY = "California State Water Resources Control Board (CIWQS Sanitary Sewer System Database)"
CREDIT = ("California State Water Resources Control Board, CIWQS Sanitary Sewer System Database, statewide spill file "
          "(Cat1-2-3-Spills.txt)")
TZ = ZoneInfo("America/Los_Angeles")
WINDOW_DAYS = 60
STALE_DAYS = 4
# California's extent, with a margin (a point outside is not used)
BOUNDS = (-124.6, 32.4, -114.0, 42.1)

# the columns read, and the short keys they are kept under
COLUMNS = {
    "REGION": "region",
    "WDID": "wdid",
    "STATUS": "enrollee_status",
    "SANITARY_SEWER_SYSTEM_NAME": "system_name",
    "AGENCY_NAME": "agency_name",
    "SPILL_EVENT_ID": "spill_event_id",
    "SPILL_REPORT_VERSION": "version",
    "SPILL_STATUS": "spill_status",
    "SUBMIT_DRAFT_DATE": "draft_submitted_on",
    "INITIAL_CERTIFICATION_DATE": "first_certified_on",
    "FINAL_CERTIFICATION_DATE": "final_certified_on",
    "SPILL_TYPE": "spill_type",
    "SPILL_LOCATION_NAME": "location_name",
    "DATE_AND_TIME_THE_ENROLLEE_WAS_NOTIFIED_OF_SPILL": "enrollee_notified_at",
    "OPERATOR_ARRIVAL_TIME": "crew_arrival_at",
    "ESTIMATED_SPILL_START_DATE_AND_TIME": "start_at",
    "DATE_TIME_ENROLLEE_NOTIFIED_CALOES": "caloes_notified_at",
    "ASSIGNED_CONTROL_NUMBER": "caloes_control_number",
    "TECHNICAL_REPORT_UPLOAD_DATE": "technical_report_on",
    "LATITUDE": "lat",
    "LONGITUDE": "lon",
    "APPEARANCE_POINTS": "appearance_points",
    "ESTIMATED_TOTAL_SPILL_VOLUME_EXITING_THE_SYSTEM_(GAL)": "volume_total_gal",
    "DID_SPILL_REACH_DRAINAGE_CONVEYANCE_SYSTEM_(YES_NO)?": "reached_drainage_system",
    "ESTIMATED_SPILL_VOLUME_FULLY_RECOVERED_FROM_DRAINAGE_CONVEYANCE_SYSTEM_(GAL)": "volume_recovered_from_drainage_gal",
    "ESTIMATED_SPILL_VOLUME_REMAINING_WITHIN_DRAINAGE_CONVEYANCE_SYSTEM_(GAL)": "volume_left_in_drainage_gal",
    "ESTIMATED_SPILL_VOLUME_THAT_DISCHARGED_TO_SURFACE_WATERS_(GAL)": "volume_to_surface_water_gal",
    "ESTIMATED_TOTAL_SPILL_VOLUME_RECOVERED_(GAL)": "volume_recovered_gal",
    "SPILL_DESTINATION(S)": "destinations",
    "COORDINATES_AVAILABLE_(YES_NO)?": "destination_points_given",
    "LATITUDE_1": "dest_lat_1", "LONGITUDE_1": "dest_lon_1",
    "LATITUDE_2": "dest_lat_2", "LONGITUDE_2": "dest_lon_2",
    "LATITUDE_3": "dest_lat_3", "LONGITUDE_3": "dest_lon_3",
    "LATITUDE_4": "dest_lat_4", "LONGITUDE_4": "dest_lon_4",
    "SPILL_END_DATE_AND_TIME": "end_at",
    "SPILL_CAUSE(S)": "causes",
    "SYSTEM_FAILURE_LOCATION": "failure_location",
    "WAS_SPILL_ASSOCIATED_WITH_A_STORM_EVENT_(YES_NO)?": "storm_event",
    "SPILL_RESPONSE_COMPLETION_DATE": "response_completed_at",
    "NAME_OF_RECEIVING_WATER_BODY(S)": "receiving_water",
    "TYPE_OF_RECEIVING_WATER_BODY(S)": "receiving_water_type",
    "PUBLIC_ACCESS_IMPACT": "public_access_impact",
    "RESPONSIBLE_ENTITY_FOR_CLOSING_RESTRICTING_USE_OF_WATER_BODY": "closing_entity",
    "NUMBER_OF_DAYS_CLOSED_RESTRICTED_AS_A_RESULT_OF_SPILL": "days_closed_or_restricted",
    "WAS_SPILL_LOCATED_WITHIN_1000_FEET_OF_A_MUNICIPAL_SURFACE_WATER_INTAKE_(YES_NO)?": "within_1000_ft_of_intake",
    "WERE_WATER_QUALITY_SAMPLES_COLLECTED_(YES_NO)?": "samples_collected",
}
KEYS = list(COLUMNS.values())
WITHHELD_NOTE = ("The file's certifier name and title and every narrative the operator wrote (descriptions of the "
                 "location, spill extent, drainage system, discharge points, destinations, volume estimates, causes, "
                 "impacts, response, corrective actions, investigation, water body and samples) are not reproduced "
                 "here: they can name staff, residents and private addresses. The source file has them.")
TRACKED = ("version", "spill_status", "start_at", "end_at", "volume_total_gal", "volume_to_surface_water_gal",
           "receiving_water", "spill_type")
CATEGORY = re.compile(r"category\s*([1-4])", re.I)
TS = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})(?:\s+(\d{1,2}):(\d{2})(?::(\d{2}))?)?$")
DMY = re.compile(r"^(\d{1,2})-([A-Za-z]{3})-(\d{2,4})$")
MONTHS = {m: i for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}
WATER_NONE = re.compile(r"^\s*(n/?a|none|no|nothing|unknown|tbd|not applicable|-+|\.+|0)\s*\.?\s*$", re.I)
PRIVATE_ONLY = {"lateral clean out (private)", "inside building or structure"}
SITE_WORDS = {"district", "dept", "department", "flood", "control", "parks", "park", "harbor", "harbors", "beaches",
              "health", "environmental", "staff", "county", "city", "state", "water", "regional", "agency", "public",
              "services", "division", "office", "board", "authority", "police", "fire", "coast", "guard", "army",
              "navy", "port", "valley", "lake", "river", "creek", "bay", "marina", "superintendent"}


# ---------------------------------------------------------------- reading the file

def clean(v) -> str:
    return " ".join(str(v if v is not None else "").replace("\xa0", " ").split())


def decode(content: bytes) -> str:
    """The file is Windows-1252 text (curly quotes as 0x92); UTF-8 is tried first in case the Board changes it."""
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return content.decode("cp1252", errors="replace")


def read_rows(text: str) -> list[dict]:
    """Rows of the file with only the read columns, under their short keys. Raises when a needed column is missing
    (a changed layout must not pass silently)."""
    csv.field_size_limit(10 ** 8)
    reader = csv.reader(io.StringIO(text), delimiter="\t")
    try:
        header = [clean(h) for h in next(reader)]
    except StopIteration:
        raise ValueError("the file is empty") from None
    idx = {h: i for i, h in enumerate(header) if h}
    missing = [c for c in ("SPILL_EVENT_ID", "SPILL_REPORT_VERSION", "SPILL_TYPE", "WDID",
                           "ESTIMATED_SPILL_START_DATE_AND_TIME") if c not in idx]
    if missing:
        raise ValueError(f"the file lacks the columns {missing}")
    out = []
    for cells in reader:
        if not any(c.strip() for c in cells):
            continue
        out.append({key: clean(cells[idx[col]]) if col in idx and idx[col] < len(cells) else ""
                    for col, key in COLUMNS.items()})
    return out


# ---------------------------------------------------------------- helpers

def parse_local(v) -> tuple[datetime | None, str | None]:
    """'04/10/2025 09:15' -> (aware Pacific datetime, note on a clock-change time or None)."""
    m = TS.match(clean(v))
    if not m:
        return None, None
    mo, d, y, hh, mm, ss = m.groups()
    try:
        naive = datetime(int(y), int(mo), int(d), int(hh or 0), int(mm or 0), int(ss or 0))
    except ValueError:
        return None, None
    dt = naive.replace(tzinfo=TZ)
    note = None
    a, b = naive.replace(tzinfo=TZ, fold=0), naive.replace(tzinfo=TZ, fold=1)
    if a.utcoffset() != b.utcoffset():
        note = f"{clean(v)} happened twice at the clock change; read as the first (daylight) time"
    elif a.astimezone(UTC).astimezone(TZ).replace(tzinfo=None) != naive:
        note = f"{clean(v)} did not exist at the clock change; read with the standard-time offset"
    return dt, note


def parse_day(v) -> date | None:
    """'11-APR-25' -> date(2025, 4, 11)."""
    m = DMY.match(clean(v))
    if not m:
        return None
    d, mon, y = m.groups()
    yr = int(y) + (2000 if len(y) == 2 else 0)
    try:
        return date(yr, MONTHS[mon.upper()], int(d))
    except (KeyError, ValueError):
        return None


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat(timespec="seconds") if dt else None


def fnum(v) -> float | None:
    s = clean(v).replace(",", "")
    try:
        f = float(s)
    except ValueError:
        return None
    return f if f == f else None


def gallons(v) -> int | None:
    f = fnum(v)
    return int(round(f)) if f is not None and f >= 0 else None


def version_key(v) -> tuple:
    return tuple(int(x) if x.isdigit() else 0 for x in re.split(r"[.\s]+", clean(v)) if x) or (0,)


def category(spill_type) -> str | None:
    m = CATEGORY.search(clean(spill_type))
    return m.group(1) if m else None


STREET_WORDS = {"street", "st", "road", "rd", "avenue", "ave", "av", "lane", "ln", "drive", "dr", "way", "court", "ct",
                "place", "pl", "circle", "cir", "boulevard", "blvd", "highway", "hwy", "parkway", "pkwy", "terrace",
                "ter", "trail", "trl", "loop", "row", "square", "alley", "mall", "plaza", "freeway", "fwy",
                "expressway", "frontage", "path", "walk", "crossing", "bridge", "tunnel", "gate", "gates", "pier",
                "wharf", "beach", "mountain", "hill", "hills", "canyon", "ranch", "estates", "village", "campus",
                "airport", "school", "library", "hospital", "station", "manhole", "mh", "main", "mainline", "lateral",
                "sewer", "trunk", "siphon", "interceptor", "force", "pump", "lift", "plant", "basin", "storm",
                "cleanout", "north", "south", "east", "west", "intersection", "near", "and", "of", "at", "the",
                "hall", "stadium", "shelter", "dock", "course", "golf", "field", "steps", "easement", "pathway", "bench",
                "apartment", "apartments", "community", "point", "rock", "boundary", "sidewalk", "liftstation",
                "fitness", "valley", "del", "manor", "max", "smart", "upper", "lower", "open", "gated", "spill",
                "no", "not", "none", "see", "closure", "applicable", "attachment", "unknown"}
NAME_WORD = re.compile(r"^(?:[A-Z][a-z]+(?:[-'][A-Z]?[a-z]+)*|[A-Z]\.?)$")


def _person(s: str) -> bool:
    """A typed value that is only a person's name: build.redact.person_shaped, or two or three capitalised name
    words (an initial allowed) none of which is a works, site, place or street word."""
    from build import redact
    words = [w for w in re.split(r"[\s\-/.,()&']+", s) if w]
    low = {w.lower() for w in words}
    if low & (OPERATOR_WORDS | SITE_WORDS | STREET_WORDS):
        return False
    if any(ch.isdigit() for ch in s):
        return False
    if redact.person_shaped(s) or redact.person_shaped(string.capwords(s)):
        return True
    toks = s.split()
    return 2 <= len(toks) <= 3 and all(NAME_WORD.match(w) for w in toks)


def entity_name(v) -> str | None:
    """A typed agency or entity with no person in it: only a person's name -> "[name removed]"."""
    s = clean(v)
    if not s:
        return None
    if _person(s):
        return NAME_REMOVED
    return scrub_text(s) or None


def location_name(v) -> str | None:
    """The spill location as typed, with every street address's house number cut (it is very often a home)."""
    s = clean(v)
    if not s:
        return None
    if _person(s):
        return NAME_REMOVED
    return strip_house_numbers(scrub_text(s)) or None


def scrubbed_row(r: dict) -> dict:
    """The kept fields as the record keeps them (see the docstring)."""
    out = {k: r.get(k, "") for k in KEYS}
    out["location_name"] = location_name(out.get("location_name"))
    out["closing_entity"] = entity_name(out.get("closing_entity"))
    for k in ("agency_name", "system_name"):          # an enrollee's name: common.scrub_discharger checks it too
        out[k] = scrub_text(out[k]) if out.get(k) else None
    for k in ("receiving_water", "receiving_water_type", "destinations", "causes", "failure_location",
              "appearance_points", "public_access_impact", "caloes_control_number"):
        if isinstance(out.get(k), str):
            out[k] = scrub_text(out[k])
    return {k: (v if v not in ("",) else None) for k, v in out.items()}


def point(lat, lon) -> tuple[float | None, float | None, str | None]:
    """(lat, lon, note): a longitude typed without its minus sign is repaired; a point outside California is None."""
    la, lo = fnum(lat), fnum(lon)
    if la is None or lo is None or (la == 0 and lo == 0):
        return None, None, None
    note = None
    if lo > 0 and BOUNDS[0] <= -lo <= BOUNDS[2] and BOUNDS[1] <= la <= BOUNDS[3]:
        lo, note = -lo, "the longitude was given without its minus sign; read as west"
    if not (BOUNDS[0] <= lo <= BOUNDS[2] and BOUNDS[1] <= la <= BOUNDS[3]):
        return None, None, f"the point ({lat}, {lon}) lies outside California and is not used"
    return la, lo, note


def wdid_index(rows: list[dict] | None = None) -> dict[str, str]:
    """WDID -> data/dischargers.json id, for California rows (a WDID two rows hold maps to neither)."""
    if rows is None:
        rows = read_json(DATA_DIR / "dischargers.json", []) or []
    seen: dict[str, set[str]] = {}
    for r in rows:
        if not isinstance(r, dict) or r.get("state") != "CA":
            continue
        for p in [r.get("npdes_permit"), *(r.get("npdes_permits") or [])]:
            if p and re.match(r"^\d[A-Z]?SSO\d+$", str(p).strip().upper()):
                seen.setdefault(str(p).strip().upper(), set()).add(r["id"])
    return {p: next(iter(v)) for p, v in seen.items() if len(v) == 1}


def latest(rows: list[dict]) -> tuple[list[dict], dict[str, list[dict]]]:
    """(one row per spill, the highest report version; {spill id: the earlier versions})."""
    by: dict[str, list[dict]] = {}
    for r in rows:
        sid = clean(r.get("spill_event_id"))
        if sid:
            by.setdefault(sid, []).append(r)
    out, earlier = [], {}
    for sid, rs in by.items():
        rs = sorted(rs, key=lambda x: (version_key(x.get("version")), clean(x.get("final_certified_on"))))
        out.append(rs[-1])
        if len(rs) > 1:
            earlier[sid] = rs[:-1]
    return out, earlier


# ---------------------------------------------------------------- records

def build_record(row: dict, fetched_at: str, prev: dict | None, wdids: dict[str, str], earlier: list[dict],
                 file_modified: str | None) -> dict:
    a = scrubbed_row(row)
    sid = clean(a.get("spill_event_id"))
    base = dict(source_id=SOURCE_ID, source_record_id=sid, fetched_at=fetched_at, source_url=FILE_URL)
    p_raw = (prev or {}).get("raw") or {}
    raw = dict(a)
    raw["_withheld"] = WITHHELD_NOTE
    raw["_first_seen_at"] = p_raw.get("_first_seen_at") or fetched_at
    raw["_first_seen_in_file"] = p_raw.get("_first_seen_in_file") or file_modified
    revs = list(p_raw.get("_revisions") or [])
    if p_raw and any(clean(p_raw.get(k)) != clean(a.get(k)) for k in TRACKED):
        revs.append({"seen_until": (prev or {}).get("fetched_at"), **{k: p_raw.get(k) for k in TRACKED}})
    if revs:
        raw["_revisions"] = revs[-10:]
    if earlier:
        raw["_versions"] = [{"version": x.get("version"), "spill_status": x.get("spill_status"),
                             "final_certified_on": x.get("final_certified_on")} for x in earlier]
    try:
        return _record(a, base, raw, fetched_at, wdids)
    except Exception as e:  # noqa: BLE001 - never drop a record
        return event(**base, event_type="sso", status="unknown", raw=raw, authority=AUTHORITY,
                     parse_error=f"{type(e).__name__}: {e}")


def _record(a: dict, base: dict, raw: dict, fetched_at: str, wdids: dict[str, str]) -> dict:
    problems, notes = [], []
    fetched = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
    cat = category(a.get("spill_type"))
    raw["spill_category"] = cat
    if cat is None:
        problems.append(f"spill category not read: {a.get('spill_type')!r}")
    start, n1 = parse_local(a.get("start_at"))
    end, n2 = parse_local(a.get("end_at"))
    notes += [n for n in (n1, n2) if n]
    if a.get("start_at") and start is None:
        problems.append(f"start not read: {a.get('start_at')!r}")
    if a.get("end_at") and end is None:
        problems.append(f"end not read: {a.get('end_at')!r}")
    if start is not None and start > fetched + timedelta(days=1):
        raw["_start_not_used"] = (f"the start as published ({iso(start)}) lies after the file was read, most likely a "
                                  "typing error in the year; the report is kept with no start")
        start = None
    if end is not None and end > fetched + timedelta(days=1):
        raw["_end_not_used"] = f"the end as published ({iso(end)}) lies after the file was read"
        end = None
    if end is not None and start is not None and end < start:
        raw["_end_not_used"] = f"the end as published ({iso(end)}) is before the start"
        end = None
    certified = clean(a.get("spill_status")).lower() in ("certified", "amended")
    if end is not None:
        status, ended_at = "ended", iso(end)
        if not certified:
            raw["_end_basis"] = (f"the report is not yet certified (CIWQS status {a.get('spill_status')}); the end is "
                                 "the one the operator gave and may change at certification")
    else:
        status, ended_at = "unknown", None
        raw["_end_basis"] = ("no end reported: the General Order asks for the spill end only in the certified report, "
                             "due within 15 calendar days of the spill end; until then the end is not known, so none "
                             "is used")
    precision = "minute"
    if start is not None and (start.hour, start.minute) == (0, 0) and \
            (end is None or (end.hour, end.minute) == (0, 0)):
        precision = "day"
        notes.append("the times are typed as midnight; read as dates")
    if notes:
        raw["_time_notes"] = notes
    raw["_time_basis"] = "Pacific local time as the file gives it, written with its UTC offset"

    calo, _ = parse_local(a.get("caloes_notified_at"))
    draft = parse_day(a.get("draft_submitted_on"))
    first = parse_day(a.get("first_certified_on"))
    final = parse_day(a.get("final_certified_on"))
    if calo is not None:
        reported_at, raw["_reported_basis"] = iso(calo), "the time the operator notified Cal OES"
    elif draft is not None:
        reported_at, raw["_reported_basis"] = draft.isoformat(), "the date of the draft spill report in CIWQS"
    elif first is not None:
        reported_at, raw["_reported_basis"] = first.isoformat(), "the date the spill report was first certified"
    else:
        reported_at = None
    updated = max([d for d in (draft, first, final) if d is not None], default=None)

    # water
    water = clean(a.get("receiving_water")) or None
    names_water = bool(water and not WATER_NONE.match(water) and water != NAME_REMOVED)
    if cat == "1":
        raw["reached_water"] = True
        raw["_water_basis"] = ("Category 1 under the General Order: the sewage reached surface water, or a drainage "
                               "system that discharges to surface water and was not recovered")
        if not names_water:
            raw["_water_note"] = ("the report names no receiving water yet (the name is required only in the "
                                  "certified report)" if not water else "the report's receiving-water entry names no "
                                  "water")
    elif cat in ("2", "3"):
        raw["reached_water"] = False
        raw["_water_basis"] = (f"Category {cat} under the General Order: a spill that did not discharge to a surface "
                               "water; kept and counted, never placed on a water")

    # point
    lat, lon, pnote = point(a.get("lat"), a.get("lon"))
    if pnote and lat is None:
        raw["_coords_rejected"] = pnote
    elif pnote:
        raw["_coords_repaired"] = pnote
    precision_m = None
    apps = {x.strip().lower() for x in clean(a.get("appearance_points")).split(";") if x.strip()}
    if lat is not None and apps and apps <= PRIVATE_ONLY:
        lat, lon, precision_m = round(lat, 3), round(lon, 3), 150
        raw["_coords_rounded"] = ("the spill appeared only on private property (a private lateral clean-out or inside "
                                  "a building): its point is rounded to about 100 m so it does not mark a home")
    dests = []
    for i in range(1, 5):
        dla, dlo, _ = point(a.get(f"dest_lat_{i}"), a.get(f"dest_lon_{i}"))
        if dla is not None:
            dests.append({"lat": dla, "lon": dlo})
    for i in range(1, 5):
        raw.pop(f"dest_lat_{i}", None)
        raw.pop(f"dest_lon_{i}", None)
    if dests:
        raw["destination_points"] = dests

    # operator
    wdid = clean(a.get("wdid")).upper() or None
    did = wdids.get(wdid) if wdid else None
    if did is None:
        raw["_discharger_basis"] = (f"No operator on record for WDID {wdid} yet." if wdid else
                                    "The report gives no WDID, so no operator is joined.")

    # volume
    total = gallons(a.get("volume_total_gal"))
    surf = gallons(a.get("volume_to_surface_water_gal"))
    rec = gallons(a.get("volume_recovered_gal"))
    parts = []
    if total is not None:
        parts.append(f"{total:,} gallons spilled (estimated total leaving the sewer system)")
    if surf is not None:
        parts.append(f"{surf:,} gallons reached surface water")
    if rec is not None:
        parts.append(f"{rec:,} gallons recovered")
    vtext = "; ".join(parts) or None
    return event(
        **base, event_type="sso", status=status,
        discharger_id=did, discharger_name=a.get("agency_name"), npdes_permit=wdid,
        outfall_id=None, outfall_name=a.get("location_name"),
        waterbody_text=water if names_water else None, water_slugs=[], water_match="none",
        lat=lat, lon=lon, coord_source="source" if lat is not None else None, coord_precision_m=precision_m,
        started_at=iso(start), ended_at=ended_at, time_precision=precision if (start or ended_at) else None,
        reported_at=reported_at, published_at=None, source_updated_at=updated.isoformat() if updated else None,
        material="untreated sewage", volume_gal=total, volume_text=vtext, estimate_flag="estimated",
        authority=AUTHORITY, advice_text=None, advice_window_hours=None, advice_window_basis=None,
        raw=raw, parse_error="; ".join(problems) or None,
    )


def in_window(row: dict, today: date, days: int = WINDOW_DAYS) -> bool:
    """Whether a spill's start, draft or certification date lies in the last `days` days (or after today)."""
    floor = today - timedelta(days=days)
    start, _ = parse_local(row.get("start_at"))
    dates = [start.date() if start else None] + [parse_day(row.get(k)) for k in
                                                 ("draft_submitted_on", "first_certified_on", "final_certified_on")]
    return any(d is not None and d >= floor for d in dates)


def build(rows: list[dict], fetched_at: str, prev_records: list[dict], wdids: dict[str, str] | None = None,
          backfill: bool = True, file_modified: str | None = None, today: date | None = None
          ) -> tuple[list[dict], dict]:
    """rows: the file's rows (short keys). backfill False keeps to the window and the spills already on record.
    Returns (records, stats); earlier records of spills not in the file are kept and marked."""
    wdids = wdid_index() if wdids is None else wdids
    today = today or datetime.fromisoformat(fetched_at.replace("Z", "+00:00")).date()
    prev = {r["event_id"]: r for r in prev_records}
    current, earlier = latest(rows)
    records, seen, skipped = [], set(), 0
    for row in current:
        sid = clean(row.get("spill_event_id"))
        eid = f"{SOURCE_ID}:{sid}"
        seen.add(eid)
        if not backfill and eid not in prev and not in_window(row, today):
            skipped += 1
            continue
        records.append(build_record(row, fetched_at, prev.get(eid), wdids, earlier.get(sid, []), file_modified))
    kept = 0
    for eid, r in prev.items():
        if eid in seen:
            continue
        raw = r.setdefault("raw", {})
        raw["_missing_from_file_since"] = raw.get("_missing_from_file_since") or fetched_at
        records.append(r)
        kept += 1
    records.sort(key=lambda r: (r.get("started_at") or r.get("reported_at") or "", r["event_id"]), reverse=True)
    cats = Counter(str((r.get("raw") or {}).get("spill_category")) for r in records)
    stats = {"rows_read": len(rows), "spills_in_file": len(current), "versions_folded": len(rows) - len(current),
             "outside_window_not_read": skipped, "kept_missing_from_file": kept,
             "by_category": {f"Category {k}" if k in "123" else k: v for k, v in sorted(cats.items())},
             "shown_category_1": cats.get("1", 0),
             "kept_not_shown": {"Category 2": cats.get("2", 0), "Category 3": cats.get("3", 0)},
             "by_status": dict(Counter(r["status"] for r in records)),
             "by_report_status": dict(Counter(clean((r.get("raw") or {}).get("spill_status")) for r in records)),
             "with_point": sum(1 for r in records if r.get("lat") is not None),
             "with_water_name": sum(1 for r in records if r.get("waterbody_text")),
             "with_operator_row": sum(1 for r in records if r.get("discharger_id")),
             "statewide": True}
    return records, stats


# ---------------------------------------------------------------- fetching and main

def fetch(sess: requests.Session, state: dict) -> tuple[bytes | None, str | None]:
    """(content or None when not modified, Last-Modified as ISO UTC)."""
    headers = {}
    if state.get("last_modified_http"):
        headers["If-Modified-Since"] = state["last_modified_http"]
    r = sess.get(FILE_URL, headers=headers, timeout=(20, 300))
    lm = r.headers.get("Last-Modified")
    lm_iso = None
    if lm:
        try:
            lm_iso = parsedate_to_datetime(lm).astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
        except (TypeError, ValueError):
            lm_iso = None
    if r.status_code == 304:
        return None, lm_iso or state.get("last_modified")
    r.raise_for_status()
    if lm:
        state["last_modified_http"] = lm
    return r.content, lm_iso


def main(argv=None) -> int:
    from build import redact
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--file", help="read this saved Cat1-2-3-Spills.txt instead of the Board's file")
    ap.add_argument("--backfill", action="store_true", help="take every spill in the file (since June 2023)")
    args = ap.parse_args(argv)
    fetched_at = now_iso()
    state = read_json(STATE_FILE, {}) or {}
    prev_doc = read_json(EVENTS_DIR / f"{SOURCE_ID}.json", {}) or {}
    prev = prev_doc.get("records", [])
    sess = requests.Session()
    sess.headers.update(HEADERS)
    try:
        if args.file:
            content, modified = Path(args.file).read_bytes(), None
        else:
            content, modified = fetch(sess, state)
            if modified:
                age = datetime.now(UTC) - datetime.fromisoformat(modified.replace("Z", "+00:00"))
                if age > timedelta(days=STALE_DAYS):
                    raise RuntimeError(f"the file has not been rebuilt since {modified} ({age.days} days)")
    except Exception as e:  # noqa: BLE001
        write_json(STATE_FILE, state)
        write_events(SOURCE_ID, [], ok=False, error=f"{type(e).__name__}: {e}")
        print(f"{SOURCE_ID}: FAILED {e}", file=sys.stderr)
        return 1
    if content is None and not args.backfill and prev:
        meta = {**(prev_doc.get("meta") or {}), "file_not_modified_since": modified, "checked_at": fetched_at}
        write_events(SOURCE_ID, prev, ok=True, error=None, meta=meta)
        write_json(STATE_FILE, {**state, "checked_at": fetched_at})
        print(f"{SOURCE_ID}: file not modified since {modified}; {len(prev)} records kept")
        return 0
    if content is None:                      # a backfill or a first run after a 304: ask for the whole file
        state.pop("last_modified_http", None)
        content, modified = fetch(sess, state)
    try:
        rows = read_rows(decode(content))
        if not rows:
            raise ValueError("the file holds no spill rows")
    except Exception as e:  # noqa: BLE001
        write_events(SOURCE_ID, [], ok=False, error=f"{type(e).__name__}: {e}")
        print(f"{SOURCE_ID}: FAILED {e}", file=sys.stderr)
        return 1
    raw_path = state.get("raw_path")
    if not args.file:
        safe = [scrubbed_row(r) for r in rows]
        doc = {"file": FILE_URL, "last_modified": modified, "fetched_at": fetched_at, "rows": safe}
        sha = hashlib.sha256(json.dumps(safe, sort_keys=True).encode()).hexdigest()
        if sha != state.get("sha256"):
            raw_path = str(save_raw(SOURCE_ID, json.dumps(doc, ensure_ascii=False), "json").relative_to(ROOT))
            state.update(sha256=sha, raw_path=raw_path, saved_at=fetched_at)
    records, stats = build(rows, fetched_at, prev, wdid_index(), backfill=args.backfill, file_modified=modified)
    records = redact.redact_events(records)
    state.update(fetched_at=fetched_at, last_modified=modified)
    if args.backfill:
        state["backfill"] = {"at": fetched_at, "spills": stats["spills_in_file"]}
    write_json(STATE_FILE, state)
    newest = max((r.get("reported_at") or "" for r in records), default="") or None
    meta = {**stats, "newest_report": newest, "file_last_modified": modified, "raw_path": raw_path, "file": FILE_URL,
            "page": INDEX_URL, "time_basis": "Pacific local time as the file gives it, written with its UTC offset",
            "credit": CREDIT, "registry_ids": [SOURCE_ID], "window_days": WINDOW_DAYS, "backfill": state.get("backfill"),
            "shown_note": ("Category 1 spills (sewage that reached surface water) are shown. Category 2 and 3 spills "
                           "did not reach surface water: they are kept on the record and counted, not placed on a "
                           "water. Category 4 spills (under 50 gallons, no surface water) are reported only as monthly "
                           "counts, and spills from private laterals are reported voluntarily to a separate file; "
                           "neither is in this file.")}
    path_notes_to_meta(records, meta)
    path = write_events(SOURCE_ID, records, ok=True, error=None, meta=meta)
    print(f"{SOURCE_ID}: {stats['spills_in_file']} spills in the file, {len(records)} records; categories "
          f"{stats['by_category']}; status {stats['by_status']}; operator row {stats['with_operator_row']} -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
