"""California State Water Board spill history under the 2006 General Order -> data/build/events/ca-swrcb-ciwqs-sso-2006-order.json

Source
  State Water Resources Control Board, Sanitary Sewer Systems program: the flat file of every spill reported to the
  CIWQS Sanitary Sewer System Database under the Statewide General Waste Discharge Requirements for Sanitary Sewer
  Systems, Order 2006-0003-DWQ, and its Monitoring and Reporting Program as amended by Order WQ 2013-0058-EXEC,
  https://www.waterboards.ca.gov/water_issues/programs/sso/docs/data_files/SSO.txt
  (index: https://www.waterboards.ca.gov/water_issues/programs/sso/docs/index.php, whose note 10 says the file
  "Contains detailed information about spill data submitted from January 2007 to June 5, 2023"). Tab-delimited, 66
  header columns (the last one empty), Windows-1252 text, one row per spill report: 69,321 rows and about 52 MB on
  2026-11-21. The Board writes the file again each night (its Last-Modified moves daily) although the spills in it
  ended with the 2006 order. No key, no licence statement. Credit "California State Water Resources Control Board,
  CIWQS Sanitary Sewer System Database (SSO.txt)".
  The spills from 2023-06-05 on, under Order WQ 2022-0103-DWQ, are in Cat1-2-3-Spills.txt, read by
  ingest/ca_swrcb_ciwqs_spills.py; this module reuses that module's reading, time, scrub and point helpers.
  Law: under the Monitoring and Reporting Program (Order WQ 2013-0058-EXEC), a Category 1 spill is a discharge of any
  volume that reaches surface water or a drainage channel tributary to one, or reaches a municipal separate storm
  sewer system and is not fully captured and returned to the sanitary sewer; Category 2 is 1,000 gallons or more that
  reaches none of these (or is fully recovered from the storm drain); Category 3 is every other spill. The file labels
  its spills with these three categories through its whole span, 2007 included.

What is read (privacy)
  Only the columns in COLUMNS are read, under short keys; every other column is never parsed into a record or saved:
  the certifier (CERT PERSON NAME, CERT PERSON TITLE, CERT LOCATION, CERT ID), the operator's contact (SSO OPERATOR
  NAME, SSO OPERATOR PHONE) and every narrative or "explain" field (SPILL LOC DESC, APPEAR PT EXPLAIN, FINAL SPILL
  DEST EXPL, SPILL CAUSE EXPLAIN, WHERE FAIL OCCUR EXP, RESPONSE ACTIVITIES EXPL, SSO CRCTIVE ACTION TAKEN EXPL,
  REASON INVESTIGATE, VISUAL INSPCT RESULT, BEACH IMPACT, SURFACE WATER IMPACT, SMPLS_ANALYZE_FOR_EXPL, SMPLS REPORT
  TO EXPL, SSO VOLUME METHOD), which can name staff, residents and private addresses (raw._withheld says so). The
  spill location name (typed by the operator, often a home's street address) loses every house number
  (ca_swrcb_ciwqs_spills.location_name: common.scrub_text, common.strip_house_numbers, then the numbers that cut
  leaves); a value that is only a person's name becomes "[name removed]". When the spill appeared only on private
  property (a private lateral clean-out, a private upper or lower lateral, a backflow prevention device, or a
  building or structure) its point is rounded to three decimals (about 100 m), coord_precision_m 150, so it does not
  mark a home; the typed point is rounded in scrubbed_row, so raw.lat, raw.lon and the saved page hold only the
  rounded digits. common.strip_personal runs on every raw (in common.event) and build.redact over the records last. The
  saved raw page (data/raw/<source>/) holds only the scrubbed short-key rows of the Category 1 spills, never the
  file. tests/test_ca_swrcb_ciwqs_sso_2006.py proves that the certifier, the operator's name and phone and a
  narrative never reach a record or the saved page.

Which reports are shown
  Only Category 1 spills become records (event_type sso, raw.spill_category "1", raw.reached_water true): the site
  covers discharges into public waters, and the order's own category says the sewage reached one. In the 2026-11-21
  file every Category 1 spill (10,537) gives a volume reaching surface water above zero and no Category 2 or 3 spill
  does; REACH_SURFACE says Yes on 9,493 Category 1 spills, and of the 1,044 that say No, 910 reached a storm drain
  (828 with the sewage not returned to the sewer system). 100 Category 2 or 3 spills say REACH_SURFACE Yes with no
  volume reaching surface water; they follow their category. Categories 2 and 3 (spills to land, 58,784 rows) are
  counted in meta (by_category, category_1_flags, category_2_3_marked_reached_surface) and make no record.

Record rules
  - Key: SPILL ID. Rows sharing a SPILL ID, WDID and start minute are versions of one spill: the certified row
    with the latest certification date is the record, the others are listed in raw._versions. Rows sharing a SPILL
    ID with another WDID or start are different spills: each gets the key "<SPILL ID>-<WDID>-<YYYYMMDDHHMM>"
    (raw._key_basis says so). Keys never move: when an ID that was one spill becomes several, the spill whose WDID
    and start match the earlier record keeps the plain key, and a split key a previous record holds is kept. A row
    with no SPILL ID is kept under "noid-<WDID>-<YYYYMMDDHHMM>" with a parse_error saying so (meta
    rows_without_spill_id counts them). Two records under one event id fail the read (check_unique).
  - No history record is dropped for the 2022 order's file (read from its events file: ca_swrcb_ciwqs_spills runs
    first in the sorted ingest loop). A copy (the same WDID and start minute, plus the same SPILL ID, or origin points
    within OVERLAP_DEG, about 150 m, and the same volume) gets duplicate_of, that file's event id, and
    raw._duplicate_basis: the status build lists the spill from that file. The same WDID and start date with a nearby
    point is a possible copy only: both are listed, raw._possible_copy_of {event_id, reason}. The same SPILL ID
    under another WDID or in another year is never a match. meta.overlap_with_2022_order counts both kinds.
  - Times are Pacific local time as typed ("MM/DD/YYYY HH:MM"), written with their offset, time_precision "minute"
    (a start typed as midnight with no end, or an end also at midnight, is read at day precision). started_at = START
    DT, ended_at = EST END DT. A start after the read, or before 2006 (the order's year: a typing error in the year),
    is not used (raw._start_not_used) and the report is kept with no start.
  - Status: an end at or after the start -> ended (a report not certified says in raw._end_basis that the end is the
    operator's draft); no end -> unknown with no end (the end is never supplied); an end before the start, or after
    the read, is kept as published with status unknown and raw._end_not_used: the status build's shared rule for an
    implausible end (unresolved.implausible_end) draws no window from it.
  - reported_at: the time of the Cal OES control number (OES CONTROL DT) when given, else the draft report's date,
    else the first certification date, else the date the report was created in CIWQS (raw._reported_basis says
    which). published_at is null (the file gives no posting time). source_updated_at is the latest of the draft,
    first certification and certification dates.
  - Water: the file names no receiving water (the only water texts are narratives, which are not read):
    waterbody_text is null and the record carries its point. The status build places such a record by the point when
    it lies within 400 m of a mapped water (GEOMETRY_MATCH_M), else on the operator's one listed receiving water; on
    2026-11-21 that placed 2,141 of the 10,536 records by point and 1,313 on the operator's water, and left 7,082
    unplaced (listed, colouring nothing).
  - Operator: npdes_permit is the enrollee's WDID (the General Order is not an NPDES permit); discharger_id is the
    data/dischargers.json California row that holds the WDID; discharger_name is that row's name, else the agency the
    2022 order's file names for the WDID (the 2006 file gives no agency name).
  - Point: LATTITUDE / LONGITUDE DECIMAL DEGREES (the spill's origin); a longitude typed without its minus sign inside
    California is repaired (raw._coords_repaired); a point outside California is not used (raw._coords_rejected).
  - Volume: volume_gal is SPILL VOL (the estimated total); volume_text adds the volume that reached surface water and
    the volume recovered, as estimated by the operator (estimate_flag "estimated").

Reading (what each run costs)
  The file is history. A run asks for it at most once every REREAD_DAYS (7) days, with If-Modified-Since; between
  those reads, and on a 304, the records are kept as they are (no request, nothing rebuilt). A read downloads the
  whole file (about 52 MB, less when the server compresses it) and builds the records in about 20 seconds, most of
  it the shared scrub and redaction; every spill is read (no window), so `--backfill` reads the whole file at once,
  without If-Modified-Since or the seven-day wait. A spill on record that leaves the file keeps its record with
  raw._missing_from_file_since. A data row with fewer fields than the header (a file cut short) or a repeated event
  id fails the read: the previous records are kept (ok false) and the error names how many rows, never their
  content. The links to the 2022 order's events file are made again on every run, without a new read. meta.frozen is true (the status build never calls the
  feed stale for its age, only for a failed read) and meta.statewide false (history watches no water now, so the
  feed is not counted as covering every California outfall).

Run from pipeline/:  python -m ingest.ca_swrcb_ciwqs_sso_2006 [--file SSO.txt] [--backfill]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import requests

from common import (DATA_DIR, BUILD_DIR, EVENTS_DIR, HEADERS, ROOT, error_detail, error_text, event, now_iso, path_notes_to_meta, read_json,
                    save_raw, scrub_text, write_events, write_json)
from ingest import ca_swrcb_ciwqs_spills as L

SOURCE_ID = "ca-swrcb-ciwqs-sso-2006-order"
FILE_URL = "https://www.waterboards.ca.gov/water_issues/programs/sso/docs/data_files/SSO.txt"
INDEX_URL = L.INDEX_URL
STATE_FILE = BUILD_DIR / "ca-swrcb-ciwqs-sso-2006-state.json"
LIVE_EVENTS = EVENTS_DIR / f"{L.SOURCE_ID}.json"
AUTHORITY = L.AUTHORITY
CREDIT = ("California State Water Resources Control Board, CIWQS Sanitary Sewer System Database, spills under Order "
          "2006-0003-DWQ, 2007 to 2023 (SSO.txt)")
REREAD_DAYS = 7
OVERLAP_DEG = 0.0015          # about 150 m: two origin points this close, same WDID and day, are one spill
EARLIEST_START = date(2006, 1, 1)

# the columns read, and the short keys they are kept under
COLUMNS = {
    "REGION": "region",
    "WDID": "wdid",
    "STATUS": "enrollee_status",
    "SPILL ID": "spill_id",
    "STEP": "report_step",
    "SPILL CREATED DT": "created_on",
    "SUBMIT DRAFT DATE": "draft_submitted_on",
    "ORIGINAL CERTIFIED DATE": "first_certified_on",
    "CERT DT": "certified_on",
    "SPILL TYPE": "spill_type",
    "SPILL VOL REACH LAND": "volume_to_land_gal",
    "SPILL VOL": "volume_total_gal",
    "SPILL VOL RECOVER": "volume_recovered_gal",
    "SPILL VOL REACH SURF": "volume_to_surface_water_gal",
    "REACH_SURFACE": "reached_surface_water",
    "REACH STORM DRAINPIPE": "reached_storm_drain",
    "RETURN TO SSS": "returned_to_sewer",
    "SPILL LOC NAME": "location_name",
    "LATTITUDE DECIMAL DEGREES": "lat",
    "LONGITUDE DECIMAL DEGREES": "lon",
    "COUNTY": "county",
    "REGIONAL BOARD": "regional_board",
    "SSO NUMBER APPEAR POINTS": "appearance_point_count",
    "APPEAR PT": "appearance_points",
    "FINAL SPILL DEST": "destinations",
    "START DT": "start_at",
    "AGENCY NOTIFY DT": "enrollee_notified_at",
    "OPRTOR ARRVL DT": "crew_arrival_at",
    "EST END DT": "end_at",
    "SPILL CAUSE": "causes",
    "WHERE FAILURE OCCUR": "failure_location",
    "SSO Storm Associated": "storm_event",
    "RESPONSE COMPLETE DT": "response_completed_at",
    "HEALTH WARNING POST": "health_warning_posted",
    "SSO IF IMPACT BEACH": "beach_impacted",
    "OES CONTROL NUMBER": "caloes_control_number",
    "OES CONTROL DT": "caloes_control_at",
}
KEYS = list(COLUMNS.values())
REQUIRED = ("SPILL ID", "WDID", "SPILL TYPE", "START DT", "EST END DT")
WITHHELD_NOTE = ("The file's certifier, the operator's contact name and phone and every narrative the operator wrote "
                 "(descriptions of the location, appearance points, destination, cause, failure, response, corrective "
                 "action, investigation, beach and surface water impacts, samples and the volume method) are not "
                 "reproduced here: they can name staff, residents and private addresses. The source file has them.")
TRACKED = ("report_step", "start_at", "end_at", "volume_total_gal", "volume_to_surface_water_gal", "spill_type")
# appearance points on private property: a spill that appeared only at these has its point rounded (it marks a home);
# the 2006 form's "building or structure" is the 2022 form's "inside building or structure"
PRIVATE_ONLY = L.PRIVATE_ONLY | {"building or structure"}
DAY_FORMS = (re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})$"), re.compile(r"^(\d{1,2})-(\d{1,2})-(\d{4})$"))
CERTIFIED = {"certified"}
SHOWN_NOTE = ("Category 1 spills (sewage that reached surface water, or a storm drain or drainage channel and was not "
              "recovered) are shown. Category 2 and 3 spills, which reached no water, are counted and not listed. "
              "Spills from June 5, 2023, are in the State Water Board's current spill file.")


# ---------------------------------------------------------------- helpers

def day(v) -> date | None:
    """A date in any of the file's forms: '11-APR-25', '04/11/2025', '4/11/25', '04-11-2025'."""
    s = L.clean(v)
    if not s:
        return None
    d = L.parse_day(s)
    if d is not None:
        return d
    for rx in DAY_FORMS:
        m = rx.match(s)
        if m:
            mo, dd, y = m.groups()
            try:
                return date(int(y) + (2000 if len(y) == 2 else 0), int(mo), int(dd))
            except ValueError:
                return None
    dt, _ = L.parse_local(s)
    return dt.date() if dt else None


