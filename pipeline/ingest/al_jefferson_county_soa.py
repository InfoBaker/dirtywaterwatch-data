"""Jefferson County (Alabama) Environmental Services' sewer overflow advisories -> data/build/events/al-jefferson-county-soa.json

Source (register row AL:al-jefferson-county-public-notice)
  "Jefferson County, AL Environmental Services Department, Sanitary Sewer Overflow Advisories", https://soa.jccal.org/
  (an ASP.NET page; 200 to this build's client and to GitHub's runner, probe run 43885170112). The page shows a table
  of ten rows per page ("3057 records available" on 2026-11-17), paged and filtered by form posts (Year, Month, City,
  Waterway), with columns Date, Location, City, Zip, Affected Waterway, Downstream Of, Reason, Status, Date Resolved;
  each Location links to a Google map at a latitude and longitude. Its button "Download as CSV file" posts the same
  form and returns the filtered rows as OverflowAdvisories.csv, which adds a Time column and the map point
  (MapLink). The page says nothing more about its columns: it does not define "Status" (every row reads "Resolved")
  or "Date Resolved". Both are kept as the source's words (raw.status_as_written, raw.date_resolved) and never read as
  the end of the overflow.
  Law: none named on the page. Ala. Admin. Code r. 335-6-6-.12(l)6.(v) requires the permittee to report a notifiable
  overflow to "the public" as soon as possible; the county's other public channels are subscriber alerts.

Reading (one GET of the page for its hidden form fields, then form posts of the export; the requests share one
  session for the read only, nothing is kept between runs)
  - Hourly: the export filtered to the current year (Central time), and to the year before during January, so a
    record posted late for December is read.
  - --backfill: the export for each year the page's Year list offers from BACKFILL_FROM's year, one post every
    PAUSE_S seconds.
  - The CSV is written without quoting although fields hold commas ("Roots, Grease or Debris", "33.47, -86.85",
    a location now and then): parse_line anchors each row on its date and time at the start and on the last
    "YYYY/MM/DD" (Date Resolved) with the status before it; the map point is what follows. Before the status, read
    from the right: the reason (one field, or the two or three "Roots, Grease or Debris" is split into), Downstream
    Of, Affected Waterway, Zip (digits as typed, often cut short: "3502") and City; the location is what remains.
    A row whose ZIP is not digits or whose city holds a digit does not line up and is not read.
    A row that does not fit is not read: the others are kept, the read is partial (health false) and the row is
    named by its date only (meta.rows_not_read; review 2026-11-17 P2-8). A header that is not the one known, or rows
    none of which fits, is a failed read (ok false, the records kept). A row with no time is read as a date.
  - Health: a page with no form fields, an export that is not this CSV, or a failed request is a failed read; an
    export with no row for the year (the first days of January) is a read with nothing new.

Records (one sso record per row; the table has no id)
  - Rows are kept only as safe_row gives them: the street and Downstream Of with every house number removed, the
    point rounded or withheld (review 2026-11-17 P1-1); the export itself is not saved.
  - source_record_id "<date>T<HHMM or 'day'>:<street key>": the row's date and time and its street, letters and
    digits with street words in one form (street_key). Rows sharing that key get "~<6 hex>" from their water, reason,
    point, city and ZIP, matched to the rows held before, so an id does not depend on the export's order
    (assign_ids; review 2026-11-17 P2-5).
  - Every row read is kept in data/build/al-jefferson-county-soa-state.json (the archive); records are rebuilt from it
    each run, so the hourly read of one year never drops the years the backfill read. A row the export no longer
    lists when its year is read again keeps its record with raw._missing_from_source_since.
  - Times: Date and Time are local wall-clock (Central: Jefferson County is in America/Chicago). started_at is that
    minute (time_precision minute); the export calls it only "Time", and it is kept as the time the county gives for
    the overflow. ended_at is null and status unknown: the table gives no end of the overflow, and "Date Resolved" is
    the date the county marked the advisory resolved (raw.date_resolved, a date, its own words). reported_at and
    published_at stay null (the table gives no posting time); raw._first_seen_at is our clock.
  - Water: "Affected Waterway" names the water and its GNIS id ("Shades Creek - IDN: 00153377": the id is the
    feature's GNIS id, the id the NHD water records carry). waterbody_text is the name; raw.gnis_id the id. The status
    build places the record by that name near the row's point (the repository's matcher), and only by that name:
    raw._placement named_water_only, so a name it cannot match never falls back to whatever water lies at the point
    (review 2026-11-17 P1-3).
    "NONE" is the county's statement that no waterway was affected: raw.reached_water false with the words, so the
    record is kept and placed on no water. "Downstream Of" is kept as written (raw.downstream_of; "N/A" is dropped).
  - Point: the MapLink latitude and longitude as the county gives them, rounded to three decimals (about 100 m;
    coord_precision_m 100), since the point is a street address that may be a home. A point outside Alabama's box,
    or a link that is not one latitude and one longitude, is not used (raw._point_withheld says why).
  - Location: the street with every house number removed (al_adem_sso.clean_text, then street_only for the numbers
    it leaves); the city and ZIP as written.
  - Operator: discharger_id al-jefferson-county (Jefferson County Commission, the federal registry's operator). The
    row does not name the treatment plant or permit, so npdes_permit stays null and raw.operator_permits lists the
    county's permits.
  - Volume: the table gives none (volume_text null, estimate_flag unknown).
  - The same overflow is usually filed with ADEM (al-adem-sso-history, read before this module in the refresh): a
    county record is duplicate_of ADEM's report of the county's permits that began the same local day with its point
    within LINK_M metres (link_adem; the closest wins, one ADEM report per county record), so the status build counts
    it once and shows ADEM's report, which carries the start, stop, volume and permit. The link is not made when the
    two name different waters (build/status.py waters_differ), nor when ADEM's report names no water reached (its flag,
    its words or a placeholder: status.no_water_flag, reached_no_water, no_receiving_water) and the county names one
    (a dry-land record never absorbs a report of a water); raw._duplicate_basis says why a link was made.
Failures: exit 1 for a failed read (the previous records kept); --backfill exits 0 when at least one year was read and
  names the years not read in meta.years_not_read (health false), 1 when none was.
Run from pipeline/: python -m ingest.al_jefferson_county_soa [--backfill [--from 2012-01-01]] [--csv saved.csv --out events.json]
Cadence: hourly with the refresh (Alabama is live).
"""
from __future__ import annotations

