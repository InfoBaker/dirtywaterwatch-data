"""Georgia EPD "Municipal Sewage Spills Reported to EPD" -> data/build/events/ga-epd-spills.json

Source
  Georgia Environmental Protection Division, Watershed Protection Branch, "Sewage Spills Report":
  https://epd.georgia.gov/sewage-spills-report (redirects to .../watershed-protection-branch/wastewater/
  sewage-spills-report). Each business day the page links a dated workbook,
  https://epd.georgia.gov/document/document/sewagespillsreportYYYYMMDD/download, labelled XLS but an .xlsx
  (Office Open XML) file: row 1 "Posting Date" and an Excel date serial, row 2 the headers, then one row per spill
  that began in the last 30 days or so. Headers: FACILITY_NAME, SPILL_BEGIN_DATE (BEGIN_DATE in files before mid
  October 2026), COUNTY, CITY, OVERFLOW_LOCATION (a street address), QUANTITY_GALLONS, OVERFLOW_TYPE, PERMIT_NUMBER,
  SPILL_SOURCE, CAUSE, RIVER_BASIN, WATERWAY_IMPACTED, OVERFLOW_DESTINATION. No licence is stated.
  Older dated files stay at the same URL pattern: on 2026-11-04 EPD served every business day's posting from
  2025-10-09 (earlier days answer 404, probed monthly back to 2018-01), with the same 13 columns (BEGIN_DATE before mid
  October 2026; the 2025-12-01 file gives its Posting Date as text, "12/1/2025"); a day with no posting answers 404
  with an HTML page. Some older files add columns: LATITUDE / LONGITUDE (ten files, 2025-11-14 to 2026-07-14),
  SPILL_END_DATE (the 2026-10-13 file), FORM_TYPE (2026-04-02), BYPASS_ID and FORM_VERSION_NUM (2026-10-26). Only the
  13 columns above and the point and end date are read (safe fields); any other column is named in meta
  (unread_columns), its values never read. Points: the public ArcGIS layer behind EPD's "Spills in Georgia" StoryMap,
  https://services1.arcgis.com/p0dLjwtOaJHU8zq2/arcgis/rest/services/Spill_Summary_Continuous_Update/
  FeatureServer/0 (registry ga-epd-spills-map-layer): the same rows with LATITUDE / LONGITUDE, but BEGIN_DATE is
  null on every row, so the layer only lends its point to a workbook row of the same permit and address.

Law (Ga. Comp. R. & Regs. 391-3-6-.05): a "spill" is any discharge of raw sewage by a publicly owned treatment works
  to waters of the State. The owner tells EPD immediately, local media within 24 hours and the local health
  department immediately, and posts signs at the spill and at public access points downstream for at least seven
  days after it ceases; a major spill (over 10,000 gallons) also needs a legal-organ notice within seven days. The
  rule sets no period after a spill during which the public is told to keep out of the water.

Record rules
  - No row id. The key is permit + begin date + the normalised OVERFLOW_LOCATION (street words abbreviated, case and
    punctuation ignored): EPD fills QUANTITY_GALLONS, OVERFLOW_TYPE, CAUSE, RIVER_BASIN, WATERWAY_IMPACTED and
    OVERFLOW_DESTINATION in on later postings (seen between the 2026-10-15 and 2026-10-30 files), so gallons and
    waterway cannot be part of the key. Rows that share a key in one file (2026-10-01: two Augusta rows at one
    address on one day) get "~2", "~3" in file order; the copies are kept and are not marked duplicates, because
    two spills at one manhole on one day are possible.
  - History from snapshots: every posting read is applied in date order. A changed row keeps the old values in
    raw._revisions (posting date and values). A row whose begin date falls before the oldest begin date of a newer
    posting has aged out of the 30-day window: it is kept, raw._aged_out_after (the last posting that showed it).
    A row that disappears while still inside the window was withdrawn or corrected: it is kept with
    raw._missing_from_source_since, and when a row of the same permit and address with another begin date within
    seven days first appeared in that posting (2026-11-03: Cauley Creek moved from 2026-10-06 to 2026-10-03), it is
    duplicate_of that row; failing that, so is exactly one row of the same begin day first listed in that posting
    with the same permit (the address corrected, a house number changed) or at the same address (the permit
    corrected): about 100 such corrections in the 13 months to 2026-11; two candidates or more: no mark. A vanished
    row is never given an end: its end stays unknown. A posting with no rows at all changes nothing (a fault in the
    file, not every spill withdrawn). The posting's date is the file's Posting Date unless it is more than 3 days from
    the date in the file's URL (older files misspell the label, leave it out, or give a wrong year), then the URL's
    date (meta.posting_date_from_url). An older posting that cannot be read is skipped and named in meta
    (unreadable_postings); the newest must be read or the run fails and keeps the previous file.
  - event_type: OVERFLOW_DESTINATION naming a CSO ("CSO Dry-weather") -> cso; every other row -> sso (the rule's
    "spill" is a raw-sewage discharge from the collection system or plant; OVERFLOW_TYPE and SPILL_SOURCE stay in
    raw.row and OVERFLOW_TYPE gives `material`). status unknown: the list has no end date and no time.
  - Times: started_at = the begin date (time_precision day), as EPD gives it, even when it is later than the posting
    that first listed the row (two rows in the 13 months to 2026-11: raw._begin_after_first_posting names it).
    published_at = the first posting that listed the row.
    source_updated_at = the workbook's HTTP Last-Modified when given. reported_at null (the list does not say when EPD
    was told). raw._first_seen_posting / _last_seen_posting say which postings showed the row; raw._first_seen_at is
    our clock. A row first listed in an older posting read after newer ones were out (a backfill, a rebuild, a
    catch-up day) has raw._read_from_archive, the time that file was read: never a time EPD received the report.
    Colour (build/status.py, data/rules.json unresolved.day_start_caution, which lists this source): a row with no end
    is a caution for 72 hours from the start of its begin day, then unresolved (end not reported) to day 30.
    SPILL_END_DATE (one posting only) is kept as given in raw.epd_spill_end_date (value, posting) and carried to later
    postings, but is not made the record's end: a day gives no time the spill stopped.
  - Volume: QUANTITY_GALLONS in gallons; blank, or "0" ("A 'zero' in the quantity field indicates the amount of the
    spill has not been determined", EPD's page) -> volume_gal null and volume_text saying so. estimate_flag unknown.
  - Water: WATERWAY_IMPACTED as given in waterbody_text (blank: null). "Ditch", "Storm Drain", "Basin", "unknown"
    name no water (raw._water.why_none); the text is kept so that build/status.py reads it as naming no water and
    never places the spill on the operator's listed receiving water instead. No Georgia water records yet: water_slugs [], water_match none. A destination that
    says dry land and names neither waters of the State nor a CSO ("Dry Land Overflow") is kept with
    raw.reached_water false, unless WATERWAY_IMPACTED names a water; any other destination wording is not read as
    "did not reach water" (raw._destination_not_read), so a spill is never hidden on a wording not yet seen.
  - Operator: discharger_id from data/dischargers.json by permit (npdes_permit / npdes_permits); discharger_name is
    EPD's FACILITY_NAME. npdes_permit only for an NPDES permit number (GA0 + 6 digits, or a general permit's
    coverage GAG + 6 digits); a state land-application permit (GAJ, GAU) or text stays in raw.row only.
  - Points: a row's own LATITUDE / LONGITUDE, when the posting gives them inside Georgia (coord_source "source"; a
    point outside Georgia, swapped or missing its sign, is not used and never repaired: raw._coords_not_used);
    else a layer row with the same permit and normalised address, when exactly one, lends LATITUDE / LONGITUDE
    (coord_source "geocode": the layer's point is EPD's location for the address; precision not stated). When the
    layer is down or no longer lists the row, the point read earlier stays (raw._coords_kept_from_earlier_read).
  - EPA's copy: Georgia permittees file 24-hour and 5-day reports in EPD's GEOS, and these reach EPA's Sewer Overflow
    and Bypass Event tables (ingest/echo_sewer_overflow_events.py, run before this module; for Georgia they carry
    times and an end but no volume, and mostly the plant's point). An EPD row pairs with the EPA record of the same
    permit and begin day; the permit is the row's NPDES permit, or else the state permit EPD typed (GAJ / GAU land
    application, GAIS), which EPA carries under the same number (pair_permit; never made the record's npdes_permit).
    No day tolerance: EPA's times are local (their hours peak at midday) and the reports a day off in the 2026-11 data
    were other spills of the same system. Copies count once on each side: EPA reports with the same start, end and
    receiving water are one spill filed twice (all are marked duplicate_of the EPD record, raw._epa_record lists
    them), and EPD rows of one key (the '~2' copies: same permit, day and address) naming the same water with the same
    gallons (or one with none) are one spill listed twice (each takes the end; the later ones say so in _end_basis).
    The record whose receiving water is the same name pairs first, when that name picks exactly one row and one record
    (two spills of one system on one water that day are not told apart); else, when only one EPD row and one EPA
    record of that permit and day remain unpaired and they do not contradict each other (two different specific water
    names, or EPD's dry land against a water EPA names: raw._epa_not_paired), those two. Several left on both sides are
    not paired (raw._epa_candidates). An end borrowed from the wrong report would be an invented end, so every doubt
    leaves the EPD row without one. The EPD record is the public one (gallons, address, waterway, cause, the map
    layer's point): it takes EPA's ended_at when it has none and EPA's end is the spill's own (minute precision; an
    extreme-weather report's reporting period is not) and plausible (end_refused: not before EPA's start, not before
    EPD's begin day, not more than MAX_EPA_SPAN, 30 days, after EPA's start; else raw._epa_end_not_used says why and
    nothing is repaired), with status ended, raw._end_basis naming the EPA record and "EPA eRule report", and
    raw._epa_record; the EPA record is marked duplicate_of the EPD record, written back into EPA's events file
    (data/build/events/echo-sewer-overflow.json). EPA's reports that say no water was reached are not among its events
    but in data/build/echo-sewer-overflow-dropped.json with their start and end: an EPD row that also says no water was
    reached (dry land, or a waterway such as "Not Applicable" with no destination in waters of the State) takes such a
    report's end when it is the only row left of its permit and day, the report the only one, and every EPA event of
    that permit and day already paired (pair_dropped; raw._epa_dropped_record). Unpaired EPA records stay as they are.
    The pairs are recomputed on every run (earlier marks on both sides are cleared first), so a report EPA receives
    later still finds its EPD row; the EPA module rewrites its file each run, and this module runs after it.

Privacy: the list names facilities and street addresses, no people. common.strip_personal runs on raw; the export's
  redactor (build/redact.py) runs over CAUSE and every other free text before the file is written.

Archive: every posting read is saved in data/build/archive/ga-epd-spills/ (sewagespillsreportYYYYMMDD.xlsx and
  index.json with each file's Last-Modified and read time), so it travels with the pipeline state (R2 state/) and a
  rebuild never downloads it again; a changed file of the same day replaces the saved one.

Run from pipeline/:  python -m ingest.ga_epd_spills [--file posting.xlsx ...] [--layer layer.json] [--no-layer]
                                                    [--backfill [YYYY-MM-DD] | --rebuild]
  --file reads saved workbooks (oldest first; no network unless --layer is absent and --no-layer is not given).
  --backfill (the history, once, before the state goes live; never in the scheduled hourly run): by hand, or in a
    dispatched refresh with the backfill input "ga_epd_spills" (.github/workflows/refresh.yml runs --backfill before
    the refresh, and the state is saved only when the whole run succeeds). Downloads every weekday's dated file from
    the date (default: 400 days before the linked one or EPD_FIRST_POSTING, whichever is earlier: at least 12
    months, as far as EPD serves) to the linked one that is not saved yet, about one request a second. A 404 is a
    day with no posting; any other answer, a timeout or a dropped connection is named in meta.errors (never counted
    as no posting) and the day is asked for again by the next --backfill. After BACKFILL_BUDGET_S the remaining
    older days are not requested (named in meta.errors), so the run fits the refresh job; a rerun continues where it
    stopped. Then it rebuilds as --rebuild does. --backfill-from DATE is the same as --backfill DATE.
  --rebuild: starts from no records and applies every saved posting (and any --file, which replaces the saved copy of
    its day) oldest first, so an old posting is never laid on top of today's rows; the previous file's
    _first_seen_at and _read_from_archive are carried over by event id, and a previous record no saved posting
    rebuilds is kept as it was. The same rows get the same ids as the daily feed's (one key), EPA's reports are
    paired by the feed's rules, and running it again on the same postings changes nothing but fetch times.
    meta.backfill gives the range, the counts by begin year, and stays in meta on every later hourly run.
  Without options: the linked posting, plus any posting since the last one read (up to 14 days) that a missed run
  skipped. Cadence: each business day (about one business day of latency).
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from io import BytesIO
from pathlib import Path

import requests

from build import redact
from common import (BUILD_DIR, DATA_DIR, EVENTS_DIR, HEADERS, RAW_DIR, event, now_iso, read_json, write_events,
                    write_json, path_notes_to_meta)
from ingest import echo_sewer_overflow_events as E

SOURCE_ID = "ga-epd-spills"
PAGE_URL = "https://epd.georgia.gov/sewage-spills-report"
FILE_URL = "https://epd.georgia.gov/document/document/sewagespillsreport{ymd}/download"
LAYER_URL = ("https://services1.arcgis.com/p0dLjwtOaJHU8zq2/arcgis/rest/services/Spill_Summary_Continuous_Update/"
             "FeatureServer/0/query")
EPA_EVENTS = EVENTS_DIR / "echo-sewer-overflow.json"
EPA_DROPPED = BUILD_DIR / "echo-sewer-overflow-dropped.json"    # EPA's reports of no water reached, with start and end
RAW = RAW_DIR / SOURCE_ID
ARCHIVE = BUILD_DIR / "archive" / SOURCE_ID     # every posting read, kept with the pipeline state (R2 state/)
BACKFILL_DAYS = 400     # --backfill with no date: about 13 months, and never later than EPD_FIRST_POSTING
EPD_FIRST_POSTING = "2025-10-09"    # the earliest dated posting EPD served on 2026-11-04 (earlier days answer 404)
BACKFILL_BUDGET_S = 15 * 60     # a backfill stops requesting older days after this, so it fits the refresh job; rerun
AUTHORITY = "Georgia Environmental Protection Division (Municipal Sewage Spills Reported to EPD)"
CATCH_UP_DAYS = 14
MOVED_DAYS = 7
BACKFILL_PAUSE_S = 1.0
REAL_PERMIT = re.compile(r"^GA[0G]\d{6}$")      # an individual (GA0...) or general (GAG...) NPDES permit
STATE_PERMIT = re.compile(r"^GA[A-Z]{1,2}\d{5,6}$")   # a state permit (GAJ, GAU, GAIS ...): paired with EPA only
LINK = re.compile(r"/document/document/sewagespillsreport(\d{8})/download")
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
HEADER_ALIASES = {"spill_begin_date": "begin_date"}
FIELDS = ["facility_name", "begin_date", "county", "city", "overflow_location", "quantity_gallons", "overflow_type",
          "permit_number", "spill_source", "cause", "river_basin", "waterway_impacted", "overflow_destination"]
# columns some older postings add, read when present: EPD's own point (ten files, 2025-11-14 to 2026-07-14) and its end
# date (the 2026-10-13 file only); BYPASS_ID, FORM_TYPE and FORM_VERSION_NUM are named in meta and not read
OPTIONAL = ["latitude", "longitude", "spill_end_date"]
NO_WATER = re.compile(r"^\s*(|n\s*/?\s*a|none|unknown|unk|basin|ditch|storm ?ditch|storm ?drains?|storm ?sewer|"
                      r"ground|dry land|land)\s*\.?\s*$", re.I)
ADDR_WORDS = {"street": "st", "avenue": "ave", "road": "rd", "drive": "dr", "lane": "ln", "court": "ct",
              "place": "pl", "boulevard": "blvd", "parkway": "pkwy", "highway": "hwy", "terrace": "ter",
              "trace": "trce", "circle": "cir", "trail": "trl", "northeast": "ne", "northwest": "nw",
              "southeast": "se", "southwest": "sw", "north": "n", "south": "s", "east": "e", "west": "w",
              "georgia": "ga"}
WATER_DEST = re.compile(r"waters of the state|\bcso\b", re.I)
DRY_DEST = re.compile(r"\bdry\s*land\b", re.I)
ZERO_NOTE = "not yet determined (EPD: a zero or blank quantity means the amount has not been determined)"


# ---------------------------------------------------------------- the workbook

def excel_date(v: str) -> str | None:
    """An Excel date serial ('46329') or an ISO / US date text -> 'YYYY-MM-DD'."""
    s = (v or "").strip()
    if not s:
        return None
    if re.fullmatch(r"\d{4,6}(\.\d+)?", s):
        return (date(1899, 12, 30) + timedelta(days=int(float(s)))).isoformat()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def sheet_rows(content: bytes) -> list[list[str]]:
    """The first worksheet of an .xlsx as rows of cell strings (shared and inline strings resolved, numbers as text)."""
    z = zipfile.ZipFile(BytesIO(content))
    names = set(z.namelist())
    shared = []
    if "xl/sharedStrings.xml" in names:
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).iter(f"{NS}si"):
            shared.append("".join(t.text or "" for t in si.iter(f"{NS}t")))
    sheet = "xl/worksheets/sheet1.xml" if "xl/worksheets/sheet1.xml" in names else \
        sorted(n for n in names if n.startswith("xl/worksheets/sheet"))[0]
    out = []
    for r in ET.fromstring(z.read(sheet)).iter(f"{NS}row"):
        cells: dict[int, str] = {}
        for c in r.iter(f"{NS}c"):
            col = re.match(r"[A-Z]+", c.get("r") or "A").group(0)
            idx = 0
            for ch in col:
                idx = idx * 26 + ord(ch) - 64
            v, t = c.find(f"{NS}v"), c.get("t")
            if t == "s":
                val = shared[int(v.text)] if v is not None and v.text else ""
            elif t == "inlineStr":
                val = "".join(x.text or "" for x in c.iter(f"{NS}t"))
            else:
                val = v.text if v is not None and v.text else ""
            cells[idx - 1] = val
        out.append([cells.get(i, "") for i in range(max(cells) + 1)] if cells else [])
    return out


def read_posting(content: bytes, unread: list | None = None) -> tuple[str | None, list[dict]]:
    """(posting date, rows as {field: text}) of one workbook. ValueError when it is not the spills list. Only the
    13 known columns (FIELDS) are read; any other column's header (never its values) is added to unread."""
    rows = sheet_rows(content)
    posting = None
    hdr_i = None
    for i, r in enumerate(rows[:10]):
        if r and r[0].strip().lower() == "posting date" and len(r) > 1:
            posting = excel_date(r[1])
        if any(c.strip().upper() == "FACILITY_NAME" for c in r):
            hdr_i = i
            break
    if hdr_i is None:
        raise ValueError("no FACILITY_NAME header row")
    hdr = [HEADER_ALIASES.get(h.strip().lower(), h.strip().lower()) for h in rows[hdr_i]]
    if "permit_number" not in hdr or "begin_date" not in hdr:
        raise ValueError(f"unexpected headers {hdr}")
    if unread is not None:
        unread.extend(h for h in hdr if h and h not in FIELDS and h not in OPTIONAL and h not in unread)
    out = []
    for r in rows[hdr_i + 1:]:
        if not any(c.strip() for c in r):
            continue
        out.append({h: " ".join((r[j] if j < len(r) else "").split()) for j, h in enumerate(hdr)
                    if h in FIELDS or h in OPTIONAL})
    return posting, out