def private_only(appearance_points) -> bool:
    """Whether the spill appeared only on private property (PRIVATE_ONLY)."""
    apps = {x.strip().lower() for x in L.clean(appearance_points).split(";") if x.strip()}
    return bool(apps) and apps <= PRIVATE_ONLY


def rounded(v) -> str | None:
    """A typed coordinate to three decimals (about 100 m), as text; None when it is not a number."""
    return L.rounded(v)


def scrubbed_row(r: dict) -> dict:
    """The kept fields as the record keeps them (see the docstring): the location loses its house numbers, the
    pick-list texts pass common.scrub_text, and the point of a spill on private property is rounded here, so no
    record or saved page holds its typed digits (review 2026-11-21 P1-1)."""
    out = {k: r.get(k, "") for k in KEYS}
    out["location_name"] = L.location_name(out.get("location_name"))
    for k in ("appearance_points", "destinations", "causes", "failure_location", "county", "caloes_control_number"):
        if isinstance(out.get(k), str) and out[k]:
            out[k] = scrub_text(out[k])
    if private_only(out.get("appearance_points")):
        out["lat"], out["lon"] = rounded(out.get("lat")), rounded(out.get("lon"))
    return {k: (v if v != "" else None) for k, v in out.items()}


def report_rank(r: dict) -> tuple:
    """Which of a spill's rows is its record: a certified row first, then the latest certification date."""
    return (L.clean(r.get("report_step")).lower() in CERTIFIED, day(r.get("certified_on")) or date.min,
            day(r.get("first_certified_on")) or date.min)