import argparse
import hashlib
import math
import re
import sys
import time
from collections import Counter
from datetime import UTC, date, datetime
from html import unescape
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from common import (BUILD_DIR, EVENTS_DIR, HEADERS, HOUSE_NUMBER_REMOVED, event, now_iso, read_json, write_events,
                    write_json)
from common import error_detail, error_text
from ingest.al_adem_sso import clean_text

SOURCE_ID = "al-jefferson-county-soa"
URL = "https://soa.jccal.org/"
TZ_NAME = "America/Chicago"
TZ = ZoneInfo(TZ_NAME)
STATE_PATH = BUILD_DIR / "al-jefferson-county-soa-state.json"
ADEM_EVENTS = EVENTS_DIR / "al-adem-sso-history.json"
DISCHARGER_ID = "al-jefferson-county"
DISCHARGER = "Jefferson County Commission"
PERMITS = ["AL0022926", "AL0022934", "AL0023027", "AL0023647", "AL0023655", "AL0026913", "AL0050881", "AL0056120",
           "AL0067067"]                 # data/dischargers.json al-jefferson-county npdes_permits
AUTHORITY = "Jefferson County Environmental Services Department, Sanitary Sewer Overflow Advisories"
HEADER = ["Date", "Time", "Location", "City", "Zip", "Affected Waterway", "Downstream Of", "Reason", "Status",
          "Date Resolved", "MapLink", ""]