# ---------------------------------------------------------------- keys and fields

def norm_addr(s: str | None) -> str:
    t = re.sub(r"[^a-z0-9]+", " ", (s or "").lower())
    return " ".join(ADDR_WORDS.get(w, w) for w in t.split())


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")


def water_key(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def base_key(row: dict) -> str:
    permit = (row.get("permit_number") or "").strip().upper() or "nopermit"
    d = excel_date(row.get("begin_date") or "")
    return "-".join([slug(permit), d.replace("-", "") if d else "nodate", slug(norm_addr(row.get("overflow_location")))
                     or "no-address"])


def assign_ids(rows: list[dict]) -> list[tuple[str, dict]]:
    seen: Counter = Counter()
    out = []
    for r in rows:
        k = base_key(r)
        seen[k] += 1
        out.append((k if seen[k] == 1 else f"{k}~{seen[k]}", r))
    return out


def load_permits(path: Path | None = None) -> dict[str, str]:
    """{permit: data/dischargers.json id} for Georgia rows (npdes_permit first, then npdes_permits)."""
    rows = read_json(path or DATA_DIR / "dischargers.json", []) or []
    idx: dict[str, str] = {}
    for r in rows:
        if r.get("npdes_permit"):
            idx.setdefault(str(r["npdes_permit"]).upper(), r["id"])
    for r in rows:
        for p in r.get("npdes_permits") or []:
            idx.setdefault(str(p).upper(), r["id"])
    return idx


def layer_points(layer: dict | None) -> dict[tuple[str, str], list[tuple[float, float]]]:
    pts: dict[tuple[str, str], list[tuple[float, float]]] = defaultdict(list)
    for f in (layer or {}).get("features") or []:
        a = f.get("attributes") or {}
        try:
            lat, lon = float(a.get("LATITUDE")), float(a.get("LONGITUDE"))
        except (TypeError, ValueError):
            continue
        if not (30.3 <= lat <= 35.1 and -85.7 <= lon <= -80.7):     # Georgia's box, a little wide
            continue
        k = (str(a.get("PERMIT_NUMBER") or "").strip().upper(), norm_addr(a.get("OVERFLOW_LOCATION")))
        if (lat, lon) not in pts[k]:
            pts[k].append((lat, lon))
    return pts


def to_record(rid: str, row: dict, posting: str | None, ctx: dict) -> dict:
    raw = {"row": dict(row), "posting_date": posting}
    base = dict(source_id=SOURCE_ID, source_record_id=rid, source_url=ctx["file_url"], authority=AUTHORITY,
                published_at=posting, source_updated_at=ctx.get("last_modified"), fetched_at=ctx["fetched_at"])
    problems = []
    dest = row.get("overflow_destination") or ""
    etype = "cso" if re.search(r"\bcso\b", dest, re.I) else "sso"
    start = excel_date(row.get("begin_date") or "")
    if not start:
        problems.append(f"unreadable begin date {row.get('begin_date')!r}")
    permit = (row.get("permit_number") or "").strip().upper()
    q = (row.get("quantity_gallons") or "").replace(",", "").strip()
    vol, vtext = None, None
    if re.fullmatch(r"\d+(\.\d+)?", q) and float(q) > 0:
        vol = int(round(float(q)))
        vtext = f"{vol:,} gallons"
    elif q in ("", "0", "0.0"):
        vtext = ZERO_NOTE
    else:
        vtext = q
        problems.append(f"unreadable quantity {q!r}")
    water = row.get("waterway_impacted") or ""
    if NO_WATER.match(water):
        raw["_water"] = {"why_none": f"waterway given as {water!r}: no surface water named" if water else
                         "waterway not given yet"}
    if dest and not WATER_DEST.search(dest):
        if not DRY_DEST.search(dest):
            raw["_destination_not_read"] = (f"destination given as {dest!r}: not a wording this reader knows; "
                                            f"not taken to mean the spill stayed out of the water")
        elif water and not NO_WATER.match(water):
            raw["_destination_not_read"] = (f"destination given as {dest!r} but the waterway impacted is given as "
                                            f"{water!r}: not taken to mean the spill stayed out of the water")
        else:
            raw["reached_water"] = False
            raw["_reached_water_basis"] = f"destination given as {dest!r}"
    lat = lon = None
    end_text = row.get("spill_end_date") or ""
    if end_text:
        raw["epd_spill_end_date"] = {
            "value": excel_date(end_text) or end_text, "posting": posting,
            "note": ("EPD's end date for the spill, day precision, given on this posting only; kept as given and not "
                     "used as the record's end (a day gives no time the spill stopped)")}
    try:
        wlat, wlon = float(row.get("latitude") or ""), float(row.get("longitude") or "")
        if not (math.isfinite(wlat) and math.isfinite(wlon)):
            wlat = wlon = None
    except ValueError:
        wlat = wlon = None
    if wlat is not None and not (30.3 <= wlat <= 35.1 and -85.7 <= wlon <= -80.7):
        # swapped, a longitude without its sign, or 0, 0: EPD's point is not used and never repaired here
        raw["_coords_not_used"] = (f"EPD's LATITUDE / LONGITUDE on the {posting} posting ({wlat}, {wlon}) is not in "
                                   f"Georgia; not used")
    hits = ctx["points"].get((permit, norm_addr(row.get("overflow_location"))), [])
    if wlat is not None and 30.3 <= wlat <= 35.1 and -85.7 <= wlon <= -80.7:      # Georgia's box, a little wide
        lat, lon = wlat, wlon
        raw["_coords"] = f"EPD's LATITUDE / LONGITUDE for this row on the {posting} posting"
    elif len(hits) == 1:
        lat, lon = hits[0]
        raw["_coords"] = "the point of the same permit and address on EPD's Spills in Georgia map layer"
    elif len(hits) > 1:
        raw["_coords"] = f"{len(hits)} different points on EPD's map layer for this address; none used"
    otype = row.get("overflow_type") or ""
    material = "untreated sewage" if otype.lower() == "raw sewage" else (otype.lower() or None)
    if etype == "cso" and otype.lower() == "raw sewage":
        material = "combined sewage (dry weather)" if "dry" in dest.lower() else "combined sewage"
    return event(**base, event_type=etype, status="unknown",
                 discharger_id=ctx["permits"].get(permit), discharger_name=row.get("facility_name") or None,
                 npdes_permit=permit if REAL_PERMIT.match(permit) else None,
                 outfall_name=row.get("overflow_location") or None,
                 waterbody_text=water or None,         # as given: status reads "Ditch", "unknown" as naming no water
                 water_slugs=[], water_match="none",
                 lat=lat, lon=lon, coord_source=(("source" if wlat == lat else "geocode") if lat is not None else None),
                 started_at=start, time_precision="day" if start else None,
                 material=material, volume_gal=vol, volume_text=vtext, estimate_flag="unknown",
                 raw=raw, parse_error="; ".join(problems) or None)


# ---------------------------------------------------------------- one posting applied to the history

def apply_posting(prev: dict[str, dict], rows: list[dict], posting: str | None, ctx: dict) -> tuple[dict, Counter]:
    """The records after one posting: its rows (with the history of earlier postings) plus every earlier record."""
    n: Counter = Counter()
    cur: dict[str, dict] = {}
    for rid, row in assign_ids(rows):
        rec = to_record(rid, row, posting, ctx)
        p = prev.get(rec["event_id"])
        if p:
            praw = p.get("raw") or {}
            for k in ("_first_seen_at", "_first_seen_posting", "_revisions", "_read_from_archive"):
                if praw.get(k) is not None:
                    rec["raw"][k] = praw[k]
            if rec.get("lat") is None and "_coords" not in rec["raw"] and p.get("lat") is not None:
                # the map layer is down, or no longer lists the row: the point read earlier stays
                rec["lat"], rec["lon"], rec["coord_source"] = p["lat"], p["lon"], p.get("coord_source")
                rec["raw"]["_coords"] = praw.get("_coords") or "a point read earlier from EPD's map layer"
                rec["raw"]["_coords_kept_from_earlier_read"] = True
            for k in ("epd_spill_end_date", "_coords_not_used"):      # given on some postings only
                if praw.get(k) and k not in rec["raw"]:
                    rec["raw"][k] = praw[k]
            old = praw.get("row") or {}
            changed = {k: old.get(k) for k in set(old) | set(row) if (old.get(k) or "") != (row.get(k) or "")
                       and (k not in OPTIONAL or (k in row and k in old))    # a column one posting lacks is no revision
                       and not only_redacted(old.get(k), row.get(k))}       # nor the redactor's mark on the saved copy
            if changed:
                rec["raw"].setdefault("_revisions", [])
                rec["raw"]["_revisions"] = [*rec["raw"]["_revisions"],
                                            {"posting_before": praw.get("_last_seen_posting"),
                                             "posting_after": posting, "old_values": changed}]
                n["revised"] += 1
            if p.get("published_at") and (not posting or p["published_at"] < posting):
                rec["published_at"] = p["published_at"]         # first published in the earlier posting
        else:
            rec["raw"]["_first_seen_at"] = ctx["fetched_at"]
            rec["raw"]["_first_seen_posting"] = posting
            if ctx.get("archived"):
                # first listed in a posting read after a newer one was out (a backfill, a rebuild or a catch-up day):
                # the time we read that archived file, never a time EPD received the report
                rec["raw"]["_read_from_archive"] = ctx["archived"]
            n["new"] += 1
        rec["raw"]["_last_seen_posting"] = posting
        first = rec["raw"].get("_first_seen_posting")
        if rec.get("started_at") and first and rec["started_at"] > first:
            # kept as EPD gives it (never moved), and named: a begin day later than the posting that first listed it
            rec["raw"]["_begin_after_first_posting"] = (f"EPD gives a begin date of {rec['started_at']}, later than the "
                                                        f"{first} posting that first listed this row")
        cur[rec["event_id"]] = rec
    if not cur:            # an empty list for the whole state is a fault in the posting, not 60 withdrawals
        n["empty_posting"] += 1
        return {**prev}, n
    oldest = min((r["started_at"] for r in cur.values() if r.get("started_at")), default=None)
    by_permit_addr = defaultdict(list)
    by_permit_day, by_addr_day = defaultdict(list), defaultdict(list)    # rows first listed in this posting
    for r in cur.values():
        row = r["raw"]["row"]
        by_permit_addr[((row.get("permit_number") or "").upper(), norm_addr(row.get("overflow_location")))].append(r)
        if r["event_id"] not in prev and r.get("started_at"):
            by_permit_day[((row.get("permit_number") or "").upper(), r["started_at"])].append(r)
            if norm_addr(row.get("overflow_location")):
                by_addr_day[(norm_addr(row.get("overflow_location")), r["started_at"])].append(r)
    for eid, p in prev.items():
        if eid in cur:
            continue
        p = {**p, "raw": dict(p.get("raw") or {})}
        if p["raw"].get("_aged_out_after") or p["raw"].get("_missing_from_source_since"):
            cur[eid] = p                                         # settled earlier
            continue
        if oldest and p.get("started_at") and p["started_at"] < oldest:
            p["raw"]["_aged_out_after"] = p["raw"].get("_last_seen_posting")
            n["aged_out"] += 1
        else:
            p["raw"]["_missing_from_source_since"] = posting
            row = p["raw"].get("row") or {}
            succ = [r for r in by_permit_addr.get(((row.get("permit_number") or "").upper(),
                                                   norm_addr(row.get("overflow_location"))), [])
                    if r["event_id"] not in prev and r.get("started_at") and p.get("started_at") and abs(
                        (date.fromisoformat(r["started_at"]) - date.fromisoformat(p["started_at"])).days) <= MOVED_DAYS]
            why = "same permit and address"
            if not succ and p.get("started_at"):
                # the address or the permit corrected: exactly one row of the same begin day first listed in this
                # posting with the same permit (address edited) or at the same address (permit edited)
                for cands, w in ((by_permit_day.get(((row.get("permit_number") or "").upper(), p["started_at"]), []),
                                  "same permit and begin day, address corrected"),
                                 (by_addr_day.get((norm_addr(row.get("overflow_location")), p["started_at"]), [])
                                  if norm_addr(row.get("overflow_location")) else [], "same address and begin day, "
                                                                                      "permit corrected")):
                    if len(cands) == 1:
                        succ, why = cands, w
                        break
            if succ and not p.get("duplicate_of"):
                p["duplicate_of"] = succ[0]["event_id"]
                p["raw"]["_duplicate_basis"] = (f"gone from the {posting} posting; {succ[0]['event_id']} ({why}, "
                                                f"begin date {succ[0]['started_at']}) looks like its corrected row")
                n["superseded_by_corrected_row"] += 1
            else:
                n["withdrawn_within_window"] += 1
        cur[eid] = p
    return cur, n


PLACEHOLDER = re.compile(r"(\[(?:name|phone|email) removed\])")


def only_redacted(old: str | None, new: str | None) -> bool:
    """True when the saved value differs from the posting's only where the redactor put its mark: the saved records
    are written redacted, and whether a phrase is marked depends on the whole set of records, so a rebuild and an
    hourly run may differ there without EPD changing anything."""
    if not old or not PLACEHOLDER.search(old):
        return False
    pat = "".join(".+?" if PLACEHOLDER.fullmatch(part) else re.escape(part) for part in PLACEHOLDER.split(old))
    return re.fullmatch(pat, new or "", re.S) is not None


# ---------------------------------------------------------------- EPA's copy

EPA_BASIS = "EPA eRule report"                  # raw._end_basis of an EPD record that took EPA's end
EPD_BASIS = "Georgia EPD spill list record"     # raw._duplicate_basis of an EPA record paired with an EPD row


def pair_permit(r: dict) -> str | None:
    """The permit an EPD row is paired on: its NPDES permit, else the state permit EPD typed (a land-application GAJ /
    GAU or an industrial GAIS number), which EPA's tables carry under the same number (2026-11 extract: 29 such rows
    met exactly one EPA report of that permit and day, the same water named in both)."""
    if r.get("npdes_permit"):
        return r["npdes_permit"]
    p = str(((r.get("raw") or {}).get("row") or {}).get("permit_number") or "").strip().upper()
    return p if STATE_PERMIT.match(p) else None


def epa_copy_key(e: dict) -> tuple:
    """Two EPA reports of one permit with the same start, end and receiving water are one spill filed twice (a 24-hour
    and a 5-day report entered as separate forms: 2026-11 extract, e.g. 13:35 to 13:48 on one creek, twice)."""
    return (e.get("started_at"), e.get("ended_at"), frozenset(epa_water_keys(e)))


def epd_copy_key(r: dict) -> tuple:
    """Rows of one key (permit, begin day, address: the '~2' copies) naming the same water are one spill listed twice
    when their gallons agree (or one row has none yet): EPD re-lists a spill as a new row at the same address, and the
    earlier row is then withdrawn or ages out beside it (2026-11: 22 such copies took an end on the 13 months of postings)."""
    return (r["source_record_id"].split("~")[0], water_key(r.get("waterbody_text")))


def _units(rows: list[dict], key, same) -> list[list[dict]]:
    """Groups rows whose key is equal and that `same` accepts against the group's first row, in input order."""
    units: list[list[dict]] = []
    for x in rows:
        for u in units:
            if key(u[0]) == key(x) and same(u[0], x):
                u.append(x)
                break
        else:
            units.append([x])
    return units


def _same_gallons(a: dict, b: dict) -> bool:
    return a.get("volume_gal") is None or b.get("volume_gal") is None or a["volume_gal"] == b["volume_gal"]


def mark_epa_duplicates(records: list[dict], epa: list[dict], epa_dropped: list[dict] | None = None) -> Counter:
    """Pair EPD rows with EPA's records of the same permit and begin day (module docstring). The EPD record is the
    public one: it takes EPA's end when it has none (raw._end_basis) and the EPA record becomes duplicate_of it.
    Both lists are changed in place; every mark of an earlier run is cleared first, so pairs are recomputed."""
    n: Counter = Counter()
    for r in records:
        if (r["raw"].get("_end_basis") or "").startswith(EPA_BASIS):
            r["ended_at"], r["status"] = None, "unknown"
            r["raw"].pop("_end_basis", None)
        for k in ("_epa_candidates", "_epa_record", "_epa_dropped_record", "_epa_not_paired", "_epa_end_not_used"):
            r["raw"].pop(k, None)
    for e in epa:
        if ((e.get("raw") or {}).get("_duplicate_basis") or "").startswith(EPD_BASIS):
            e["duplicate_of"] = None
            e["raw"].pop("_duplicate_basis", None)
    groups = defaultdict(list)
    for e in epa:
        if e.get("duplicate_of") or not e.get("npdes_permit") or not e.get("started_at"):
            continue
        if not str(e["npdes_permit"]).startswith("GA") or e.get("event_type") not in ("sso", "cso", "unknown"):
            continue
        groups[(e["npdes_permit"], e["started_at"][:10])].append(e)
    mine = defaultdict(list)
    for r in records:
        p = pair_permit(r)
        if r.get("duplicate_of") or not p or not r.get("started_at"):
            continue
        if not r.get("npdes_permit"):
            n["state_permit_rows"] += 1
        mine[(p, r["started_at"][:10])].append(r)
    paired_epa = set()

    def pair(unit: list[dict], eunit: list[dict], why: str) -> None:
        for i, r in enumerate(unit):
            n["end_" + _pair(r, eunit[0], why if i == 0 else why + COPY_NOTE.format(unit[0]["event_id"]),
                             mark=i == 0)] += 1
        for e in eunit[1:]:
            e["duplicate_of"] = unit[0]["event_id"]
            e.setdefault("raw", {})["_duplicate_basis"] = (f"{EPD_BASIS} {unit[0]['event_id']}: {why}; the same start, "
                                                           f"end and receiving water as EPA report {eunit[0]['event_id']}"
                                                           f" (one spill filed twice)")
            n["epa_copies"] += 1
        unit[0]["raw"]["_epa_record"] = eunit[0]["event_id"] if len(eunit) == 1 else [e["event_id"] for e in eunit]
        if len(unit) > 1:
            n["epd_copies"] += len(unit) - 1
        paired_epa.update(e["event_id"] for e in eunit)

    for k, rs in mine.items():
        es_all = groups.get(k, [])
        if not es_all:
            n["epd_without_epa"] += len(rs)
            continue
        es = _units(es_all, epa_copy_key, lambda a, b: True)
        units = _units(rs, epd_copy_key, _same_gallons)
        left = []
        unit_keys = Counter(water_key(u[0].get("waterbody_text")) for u in units)
        for u in units:
            wk = water_key(u[0].get("waterbody_text"))
            hits = [eu for eu in es if wk and wk in epa_water_keys(eu[0])]
            if len(hits) == 1 and unit_keys[wk] == 1:
                es.remove(hits[0])
                pair(u, hits[0], "same permit, day and receiving water")
                n["paired_by_water"] += 1
            else:
                if hits:                 # two spills of one permit, day and water: whose end is whose is not known
                    n["same_water_ambiguous"] += len(u)
                left.append(u)
        if len(left) == 1 and len(es) == 1 and not contradicts(left[0][0], es[0][0]):
            pair(left[0], es[0], "the only EPD row and the only EPA report of this permit and day")
            n["paired_alone"] += 1
        elif left:
            if len(left) == 1 and len(es) == 1:
                for r in left[0]:
                    r["raw"]["_epa_not_paired"] = (f"{es[0][0]['event_id']} is the only EPA report of this permit and "
                                                   f"day, but {contradicts(left[0][0], es[0][0])}")
                n["not_paired_contradiction"] += len(left[0])
            for u in left:
                for r in u:
                    r["raw"]["_epa_candidates"] = [e["event_id"] for eu in es for e in eu]
                n["epd_without_epa"] += len(u)
    n["epa_without_epd"] = sum(len(v) for v in groups.values()) - len(paired_epa)
    pair_dropped(mine, groups, paired_epa, epa_dropped or [], n)
    return n


def says_no_water(r: dict) -> bool:
    """EPD's row says the spill stayed out of the water: dry land with no water named (raw.reached_water false), or a
    waterway text naming none ('Not Applicable', 'Ditch', blank) with a destination that does not say waters of the
    State or a CSO."""
    if r["raw"].get("reached_water") is False:
        return True
    w = r.get("waterbody_text") or ""
    dest = str((r["raw"].get("row") or {}).get("overflow_destination") or "")
    return (not w or bool(NO_WATER.match(w)) or E.no_water(w, "GA")) and not WATER_DEST.search(dest)


def pair_dropped(mine: dict, groups: dict, paired_epa: set, dropped: list[dict], n: Counter) -> None:
    """EPA's reports that say the spill reached no water are not in EPA's events (ingest/echo_sewer_overflow_events.py
    keeps them in echo-sewer-overflow-dropped.json with their start and end). An EPD row that also says no water was
    reached takes such a report's end when, for that permit and day, it is the only EPD row (copies counted once) left
    without an EPA report, every EPA report kept as an event is already paired, and the dropped report is the only one
    (copies with the same start and end counted once): both say the same spill stayed on land or in a building.
    2026-11: 173 EPD rows had a dropped EPA report of the same permit and day, 135 of them EPD's own dry land."""
    dg = defaultdict(list)
    for d in dropped:
        start = E.naive(d.get("start"))
        if str(d.get("permit") or "").startswith("GA") and start:
            dg[(d["permit"], start[:10])].append({**d, "start": start, "end": E.naive(d.get("end"))})
    for k, rs in mine.items():
        if k not in dg or any(e["event_id"] not in paired_epa for e in groups.get(k, [])):
            continue
        rest = [r for r in rs if not any(r["raw"].get(x) for x in ("_epa_record", "_epa_candidates", "_epa_not_paired"))]
        units = _units(rest, epd_copy_key, _same_gallons)
        ds = _units(dg[k], lambda d: (d["start"], d["end"]), lambda a, b: True)
        if len(units) != 1 or len(ds) != 1:
            if units:
                n["dropped_ambiguous"] += sum(len(u) for u in units)
            continue
        d = ds[0][0]
        if not says_no_water(units[0][0]):
            for r in units[0]:
                r["raw"]["_epa_not_paired"] = (f"EPA report {d['source_record_id']} of this permit and day says the "
                                               f"spill reached no water ({d.get('reason')}); EPD's row does not")
            n["dropped_not_paired_water"] += len(units[0])
            continue
        e = {"event_id": f"{EPA_SOURCE}:{d['source_record_id']}", "started_at": d["start"], "ended_at": d["end"],
             "time_precision": "minute"}
        why = (f"the only EPD row and the only EPA report of this permit and day, both saying no water was reached; "
               f"EPA's report is not among its events ({d.get('reason')})")
        for i, r in enumerate(units[0]):
            n["dropped_end_" + _pair(r, e, why if i == 0 else why + COPY_NOTE.format(units[0][0]["event_id"]),
                                     mark=False)] += 1
            r["raw"]["_epa_dropped_record"] = r["raw"].pop("_epa_record")    # not an event: nothing to mark duplicate
        n["paired_dropped"] += 1


EPA_SOURCE = "echo-sewer-overflow"
COPY_NOTE = "; a second listing on EPD's list of the spill in {} (same address, water and gallons)"
MAX_EPA_SPAN = timedelta(days=30)     # an EPA end more than this after EPA's start is not taken (module docstring)


# a water key that names no particular water ("Unnamed tributary", "UT", "creek"): it contradicts no name
GENERIC_WATER = re.compile(r"^(?:unnamed|unamed|unnammed|unknown|an?)?(?:ut|trib\w*|stream|creek|branch|ditch|"
                           r"storm\w*|ms4\w*|catchbasin|basin|pond|unk|na|none|ground|land|dryland)?$")


def epa_water_keys(e: dict) -> set[str]:
    return {k for k in (water_key(w) for w in (e.get("waterbody_text") or "").split("; ")) if k}


def contradicts(r: dict, e: dict) -> str | None:
    """Why the EPD row r and EPA's report e cannot be the same spill, or None. Both name a water and the names differ
    (another spill of the same system that day), or EPD says the spill stayed on dry land and EPA names a water."""
    wk, ek = water_key(r.get("waterbody_text")), epa_water_keys(e)
    specific = {k for k in ek if not GENERIC_WATER.match(k)}
    if wk and not GENERIC_WATER.match(wk) and specific and not any(wk in k or k in wk for k in specific):
        return f"EPD names {r.get('waterbody_text')!r} and EPA {e.get('waterbody_text')!r}"
    if r["raw"].get("reached_water") is False and ek:
        return f"EPD says the spill did not reach a water and EPA names {e.get('waterbody_text')!r}"
    return None


def _naive_dt(s: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(s).replace(tzinfo=None) if s else None
    except ValueError:
        return None


def end_refused(r: dict, e: dict) -> str | None:
    """Why EPA's end cannot be the EPD spill's end, or None: it lies before EPA's own start (an a.m./p.m. or date slip:
    12:42 to 03:45 the same day), before the day EPD says the spill began, or more than MAX_EPA_SPAN after EPA's start
    (a year typed wrong: 2025-09-28 to 2026-09-29). Never repaired: the row keeps an unknown end."""
    start, end = _naive_dt(e.get("started_at")), _naive_dt(e.get("ended_at"))
    day = _naive_dt((r.get("started_at") or "")[:10])
    if not start or not end:
        return "EPA's start or end cannot be read"
    if end < start:
        return f"EPA's end {e['ended_at']} is before EPA's start {e['started_at']}"
    if day and end < day:
        return f"EPA's end {e['ended_at']} is before the day EPD says the spill began ({r['started_at'][:10]})"
    if end - start > MAX_EPA_SPAN:
        return (f"EPA's end {e['ended_at']} is {(end - start).days} days after its start {e['started_at']}, more than "
                f"{MAX_EPA_SPAN.days}: not taken without a check")
    return None


def _pair(r: dict, e: dict, why: str, mark: bool = True) -> str:
    """The EPD record r stays primary; EPA's e is duplicate_of it (mark; a second listing of the same spill on EPD's list
    takes the end too but is not what EPA's record points to). r takes e's end only when it has none and e's end is the
    spill's own reported end (minute precision: not the reporting period of an extreme-weather report) and plausible
    (end_refused). Returns what happened to the end: taken, own (r has one), none, period or refused."""
    r["raw"]["_epa_record"] = e["event_id"]
    out = "own" if r.get("ended_at") else "none" if not e.get("ended_at") else ""
    if not out and e.get("time_precision") != "minute":
        r["raw"]["_epa_end_not_used"] = (f"{e['event_id']} gives an end of {e['ended_at']} at {e.get('time_precision')} "
                                         f"precision (a reporting period, not the spill's own end)")
        out = "period"
    elif not out and (bad := end_refused(r, e)):
        r["raw"]["_epa_end_not_used"] = f"{e['event_id']}: {bad}"
        out = "refused"
    elif not out:
        r["ended_at"], r["status"] = e["ended_at"], "ended"
        r["raw"]["_end_basis"] = (f"{EPA_BASIS} {e['event_id']} ({why}; EPA start {e.get('started_at')}, end "
                                  f"{e['ended_at']}, as given, presumably local time)")
        out = "taken"
    if mark:
        e["duplicate_of"] = r["event_id"]
        e.setdefault("raw", {})["_duplicate_basis"] = (f"{EPD_BASIS} {r['event_id']}: {why}; the state's list carries "
                                                       f"the gallons, address and waterway")
    return out


# ---------------------------------------------------------------- fetch

def get(sess: requests.Session, url: str, **kw) -> requests.Response:
    r = sess.get(url, timeout=(15, 90), **kw)
    return r


def fetch_postings(sess: requests.Session, last_read: str | None, backfill_from: str | None,
                   errors: list | None = None, have: set | None = None,
                   counts: Counter | None = None, keep=None) -> tuple[list, str | None]:
    """[(ymd, url, bytes, last_modified)] oldest first, and the linked file's date. A catch-up or backfill day that
    answers neither a workbook nor 404 (no posting that day) is named in errors: that posting is not read. A day in
    have (already saved) is not requested again, except the linked one. counts gets requested / not_posted (404).
    keep(ymd, content, last_modified) is called as each file arrives, so a long backfill cut short keeps its downloads."""
    page = get(sess, PAGE_URL)
    page.raise_for_status()
    links = sorted(set(LINK.findall(page.text)))
    if not links:
        raise ValueError("the page links no sewagespillsreport file")
    linked = links[-1]
    newest = datetime.strptime(linked, "%Y%m%d").date()
    if backfill_from:
        first = date.fromisoformat(backfill_from)
    elif last_read:
        first = max(date.fromisoformat(last_read) + timedelta(days=1), newest - timedelta(days=CATCH_UP_DAYS))
    else:
        first = newest
    first = min(first, newest)                          # the linked posting is always read
    out = []
    d = first
    t0, skipped = time.monotonic(), []
    while d <= newest:
        ymd = d.strftime("%Y%m%d")
        if (d.weekday() < 5 or ymd == linked) and (ymd == linked or ymd not in (have or ())):
            url = FILE_URL.format(ymd=ymd)
            if backfill_from and ymd != linked and time.monotonic() - t0 > BACKFILL_BUDGET_S:
                skipped.append(ymd)                     # out of time: a later --backfill asks for these days
                d += timedelta(days=1)
                continue
            try:
                r = get(sess, url)
            except requests.RequestException as e:
                if ymd == linked:
                    raise
                # a timeout or a dropped connection is not "no posting that day": named, and asked for again next time
                if errors is not None:
                    errors.append(f"posting {ymd} not read: {url}: {type(e).__name__}")
                if counts is not None:
                    counts["requested"] += 1
                    counts["failed"] += 1
                if backfill_from:
                    time.sleep(BACKFILL_PAUSE_S)
                d += timedelta(days=1)
                continue
            if counts is not None:
                counts["requested"] += 1
            ctype = r.headers.get("content-type") or ""
            if r.status_code == 200 and r.content[:2] == b"PK":
                lm = r.headers.get("Last-Modified")
                lm_iso = parsedate_to_datetime(lm).isoformat().replace("+00:00", "Z") if lm else None
                out.append((ymd, url, r.content, lm_iso))
                if keep:
                    keep(ymd, r.content, lm_iso)
            elif ymd == linked:
                raise ValueError(f"linked file {url} answered {r.status_code} {ctype}")
            elif r.status_code == 404 and counts is not None:
                counts["not_posted"] += 1
            elif r.status_code != 404:
                if errors is not None:
                    errors.append(f"posting {ymd} not read: {url} answered {r.status_code} {ctype}")
                if counts is not None:
                    counts["failed"] += 1
            if backfill_from:
                time.sleep(BACKFILL_PAUSE_S)            # one request a second or so for a long backfill
        d += timedelta(days=1)
    if skipped:
        if errors is not None:
            errors.append(f"backfill stopped after {BACKFILL_BUDGET_S // 60} minutes: {len(skipped)} days from "
                          f"{skipped[0]} to {skipped[-1]} not requested; run --backfill again to read them")
        if counts is not None:
            counts["not_requested"] += len(skipped)
    return out, linked


def fetch_layer(sess: requests.Session) -> tuple[dict | None, str | None]:
    try:
        r = get(sess, LAYER_URL, params={"where": "1=1", "outFields": "PERMIT_NUMBER,OVERFLOW_LOCATION,LATITUDE,LONGITUDE",
                                          "returnGeometry": "false", "f": "json"})
        r.raise_for_status()
        doc = r.json()
        if "features" not in doc:
            return None, f"map layer: {str(doc.get('error'))[:200]}"
        return doc, None
    except (requests.RequestException, ValueError) as e:
        return None, f"map layer: {type(e).__name__}: {e}"


def keep_posting(ymd: str, content: bytes, last_modified: str | None, fetched_at: str, archive: Path | None = None) -> None:
    """Save a posting read from EPD in the archive (data/build, so it travels with the pipeline state and a rebuild
    never downloads it again). A changed file of the same day replaces the saved one: the day's last copy is kept.
    index.json keeps each file's Last-Modified and the time it was read."""
    a = archive or ARCHIVE
    p = a / f"sewagespillsreport{ymd}.xlsx"
    idx_path = a / "index.json"
    idx = read_json(idx_path, {}) or {}
    if p.exists() and p.read_bytes() == content and ymd in idx:
        return
    a.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)
    idx[ymd] = {"last_modified": last_modified, "fetched_at": fetched_at}
    write_json(idx_path, dict(sorted(idx.items())))


def saved_postings(archive: Path | None = None) -> tuple[list, dict]:
    """([(ymd, url, bytes, last_modified)] oldest first, {ymd: time read}) from the archive."""
    a = archive or ARCHIVE
    idx = read_json(a / "index.json", {}) or {}
    out, read_at = [], {}
    for p in sorted(a.glob("sewagespillsreport*.xlsx")):
        m = re.fullmatch(r"sewagespillsreport(\d{8})\.xlsx", p.name)
        if not m:
            continue
        ymd = m.group(1)
        info = idx.get(ymd) or {}
        out.append((ymd, FILE_URL.format(ymd=ymd), p.read_bytes(), info.get("last_modified")))
        if info.get("fetched_at"):
            read_at[ymd] = info["fetched_at"]
    return out, read_at


# ---------------------------------------------------------------- main

POSTING_DATE_SLACK = 3     # days a file's own Posting Date may differ from the date in its URL


def posting_date(cell: str | None, ymd: str, stats: dict) -> str | None:
    """The posting's date: the file's Posting Date cell, unless the URL's date says otherwise. Older files spell the
    label variously ("Positng Date"), leave it out, or give a wrong year (the 2026-05-18 file says 2025-05-18): the
    URL's date is used then, and a disagreement is named in stats["posting_date_from_url"]."""
    url_day = f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}" if re.fullmatch(r"20\d{6}", ymd or "") else None
    if not url_day:
        return cell
    if cell and abs((date.fromisoformat(cell) - date.fromisoformat(url_day)).days) <= POSTING_DATE_SLACK:
        return cell
    if cell:
        stats.setdefault("posting_date_from_url", []).append(f"{ymd}: the file says {cell}; {url_day} used")
    return url_day