def stamp(start) -> str:
    """A typed start as YYYYMMDDHHMM (Pacific, as typed); the digits as typed when it does not read; "nostart"."""
    dt, _ = L.parse_local(start)
    if dt is not None:
        return dt.strftime("%Y%m%d%H%M")
    return re.sub(r"[^0-9]", "", L.clean(start)) or "nostart"


def identity(r: dict) -> tuple[str, str]:
    """(WDID, start stamp) of a row, or of a record's raw (both keep the typed wdid and start_at)."""
    return L.clean(r.get("wdid")).upper(), stamp(r.get("start_at"))


def spills(rows: list[dict], prev_records: list[dict] | None = None
           ) -> tuple[list[tuple[str, dict, list[dict], str | None]], int, int]:
    """[(record key, the row, its other versions, key note)], the number of rows folded as versions and the number
    of rows with no SPILL ID. Rows with one SPILL ID, WDID and start minute are one spill. One SPILL ID with several
    WDIDs or starts is several spills: each is keyed "<SPILL ID>-<WDID>-<YYYYMMDDHHMM>", except the one a previous
    record keyed with the SPILL ID alone holds (same WDID and start), which keeps that key; a spill keeps a split key
    a previous record holds even when it is alone again (keys never move). A row with no SPILL ID is keyed
    "noid-<WDID>-<YYYYMMDDHHMM>"."""
    prev_ids = {}
    for r in prev_records or []:
        key = str(r.get("source_record_id") or "")
        if key:
            prev_ids[key] = identity(r.get("raw") or {})
    by: dict[str, dict[tuple, list[dict]]] = {}
    no_id = 0
    for r in rows:
        sid = L.clean(r.get("spill_id"))
        if not sid:
            no_id += 1
        by.setdefault(sid, {}).setdefault(identity(r), []).append(r)
    out, folded = [], 0
    for sid, groups in by.items():
        for (wdid, st), rs in groups.items():
            rs = sorted(rs, key=report_rank)
            folded += len(rs) - 1
            split = f"{sid}-{wdid or 'nowdid'}-{st}"
            if not sid:
                out.append((f"noid-{wdid or 'nowdid'}-{st}", rs[-1], rs[:-1],
                            "the file gives no SPILL ID for this spill; it is keyed by its WDID and start"))
            elif prev_ids.get(split) == (wdid, st):
                out.append((split, rs[-1], rs[:-1], "keyed with its WDID and start, as when it was first read"))
            elif len(groups) == 1 or prev_ids.get(sid) == (wdid, st):
                note = None if len(groups) == 1 else (f"the file gives SPILL ID {sid} to {len(groups)} spills; this "
                                                      "one keeps the key it had")
                out.append((sid, rs[-1], rs[:-1], note))
            else:
                out.append((split, rs[-1], rs[:-1],
                            f"the file gives SPILL ID {sid} to {len(groups)} spills (different WDIDs or starts); this "
                            "one is keyed with its WDID and start"))
    return out, folded, no_id