BACKFILL_FROM = "2012-01-01"
PAUSE_S = 3
LINK_M = 1000
AL_BOX = (-88.6, -84.8, 30.1, 35.1)          # lon min, lon max, lat min, lat max
POINT_DECIMALS = 3
# the one reason the list writes with commas, split by the unquoted export into two or three fields
SPLIT_REASON = re.compile(r"(?i)roots\s*,\s*grease\s*,?\s*or\s+debris")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
TIME = re.compile(r"(\d{1,2}):(\d{2})\s*([AP])M", re.I)
RESOLVED = re.compile(r"\s*(\d{4})/(\d{2})/(\d{2})\s*")
ZIP_AS_WRITTEN = re.compile(r"\s*\d{0,5}(?:-\d{4})?\s*")   # as typed: "35211", "3502", "352", blank
IDN = re.compile(r"^(.*?)\s*-\s*IDN:\s*0*(\d+)\s*$", re.I)
NUM = r"-?\d{1,3}\.\d+"
POINT = re.compile(rf"^\s*(?:lat\s*)?({NUM})\s*[,;/ ]\s*(?:long?\s*)?({NUM})\.?\s*$", re.I)
# a number left in a street after the scrub: a house number unless a route word stands before it (I-65, Hwy 150)
LEFT_NUMBER = re.compile(r"(?<![\w\-.\[])\d+[A-Za-z]?(?:\s*[-/]\s*\d+[A-Za-z]?)*(?![\w])")
# "33RD COURT N3444", "n1234 Main St": a number run into a direction letter (any case, any length)
GLUED_NUMBER = re.compile(r"(?i)\b([NSEW])(\d{1,6})\b")
# "5711Governor John Sevier", "12Main St": a number run into its street (an ordinal's two letters are not a street)
GLUED_BEFORE = re.compile(r"\b\d{1,6}(?=[A-Za-z]{3,}|(?!(?i:st|nd|rd|th)\b)[A-Za-z]{2}\b)")
ROUTE_BEFORE = re.compile(r"(?i)\b(?:highway|hwy|interstate|i|us|u\.s\.|sr|cr|route|rte|rt|county\s+road|co\.?\s*rd|"
                          r"state\s+road|exit|mile|lift\s+station|ls|pump\s+station)\s*[-#]?\s*$")


class ReadError(ValueError):
    """The page or the export is not the one this reader knows: a failed read, never "no overflows"."""


# ---------------------------------------------------------------- text

def street_only(v: str | None) -> str | None:
    """A location with every house number removed: al_adem_sso.clean_text (common.strip_house_numbers and the
    Alabama forms), then any number still standing on its own that no route word precedes ("2025", "1234-B MAIN
    ST", "99/105 SUMMIT BOULEVARD"); ordinals ("15th Ave") and route numbers ("Highway 150") stay."""
    s = clean_text(v)
    if not s:
        return None

    def repl(m):
        return m.group(0) if ROUTE_BEFORE.search(s[:m.start()]) else HOUSE_NUMBER_REMOVED
    s = GLUED_NUMBER.sub(lambda m: f"{m.group(1)} {HOUSE_NUMBER_REMOVED}", s)
    s = GLUED_BEFORE.sub(HOUSE_NUMBER_REMOVED + " ", s)
    s = LEFT_NUMBER.sub(repl, s)
    s = re.sub(rf"(?:{re.escape(HOUSE_NUMBER_REMOVED)}\s*[-/&,]?\s*){{2,}}", HOUSE_NUMBER_REMOVED + " ", s)
    return " ".join(s.split()) or None


SUFFIXES = {"ROAD": "RD", "STREET": "ST", "AVENUE": "AVE", "AV": "AVE", "DRIVE": "DR", "LANE": "LN", "COURT": "CT",
            "PLACE": "PL", "CIRCLE": "CIR", "BOULEVARD": "BLVD", "PARKWAY": "PKWY", "PIKE": "PK", "HIGHWAY": "HWY",
            "TERRACE": "TER", "TRAIL": "TRL", "NORTH": "N", "SOUTH": "S", "EAST": "E", "WEST": "W"}