CARRIED = ("_first_seen_at", "_read_from_archive")     # a rebuild keeps these from the previous file, by event id


def build(postings: list[tuple[str, str, bytes, str | None]], prev_records: list[dict], layer: dict | None,
          epa: list[dict], permits: dict, fetched_at: str, rebuild: bool = False,
          read_at: dict | None = None, epa_dropped: list[dict] | None = None) -> tuple[list[dict], dict]:
    """Apply each posting (oldest first) to the previous records; then EPA pairing and the redactor.

    rebuild (--backfill, --rebuild): start from no records and apply every posting given, so an old posting is never
    laid on top of today's rows (which would mark them missing); then, by event id, the previous file's
    _first_seen_at and _read_from_archive (or its absence: a row first read live) and its point when the map layer
    no longer gives one are carried over. A previous record the postings do not rebuild (its posting was not saved)
    is kept as it was. Every posting but the newest is an archived one: a row first listed there gets
    raw._read_from_archive, the time that file was read (read_at[ymd], else this run's clock)."""
    prev_by_id = {r["event_id"]: r for r in prev_records}
    state = {} if rebuild else dict(prev_by_id)
    stats: dict = {"postings": [], "history": Counter()}
    pts = layer_points(layer)
    stats["unreadable_postings"] = []
    unread_cols: list = []
    for i, (ymd, url, content, lm) in enumerate(postings):
        try:
            posting, rows = read_posting(content, unread_cols)
        except (ValueError, KeyError, IndexError, zipfile.BadZipFile, ET.ParseError) as e:
            if i == len(postings) - 1:
                raise                                   # the newest posting must be read
            stats["unreadable_postings"].append(f"{ymd}: {type(e).__name__}: {e}"[:300])
            continue
        posting = posting_date(posting, ymd, stats)
        archived = ((read_at or {}).get(ymd) or fetched_at) if i < len(postings) - 1 else None
        ctx = {"file_url": url, "last_modified": lm, "fetched_at": fetched_at, "points": pts, "permits": permits,
               "archived": archived}
        state, n = apply_posting(state, rows, posting, ctx)
        stats["history"].update(n)
        stats["postings"].append({"posting_date": posting, "rows": len(rows), "url": url})
    if unread_cols:
        stats["unread_columns"] = unread_cols          # headers only; their values are never read
    if rebuild:
        kept = 0
        for eid, p in prev_by_id.items():
            r = state.get(eid)
            if r is None:
                state[eid] = p
                kept += 1
                continue
            praw = p.get("raw") or {}
            for k in CARRIED:
                if praw.get(k) is not None:
                    r["raw"][k] = praw[k]
                else:
                    r["raw"].pop(k, None)
            if r.get("lat") is None and "_coords" not in r["raw"] and p.get("lat") is not None:
                r["lat"], r["lon"], r["coord_source"] = p["lat"], p["lon"], p.get("coord_source")
                r["raw"]["_coords"] = praw.get("_coords") or "a point read earlier from EPD's map layer"
                r["raw"]["_coords_kept_from_earlier_read"] = True
        stats["kept_from_previous_file_not_rebuilt"] = kept
    records = list(state.values())
    stats["epa_pairing"] = dict(mark_epa_duplicates(records, epa, epa_dropped))
    records = redact.redact_events(records)
    records.sort(key=lambda r: (r.get("started_at") or "", r["event_id"]), reverse=True)
    current = [r for r in records if not r["raw"].get("_missing_from_source_since") and not r["raw"].get("_aged_out_after")]
    stats.update({
        "history": dict(stats["history"]), "records_written": len(records), "in_latest_posting": len(current),
        "by_type": dict(Counter(r["event_type"] for r in records)),
        "paired_with_epa": sum(1 for r in records if r["raw"].get("_epa_record")),
        "end_from_epa": sum(1 for r in records if (r["raw"].get("_end_basis") or "").startswith(EPA_BASIS)),
        "with_coordinates": sum(1 for r in records if r.get("lat") is not None),
        "with_volume": sum(1 for r in records if r.get("volume_gal") is not None),
        "with_operator": sum(1 for r in records if r.get("discharger_id")),
    })
    return records, stats