def check_unique(records: list[dict]) -> None:
    """Two records under one event id would lose one spill downstream: such a read is not used."""
    rep_ = [k for k, n in Counter(r["event_id"] for r in records).items() if n > 1]
    if rep_:
        raise ValueError(f"{len(rep_):,} event id{'s' if len(rep_) != 1 else ''} would repeat (first {rep_[0]}); "
                         "the read is not used")


def operator_names(live_records: list[dict]) -> dict[str, str]:
    """WDID -> the agency the 2022 order's file names for it (one name only)."""
    seen: dict[str, set[str]] = {}
    for r in live_records:
        w, n = L.clean(r.get("npdes_permit")).upper(), r.get("discharger_name")
        if w and isinstance(n, str) and n.strip() and n != L.NAME_REMOVED:
            seen.setdefault(w, set()).add(n.strip())
    return {w: next(iter(v)) for w, v in seen.items() if len(v) == 1}


def discharger_names(rows: list[dict] | None = None) -> dict[str, str]:
    """data/dischargers.json id -> name, for California rows."""
    if rows is None:
        rows = read_json(DATA_DIR / "dischargers.json", []) or []
    return {r["id"]: r["name"] for r in rows if isinstance(r, dict) and r.get("state") == "CA" and r.get("id")
            and isinstance(r.get("name"), str) and r["name"].strip()}


# ---------------------------------------------------------------- records

def build_record(key: str, row: dict, fetched_at: str, prev: dict | None, wdids: dict[str, str], names: dict[str, str],
                 live_names: dict[str, str], earlier: list[dict], key_note: str | None,
                 file_modified: str | None) -> dict:
    a = scrubbed_row(row)
    base = dict(source_id=SOURCE_ID, source_record_id=key, fetched_at=fetched_at, source_url=FILE_URL)
    p_raw = (prev or {}).get("raw") or {}
    raw = dict(a)
    raw["_withheld"] = WITHHELD_NOTE
    raw["_first_seen_at"] = p_raw.get("_first_seen_at") or fetched_at
    raw["_first_seen_in_file"] = p_raw.get("_first_seen_in_file") or file_modified
    revs = list(p_raw.get("_revisions") or [])
    if p_raw and any(L.clean(p_raw.get(k)) != L.clean(a.get(k)) for k in TRACKED):
        revs.append({"seen_until": (prev or {}).get("fetched_at"), **{k: p_raw.get(k) for k in TRACKED}})
    if revs:
        raw["_revisions"] = revs[-10:]
    if earlier:
        raw["_versions"] = [{"report_step": x.get("report_step"), "certified_on": x.get("certified_on"),
                             "spill_type": x.get("spill_type")} for x in earlier]
    if key_note:
        raw["_key_basis"] = key_note
    try:
        rec = _record(a, base, raw, fetched_at, wdids, names, live_names)
        if not L.clean(a.get("spill_id")):
            rec["parse_error"] = "; ".join(x for x in ("the file gives no SPILL ID; keyed by WDID and start",
                                                       rec.get("parse_error")) if x)
        return rec
    except Exception as e:  # noqa: BLE001 - never drop a record
        return event(**base, event_type="sso", status="unknown", raw=raw, authority=AUTHORITY,
                     parse_error=f"{error_text(e)}")