def street_key(v: str | None) -> str:
    """A comparison key for a scrubbed street: letters and digits, street words in one form ("PINE GROVE ROAD" and
    "Pine Grove Rd." give "PINEGROVERD"; review 2026-11-17 P2-6)."""
    s = (v or "").replace(HOUSE_NUMBER_REMOVED, " ").upper()
    words = [SUFFIXES.get(w, w) for w in re.findall(r"[A-Z0-9]+", s)]
    return "".join(words)[:40] or "NOLOCATION"


def clock(v: str) -> tuple[int, int] | None:
    m = TIME.fullmatch(v.strip())
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if not 1 <= h <= 12 or mi > 59:
        return None
    return h % 12 + (12 if m.group(3).upper() == "P" else 0), mi


def point(text: str) -> tuple[float | None, float | None, str | None]:
    """(lat, lon, None) rounded to POINT_DECIMALS, or (None, None, why the point is not used)."""
    t = " ".join((text or "").replace("\t", " ").split())
    if not t:
        return None, None, "the row gives no map point"
    m = POINT.match(t)
    if not m:
        return None, None, "the map link is not one latitude and one longitude"
    lat, lon = float(m.group(1)), float(m.group(2))
    if not (AL_BOX[2] <= lat <= AL_BOX[3] and AL_BOX[0] <= lon <= AL_BOX[1]):
        return None, None, "the map point lies outside Alabama"
    return round(lat, POINT_DECIMALS), round(lon, POINT_DECIMALS), None


# ---------------------------------------------------------------- the export

def parse_csv(text: str) -> tuple[list[dict], list[str]]:
    """(rows, the dates of the rows not read) from the export (module docstring). Raises ReadError when the header is
    not the known one."""
    lines = text.lstrip("﻿").splitlines()
    if not lines or [h.strip() for h in lines[0].split(",")] != HEADER:
        raise ReadError(f"the export's header is not the known one: {lines[0][:120] if lines else '(empty)'!r}")
    rows, bad = [], []
    for line in lines[1:]:
        if not line.strip():
            continue
        row = parse_line(line)
        if row is None:
            d = line.split(",", 1)[0].strip()
            bad.append(d if DATE.fullmatch(d) else "(no date)")
        else:
            rows.append(row)
    return rows, bad


def parse_line(line: str) -> dict | None:
    t = line.split(",")
    if len(t) < 12 or not DATE.fullmatch(t[0].strip()) or t[-1].strip() or (t[1].strip() and clock(t[1]) is None):
        return None
    # Date Resolved: the last "YYYY/MM/DD" field; the status before it; the map point after it (to the trailing comma)
    ri = next((i for i in range(len(t) - 2, 2, -1) if RESOLVED.fullmatch(t[i])), None)
    if ri is None:
        return None
    status, resolved, maplink = t[ri - 1].strip(), t[ri].strip(), ",".join(t[ri + 1:-1])
    mid = t[2:ri - 1]                              # Location .. Reason
    # the reason: one field, or the two or three a comma splits "Roots, Grease or Debris" into
    n = 1
    for k in (3, 2):
        if len(mid) >= k + 5 and SPLIT_REASON.fullmatch(",".join(mid[-k:]).strip()):
            n = k
            break
    reason = " ".join(",".join(mid[-n:]).split())
    body = mid[:-n]                                # Location (may hold commas), City, Zip, Waterway, Downstream Of
    if len(body) < 5:
        return None
    location, city, zipc, water, down = ",".join(body[:-4]), body[-4], body[-3], body[-2], body[-1]
    if not ZIP_AS_WRITTEN.fullmatch(zipc) or re.search(r"\d", city):
        return None                                # the fields do not line up: not read
    y, mo, d = RESOLVED.fullmatch(resolved).groups()
    try:
        date(int(y), int(mo), int(d))
        date.fromisoformat(t[0].strip())
    except ValueError:
        return None
    return {"date": t[0].strip(), "time": t[1].strip(), "location": location.strip(), "city": city.strip(),
            "zip": zipc.strip(), "waterway": water.strip(), "downstream_of": down.strip(), "reason": reason,
            "status": status, "date_resolved": f"{y}-{mo}-{d}", "maplink": maplink.strip()}


