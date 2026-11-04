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
  Older dated files stay at the same URL pattern (2026-06-01 and 2026-10-01 were fetched on 2026-11-04); a day with
  no posting answers 404 with an HTML page. Points: the public ArcGIS layer behind EPD's "Spills in Georgia"
  StoryMap, https://services1.arcgis.com/p0dLjwtOaJHU8zq2/arcgis/rest/services/Spill_Summary_Continuous_Update/
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
    duplicate_of that row. A vanished row is never given an end: its end stays unknown. A posting with no rows at all
    changes nothing (a fault in the file, not every spill withdrawn); an older posting that cannot be read is skipped
    and named in meta (unreadable_postings); the newest must be read or the run fails and keeps the previous file.
  - event_type: OVERFLOW_DESTINATION naming a CSO ("CSO Dry-weather") -> cso; every other row -> sso (the rule's
    "spill" is a raw-sewage discharge from the collection system or plant; OVERFLOW_TYPE and SPILL_SOURCE stay in
    raw.row and OVERFLOW_TYPE gives `material`). status unknown: the list has no end date and no time.
  - Times: started_at = the begin date (time_precision day). published_at = the posting date. source_updated_at =
    the workbook's HTTP Last-Modified when given. reported_at null (the list does not say when EPD was told).
    raw._first_seen_posting / _last_seen_posting say which postings showed the row; raw._first_seen_at is our clock.
    Colour (build/status.py, data/rules.json unresolved.day_start_caution, which lists this source): a row with no end
    is a caution for 72 hours from the start of its begin day, then unresolved (end not reported) to day 30.
  - Volume: QUANTITY_GALLONS in gallons; blank, or "0" ("A 'zero' in the quantity field indicates the amount of the
    spill has not been determined", EPD's page) -> volume_gal null and volume_text saying so. estimate_flag unknown.
  - Water: WATERWAY_IMPACTED as given in waterbody_text. "Ditch", "Storm Drain", "Basin", "unknown" or blank name no
    water (raw._water.why_none). No Georgia water records yet: water_slugs [], water_match none. A destination that
    says dry land and names neither waters of the State nor a CSO ("Dry Land Overflow") is kept with
    raw.reached_water false, unless WATERWAY_IMPACTED names a water; any other destination wording is not read as
    "did not reach water" (raw._destination_not_read), so a spill is never hidden on a wording not yet seen.
  - Operator: discharger_id from data/dischargers.json by permit (npdes_permit / npdes_permits); discharger_name is
    EPD's FACILITY_NAME. npdes_permit only for a real permit number (GA + 7 digits).
  - Points: a layer row with the same permit and normalised address, when exactly one, lends LATITUDE / LONGITUDE
    (coord_source "geocode": the layer's point is EPD's location for the address; precision not stated). When the
    layer is down or no longer lists the row, the point read earlier stays (raw._coords_kept_from_earlier_read).
  - EPA's copy: Georgia permittees file 24-hour and 5-day reports in EPD's GEOS, and these reach EPA's Sewer Overflow
    and Bypass Event tables (ingest/echo_sewer_overflow_events.py, run before this module; for Georgia they carry
    times and an end but no volume, and mostly the plant's point). An EPD row pairs with the EPA record of the same
    permit and begin day: the record whose receiving water is the same name first, when that name picks exactly one
    row and one record (two spills of one system on one water that day are not told apart); else, when only one EPD
    row and one EPA record of that permit and day remain unpaired and they do not contradict each other (two different
    specific water names, or EPD's dry land against a water EPA names: raw._epa_not_paired), those two. Several left
    on both sides are not paired (raw._epa_candidates). An end borrowed from the wrong report would be an invented end,
    so every doubt leaves the EPD row without one. The EPD record is the public one (gallons, address, waterway,
    cause, the map layer's point): it takes EPA's ended_at when it has none and EPA's end is the spill's own (minute
    precision; an extreme-weather report's reporting period is not: raw._epa_end_not_used), with status ended,
    raw._end_basis naming the EPA record and "EPA eRule report", and raw._epa_record; the EPA record is marked duplicate_of the EPD record, written back into
    EPA's events file (data/build/events/echo-sewer-overflow.json). Unpaired EPA records stay as they are. The pairs
    are recomputed on every run (earlier marks on both sides are cleared first), so a report EPA receives later
    still finds its EPD row; the EPA module rewrites its file each run, and this module runs after it.

Privacy: the list names facilities and street addresses, no people. common.strip_personal runs on raw; the export's
  redactor (build/redact.py) runs over CAUSE and every other free text before the file is written.

Run from pipeline/:  python -m ingest.ga_epd_spills [--file posting.xlsx ...] [--layer layer.json]
                                                    [--backfill-from YYYY-MM-DD]
  --file reads saved workbooks (oldest first; no network unless --layer is absent and --no-layer is not given).
  --backfill-from also reads every dated file from that date to the linked one (a 404 is a day with no posting; about
    one request a second). Run by hand, once, before the state goes live; the hourly run never backfills.
  Without options: the linked posting, plus any posting since the last one read (up to 14 days) that a missed run
  skipped. Cadence: each business day (about one business day of latency).
"""
from __future__ import annotations

import argparse
import json
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
from common import (DATA_DIR, EVENTS_DIR, HEADERS, RAW_DIR, ROOT, event, now_iso, read_json, write_events,
                    write_json, path_notes_to_meta)

SOURCE_ID = "ga-epd-spills"
PAGE_URL = "https://epd.georgia.gov/sewage-spills-report"
FILE_URL = "https://epd.georgia.gov/document/document/sewagespillsreport{ymd}/download"
LAYER_URL = ("https://services1.arcgis.com/p0dLjwtOaJHU8zq2/arcgis/rest/services/Spill_Summary_Continuous_Update/"
             "FeatureServer/0/query")
EPA_EVENTS = EVENTS_DIR / "echo-sewer-overflow.json"
RAW = RAW_DIR / SOURCE_ID
AUTHORITY = "Georgia Environmental Protection Division (Municipal Sewage Spills Reported to EPD)"
CATCH_UP_DAYS = 14
MOVED_DAYS = 7
BACKFILL_PAUSE_S = 1.0
REAL_PERMIT = re.compile(r"^GA\d{7}$")
LINK = re.compile(r"/document/document/sewagespillsreport(\d{8})/download")
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
HEADER_ALIASES = {"spill_begin_date": "begin_date"}
FIELDS = ["facility_name", "begin_date", "county", "city", "overflow_location", "quantity_gallons", "overflow_type",
          "permit_number", "spill_source", "cause", "river_basin", "waterway_impacted", "overflow_destination"]
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


def read_posting(content: bytes) -> tuple[str | None, list[dict]]:
    """(posting date, rows as {field: text}) of one workbook. ValueError when it is not the spills list."""
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
    out = []
    for r in rows[hdr_i + 1:]:
        if not any(c.strip() for c in r):
            continue
        out.append({h: " ".join((r[j] if j < len(r) else "").split()) for j, h in enumerate(hdr) if h})
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
    hits = ctx["points"].get((permit, norm_addr(row.get("overflow_location"))), [])
    if len(hits) == 1:
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
                 waterbody_text=water if water and not NO_WATER.match(water) else None,
                 water_slugs=[], water_match="none",
                 lat=lat, lon=lon, coord_source="geocode" if lat is not None else None,
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
            for k in ("_first_seen_at", "_first_seen_posting", "_revisions"):
                if praw.get(k) is not None:
                    rec["raw"][k] = praw[k]
            if rec.get("lat") is None and "_coords" not in rec["raw"] and p.get("lat") is not None:
                # the map layer is down, or no longer lists the row: the point read earlier stays
                rec["lat"], rec["lon"], rec["coord_source"] = p["lat"], p["lon"], p.get("coord_source")
                rec["raw"]["_coords"] = praw.get("_coords") or "a point read earlier from EPD's map layer"
                rec["raw"]["_coords_kept_from_earlier_read"] = True
            old = praw.get("row") or {}
            changed = {k: old.get(k) for k in set(old) | set(row) if (old.get(k) or "") != (row.get(k) or "")}
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
            n["new"] += 1
        rec["raw"]["_last_seen_posting"] = posting
        cur[rec["event_id"]] = rec
    if not cur:            # an empty list for the whole state is a fault in the posting, not 60 withdrawals
        n["empty_posting"] += 1
        return {**prev}, n
    oldest = min((r["started_at"] for r in cur.values() if r.get("started_at")), default=None)
    by_permit_addr = defaultdict(list)
    for r in cur.values():
        row = r["raw"]["row"]
        by_permit_addr[((row.get("permit_number") or "").upper(), norm_addr(row.get("overflow_location")))].append(r)
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
            if succ and not p.get("duplicate_of"):
                p["duplicate_of"] = succ[0]["event_id"]
                p["raw"]["_duplicate_basis"] = (f"gone from the {posting} posting; {succ[0]['event_id']} (same permit "
                                                f"and address, begin date {succ[0]['started_at']}) looks like its "
                                                f"corrected row")
                n["superseded_by_corrected_row"] += 1
            else:
                n["withdrawn_within_window"] += 1
        cur[eid] = p
    return cur, n


# ---------------------------------------------------------------- EPA's copy

EPA_BASIS = "EPA eRule report"                  # raw._end_basis of an EPD record that took EPA's end
EPD_BASIS = "Georgia EPD spill list record"     # raw._duplicate_basis of an EPA record paired with an EPD row


def mark_epa_duplicates(records: list[dict], epa: list[dict]) -> Counter:
    """Pair EPD rows with EPA's records of the same permit and begin day (module docstring). The EPD record is the
    public one: it takes EPA's end when it has none (raw._end_basis) and the EPA record becomes duplicate_of it.
    Both lists are changed in place; every mark of an earlier run is cleared first, so pairs are recomputed."""
    n: Counter = Counter()
    for r in records:
        if (r["raw"].get("_end_basis") or "").startswith(EPA_BASIS):
            r["ended_at"], r["status"] = None, "unknown"
            r["raw"].pop("_end_basis", None)
        for k in ("_epa_candidates", "_epa_record", "_epa_not_paired", "_epa_end_not_used"):
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
        if r.get("duplicate_of") or not r.get("npdes_permit") or not r.get("started_at"):
            continue
        mine[(r["npdes_permit"], r["started_at"][:10])].append(r)
    paired_epa = set()
    for k, rs in mine.items():
        es = list(groups.get(k, []))
        if not es:
            n["epd_without_epa"] += len(rs)
            continue
        left = []
        row_keys = Counter(water_key(r.get("waterbody_text")) for r in rs)
        for r in rs:
            wk = water_key(r.get("waterbody_text"))
            hits = [e for e in es if wk and wk in epa_water_keys(e)]
            if len(hits) == 1 and row_keys[wk] == 1:
                es.remove(hits[0])
                _pair(r, hits[0], "same permit, day and receiving water")
                paired_epa.add(hits[0]["event_id"])
                n["paired_by_water"] += 1
            else:
                if hits:                 # two spills of one permit, day and water: whose end is whose is not known
                    n["same_water_ambiguous"] += 1
                left.append(r)
        if len(left) == 1 and len(es) == 1 and not contradicts(left[0], es[0]):
            _pair(left[0], es[0], "the only EPD row and the only EPA report of this permit and day")
            paired_epa.add(es[0]["event_id"])
            n["paired_alone"] += 1
        elif left:
            if len(left) == 1 and len(es) == 1:
                left[0]["raw"]["_epa_not_paired"] = (f"{es[0]['event_id']} is the only EPA report of this permit and "
                                                     f"day, but {contradicts(left[0], es[0])}")
                n["not_paired_contradiction"] += 1
            for r in left:
                r["raw"]["_epa_candidates"] = [e["event_id"] for e in es]
            n["epd_without_epa"] += len(left)
    n["epa_without_epd"] = sum(len(v) for v in groups.values()) - len(paired_epa)
    return n


# a water key that names no particular water ("Unnamed tributary", "UT", "creek"): it contradicts no name
GENERIC_WATER = re.compile(r"^(?:unnamed|unamed|unnammed|unknown|an?)?(?:ut|trib\w*|stream|creek|branch|ditch|"
                           r"storm\w*|ms4\w*|catchbasin|pond)?$")


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


def _pair(r: dict, e: dict, why: str) -> None:
    """The EPD record r stays primary; EPA's e is duplicate_of it. r takes e's end only when it has none and e's end is
    the spill's own reported end (minute precision: not the reporting period of an extreme-weather report)."""
    r["raw"]["_epa_record"] = e["event_id"]
    if not r.get("ended_at") and e.get("ended_at") and e.get("time_precision") != "minute":
        r["raw"]["_epa_end_not_used"] = (f"{e['event_id']} gives an end of {e['ended_at']} at {e.get('time_precision')} "
                                         f"precision (a reporting period, not the spill's own end)")
    elif not r.get("ended_at") and e.get("ended_at"):
        r["ended_at"], r["status"] = e["ended_at"], "ended"
        r["raw"]["_end_basis"] = (f"{EPA_BASIS} {e['event_id']} ({why}; EPA start {e.get('started_at')}, end "
                                  f"{e['ended_at']}, as given, presumably local time)")
    e["duplicate_of"] = r["event_id"]
    e.setdefault("raw", {})["_duplicate_basis"] = (f"{EPD_BASIS} {r['event_id']}: {why}; the state's list carries the "
                                                   f"gallons, address and waterway")


# ---------------------------------------------------------------- fetch

def get(sess: requests.Session, url: str, **kw) -> requests.Response:
    r = sess.get(url, timeout=(15, 90), **kw)
    return r


def fetch_postings(sess: requests.Session, last_read: str | None, backfill_from: str | None,
                   errors: list | None = None) -> tuple[list, str | None]:
    """[(ymd, url, bytes, last_modified)] oldest first, and the linked file's date. A catch-up or backfill day that
    answers neither a workbook nor 404 (no posting that day) is named in errors: that posting is not read."""
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
    while d <= newest:
        ymd = d.strftime("%Y%m%d")
        if d.weekday() < 5 or ymd == linked:
            url = FILE_URL.format(ymd=ymd)
            r = get(sess, url)
            ctype = r.headers.get("content-type") or ""
            if r.status_code == 200 and r.content[:2] == b"PK":
                lm = r.headers.get("Last-Modified")
                lm_iso = parsedate_to_datetime(lm).isoformat().replace("+00:00", "Z") if lm else None
                out.append((ymd, url, r.content, lm_iso))
            elif ymd == linked:
                raise ValueError(f"linked file {url} answered {r.status_code} {ctype}")
            elif r.status_code != 404 and errors is not None:
                errors.append(f"posting {ymd} not read: {url} answered {r.status_code} {ctype}")
            if backfill_from:
                time.sleep(BACKFILL_PAUSE_S)            # one request a second or so for a long backfill
        d += timedelta(days=1)
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


def keep_raw(ymd: str, content: bytes) -> str:
    p = RAW / f"sewagespillsreport{ymd}.xlsx"
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
    return str(p.relative_to(ROOT))


# ---------------------------------------------------------------- main

def build(postings: list[tuple[str, str, bytes, str | None]], prev_records: list[dict], layer: dict | None,
          epa: list[dict], permits: dict, fetched_at: str) -> tuple[list[dict], dict]:
    """Apply each posting (oldest first) to the previous records; then EPA pairing and the redactor."""
    state = {r["event_id"]: r for r in prev_records}
    stats: dict = {"postings": [], "history": Counter()}
    pts = layer_points(layer)
    stats["unreadable_postings"] = []
    for i, (ymd, url, content, lm) in enumerate(postings):
        try:
            posting, rows = read_posting(content)
        except (ValueError, KeyError, IndexError, zipfile.BadZipFile, ET.ParseError) as e:
            if i == len(postings) - 1:
                raise                                   # the newest posting must be read
            stats["unreadable_postings"].append(f"{ymd}: {type(e).__name__}: {e}"[:300])
            continue
        posting = posting or f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}"
        ctx = {"file_url": url, "last_modified": lm, "fetched_at": fetched_at, "points": pts, "permits": permits}
        state, n = apply_posting(state, rows, posting, ctx)
        stats["history"].update(n)
        stats["postings"].append({"posting_date": posting, "rows": len(rows), "url": url})
    records = list(state.values())
    stats["epa_pairing"] = dict(mark_epa_duplicates(records, epa))
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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--file", nargs="*", help="saved workbooks to read (oldest first) instead of downloading")
    ap.add_argument("--layer", help="a saved map-layer query response (JSON)")
    ap.add_argument("--no-layer", action="store_true", help="do not fetch the map layer")
    ap.add_argument("--backfill-from", help="also read every dated posting from this date (YYYY-MM-DD)")
    args = ap.parse_args(argv)
    fetched_at = now_iso()
    prev_doc = read_json(EVENTS_DIR / f"{SOURCE_ID}.json", {}) or {}
    prev = prev_doc.get("records", [])
    errors = []
    sess = requests.Session()
    sess.headers.update(HEADERS)
    try:
        if args.file:
            postings = []
            for f in args.file:
                m = re.search(r"(\d{8})", Path(f).name)
                ymd = m.group(1) if m else "00000000"
                postings.append((ymd, FILE_URL.format(ymd=ymd) if m else PAGE_URL, Path(f).read_bytes(), None))
            linked = postings[-1][0] if postings else None
        else:
            postings, linked = fetch_postings(sess, (prev_doc.get("meta") or {}).get("last_posting_read"),
                                              args.backfill_from, errors)
            for ymd, _, content, _ in postings:
                keep_raw(ymd, content)
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
        records, stats = build(postings, prev, layer, epa, load_permits(), fetched_at)
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
    path_notes_to_meta(records, meta)
    path = write_events(SOURCE_ID, records, ok=True, error=None, meta=meta)
    if epa:            # EPA's Georgia records paired here become duplicate_of the EPD record (in EPA's events file)
        epa_doc["meta"] = {**(epa_doc.get("meta") or {}), "ga_epd_pairing": {"at": fetched_at, **stats["epa_pairing"]}}
        write_json(EPA_EVENTS, epa_doc)
    print(f"{SOURCE_ID}: {len(postings)} posting(s), {stats['in_latest_posting']} in the latest -> "
          f"{stats['records_written']} records; history {stats['history']}; EPA pairing {stats['epa_pairing']}; "
          f"{stats['with_coordinates']} with points -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