def _record(a: dict, base: dict, raw: dict, fetched_at: str, wdids: dict[str, str], names: dict[str, str],
            live_names: dict[str, str]) -> dict:
    problems, notes = [], []
    fetched = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
    cat = L.category(a.get("spill_type"))
    raw["spill_category"] = cat
    raw["reached_water"] = True
    raw["_water_basis"] = ("Category 1 under the 2006 General Order: the sewage reached surface water or a drainage "
                           "channel, or a storm drain from which it was not fully recovered; the file names no "
                           "receiving water")
    start, n1 = L.parse_local(a.get("start_at"))
    end, n2 = L.parse_local(a.get("end_at"))
    oes, n3 = L.parse_local(a.get("caloes_control_at"))
    notes += [f"{field}: {n}" for field, n in (("START DT", n1), ("EST END DT", n2), ("OES CONTROL DT", n3)) if n]
    if a.get("start_at") and start is None:
        problems.append(f"start not read: {a.get('start_at')!r}")
    if a.get("end_at") and end is None:
        problems.append(f"end not read: {a.get('end_at')!r}")
    if start is not None and start > fetched + timedelta(days=1):
        raw["_start_not_used"] = (f"the start as published ({L.iso(start)}) lies after the file was read, most likely "
                                  "a typing error in the year; the report is kept with no start")
        start = None
    elif start is not None and start.date() < EARLIEST_START:
        raw["_start_not_used"] = (f"the start as published ({L.iso(start)}) lies before the 2006 General Order, most "
                                  "likely a typing error in the year; the report is kept with no start")
        start = None
    implausible = None
    if end is not None and start is not None and end < start:
        implausible = "is before the start"
    elif end is not None and end > fetched + timedelta(days=1):
        implausible = "lies after the file was read"
    certified = L.clean(a.get("report_step")).lower() in CERTIFIED
    if implausible:
        status, ended_at = "unknown", L.iso(end)
        raw["_end_not_used"] = f"the end as published ({L.iso(end)}) {implausible}"
        raw["_end_basis"] = (
            "the report gives an end before the start, most likely a typing error: it is kept as published and not "
            "used, so the spill has no confirmed end (the site's rule for an implausible end, "
            "unresolved.implausible_end)" if implausible == "is before the start" else
            "the report gives an end after the file was read, most likely a typing error: it is kept as published and "
            "the report is not counted as ended; the site's rule for an implausible end (unresolved.implausible_end) "
            "decides whether a window is drawn to it")
    elif end is not None:
        status, ended_at = "ended", L.iso(end)
        if not certified:
            raw["_end_basis"] = (f"the report was never certified (CIWQS step {a.get('report_step')}); the end is the "
                                 "one the operator gave in the draft")
    else:
        status, ended_at = "unknown", None
        raw["_end_basis"] = "the file gives no end for this spill; none is used"
    precision = "minute"
    if start is not None and (start.hour, start.minute) == (0, 0) and \
            (end is None or implausible or (end.hour, end.minute) == (0, 0)):
        precision = "day"
        notes.append("the times are typed as midnight; read as dates")
    if notes:
        raw["_time_notes"] = notes
    raw["_time_basis"] = "Pacific local time as the file gives it, written with its UTC offset"

    draft, first, cert, created = (day(a.get(k)) for k in ("draft_submitted_on", "first_certified_on",
                                                             "certified_on", "created_on"))
    if oes is not None:
        reported_at, raw["_reported_basis"] = L.iso(oes), "the time of the Cal OES control number"
    elif draft is not None:
        reported_at, raw["_reported_basis"] = draft.isoformat(), "the date of the draft spill report in CIWQS"
    elif first is not None:
        reported_at, raw["_reported_basis"] = first.isoformat(), "the date the spill report was first certified"
    elif created is not None:
        reported_at, raw["_reported_basis"] = created.isoformat(), "the date the spill report was created in CIWQS"
    else:
        reported_at = None
    updated = max([d for d in (draft, first, cert) if d is not None], default=None)

    lat, lon, pnote = L.point(a.get("lat"), a.get("lon"))
    if pnote and lat is None:
        raw["_coords_rejected"] = pnote
    elif pnote:
        raw["_coords_repaired"] = pnote
    precision_m = None
    if lat is not None and private_only(a.get("appearance_points")):
        lat, lon, precision_m = round(lat, 3), round(lon, 3), 150
        raw["_coords_rounded"] = ("the spill appeared only on private property (a private lateral, a building or "
                                  "structure): its point is rounded to about 100 m so it does not mark a home")

    wdid = L.clean(a.get("wdid")).upper() or None
    did = wdids.get(wdid) if wdid else None
    name = names.get(did) if did else None
    if name is None and wdid and live_names.get(wdid):
        name = live_names[wdid]
        raw["_name_basis"] = "the agency the State Water Board's current spill file names for this WDID"
    if did is None:
        raw["_discharger_basis"] = (f"No operator on record for WDID {wdid} yet." if wdid else
                                    "The report gives no WDID, so no operator is joined.")

    total = L.gallons(a.get("volume_total_gal"))
    surf = L.gallons(a.get("volume_to_surface_water_gal"))
    rec = L.gallons(a.get("volume_recovered_gal"))
    parts = []
    if total is not None:
        parts.append(f"{total:,} gallons spilled (estimated total)")
    if surf is not None:
        parts.append(f"{surf:,} gallons reached surface water")
    if rec is not None:
        parts.append(f"{rec:,} gallons recovered")
    return event(
        **base, event_type="sso", status=status,
        discharger_id=did, discharger_name=name, npdes_permit=wdid,
        outfall_id=None, outfall_name=a.get("location_name"),
        waterbody_text=None, water_slugs=[], water_match="none",
        lat=lat, lon=lon, coord_source="source" if lat is not None else None, coord_precision_m=precision_m,
        started_at=L.iso(start), ended_at=ended_at, time_precision=precision if (start or ended_at) else None,
        reported_at=reported_at, published_at=None, source_updated_at=updated.isoformat() if updated else None,
        material="untreated sewage", volume_gal=total, volume_text="; ".join(parts) or None, estimate_flag="estimated",
        authority=AUTHORITY, advice_text=None, advice_window_hours=None, advice_window_basis=None,
        raw=raw, parse_error="; ".join(problems) or None,
    )