def form_fields(page: str) -> dict:
    """The page's hidden fields (the form post's state); ReadError when the page is not the advisories table."""
    f = {m.group(1): unescape(m.group(2)) for m in
         re.finditer(r'<input type="hidden" name="([^"]+)" id="[^"]*" value="([^"]*)"', page)}
    if "__VIEWSTATE" not in f or 'id="btnExport"' not in page or 'id="GridView1"' not in page:
        raise ReadError("the page has no advisories table, export button or form state")
    return f


def record_count(page: str) -> int | None:
    m = re.search(r'id="lblCount">\s*([\d,]+)\s+records available', page)
    return int(m.group(1).replace(",", "")) if m else None


def year_options(page: str) -> list[int]:
    sel = re.search(r'<select name="ddlYear".*?</select>', page, re.S)
    return sorted(int(y) for y in re.findall(r'<option[^>]*value="(\d{4})"', sel.group(0))) if sel else []


# ---------------------------------------------------------------- state and records

def row_hash(r: dict) -> str:
    return hashlib.sha256("\x1f".join(str(r.get(k) or "") for k in sorted(r)).encode()).hexdigest()[:16]


def safe_row(r: dict) -> dict:
    """The row as it is kept (state, ids, records): the street and Downstream Of with every house number removed, the
    map point rounded to three decimals or withheld with the reason (review 2026-11-17 P1-1: nothing finer is
    stored)."""
    lat, lon, why = point(r.get("maplink") or "")
    ds = " ".join((r.get("downstream_of") or "").split())
    out = {**r, "location": street_only(r.get("location")) or "",
           "downstream_of": ds if ds.upper() in ("", "N/A", "NA", "NONE") else (street_only(ds) or ""),
           "maplink": f"{lat}, {lon}" if lat is not None else ""}
    if why:
        out["point_withheld"] = r.get("point_withheld") or why     # safe_row of a kept row keeps the first reason
    return out


def base_id(r: dict) -> str:
    c = clock(r["time"]) if r.get("time") else None
    hm = f"{c[0]:02d}{c[1]:02d}" if c else "day"
    return f"{r['date']}T{hm}:{street_key(r['location'])}"


def ident(r: dict) -> str:
    """What tells two rows of one date, time and street apart (the water, reason, point, city and ZIP)."""
    return hashlib.sha256("\x1f".join(str(r.get(k) or "") for k in ("waterway", "reason", "maplink", "city", "zip"))
                          .encode()).hexdigest()[:6]


def assign_ids(rows: list[dict], held: dict, base_of=base_id, ident_of=ident) -> list[tuple[str, dict]]:
    """(source_record_id, row) for one read, stable across reads (review 2026-11-17 P2-5): a row whose date, time and
    street no other row shares (in this read or the state) keeps the plain key; rows that share one are told apart by
    ident_of, matched first to the held row with the same ident, then (one left on each side) to the one held row
    left; a new one gets "<key>~<ident>" ("~2", "~3" more for rows identical in every field)."""
    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(base_of(r), []).append(r)
    out = []
    for base, grp in groups.items():
        olds = {rid: h for rid, h in held.items() if rid == base or rid.startswith(base + "~")}
        taken, left = set(), []
        for r in grp:
            i = ident_of(r)
            rid = next((k for k, h in olds.items() if k not in taken and h.get("ident") == i), None)
            if rid:
                taken.add(rid)
                out.append((rid, r))
            else:
                left.append(r)
        spare = [k for k in olds if k not in taken]
        if len(left) == 1 and len(spare) == 1:
            out.append((spare[0], left[0]))
            continue
        for r in left:
            rid = base if not olds and len(grp) == 1 else f"{base}~{ident_of(r)}"
            n = 1
            while rid in taken or (rid in olds and rid not in spare):
                n += 1
                rid = f"{base}~{ident_of(r)}~{n}"
            taken.add(rid)
            out.append((rid, r))
    return out