def backfill_summary(records: list[dict], postings_applied: list[dict], mode: str, requested_from: str | None,
                     fetched_at: str, fetch_counts: Counter, kept: int) -> dict:
    """meta.backfill: what the backfill or rebuild covered (kept in meta by every later run until the next one)."""
    archived = [r for r in records if (r.get("raw") or {}).get("_read_from_archive")]
    years = lambda rs: dict(sorted(Counter((r.get("started_at") or "")[:4] or "no date" for r in rs).items()))  # noqa: E731
    dates = [p["posting_date"] for p in postings_applied]
    return {"mode": mode, "at": fetched_at, "requested_from": requested_from,
            "postings_from": min(dates) if dates else None, "postings_to": max(dates) if dates else None,
            "postings_applied": len(dates), "requests": fetch_counts.get("requested", 0),
            "days_not_posted": fetch_counts.get("not_posted", 0),
            "days_failed": fetch_counts.get("failed", 0), "days_not_requested": fetch_counts.get("not_requested", 0),
            "records": len(records), "records_by_begin_year": years(records),
            "records_first_read_from_archive": len(archived), "first_read_from_archive_by_begin_year": years(archived),
            "began_from": min((r["started_at"] for r in records if r.get("started_at")), default=None),
            "kept_from_previous_file_not_rebuilt": kept,
            "note": ("Rows first listed in an older dated posting read after newer ones were out carry "
                     "raw._read_from_archive, the time the file was read; published_at stays the first posting that "
                     "listed the row. The list gives the day a spill began and no end: rows past day 30 set no "
                     "colour.")}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--file", nargs="*", help="saved workbooks to read (oldest first) instead of downloading")
    ap.add_argument("--layer", help="a saved map-layer query response (JSON)")
    ap.add_argument("--no-layer", action="store_true", help="do not fetch the map layer")
    ap.add_argument("--backfill", nargs="?", const="auto", metavar="FROM",
                    help=f"download every dated posting from FROM (YYYY-MM-DD; default {BACKFILL_DAYS} days before the "
                         f"linked one or {EPD_FIRST_POSTING}, whichever is earlier) that is not saved yet, then rebuild "
                         "from the saved postings; once")
    ap.add_argument("--backfill-from", dest="backfill", metavar="FROM", help="the same as --backfill FROM")
    ap.add_argument("--rebuild", action="store_true",
                    help="rebuild from the saved postings (and any --file) without downloading a workbook")
    args = ap.parse_args(argv)
    fetched_at = now_iso()
    prev_doc = read_json(EVENTS_DIR / f"{SOURCE_ID}.json", {}) or {}
    prev = prev_doc.get("records", [])
    prev_meta = prev_doc.get("meta") or {}
    rebuild = bool(args.backfill or args.rebuild)
    errors = []
    fetch_counts: Counter = Counter()
    sess = requests.Session()
    sess.headers.update(HEADERS)
    try:
        read_at: dict = {}
        start = args.backfill if args.backfill != "auto" else None
        if start:
            date.fromisoformat(start)                    # a bad date fails before any request
        given = []
        for f in args.file or []:
            m = re.search(r"(\d{8})", Path(f).name)
            ymd = m.group(1) if m else "00000000"
            given.append((ymd, FILE_URL.format(ymd=ymd) if m else PAGE_URL, Path(f).read_bytes(), None))
        if rebuild:
            saved, read_at = saved_postings()
            if args.backfill and not args.file:
                have = {p[0] for p in saved}
                if not start:
                    page = get(sess, PAGE_URL)
                    page.raise_for_status()
                    links = sorted(set(LINK.findall(page.text)))
                    if not links:
                        raise ValueError("the page links no sewagespillsreport file")
                    start = min((datetime.strptime(links[-1], "%Y%m%d").date()
                                 - timedelta(days=BACKFILL_DAYS)).isoformat(), EPD_FIRST_POSTING)
                got, linked = fetch_postings(sess, None, start, errors, have=have, counts=fetch_counts,
                                             keep=lambda ymd, content, lm: keep_posting(ymd, content, lm, fetched_at))
                saved, read_at = saved_postings()
                saved = [p for p in saved if p[0] <= linked]
            by_day = {p[0]: p for p in saved}
            by_day.update({p[0]: p for p in given})      # a saved copy handed in replaces the archive's
            postings = [by_day[k] for k in sorted(by_day)]      # every saved posting: the archive is the history
            linked = postings[-1][0] if postings else None
        elif given:
            postings, linked = given, given[-1][0]
        else:
            postings, linked = fetch_postings(sess, prev_meta.get("last_posting_read"), None, errors)
            for ymd, _, content, lm in postings:
                keep_posting(ymd, content, lm, fetched_at)
        if not postings:
            raise ValueError("no posting read")
        if args.layer:
            layer = json.loads(Path(args.layer).read_text())
        elif args.no_layer or args.file:
            layer = None
        else:
            layer, err = fetch_layer(sess)
            if err:
                errors.append(err)
            elif layer is not None:
                write_json(RAW / "map-layer-latest.json", layer)
        epa_doc = read_json(EPA_EVENTS, {}) or {}
        epa = epa_doc.get("records", [])
        records, stats = build(postings, prev, layer, epa, load_permits(), fetched_at, rebuild=rebuild,
                               read_at=read_at, epa_dropped=(read_json(EPA_DROPPED, {}) or {}).get("dropped", []))
    except Exception as e:  # noqa: BLE001 - a failed run keeps the previous records
        write_events(SOURCE_ID, [], ok=False, error=f"{type(e).__name__}: {e}")
        print(f"{SOURCE_ID}: FAILED {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    meta = {**stats, "page_url": PAGE_URL, "linked_posting": linked,
            "last_posting_read": max(f"{p[0][:4]}-{p[0][4:6]}-{p[0][6:]}" for p in postings),
            "layer_rows": len((layer or {}).get("features") or []) if layer else None, "errors": errors,
            "credit": "Georgia Environmental Protection Division, Municipal Sewage Spills Reported to EPD",
            "license": "none stated",
            "caveat": ("Reported to EPD by the owner of the sewer system; the list gives the day a spill began, not its "
                       "time or end, and does not say whether the public was notified."),
            "registry_ids": ["ga-epd-sewage-spills-report", "ga-epd-spills-map-layer"]}
    if rebuild:
        meta["backfill"] = backfill_summary(records, stats["postings"], "backfill" if args.backfill else "rebuild",
                                            start, fetched_at,
                                            fetch_counts, stats.get("kept_from_previous_file_not_rebuilt", 0))
        meta["postings"] = [stats["postings"][0], stats["postings"][-1]] if stats["postings"] else []
        meta["postings_note"] = f"{len(stats['postings'])} postings applied; first and last shown"
    elif prev_meta.get("backfill"):
        meta["backfill"] = prev_meta["backfill"]         # the backfill's range and counts stay in the feed's meta
    path_notes_to_meta(records, meta)
    path = write_events(SOURCE_ID, records, ok=True, error=None, meta=meta)
    if epa:            # EPA's Georgia records paired here become duplicate_of the EPD record (in EPA's events file)
        epa_doc["meta"] = {**(epa_doc.get("meta") or {}), "ga_epd_pairing": {"at": fetched_at, **stats["epa_pairing"]}}
        write_json(EPA_EVENTS, epa_doc)
    print(f"{SOURCE_ID}: {len(postings)} posting(s), {stats['in_latest_posting']} in the latest -> "
          f"{stats['records_written']} records; history {stats['history']}; EPA pairing {stats['epa_pairing']}; "
          f"{stats['with_coordinates']} with points -> {path}")
    if rebuild:
        print(f"{SOURCE_ID}: {meta['backfill']['mode']} {json.dumps(meta['backfill'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