# ---------------------------------------------------------------- overlap with the 2022 order's file

def _time(v) -> datetime | None:
    try:
        return datetime.fromisoformat(str(v)) if v else None
    except ValueError:
        return None


def _near(a: dict, b: dict) -> bool:
    la, lo, la2, lo2 = a.get("lat"), a.get("lon"), b.get("lat"), b.get("lon")
    return None not in (la, lo, la2, lo2) and abs(la - la2) <= OVERLAP_DEG and abs(lo - lo2) <= OVERLAP_DEG


def relation(rec: dict, live: dict) -> tuple[str, str] | None:
    """("copy" | "possible", basis) for a history record and a record of the 2022 order's file, else None.
    A copy: the same WDID and start minute, plus the same SPILL ID, or origin points within about 150 m and the same
    volume. A possible copy: the same WDID and start date with origin points within about 150 m (what is missing for
    a copy is said). The same SPILL ID under another WDID or in another year is a contradiction, never a match."""
    sid = L.clean((rec.get("raw") or {}).get("spill_id"))
    w, cw = L.clean(rec.get("npdes_permit")).upper(), L.clean(live.get("npdes_permit")).upper()
    t, ct = _time(rec.get("started_at")), _time(live.get("started_at"))
    same_id = bool(sid) and L.clean(live.get("source_record_id")) == sid
    if same_id and (w != cw or (t is not None and ct is not None and t.year != ct.year)):
        return None
    if not w or w != cw or t is None or ct is None:
        return None
    same_minute = t == ct
    near = _near(rec, live)
    same_volume = rec.get("volume_gal") is not None and rec.get("volume_gal") == live.get("volume_gal")
    if same_minute and same_id:
        return "copy", "the same WDID, start minute and SPILL ID"
    if same_minute and near and same_volume:
        return "copy", "the same WDID and start minute, origin points within about 150 m and the same volume"
    if t.astimezone(L.TZ).date() == ct.astimezone(L.TZ).date() and near:
        lt, lct = t.astimezone(L.TZ), ct.astimezone(L.TZ)
        differs = (f"the starts differ ({lt:%H:%M} and {lct:%H:%M})" if not same_minute else
                   f"the volumes differ ({rec.get('volume_gal')} and {live.get('volume_gal')} gallons)")
        return "possible", (f"the same WDID and start date and origin points within about 150 m, but {differs}: "
                            "both are listed")
    return None


def link_copies(records: list[dict], live_records: list[dict]) -> dict:
    """Mark each history record the 2022 order's file also holds (relation): a copy gets duplicate_of (that file's
    event id; the status build lists the spill from that file) and raw._duplicate_basis; a possible copy keeps no
    link but raw._possible_copy_of {event_id, reason}. No record is dropped. Links are made afresh on every run.
    Returns the meta block."""
    by_id, by_day = {}, {}
    for c in live_records:
        cs, cw, ct = L.clean(c.get("source_record_id")), L.clean(c.get("npdes_permit")).upper(), _time(c.get("started_at"))
        if cs:
            by_id.setdefault(cs, []).append(c)
        if cw and ct is not None:
            by_day.setdefault((cw, ct.astimezone(L.TZ).date()), []).append(c)
    links, copies, possible = [], 0, 0
    for r in records:
        raw = r.setdefault("raw", {})
        r["duplicate_of"] = None
        raw.pop("_duplicate_basis", None)
        raw.pop("_possible_copy_of", None)
        sid = L.clean(raw.get("spill_id"))
        w, t = L.clean(r.get("npdes_permit")).upper(), _time(r.get("started_at"))
        cands = list(by_id.get(sid, [])) if sid else []
        if w and t is not None:
            cands += by_day.get((w, t.astimezone(L.TZ).date()), [])
        found = {}
        for c in cands:
            rel = relation(r, c)
            if rel and rel[0] not in found:
                found[rel[0]] = (c, rel[1])
        if "copy" in found:
            c, basis = found["copy"]
            eid = c.get("event_id") or f"{L.SOURCE_ID}:{c.get('source_record_id')}"
            r["duplicate_of"] = eid
            raw["_duplicate_basis"] = (f"the State Water Board's current spill file holds this spill as {eid} "
                                       f"({basis}); it is listed from that file")
            copies += 1
            links.append({"event_id": r["event_id"], "duplicate_of": eid, "basis": basis})
        elif "possible" in found:
            c, reason = found["possible"]
            eid = c.get("event_id") or f"{L.SOURCE_ID}:{c.get('source_record_id')}"
            raw["_possible_copy_of"] = {"event_id": eid, "reason": reason}
            possible += 1
            links.append({"event_id": r["event_id"], "possible_copy_of": eid, "reason": reason})
    return {"duplicate_of": copies, "possible_copy_of": possible, "checked_against": len(live_records),
            "links": links[:200]}