def keyed(rows: list[dict], held: dict | None = None) -> list[tuple[str, dict]]:
    return assign_ids([safe_row(r) for r in rows], held or {})


def take(state: dict, years: list[int], rows: list[dict], now: str) -> dict:
    """Merge one read of the given years into the state (rows kept only as safe_row gives them); returns counts."""
    held = state.setdefault("rows", {})
    got = dict(keyed(rows, held))
    counts = Counter()
    for rid, r in got.items():
        h = row_hash(r)
        prev = held.get(rid)
        if prev is None:
            held[rid] = {"row": r, "hash": h, "ident": ident(r), "first_seen_at": now, "last_seen_at": now}
            counts["new"] += 1
        else:
            if prev.get("hash") != h:
                prev.update(row=r, hash=h, ident=ident(r), revised_at=now)
                counts["revised"] += 1
            else:
                counts["same"] += 1
            prev["last_seen_at"] = now
            prev.pop("missing_since", None)
    for rid, h in held.items():
        if int(rid[:4]) in years and rid not in got and not h.get("missing_since"):
            h["missing_since"] = now
            counts["missing"] += 1
    for y in years:
        state.setdefault("years_read", {})[str(y)] = now
    return counts


def to_record(rid: str, h: dict) -> dict:
    r = safe_row(h["row"])
    c = clock(r["time"]) if r.get("time") else None
    d = date.fromisoformat(r["date"])
    st = datetime(d.year, d.month, d.day, *(c or (0, 0)), tzinfo=TZ)
    lat, lon, _ = point(r.get("maplink") or "")
    why = r.get("point_withheld")
    ww = " ".join((r.get("waterway") or "").split())
    m = IDN.match(ww)
    water, gnis = (m.group(1).strip(), m.group(2)) if m else (ww or None, None)
    raw = {"state": "AL", "county": "Jefferson", "time_zone": TZ_NAME, "location": r.get("location") or None,
           "city": r.get("city") or None, "zip": r.get("zip") or None,
           "affected_waterway_as_written": ww or None, "gnis_id": gnis,
           "reason": r.get("reason") or None, "status_as_written": r.get("status") or None,
           "date_resolved": r.get("date_resolved") or None,
           "date_resolved_note": ("the table's \"Date Resolved\", the date the county marked the advisory resolved; "
                                  "the page does not say it is the end of the overflow, so it is not used as one"),
           "time_note": ("the export's Date and Time, local wall-clock with no zone; Jefferson County is on Central time"
                         if c else "the export gives a date and no time: the record is dated to the day"),
           "_placement": "named_water_only",
           "operator_permits": PERMITS,
           "_first_seen_at": h.get("first_seen_at"), "_last_seen_in_source": h.get("last_seen_at")}
    ds = " ".join((r.get("downstream_of") or "").split())
    if ds and ds.upper() not in ("N/A", "NA", "NONE"):
        raw["downstream_of"] = ds
    if water and water.strip().upper() == "NONE":
        water = None
        raw["reached_water"] = False
        raw["_no_water_reason"] = "the county's advisory gives the affected waterway as NONE"
    if why:
        raw["_point_withheld"] = why
    if h.get("missing_since"):
        raw["_missing_from_source_since"] = h["missing_since"]
    return event(
        source_id=SOURCE_ID, source_record_id=rid, event_type="sso", status="unknown",
        discharger_id=DISCHARGER_ID, discharger_name=DISCHARGER, npdes_permit=None,
        waterbody_text=water, lat=lat, lon=lon, coord_source="source" if lat is not None else None,
        coord_precision_m=100 if lat is not None else None,
        started_at=st.isoformat(), ended_at=None, time_precision="minute" if c else "day",
        reported_at=None, published_at=None, source_updated_at=None, fetched_at=h.get("last_seen_at") or now_iso(),
        material="untreated sewage", volume_gal=None, volume_text=None, estimate_flag="unknown",
        authority=AUTHORITY, advice_text=None, source_url=URL, raw=raw)


def _metres(a: dict, b: dict) -> float | None:
    if None in (a.get("lat"), a.get("lon"), b.get("lat"), b.get("lon")):
        return None
    la1, lo1, la2, lo2 = map(math.radians, (a["lat"], a["lon"], b["lat"], b["lon"]))
    x = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371000 * 2 * math.asin(math.sqrt(x))


def _local_day(v) -> date | None:
    try:
        t = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return (t.replace(tzinfo=UTC) if t.tzinfo is None else t).astimezone(TZ).date()


def link_adem(records: list[dict], adem: list[dict]) -> Counter:
    """Mark each county record duplicate_of ADEM's report of the same overflow (module docstring); returns counts.
    Not when the two name different waters, nor when ADEM's report names no water reached (its flag, its words, or a
    placeholder) and the county names one (build/status.py's own tests: review 2026-11-17 P1-4)."""
    from build import status as S          # here, not at the top: the status build's tests of a water and of none
    by_day: dict[date, list[dict]] = {}
    for a in adem:
        if a.get("npdes_permit") not in PERMITS or a.get("duplicate_of"):
            continue
        d = _local_day(a.get("started_at"))
        if d:
            by_day.setdefault(d, []).append(a)
    pairs = []
    for r in records:
        d = _local_day(r["started_at"])
        for a in by_day.get(d, []):
            m = _metres(r, a)
            if m is not None and m <= LINK_M:
                pairs.append((m, r["event_id"], a["event_id"]))
    pairs.sort()
    by_id = {r["event_id"]: r for r in records}
    adem_by = {a["event_id"]: a for a in adem}
    used, counts = set(), Counter()
    for m, rid, aid in pairs:
        r, a = by_id[rid], adem_by[aid]
        if r.get("duplicate_of") or aid in used:
            continue
        if S.waters_differ(r, a):
            counts["not linked: the two name different waters"] += 1
            continue
        a_dry = bool(S.no_water_flag(a) or S.reached_no_water(a) or S.no_receiving_water(a))
        if a_dry and r.get("waterbody_text"):
            counts["not linked: ADEM's report names no water reached, the county names one"] += 1
            continue
        r["duplicate_of"] = aid
        r["raw"]["_duplicate_basis"] = (f"ADEM's report {aid.split(':', 1)[-1]} of permit {a.get('npdes_permit')} "
                                        f"began the same day, {round(m)} m from the county's point")
        used.add(aid)
        counts["linked"] += 1
    return counts


def build(state: dict, adem: list[dict] | None = None) -> tuple[list[dict], Counter]:
    recs = [to_record(rid, h) for rid, h in (state.get("rows") or {}).items()]
    links = link_adem(recs, adem if adem is not None else (read_json(ADEM_EVENTS, {}) or {}).get("records") or [])
    recs.sort(key=lambda r: (r["started_at"], r["event_id"]), reverse=True)
    return recs, links


# ---------------------------------------------------------------- fetching