# ---------------------------------------------------------------- the build

def build(rows: list[dict], fetched_at: str, prev_records: list[dict], live_records: list[dict] | None = None,
          wdids: dict[str, str] | None = None, names: dict[str, str] | None = None,
          file_modified: str | None = None) -> tuple[list[dict], dict]:
    """rows: the file's rows (short keys). Returns (the Category 1 records not in the 2022 order's file, stats);
    earlier records of spills no longer in the file are kept and marked."""
    wdids = L.wdid_index() if wdids is None else wdids
    names = discharger_names() if names is None else names
    live_records = live_records or []
    live_names = operator_names(live_records)
    prev = {r["event_id"]: r for r in L.scrub_history(prev_records, PRIVATE_ONLY)}
    current, folded, no_id = spills(rows, prev_records)
    cats = Counter(L.category(r.get("spill_type")) for _, r, _, _ in current)
    flags = Counter()
    marked_other = 0
    records, seen = [], set()
    for key, row, earlier, note in current:
        eid = f"{SOURCE_ID}:{key}"
        seen.add(eid)
        cat = L.category(row.get("spill_type"))
        yes = L.clean(row.get("reached_surface_water")).lower() == "yes"
        if cat != "1":
            marked_other += yes
            continue
        drain = L.clean(row.get("reached_storm_drain")).lower() == "yes"
        ret = L.clean(row.get("returned_to_sewer")).lower()
        flags["reached surface water: yes" if yes else
              ("reached surface water: no; storm drain, sewage not returned" if drain and ret == "no" else
               "reached surface water: no; storm drain, sewage returned" if drain and ret == "yes" else
               "reached surface water: no; storm drain, return not stated" if drain else
               "reached surface water: no; no storm drain")] += 1
        records.append(build_record(key, row, fetched_at, prev.get(eid), wdids, names, live_names, earlier, note,
                                    file_modified))
    kept = 0
    for eid, r in prev.items():
        if eid in seen:
            continue
        raw = r.setdefault("raw", {})
        raw["_missing_from_file_since"] = raw.get("_missing_from_file_since") or fetched_at
        records.append(r)
        kept += 1
    overlap = link_copies(records, live_records)
    check_unique(records)
    records.sort(key=lambda r: (r.get("started_at") or r.get("reported_at") or "", r["event_id"]), reverse=True)
    starts = sorted(r["started_at"] for r in records if r.get("started_at"))
    stats = {"rows_read": len(rows), "spills_in_file": len(current), "versions_folded": folded,
             "rows_without_spill_id": no_id,
             "by_category": {f"Category {k}" if k else "not read": v for k, v in sorted(cats.items(), key=str)},
             "records": len(records),
             "shown_category_1": sum(1 for r in records if not r.get("duplicate_of")),
             "not_kept": {"Category 2": cats.get("2", 0), "Category 3": cats.get("3", 0)},
             "category_1_flags": dict(sorted(flags.items())),
             "category_2_3_marked_reached_surface": marked_other,
             "overlap_with_2022_order": overlap,
             "kept_missing_from_file": kept,
             "by_status": dict(Counter(r["status"] for r in records)),
             "by_report_step": dict(Counter(L.clean((r.get("raw") or {}).get("report_step")) for r in records)),
             "with_point": sum(1 for r in records if r.get("lat") is not None),
             "with_rounded_point": sum(1 for r in records if r.get("coord_precision_m")),
             "with_operator_row": sum(1 for r in records if r.get("discharger_id")),
             "start_range": [starts[0], starts[-1]] if starts else None,
             # history: the file watches no water now, so it is not counted as covering every California outfall,
             # and its age never makes it stale (only a failed read does)
             "statewide": False, "frozen": True}
    return records, stats


# ---------------------------------------------------------------- fetching and main

def read_file(text: str) -> list[dict]:
    """The file's rows (short keys); a missing column or a row cut short fails the read (ValueError)."""
    rows = L.read_rows(text, COLUMNS, REQUIRED, strict=True)
    if not rows:
        raise ValueError("the file holds no spill rows")
    return rows


def due(state: dict, now: datetime) -> bool:
    """Whether the file is asked for this run: REREAD_DAYS after the last read (or never read)."""
    t = _time(str(state.get("read_at") or "").replace("Z", "+00:00"))
    return t is None or now - t >= timedelta(days=REREAD_DAYS)