def _session():
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def run(now: str, state_path: Path = STATE_PATH, out: Path | None = None, sess=None, backfill: bool = False,
        since: str = BACKFILL_FROM, today: date | None = None, sleep=time.sleep, adem: list[dict] | None = None,
        save: bool = True) -> int:
    """One run (module docstring); returns the exit code. sess has get(url) and post(url, data=...)."""
    sess = sess or _session()
    today = today or datetime.now(TZ).date()
    try:
        r = sess.get(URL, timeout=(20, 90))
        r.raise_for_status()
        page = r.text
        fields = form_fields(page)
    except (requests.RequestException, ReadError) as e:
        write_events(SOURCE_ID, [], ok=False, error=f"page: {error_text(e)}"[:300], path=out)
        print(f"{SOURCE_ID}: FAILED {error_detail(e)}", file=sys.stderr)
        return 1
    offered = year_options(page)
    if backfill:
        years = [y for y in offered if y >= int(since[:4])] or [today.year]
    else:
        years = [today.year] + ([today.year - 1] if today.month == 1 else [])
    state = read_json(state_path, {}) or {}
    counts, not_read, bad_all, read_any = Counter(), {}, [], False
    for i, y in enumerate(years):
        if i:
            sleep(PAUSE_S)
        data = {**fields, "ddlYear": str(y), "ddlMonth": "", "ddlCity": " ", "ddlWaterway": "",
                "btnExport": "Download as CSV file"}
        try:
            resp = sess.post(URL, data=data, timeout=(20, 120))
            resp.raise_for_status()
            if "csv" not in (resp.headers.get("content-type") or "").lower():
                raise ReadError(f"the export answered {resp.headers.get('content-type')!r}, not CSV")
            rows, bad = parse_csv(resp.content.decode("utf-8-sig", "replace"))
            if bad and not rows:
                raise ReadError(f"all {len(bad)} rows do not fit the known columns")
            wrong = [x for x in rows if not x["date"].startswith(str(y))]
            if wrong:
                raise ReadError(f"the export for {y} holds {len(wrong)} rows of other years")
        except (requests.RequestException, ReadError) as e:
            not_read[str(y)] = f"{error_text(e)}"[:200]
            continue
        read_any = True
        bad_all += bad
        counts.update(take(state, [y], rows, now))
    state["last_read"] = {"at": now, "years": years, "listed_on_page": record_count(page), **counts}
    if read_any:
        write_json(state_path, state)
    recs, links = build(state, adem)
    meta = {"registry_ids": [SOURCE_ID], "url": URL, "credit": AUTHORITY, "time_zone": TZ_NAME,
            "records_on_page": record_count(page), "years_read": years, "rows_not_read": bad_all,
            "adem_links": dict(links), "covers_operator": DISCHARGER_ID}
    if bad_all:
        # rows that do not line up: the others are kept, the read is partial (health false) and the rows are named
        # by date only (review 2026-11-17 P2-8)
        not_read["rows"] = f"{len(bad_all)} rows do not fit the known columns: " + ", ".join(bad_all[:10])
    if not_read:
        meta["years_not_read"] = {k: v for k, v in not_read.items() if k != "rows"}
        err = "export not read: " + "; ".join(f"{y}: {w}" for y, w in not_read.items())
        if not read_any:
            write_events(SOURCE_ID, [], ok=False, error=err, meta=meta, path=out)
            print(f"{SOURCE_ID}: FAILED {err}", file=sys.stderr)
            return 1
        write_events(SOURCE_ID, recs, ok=False, partial=True, error=err, meta=meta, path=out)
        print(f"{SOURCE_ID}: PARTIAL {len(recs)} records; {err}", file=sys.stderr)
        return 0 if backfill else 1
    path = write_events(SOURCE_ID, recs, meta=meta, path=out)
    print(f"{SOURCE_ID}: {len(recs)} records ({dict(counts)}; ADEM links {dict(links)}) -> {path}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", action="store_true", help="read every year the page offers from --from")
    ap.add_argument("--from", dest="since", default=BACKFILL_FROM)
    ap.add_argument("--csv", help="a saved export, read in place of the live one (needs --out)")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    if a.csv and not a.out:
        ap.error("--csv needs --out")
    out = Path(a.out) if a.out else None
    state_path = out.with_suffix(".state.json") if out else STATE_PATH
    if a.csv:
        text = Path(a.csv).read_text(encoding="utf-8-sig")
        rows, bad = parse_csv(text)
        state = read_json(state_path, {}) or {}
        years = sorted({int(r["date"][:4]) for r in rows})
        for y in years:
            take(state, [y], [r for r in rows if r["date"].startswith(str(y))], now_iso())
        write_json(state_path, state)
        recs, links = build(state)
        write_events(SOURCE_ID, recs, meta={"registry_ids": [SOURCE_ID], "url": URL, "rows_not_read": bad,
                                            "adem_links": dict(links)}, path=out)
        print(f"{SOURCE_ID}: {len(recs)} records from {a.csv}; {len(bad)} rows not read; ADEM links {dict(links)}")
        return 0
    return run(now_iso(), state_path, out, backfill=a.backfill, since=a.since)


if __name__ == "__main__":
    sys.exit(main())