def keep(prev_doc: dict, prev: list[dict], fetched_at: str, state: dict, why: dict, said: str) -> int:
    """A run that reads nothing: the records are kept (the overlap with the 2022 order's file checked again)."""
    from build import redact
    live = (read_json(LIVE_EVENTS, {}) or {}).get("records", [])
    records = L.scrub_history(prev, PRIVATE_ONLY)
    overlap = link_copies(records, live)
    meta = {**(prev_doc.get("meta") or {}), **why, "checked_at": fetched_at, "overlap_with_2022_order": overlap,
            "records": len(records), "shown_category_1": sum(1 for r in records if not r.get("duplicate_of"))}
    write_events(SOURCE_ID, redact.redact_events(records), ok=True, error=None, meta=meta)
    write_json(STATE_FILE, {**state, "checked_at": fetched_at})
    print(f"{SOURCE_ID}: {said}; {len(records)} records kept ({overlap['duplicate_of']} listed from the 2022 order's "
          f"file, {overlap['possible_copy_of']} possible copies)")
    return 0


def main(argv=None) -> int:
    from build import redact
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--file", help="read this saved SSO.txt instead of the Board's file")
    ap.add_argument("--backfill", action="store_true",
                    help="read the whole file now (every run reads every spill; this skips the wait and the 304)")
    args = ap.parse_args(argv)
    fetched_at = now_iso()
    now = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
    state = read_json(STATE_FILE, {}) or {}
    prev_doc = read_json(EVENTS_DIR / f"{SOURCE_ID}.json", {}) or {}
    prev = L.scrub_history(prev_doc.get("records", []), PRIVATE_ONLY)
    if not args.file and not args.backfill and prev and not due(state, now):
        return keep(prev_doc, prev, fetched_at, state, {"last_read_at": state.get("read_at")},
                    f"read {state.get('read_at')}, next read {REREAD_DAYS} days after it")
    sess = requests.Session()
    sess.headers.update(HEADERS)
    try:
        if args.file:
            content, modified = Path(args.file).read_bytes(), None
        else:
            if args.backfill or not prev:
                state.pop("last_modified_http", None)
            content, modified = L.fetch(sess, state, FILE_URL)
    except Exception as e:  # noqa: BLE001
        write_json(STATE_FILE, state)
        write_events(SOURCE_ID, prev, ok=False, partial=True, error=f"{error_text(e)}")
        print(f"{SOURCE_ID}: FAILED {error_detail(e)}", file=sys.stderr)
        return 1
    if content is None:
        state["read_at"] = fetched_at
        return keep(prev_doc, prev, fetched_at, state, {"file_not_modified_since": modified, "last_read_at": fetched_at},
                    f"file not modified since {modified}")
    live = (read_json(LIVE_EVENTS, {}) or {}).get("records", [])
    try:
        rows = read_file(L.decode(content))
        del content
        records, stats = build(rows, fetched_at, prev, live, file_modified=modified)
    except Exception as e:  # noqa: BLE001 - a read that fails keeps the previous records
        write_json(STATE_FILE, state)
        write_events(SOURCE_ID, prev, ok=False, partial=True, error=f"{error_text(e)}")
        print(f"{SOURCE_ID}: FAILED {error_detail(e)}", file=sys.stderr)
        return 1
    raw_path = state.get("raw_path")
    if not args.file:
        safe = [scrubbed_row(r) for r in rows if L.category(r.get("spill_type")) == "1"]
        sha = hashlib.sha256(json.dumps(safe, sort_keys=True).encode()).hexdigest()
        if sha != state.get("sha256"):
            doc = {"file": FILE_URL, "last_modified": modified, "fetched_at": fetched_at,
                   "rows_note": "the Category 1 rows only, scrubbed (the other categories are counted, not kept)",
                   "rows": safe}
            raw_path = str(save_raw(SOURCE_ID, json.dumps(doc, ensure_ascii=False), "json").relative_to(ROOT))
            state.update(sha256=sha, raw_path=raw_path, saved_at=fetched_at)
    records = redact.redact_events(records)
    state.update(fetched_at=fetched_at, last_modified=modified)
    if not args.file:
        state["read_at"] = fetched_at
    if args.backfill:
        state["backfill"] = {"at": fetched_at, "spills": stats["spills_in_file"]}
    write_json(STATE_FILE, state)
    newest = max((r.get("reported_at") or "" for r in records), default="") or None
    meta = {**stats, "newest_report": newest, "file_last_modified": modified, "raw_path": raw_path, "file": FILE_URL,
            "page": INDEX_URL, "time_basis": "Pacific local time as the file gives it, written with its UTC offset",
            "credit": CREDIT, "registry_ids": [SOURCE_ID], "reread_days": REREAD_DAYS, "backfill": state.get("backfill"),
            "overlap_basis": ("A spill also in the State Water Board's current spill file is listed from that file: "
                              "the same WDID and start minute, with the same SPILL ID or an origin point within about "
                              "150 m and the same volume. A match by WDID, date and place alone is noted as a "
                              "possible copy, and both reports are listed."),
            "shown_note": SHOWN_NOTE}
    if not live:
        meta["overlap_note"] = "the current spill file's records were not found, so no overlap was checked this run"
    path_notes_to_meta(records, meta)
    path = write_events(SOURCE_ID, records, ok=True, error=None, meta=meta)
    o = stats["overlap_with_2022_order"]
    print(f"{SOURCE_ID}: {stats['spills_in_file']} spills in the file, {len(records)} Category 1 records; categories "
          f"{stats['by_category']}; listed from the 2022 order's file {o['duplicate_of']}, possible copies "
          f"{o['possible_copy_of']}; no SPILL ID {stats['rows_without_spill_id']}; with a point "
          f"{stats['with_point']}; starts {stats['start_range']} -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
