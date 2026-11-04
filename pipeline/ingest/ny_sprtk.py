"""DEC Sewage Pollution Right to Know workbook (New York) -> data/build/events/ny-dec-sprtk.json

Source
  NYS DEC posts its export of NY-Alert sewage discharge notices as an Excel workbook,
  https://www.dec.ny.gov/fs/data/SPRTK_Data.xlsx ("Updated NY-Alerts from January 2021 through
  current", linked from the SPRTK page). Every notice a POTW or sewer system files under ECL
  17-0826-a / 6 NYCRR 750-2.7 is a row: a "New" notice, zero or more "Update" notices (daily for an
  ongoing discharge, or running totals) and a "Close" notice with the final duration and volume.
  The host (extapps.dec.ny.gov, where www.dec.ny.gov 301s) often does not answer; the Internet
  Archive keeps captures, so the module tries DEC first and then the latest archive.org capture
  (`web/<now>id_/...`), and records which copy it read (`meta.workbook`). DEC's caveats: "Data
  quality is not checked by DEC"; "Multiple notifications may be entered for the same discharge".
  Credit: "NYS DEC Sewage Pollution Right to Know (NY-Alert notices)". No licence stated.

Quirks (research/ny/report.md 2.4, and what this module found)
  - 27 tabs, one per month or batch, with five header layouts; every header variant is mapped to
    one set of names (FIELD_ALIASES). One tab ("May _website") is a copy of the DEC web page
    with no notification ids: its rows are kept only where no id-bearing notice has the same
    facility, address and start (meta.website_rows).
  - Tabs overlap: the same notificationId appears in several tabs. One notice per id; the row from
    the latest tab wins and the other tabs are listed in raw._tabs (with the fields that differ).
  - Times are UTC (checked against the alert text: 17:37 in the workbook = 13:37 EDT). They are
    converted to America/New_York and labelled (raw._time_basis). Tabs before April 2024 give dates
    only (time_precision "day": the UTC date, which can be a day after the local date late in the
    evening); two tabs carry Excel serial dates; one transposes name and id.
  - latitude holds longitude and vice versa in most rows; coordinates are checked against New
    York's bounding box and swapped (or given their missing minus sign) only when that puts them in
    the state (raw._coords). The NYC citywide CSO notice (NYCDEPCSO) carries a placeholder
    geocode: no coordinates. Geocodes are street-address points chosen by the notifier.
  - Chains: incidentId links the notices of one incident in the tabs up to March 2025; later tabs
    dropped it, so notices are chained by facility + address + start (minute). Notices are records
    of their own (plan §3: one object per source record); within a chain each notice's
    parent_event_id is the notice before it, so the chain's latest notice is its one live record
    and status (build/status.py resolve_revisions) uses it. raw._chain names the chain, the basis
    and every notice in it.
  - Status: a Close notice, or a duration that says "- Ended", is ended (ended_at = the notice's
    end time); "- Ongoing" is ongoing and the end time is NY-Alert's required projection, kept in
    raw._projected_end only. Anything else is unknown.
  - Volumes: "60,000 Gallons Estimated", "381 Gallons per Minute Estimated", "10,000 Gallons
    Actual". A first (New) notice's volume is usually a placeholder (DEC's notifier manual: an
    estimate is required up front): estimate_flag "estimated" with the text kept; rates keep the
    text with volume_gal null; "Actual" is measured.
  - Water: outfall id (csoOutfallDescription, filled on a few % of notices) joined to the ECHO CSO
    inventory in data/outfalls-mid-atlantic.json (permit + outfall number), then the receiving water
    by name within New York (ingest/ny_waters.py), gated by the notice's geocode.
  - advice_text is the notice's own text (additional instructions / impacted area); New York sets
    no post-discharge window, so advice_window_hours stays null.
  - Personal fields: none by column, but free text carries phone numbers and emails (scrubbed by
    common.strip_personal before anything is written; the cached workbook stays in data/raw).

Cadence
  The workbook is a batch export with 1-2 month lag and gaps (December 2025 is missing). Daily is
  plenty. The download is cached (data/build/ny-sprtk-workbook.json says which copy and when); a
  copy younger than --max-age hours (default 20) is reused. The default run writes the chains with
  a notice aired in the last --since days (default 365; older tabs are read only to complete
  those chains) and keeps every record of earlier runs; --backfill writes every chain in every tab.
  The near-live notices come from ingest/ny_sprtk_web.py (the DEC page), which dedupes against
  this file.

Usage (from pipeline/):  python -m ingest.ny_sprtk [--since DAYS] [--backfill] [--refetch] [--file PATH]
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from common import (BUILD_DIR, DATA_DIR, EVENTS_DIR, HEADERS, event, now_iso, parse_volume_gal,
                    path_notes_to_meta, read_json, save_raw, write_events, write_json)
from ingest import ny_waters

SOURCE_ID = "ny-dec-sprtk"
DEC_URLS = ["https://www.dec.ny.gov/fs/data/SPRTK_Data.xlsx", "https://extapps.dec.ny.gov/fs/data/SPRTK_Data.xlsx"]
ARCHIVE_URL = "https://web.archive.org/web/{ts}id_/https://extapps.dec.ny.gov/fs/data/SPRTK_Data.xlsx"
PAGE_URL = "https://dec.ny.gov/environmental-protection/water/water-quality/sewage-pollution-right-to-know"
SOURCE_URL = DEC_URLS[0]
CACHE_META = BUILD_DIR / "ny-sprtk-workbook.json"
ECHO_OUTFALLS = DATA_DIR / "outfalls-mid-atlantic.json"
DISCHARGERS = DATA_DIR / "dischargers.json"
TZ = ZoneInfo("America/New_York")
EXCEL_EPOCH = datetime(1899, 12, 30)

# A start later than this after the record was fetched is a typing error in the source (ny-dec-sprtk:2310900174603285,
# aired 2026-01-02, starts 2026-12-30): kept as written and noted; the status build gives it no status
# (build/status.py FUTURE_START_H, the same limit)
FUTURE_START_H = 24

AUTHORITY_SUFFIX = "(NY DEC Sewage Pollution Right to Know)"
TIME_BASIS = ("DEC's workbook gives times in UTC (checked against NY-Alert text: 17:37 in the workbook = 13:37 EDT); "
              "converted here to America/New_York")
DAY_BASIS = ("this tab gives the date only (no time of day); the date is DEC's (UTC) date and is shown as that day "
             "in New York time, so a late-evening local start can carry the next day's date")
PLACEHOLDER_NOTE = ("first (New) notice: NY-Alert requires a volume and an end time up front, so this figure is "
                    "the notifier's estimate or placeholder, not a measured total")

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
RNS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"

# header (lowercased, non-alphanumerics removed) -> canonical field
FIELD_ALIASES = {
    "notificationid": "notificationId", "incidentid": "incidentId",
    "notifcationsentdate": "airDateTime", "notificationsentdate": "airDateTime", "notificationsentdte": "airDateTime",
    "createddate": "airDateTime", "sprtkairdatetime": "airDateTime",
    "notificationstatus": "notificationStatus",
    "notificationlastmodifieddate": "lastModified", "lastmodifieddate": "lastModified",
    "potwpossname": "facilityName", "facilityname": "facilityName",
    "potwpossid": "facilityId", "facilityid": "facilityId", "sprtkid": "facilityId",
    "dischargestartdate": "startDateTime", "startdate": "startDateTime", "sprtkstartdischargedatetime": "startDateTime",
    "starttime": "startDateTime",
    "dischargeenddate": "endDateTime", "enddate": "endDateTime", "sprtkenddischargedatetime": "endDateTime",
    "duration": "duration", "dischargeduration": "duration",
    "streetnumber": "streetNumber", "streetname": "streetName", "sprtkstreetname": "streetName", "address": "streetName",
    "city": "city", "addressdescription": "addressDescription", "locationdescription": "addressDescription",
    "receivingwaterbody": "receivingWaterBody", "affectedwaterbody": "receivingWaterBody",
    "quantityvolume": "quantity", "quantity": "quantity",
    "treatedstate": "treatedState", "dischargedescription": "dischargeDescription",
    "impactedarea": "impactedArea", "reason": "dischargeReason", "dischargereason": "dischargeReason",
    "reasonsfordischarge": "dischargeReason",
    "stepstocontain": "stepsToContain",
    "additionalinformation": "additionalInstructions", "additionalinstructions": "additionalInstructions",
    "potentialtoreachsurfacewater": "surfaceWater", "surfacewater": "surfaceWater",
    "dischargewaterconveyance": "dischargeWaterFlow", "dischargewaterflow": "dischargeWaterFlow",
    "sprtkdischargewaterflow": "dischargeWaterFlow",
    "systemcomponent": "systemComponent", "componentdescription": "componentDescription",
    "csooutfalldescription": "csoOutfallDescription",
    "latitude": "latitude", "longitude": "longitude", "geoaddress": "geoaddress",
    "county": "countyName", "countyname": "countyName", "region": "region",
    "sprtktemplatename": "templateName", "sprtkimpactareadesc": "impactAreaDesc", "sprtkexplanation": "explanation",
    "sprtkadditionalinstructions": "sprtkAdditionalInstructions", "sprtkwebsiteurl": "websiteUrl",
    "fivedayreportrecievedindsetdate": "fiveDayReportDate", "headline": "headline", "units": "durationUnits",
    "estimatedindicator": "estimatedIndicator", "reasondescription": "reasonDescription",
}
FACILITY_ID_RE = re.compile(r"^(NY\d{7}|NYS\d{6}|NYCDEPCSO|[A-Z]{2,}[A-Z0-9]{3,12})$")
FACILITY_ID_IN_NAME = re.compile(r"\b(NY\d{7}|NYS\d{6})\b")
STATUS_RANK = {"New": 0, "Update": 1, "Close": 2}


# ---------------------------------------------------------------- xlsx (stdlib reader)

def _col(ref: str) -> int:
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group(0):
        n = n * 26 + ord(ch) - 64
    return n - 1


def _shared_strings(z: zipfile.ZipFile) -> list[str]:
    out = []
    if "xl/sharedStrings.xml" not in z.namelist():
        return out
    with z.open("xl/sharedStrings.xml") as f:
        for _ev, el in ET.iterparse(f, events=("end",)):
            if el.tag == NS + "si":
                out.append("".join(t.text or "" for t in el.iter(NS + "t")))
                el.clear()
    return out


def _sheets(z: zipfile.ZipFile) -> list[tuple[str, str]]:
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
    out = []
    for s in wb.iter(NS + "sheet"):
        t = rels[s.get(RNS + "id")].lstrip("/")
        out.append((s.get("name"), t if t.startswith("xl/") else "xl/" + t))
    return out


def _rows(z: zipfile.ZipFile, path: str, ss: list[str]):
    with z.open(path) as f:
        for _ev, el in ET.iterparse(f, events=("end",)):
            if el.tag != NS + "row":
                continue
            vals = {}
            for c in el.iter(NS + "c"):
                t, v = c.get("t"), c.find(NS + "v")
                if t == "s" and v is not None:
                    val = ss[int(v.text)]
                elif t == "inlineStr":
                    val = "".join(x.text or "" for x in c.iter(NS + "t"))
                else:
                    val = v.text if v is not None else None
                if val is not None and str(val).strip() != "":
                    vals[_col(c.get("r"))] = str(val)
            el.clear()
            if vals:
                yield [vals.get(i) for i in range(max(vals) + 1)]


def read_workbook(content: bytes) -> list[dict]:
    """[{tab, columns, rows: [{header: value}]}] for every tab, in workbook order."""
    z = zipfile.ZipFile(io.BytesIO(content))
    ss = _shared_strings(z)
    tabs = []
    for name, path in _sheets(z):
        it = _rows(z, path, ss)
        hdr = next(it, None) or []
        cols = [(h.strip() if h else f"col{i + 1}") for i, h in enumerate(hdr)]
        rows = []
        for r in it:
            d = {}
            for i, v in enumerate(r):
                if v is None:
                    continue
                d[cols[i] if i < len(cols) else f"col{i + 1}"] = v.strip() if isinstance(v, str) else v
            if d:
                rows.append(d)
        tabs.append({"tab": name, "columns": cols, "rows": rows})
    return tabs


# ---------------------------------------------------------------- times

# The workbook's clock is not one clock (found by comparing the same chain across tabs and the
# daily filing time of Warwick SD #1, which files around 21:45 local every evening):
#  - rows aired from late May 2025 on (MM/DD/YYYY hh:mm:ss): UTC, as the research checked;
#  - earlier rows in MM/DD/YYYY or ISO form (April-July 2024, April-May 2025): New York local time;
#  - rows in DD/MON/YYYY form (August 2024-March 2025, and the April-June 2023 tab): local time
#    shifted back once more by the UTC offset (17:11 EDT appears as 13:11; 21:45 EST as 16:45), so
#    local = shown + 4 h (EDT) or + 5 h (EST);
#  - date-only tabs (2021 to March 2024) and whole Excel serials: the date only, most likely the
#    local date (the stored clock was local before May 2025, inferred).
CUTOVER = datetime(2025, 5, 24)          # first day read as UTC (local before; switch seen 23-24 May 2025)
CUTOVER_FUZZ = timedelta(days=1)
BASIS_TEXT = {
    "utc": "UTC in the workbook (rows aired from late May 2025); converted to America/New_York",
    "local": ("New York local time in the workbook (rows aired before late May 2025 are local, found by "
              "comparing tabs); read as America/New_York"),
    "dmon_shifted": ("DD/MON rows hold local time shifted back by the UTC offset (found by comparing tabs: 17:11 EDT "
                     "is shown as 13:11); read as shown + 4 h (EDT) or 5 h (EST), America/New_York"),
    "local_serial": "Excel serial time on the DEC web-page copy tab; read as America/New_York (inferred)",
    "date": ("date only in this tab; most likely the local date (the stored clock was local before May 2025, "
             "inferred)"),
}


def parse_dt(v) -> tuple[datetime | date | None, str | None]:
    """A workbook time -> (naive datetime or date, format family); (None, None) when absent.
    Families: iso_date, iso_dt, mdy, dmon, serial_date, serial_dt. Raises ValueError otherwise."""
    if v is None:
        return None, None
    s = " ".join(str(v).split())
    if not s or s.lower() in ("null", "none", "n/a"):
        return None, None
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{1,2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?)?", s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if m.group(4) is None:
            return date(y, mo, d), "iso_date"
        return datetime(y, mo, d, int(m.group(4)), int(m.group(5)), int(m.group(6) or 0)), "iso_dt"
    for fmt, fam in (("%m/%d/%Y %H:%M:%S", "mdy"), ("%m/%d/%Y %H:%M", "mdy"),
                     ("%d/%b/%Y %H:%M:%S", "dmon"), ("%d/%b/%Y %H:%M", "dmon")):
        try:
            return datetime.strptime(s.title() if fam == "dmon" else s, fmt), fam
        except ValueError:
            pass
    for fmt, fam in (("%m/%d/%Y", "iso_date"), ("%d/%b/%Y", "iso_date")):
        try:
            return datetime.strptime(s.title() if "%b" in fmt else s, fmt).date(), fam
        except ValueError:
            pass
    if re.fullmatch(r"\d{5}(\.\d+)?", s):
        f = float(s)
        if 30000 < f < 60000:
            dt = EXCEL_EPOCH + timedelta(days=f)
            if f == int(f):
                return dt.date(), "serial_date"
            return (dt + timedelta(seconds=30)).replace(second=0, microsecond=0), "serial_dt"
    raise ValueError(f"time {s!r} not understood")


def row_era(air, family: str | None) -> tuple[str | None, bool]:
    """(clock of the row's date-times, near the cutover?) from the row's air time."""
    if family == "dmon":
        return "dmon_shifted", False
    if family == "serial_dt":
        return "local_serial", False
    if family in ("mdy", "iso_dt") and isinstance(air, datetime):
        return ("utc" if air >= CUTOVER else "local"), abs(air - CUTOVER) <= CUTOVER_FUZZ
    return None, False


def resolve(v, family: str | None, era: str | None) -> tuple[datetime | date | None, str | None, str | None]:
    """Naive workbook value -> (aware UTC datetime, "minute", basis) or (date, "day", "date")."""
    if v is None:
        return None, None, None
    if not isinstance(v, datetime):
        return v, "day", "date"
    basis = {"dmon": "dmon_shifted", "serial_dt": "local_serial"}.get(family) or era or (
        "utc" if v >= CUTOVER else "local")
    if basis == "utc":
        return v.replace(tzinfo=UTC), "minute", basis
    if basis == "dmon_shifted":
        for h in (4, 5):
            cand = (v + timedelta(hours=h)).replace(tzinfo=TZ)
            if cand.utcoffset() == timedelta(hours=-h):
                return cand.astimezone(UTC), "minute", basis
        return (v + timedelta(hours=5)).replace(tzinfo=TZ).astimezone(UTC), "minute", basis
    return v.replace(tzinfo=TZ).astimezone(UTC), "minute", basis


def local_iso(v: datetime | date | None) -> str | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.astimezone(TZ).isoformat(timespec="seconds")
    return datetime(v.year, v.month, v.day, tzinfo=TZ).isoformat(timespec="seconds")


def future_start_note(start: datetime | date | None, fetched_at: str | None) -> str | None:
    """The note for a start more than FUTURE_START_H hours after the fetch time ("start is in the future as
    published"), else None. The date itself is never changed."""
    st = as_utc(start)
    try:
        now = datetime.fromisoformat(str(fetched_at).replace("Z", "+00:00"))
    except ValueError:
        return None
    if st is None or now.tzinfo is None or st <= now + timedelta(hours=FUTURE_START_H):
        return None
    return (f"start is in the future as published: {local_iso(start)} is more than {FUTURE_START_H} hours after the "
            f"record was fetched ({fetched_at}); kept as written")


def as_utc(v: datetime | date | None) -> datetime | None:
    """For ordering and windows: a date counts as its local midnight."""
    if v is None:
        return None
    if isinstance(v, datetime):
        return v
    return datetime(v.year, v.month, v.day, tzinfo=TZ).astimezone(UTC)


# ---------------------------------------------------------------- notices

def canonical(row: dict) -> tuple[dict, dict]:
    """(fields under canonical names, original columns that have no canonical name)."""
    out, extra = {}, {}
    for k, v in row.items():
        key = FIELD_ALIASES.get(re.sub(r"[^a-z0-9]", "", k.lower()))
        if key and key not in out:
            out[key] = v
        elif key:
            extra[k] = v
        else:
            extra[k] = v
    return out, extra


def norm_text(s) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", str(s or "").lower())).strip()


def facility_of(f: dict) -> tuple[str | None, str | None, str | None]:
    """(facility id, facility name, problem). Fixes the tab that transposes name and id and the rows
    whose id column holds a long number (a notification id)."""
    fid, name = (f.get("facilityId") or "").strip() or None, (f.get("facilityName") or "").strip() or None
    problem = None
    if fid and name and not FACILITY_ID_RE.match(fid) and FACILITY_ID_RE.match(name):
        fid, name, problem = name, fid, "facility name and id columns transposed in this tab; swapped back"
    if fid and not FACILITY_ID_RE.match(fid):
        m = FACILITY_ID_IN_NAME.search(name or "")
        problem = f"facility id column holds {fid!r}" + ("; id taken from the facility name" if m else "")
        fid = m.group(1) if m else None
    if not fid and name:
        m = FACILITY_ID_IN_NAME.search(name)
        fid = m.group(1) if m else None
    return fid, name, problem


def address_key(f: dict) -> str:
    return norm_text(" ".join(str(f.get(k) or "") for k in ("streetNumber", "streetName", "city")))


def coords(f: dict, facility_id: str | None) -> tuple[float | None, float | None, str]:
    """(lat, lon, note). The workbook mostly stores longitude in 'latitude' and vice versa."""
    if facility_id == "NYCDEPCSO":
        return None, None, "the citywide NYC DEP notice carries a placeholder geocode: not used"
    a, b = f.get("latitude"), f.get("longitude")
    try:
        la, lo = float(a), float(b)
    except (TypeError, ValueError):
        return None, None, ("no geocode" if a in (None, "") and b in (None, "") else f"geocode {a!r},{b!r} not numeric")
    if la == 0 or lo == 0:
        return None, None, f"geocode {a},{b}: zero, not used"
    dec = [len(str(x).split(".")[1]) if "." in str(x) else 0 for x in (a, b)]
    if min(dec) < 2:
        return None, None, f"geocode {a},{b} has fewer than two decimals: too coarse, not used"
    for lat, lon, how in ((la, lo, "as given"), (lo, la, "latitude and longitude columns swapped"),
                          (la, -lo, "longitude given its missing minus sign"),
                          (lo, -la, "columns swapped and longitude given its missing minus sign")):
        if ny_waters.in_ny(lon, lat):
            return round(lat, 6), round(lon, 6), how
    return None, None, f"geocode {a},{b} is outside New York in every column order: not used"


def duration_state(text) -> str | None:
    t = str(text or "").lower()
    if re.search(r"-\s*ended\s*$", t):
        return "ended"
    if re.search(r"-\s*ongoing\s*$", t):
        return "ongoing"
    return None


QTY_RE = re.compile(r"^\s*(?P<num>[\d,]*\.?\d+)?\s*(?P<unit>.*?)\s*(?P<flag>Estimated|Actual)?\s*$", re.I)


def volume_of(text, status: str) -> tuple[int | None, str | None, str, str | None]:
    """(gallons, text, estimate_flag, note). 'Gallons per Minute' and other rates keep the text."""
    if text in (None, ""):
        return None, None, "unknown", None
    s = " ".join(str(text).split())
    flag_word = re.search(r"\b(estimated|actual)\b", s, re.I)
    flag = {"estimated": "estimated", "actual": "measured"}.get(flag_word.group(1).lower()) if flag_word else None
    low = s.lower()
    note = None
    if re.search(r"per\s+(minute|hour|day|second)|/\s*(min|hr|day)\b|\bgpm\b|\bmgd\b|\bgpd\b", low):
        note = "a rate, not a volume"
        if status == "New":
            return None, s, "estimated", f"{note}; {PLACEHOLDER_NOTE}"
        return None, s, flag or "unknown", note
    m = re.match(r"^\s*([\d,]*\.?\d+)\s*(million gallons|million|mil gallons|m gallons|mgal|mg|gallons?|gal)?\b", low)
    gal = None
    if m and not re.search(r"\d\s*(-|to)\s*\d", low) and not re.match(r"^\s*[<>~]", low):
        n = float(m.group(1).replace(",", ""))
        unit = m.group(2) or ""
        gal = int(round(n * 1_000_000)) if unit.startswith(("mg", "mil", "m ")) else int(round(n))
        if not unit and not re.search(r"gallon", low):
            note = "no unit given; read as gallons"
    else:
        gal, est = parse_volume_gal(s)
        flag = flag or est
    if status == "New":
        flag = "estimated"
        note = "; ".join(x for x in (note, PLACEHOLDER_NOTE) if x)
    return gal, s, flag or "unknown", note


def classify(f: dict, cso_permits: set[str] | None = None, permit: str | None = None) -> tuple[str, str]:
    """(event_type, basis). NY-Alert has no type field: the system component, treated state, the
    notifier's words and the facility name decide; the basis is kept in raw._event_type_basis."""
    def txt(*keys):
        return " ".join(str(f.get(k) or "") for k in keys).lower()
    comp = txt("systemComponent", "componentDescription", "csoOutfallDescription")
    words = txt("templateName", "explanation", "dischargeReason", "dischargeDescription", "addressDescription")
    fac = txt("facilityName")
    treated = txt("treatedState")
    if re.search(r"\bcsos?\b|combined sewer", comp) or f.get("csoOutfallDescription") and re.search(r"cso|outfall", comp):
        return "cso", "a CSO outfall named in the system component"
    if re.search(r"\bcsos?\b|combined sewer|city wide cso", words + " " + fac):
        return "cso", "CSO named in the notice text or the facility name"
    if re.search(r"\bblend", words + " " + comp):
        return "blended", "blending named in the notice text"
    if "partial" in treated:
        return "bypass", "partially treated discharge (treated state)"
    collection = r"manhole|pump station|lift station|force main|sewer main|collection|regulator|\bpipe\b|overflow retention|\borf\b|sanitary sewer|\bsso\b"
    if re.search(collection, comp):
        return "sso", "untreated discharge from a collection-system component"
    if re.search(r"\bposs\b|sanitary sewer|sanitary sd|\bssos?\b|\borf\b|sewer district|sewers\b|pump sta", fac):
        return "sso", "untreated discharge; the notifier is a sewer system (facility name)"
    plant = r"treatment|plant|filter|headworks|\bsbr\b|clarifier|digester|\bwwtp\b|\bwpcp\b|\bstp\b|\bwwtf\b|\bwrrf\b"
    wet = re.search(r"rain|storm|snow|thaw|wet weather|high flow", words)
    if permit and cso_permits and permit in cso_permits and wet and not re.search(plant, comp):
        return "cso", ("inferred: untreated wet-weather discharge from a CSO permittee, no component given "
                       "(could also be a sanitary overflow or plant bypass)")
    if re.search(plant, comp + " " + words):
        return "plant_bypass", "untreated discharge at the treatment plant (component or notice text)"
    return "unknown", "the notice does not say what kind of discharge this is"


def synthetic_id(f: dict) -> str:
    """A stable id for rows without a notificationId (two 2022-23 tabs and the web-page tab): the
    incident id when there is one, plus a hash of the notice's own fields."""
    keys = ("facilityId", "facilityName", "incidentId", "notificationStatus", "airDateTime", "startDateTime",
            "endDateTime", "duration", "quantity", "streetNumber", "streetName", "receivingWaterBody")
    h = hashlib.sha1(json.dumps([str(f.get(k) or "") for k in keys]).encode()).hexdigest()[:12]
    inc = str(f.get("incidentId") or "").strip()
    return f"i{inc}-{h}" if inc.isdigit() else f"r{h}"


def notices_from(tabs: list[dict]) -> tuple[list[dict], list[dict], Counter]:
    """(notices one per id, the web-page tab's rows, counts). The row from the latest tab wins;
    the other tabs it appeared in are kept in other_tabs with the fields that differ."""
    by_id: dict[str, dict] = {}
    website: list[dict] = []
    stats = Counter()
    for t_i, tab in enumerate(tabs):
        is_web = "website" in tab["tab"].lower()
        for r_i, row in enumerate(tab["rows"]):
            f, extra = canonical(row)
            stats["rows"] += 1
            nid = str(f.get("notificationId") or "").strip()
            synthetic = not re.fullmatch(r"\d{6,}", nid)
            if synthetic:
                nid = synthetic_id(f)
                stats["synthetic_ids"] += 1
            n = {"id": nid, "synthetic_id": synthetic, "tab": tab["tab"], "tab_index": t_i, "row": r_i + 2,
                 "f": f, "row_raw": row, "website": is_web}
            if is_web:
                website.append(n)
                continue
            prev = by_id.get(nid)
            if prev:
                stats["duplicate_rows"] += 1
                differ = sorted(k for k in set(prev["f"]) | set(f) if str(prev["f"].get(k) or "") != str(f.get(k) or ""))
                n["other_tabs"] = prev.get("other_tabs", []) + [
                    {"tab": prev["tab"], "row": prev["row"], "differs": differ or None}]
            by_id[nid] = n
    return list(by_id.values()), website, stats


def parse_notice(n: dict) -> dict:
    """Times (with their clock), status, facility and address key of one notice -> n["p"]."""
    f, problems = n["f"], []
    raw_vals = {}
    for key in ("airDateTime", "startDateTime", "endDateTime", "lastModified"):
        try:
            raw_vals[key] = parse_dt(f.get(key))
        except ValueError as e:
            raw_vals[key] = (None, None)
            problems.append(f"{key}: {e}")
    era, near = row_era(*raw_vals["airDateTime"])
    p = {"problems": problems, "near_cutover": near, "basis": {}}
    for key, short in (("airDateTime", "air"), ("startDateTime", "start"), ("endDateTime", "end"),
                       ("lastModified", "modified")):
        v, fam = raw_vals[key]
        val, prec, basis = resolve(v, fam, era)
        if n["tab"] == "April-June23" and basis == "dmon_shifted":
            p["basis_unverified"] = True   # same export format as the 2024-25 tab; the shift is inferred, not checked
        p[short], p[short + "_prec"] = val, prec
        if basis:
            p["basis"][short] = basis
    st = str(f.get("notificationStatus") or "").strip().title() or None
    if st and st not in STATUS_RANK:
        problems.append(f"notificationStatus {st!r} not recognised")
    p["status"] = st if st in STATUS_RANK else None
    p["facility_id"], p["facility_name"], fprob = facility_of(f)
    if fprob:
        p["facility_problem"] = fprob
    p["address_key"] = address_key(f)
    n["p"] = p
    return p


# ---------------------------------------------------------------- chains

def chain_key(n: dict) -> str | None:
    p = n["p"]
    fac = p["facility_id"] or norm_text(p["facility_name"])
    st = p["start"]
    if st is None or not fac:
        return None
    stk = st.strftime("%Y-%m-%dT%H:%MZ") if isinstance(st, datetime) else st.isoformat()
    return f"{fac}|{p['address_key']}|{stk}"


def sort_key(n: dict):
    p = n["p"]
    t = as_utc(p["air"]) or as_utc(p["start"]) or datetime(1900, 1, 1, tzinfo=UTC)
    return (t, STATUS_RANK.get(p["status"], 1), len(n["id"]), n["id"])


def build_chains(notices: list[dict]) -> dict[str, list[dict]]:
    """chain id -> notices in order. incidentId first; then facility + address + start (minute), which
    also joins a later notice to an incidentId chain with the same key."""
    chains: dict[str, list[dict]] = {}
    key_to_chain: dict[str, str] = {}
    for n in notices:
        inc = str(n["f"].get("incidentId") or "").strip()
        if inc.isdigit():
            cid = f"incident:{inc}"
            chains.setdefault(cid, []).append(n)
            n["chain_basis"] = "incidentId"
            k = chain_key(n)
            if k:
                key_to_chain.setdefault(k, cid)
    for n in sorted((n for n in notices if "chain_basis" not in n), key=sort_key):
        k = chain_key(n)
        if k is None:
            cid, basis = f"single:{n['id']}", "no facility or start time: a chain of its own"
        elif k in key_to_chain:
            cid = key_to_chain[k]
            basis = ("facility + address + start, joined to an incidentId chain" if cid.startswith("incident:")
                     else "facility + address + start")
        else:
            cid, basis = f"key:{k}", "facility + address + start"
            key_to_chain[k] = cid
        chains.setdefault(cid, []).append(n)
        n["chain_basis"] = basis
    for lst in chains.values():
        lst.sort(key=sort_key)
    merge_edited_starts(chains)
    return chains


def merge_edited_starts(chains: dict[str, list[dict]], max_hours: float = 48) -> int:
    """A key-based chain that does not open with a New notice is usually the rest of a chain whose
    start the notifier edited (Washingtonville moved its start by weeks; Auburn and Onondaga by
    minutes). Join it to the open chain at the same facility and address whose New notice came
    first and whose start is nearest, within max_hours; otherwise it stays on its own."""
    by_place: dict[tuple, list[str]] = {}
    for cid, lst in chains.items():
        p = lst[0]["p"]
        by_place.setdefault((p["facility_id"] or norm_text(p["facility_name"]), p["address_key"]), []).append(cid)
    merged = 0
    for cid in sorted(chains, key=lambda c: sort_key(chains[c][0])):
        lst = chains.get(cid)
        if not lst or not cid.startswith("key:") or lst[0]["p"]["status"] == "New" or lst[0]["p"]["start"] is None:
            continue
        head = lst[0]
        hp = head["p"]
        best = None
        for other in by_place.get((hp["facility_id"] or norm_text(hp["facility_name"]), hp["address_key"]), []):
            ol = chains.get(other)
            if other == cid or not ol or ol[0]["p"]["status"] != "New" or ol[0]["p"]["start"] is None:
                continue
            if sort_key(ol[0]) > sort_key(head):
                continue
            if any(x["p"]["status"] == "Close" and sort_key(x) < sort_key(head) for x in ol):
                continue
            dh = abs((as_utc(hp["start"]) - as_utc(ol[0]["p"]["start"])).total_seconds()) / 3600
            if dh <= max_hours and (best is None or dh < best[0]):
                best = (dh, other)
        if best:
            for x in lst:
                x["chain_basis"] = (f"facility + address; the start was edited by {best[0]:.2f} h after the New notice "
                                    "(joined to the open chain at the same place)")
            chains[best[1]].extend(lst)
            chains[best[1]].sort(key=sort_key)
            del chains[cid]
            merged += 1
    return merged


# ---------------------------------------------------------------- reference data and water

OUTFALL_NUM = re.compile(r"\b(?:cso|outfall|of|regulator)\s*(?:no\.?|number|#)?\s*0*(\d{1,3})([a-z])?\b", re.I)
JUNK_WATER = re.compile(r"^(none|n/?a|na|unknown|tbd|-|\.|please see dep.*|see dep.*|no|not applicable)$", re.I)


def load_echo() -> dict:
    idx = {}
    for o in (read_json(ECHO_OUTFALLS, {}) or {}).get("outfalls", []):
        if o.get("state") == "NY":
            idx[(o["npdes_permit"], str(o["outfall"]).upper())] = o
    return idx


def load_dischargers() -> tuple[dict, set[str]]:
    """(permit or POSS id -> discharger id, CSO permits) from data/dischargers.json."""
    out, cso = {}, set()
    for d in read_json(DISCHARGERS, []) or []:
        if d.get("state") != "NY" and not str(d.get("id", "")).startswith(("ny-", "nyc-")):
            continue
        for p in [d.get("npdes_permit")] + list(d.get("npdes_permits") or []):
            for m in re.finditer(r"\b(NY\d{7}|NYS\d{6})\b", str(p or "")):
                out.setdefault(m.group(1), d["id"])
                if d.get("kind") == "cso":
                    cso.add(m.group(1))
    for o in (read_json(ECHO_OUTFALLS, {}) or {}).get("outfalls", []):
        if o.get("state") == "NY" and o.get("outfall_status") == "CSO":
            cso.add(o["npdes_permit"])
    return out, cso


def outfall_numbers(*texts) -> set[str]:
    nums = set()
    for t in texts:
        s = str(t or "").strip()
        if not s:
            continue
        if re.fullmatch(r"0*\d{1,3}[A-Za-z]?", s):
            m = re.fullmatch(r"0*(\d{1,3})([A-Za-z]?)", s)
            nums.add(f"{int(m.group(1)):03d}{m.group(2).upper()}")
            continue
        for m in OUTFALL_NUM.finditer(s):
            nums.add(f"{int(m.group(1)):03d}" + (m.group(2) or "").upper())
    return nums


def clean_water(text) -> str | None:
    s = " ".join(str(text or "").split()).strip(" .,;")
    return None if not s or JUNK_WATER.match(s) else s


def name_words(s) -> set[str]:
    return {w for w in norm_text(s).split() if len(w) > 3 and w not in
            ("river", "creek", "brook", "lake", "harbor", "channel", "canal", "kill", "upper", "lower")}


def place(ctx: dict, permit: str | None, outfalls: set[str], water: str | None, city: str | None,
          lat, lon, surface: str | None) -> dict:
    """{slugs, match, outfall, echo, note} for one notice (cached on its inputs)."""
    key = (permit, tuple(sorted(outfalls)), water, city, lat, lon, surface)
    hit = ctx["place_cache"].get(key)
    if hit is not None:
        return hit
    out = {"slugs": [], "match": "none", "echo": None, "note": {}}
    if str(surface or "").strip().lower() == "no":
        out["note"]["why_none"] = "the notifier says the discharge does not reach surface water"
        ctx["place_cache"][key] = out
        return out
    if permit and len(outfalls) == 1:
        o = next(iter(outfalls))
        e = ctx["echo"].get((permit, o)) or ctx["echo"].get((permit, o + "A"))
        if e:
            out["echo"] = e
            em = e.get("match")
            agree = bool(name_words(water) & name_words(e.get("water_name"))) if water else False
            if e.get("water_slug") and (em in ("geometry+name", "name_only") or (em == "geometry" and agree)):
                out.update(slugs=[e["water_slug"]], match="outfall_registry")
                out["note"].update(via="ECHO CSO inventory (outfalls-mid-atlantic)", echo_outfall=e["outfall"],
                                   echo_match=em, echo_receiving_water=e.get("receiving_water_echo"))
                ctx["place_cache"][key] = out
                return out
            out["note"]["echo_candidate"] = {"outfall": e["outfall"], "slug": e.get("water_slug"), "match": em,
                                             "receiving_water": e.get("receiving_water_echo"),
                                             "why_not": "no slug" if not e.get("water_slug") else "geometry only and the names differ"}
    if water:
        point = (lon, lat) if lat is not None and lon is not None else None
        slugs, notes = ny_waters.match_waters(water, [city] if city else [], point)
        if slugs:
            out.update(slugs=slugs, match="name")
            out["note"]["via"] = "receiving water name within New York" + (" (checked against the geocode)" if point else "")
        if notes:
            out["note"]["name_notes"] = notes
    ctx["place_cache"][key] = out
    return out


# ---------------------------------------------------------------- records

def clean_name(name: str | None) -> str | None:
    if not name:
        return None
    s = re.sub(r"[,\s]*\b(NY\d{7}|NYS\d{6})\b\.?", "", name)
    return " ".join(s.split()).strip(" ,.-") or name


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")


def first(f: dict, *keys):
    for k in keys:
        v = f.get(k)
        if v not in (None, "") and str(v).strip() not in ("-", "None", "null"):
            return " ".join(str(v).split())
    return None


def to_record(n: dict, chain_id: str, chain: list[dict], pos: int, parent: str | None, ctx: dict) -> dict:
    f, p = n["f"], n["p"]
    base = dict(source_id=SOURCE_ID, source_record_id=n["id"], parent_event_id=parent,
                fetched_at=ctx["fetched_at"], source_url=SOURCE_URL)
    raw = {"row": n["row_raw"], "_tab": n["tab"], "_row": n["row"]}
    try:
        return build_record(n, f, p, chain_id, chain, pos, base, raw, ctx)
    except Exception as e:  # noqa: BLE001 - never drop a record
        return event(**base, event_type="unknown", status="unknown", raw=raw, parse_error=f"{type(e).__name__}: {e}")


def build_record(n, f, p, chain_id, chain, pos, base, raw, ctx) -> dict:
    problems = list(p["problems"])
    if n.get("other_tabs"):
        raw["_other_tabs"] = n["other_tabs"]
    if n["synthetic_id"]:
        raw["_id_note"] = "this tab has no notificationId; the record id is built from the incident id and the row's fields"
    raw["_time_basis"] = {k: BASIS_TEXT.get(v, v) for k, v in p["basis"].items()}
    if p["near_cutover"]:
        raw["_time_basis_uncertain"] = "aired within a day of the switch from local time to UTC (2025-05-23/24)"
    if p.get("basis_unverified"):
        raw["_time_basis_unverified"] = "the DD/MON shift is established for the 2024-25 tab and assumed for this tab"
    if p.get("facility_problem"):
        raw["_facility_note"] = p["facility_problem"]

    status_word = p["status"]
    dstate = duration_state(f.get("duration"))
    if status_word == "Close":
        status = "ended"
    elif dstate in ("ended", "ongoing"):
        status = dstate
    else:
        status = "unknown"
    start, end = p["start"], p["end"]
    ended_at = None
    if status == "ended" and end is not None:
        if start is not None and as_utc(end) < as_utc(start):
            raw["_end_before_start"] = local_iso(end)
            problems.append("end time before start time (NY-Alert allows negative durations): ended_at left empty")
        else:
            ended_at = local_iso(end)
    elif end is not None:
        raw["_projected_end"] = local_iso(end)
        raw["_projected_end_note"] = ("NY-Alert requires an expected end time on every notice; this one is a projection, "
                                      "not a reported end")
    prec = p["start_prec"] or p["air_prec"]
    future = future_start_note(start, base["fetched_at"])
    if future:
        raw["_dww_note"] = [future]

    fid, fname = p["facility_id"], clean_name(p["facility_name"])
    permit = fid if fid and re.fullmatch(r"NY\d{7}", fid) else None
    lat, lon, cnote = coords(f, fid)
    raw["_coords"] = cnote + ("; a street-address geocode chosen by the notifier" if lat is not None else "")

    etype, raw["_event_type_basis"] = classify(f, ctx["cso_permits"], permit)
    water = clean_water(f.get("receivingWaterBody"))
    outs = outfall_numbers(f.get("csoOutfallDescription"), f.get("componentDescription"))
    pl = place(ctx, permit, outs, water, first(f, "city"), lat, lon, f.get("surfaceWater"))
    if pl["note"]:
        raw["_water"] = pl["note"]
    outfall_id = next(iter(outs)) if len(outs) == 1 else None
    coord_source = "source" if lat is not None else None
    e = pl.get("echo")
    if e and pl["match"] == "outfall_registry" and e.get("lat") is not None:
        raw["_coords_notice"] = {"lat": lat, "lon": lon, "note": cnote}
        lat, lon, coord_source = e["lat"], e["lon"], "outfall_layer"
        raw["_coords"] = f"EPA ECHO CSO inventory {e['npdes_permit']} outfall {e['outfall']}"

    gal, vtext, est, vnote = volume_of(f.get("quantity"), status_word)
    if vnote:
        raw["_volume_note"] = vnote
    advice = first(f, "additionalInstructions", "sprtkAdditionalInstructions")

    head, last = chain[0], chain[-1]
    ch = {"id": chain_id, "basis": n.get("chain_basis"), "position": pos + 1, "of": len(chain),
          "head": f"{SOURCE_ID}:{head['id']}", "latest": f"{SOURCE_ID}:{last['id']}"}
    if n is last:
        ch["notices"] = [{"id": x["id"], "status": x["p"]["status"], "aired": local_iso(x["p"]["air"])} for x in chain]
    if head["p"]["status"] != "New":
        ch["head_missing"] = "the chain's first notice in the workbook is not a New notice (earlier notices missing)"
    raw["_chain"] = ch

    return event(
        **base, event_type=etype, status=status,
        discharger_id=ctx["dischargers"].get(fid) or (f"ny-{slugify(fname)}" if fname else None),
        discharger_name=fname, npdes_permit=permit,
        outfall_id=outfall_id,
        outfall_name=first(f, "csoOutfallDescription", "componentDescription", "addressDescription"),
        waterbody_text=water, water_slugs=pl["slugs"], water_match=pl["match"],
        lat=lat, lon=lon, coord_source=coord_source, coord_precision_m=None,
        started_at=local_iso(start), ended_at=ended_at, time_precision=prec,
        reported_at=local_iso(p["air"]), published_at=local_iso(p["air"]),
        source_updated_at=local_iso(p["modified"]),
        material=first(f, "treatedState"), volume_gal=gal, volume_text=vtext, estimate_flag=est,
        authority=f"{fname or 'Unnamed facility'} {AUTHORITY_SUFFIX}",
        advice_text=advice, advice_window_hours=None, advice_window_basis=None,
        raw=raw, parse_error="; ".join(problems) or None,
    )


# ---------------------------------------------------------------- fetch

def _is_xlsx(content: bytes) -> bool:
    return content[:2] == b"PK" and len(content) > 100_000


def fetch_workbook(sess: requests.Session, refetch: bool, max_age_h: float, file_path: str | None) -> tuple[bytes, dict]:
    """The workbook bytes and where they came from. DEC first, then the latest archive.org capture;
    a copy younger than max_age_h is reused; on failure the last copy is used (noted)."""
    cache = read_json(CACHE_META, {}) or {}
    cached_file = (DATA_DIR.parent / cache["raw_path"]) if cache.get("raw_path") else None
    if file_path:
        content, info = Path(file_path).read_bytes(), {"via": "file", "url": None, "file": Path(file_path).name}
    elif (not refetch and cached_file and cached_file.exists() and cache.get("fetched_at") and
          datetime.now(UTC) - datetime.fromisoformat(cache["fetched_at"].replace("Z", "+00:00")) < timedelta(hours=max_age_h)):
        return cached_file.read_bytes(), {**cache, "used_cache": True}
    else:
        content, info, errors = None, {}, []
        for url in DEC_URLS:
            try:
                r = sess.get(url, timeout=(15, 180))
                r.raise_for_status()
                if not _is_xlsx(r.content):
                    raise ValueError(f"not an xlsx ({len(r.content)} bytes, {r.headers.get('content-type')})")
                content, info = r.content, {"via": "dec", "url": r.url, "last_modified": r.headers.get("Last-Modified")}
                break
            except Exception as e:  # noqa: BLE001
                errors.append(f"{url}: {type(e).__name__}: {str(e)[:160]}")
        if content is None:
            url = ARCHIVE_URL.format(ts=datetime.now(UTC).strftime("%Y%m%d%H%M%S"))
            for attempt in range(3):
                try:
                    r = sess.get(url, timeout=(20, 300))
                    if r.status_code == 429:
                        raise requests.HTTPError("429 Too Many Requests")
                    r.raise_for_status()
                    if not _is_xlsx(r.content):
                        raise ValueError(f"not an xlsx ({len(r.content)} bytes)")
                    cap = re.search(r"/web/(\d{14})", r.url)
                    content = r.content
                    info = {"via": "archive.org", "url": r.url,
                            "capture": datetime.strptime(cap.group(1), "%Y%m%d%H%M%S").replace(tzinfo=UTC).isoformat().replace("+00:00", "Z") if cap else None,
                            "last_modified": r.headers.get("x-archive-orig-last-modified"),
                            "dec_errors": errors}
                    break
                except Exception as e:  # noqa: BLE001
                    errors.append(f"archive.org: {type(e).__name__}: {str(e)[:160]}")
                    time.sleep(10 * (attempt + 1))
        if content is None:
            if cached_file and cached_file.exists():
                return cached_file.read_bytes(), {**cache, "used_cache": True, "stale": True, "errors": errors}
            raise RuntimeError("; ".join(errors))
    sha = hashlib.sha256(content).hexdigest()
    if sha != cache.get("sha256") or not (cached_file and cached_file.exists()):
        path = save_raw(SOURCE_ID, content, "xlsx")
        raw_path = str(path.relative_to(DATA_DIR.parent))
        changed = True
    else:
        raw_path, changed = cache["raw_path"], False
    meta = {**info, "fetched_at": now_iso(), "sha256": sha, "bytes": len(content), "raw_path": raw_path,
            "changed_since_last_fetch": changed,
            "first_seen_at": cache.get("first_seen_at") if not changed else now_iso()}
    write_json(CACHE_META, meta)
    return content, meta


# ---------------------------------------------------------------- main

def website_duplicates(website: list[dict], notices: list[dict]) -> tuple[list[dict], int]:
    """The web-page tab copies notices that also have ids: drop a row when an id-bearing notice has
    the same facility and start date (New York time)."""
    seen = set()
    for n in notices:
        p = n["p"]
        if p["start"] is not None and p["facility_id"]:
            d = as_utc(p["start"]).astimezone(TZ).date() if isinstance(p["start"], datetime) else p["start"]
            seen.add((p["facility_id"], d))
    keep, dropped = [], 0
    for n in website:
        p = parse_notice(n)
        d = None
        if p["start"] is not None:
            d = as_utc(p["start"]).astimezone(TZ).date() if isinstance(p["start"], datetime) else p["start"]
        if (p["facility_id"], d) in seen:
            dropped += 1
        else:
            keep.append(n)
    return keep, dropped


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--since", type=int, default=365, help="write chains with a notice aired in the last DAYS (default 365)")
    ap.add_argument("--backfill", action="store_true", help="write every chain in every tab")
    ap.add_argument("--refetch", action="store_true", help="download even if the cached copy is fresh")
    ap.add_argument("--max-age", type=float, default=20, help="hours a downloaded copy is reused (default 20)")
    ap.add_argument("--file", help="read this workbook instead of downloading")
    args = ap.parse_args(argv)

    sess = requests.Session()
    sess.headers.update(HEADERS)
    try:
        content, wb = fetch_workbook(sess, args.refetch, args.max_age, args.file)
        tabs = read_workbook(content)
    except Exception as e:  # noqa: BLE001
        write_events(SOURCE_ID, [], ok=False, error=f"{type(e).__name__}: {e}")
        print(f"ny-dec-sprtk: FAILED {e}", file=sys.stderr)
        return 1

    notices, website, stats = notices_from(tabs)
    for n in notices:
        parse_notice(n)
    web_keep, web_dropped = website_duplicates(website, notices)
    all_notices = notices + web_keep
    chains = build_chains(all_notices)

    now = datetime.now(UTC)
    cutoff = now - timedelta(days=args.since)
    dmap, cso_permits = load_dischargers()
    ctx = {"echo": load_echo(), "dischargers": dmap, "cso_permits": cso_permits, "place_cache": {},
           "fetched_at": wb.get("fetched_at") or now_iso()}
    records = []
    written_chains = Counter()
    for cid, chain in chains.items():
        latest = max((as_utc(x["p"]["air"]) or as_utc(x["p"]["start"]) for x in chain if (x["p"]["air"] or x["p"]["start"])),
                     default=None)
        if not args.backfill and (latest is None or latest < cutoff):
            continue
        parent = None
        for i, n in enumerate(chain):
            rec = to_record(n, cid, chain, i, parent, ctx)
            records.append(rec)
            parent = rec["event_id"]
        written_chains[records[-1]["status"]] += 1

    # keep every record of earlier runs that this run did not rewrite (older than the window, or
    # gone from the workbook): the events file is the history seen so far
    prev = read_json(EVENTS_DIR / f"{SOURCE_ID}.json", {}) or {}
    new_ids = {r["event_id"] for r in records}
    all_ids = {f"{SOURCE_ID}:{n['id']}" for n in all_notices}
    kept = 0
    for r in prev.get("records", []):
        if r["event_id"] in new_ids:
            continue
        if r["event_id"] not in all_ids:
            r.setdefault("raw", {})["_missing_from_workbook_since"] = r["raw"].get("_missing_from_workbook_since") or now_iso()
        records.append(r)
        kept += 1
    records.sort(key=lambda r: (r.get("published_at") or r.get("started_at") or ""), reverse=True)

    latest_recs = [r for r in records if (r["raw"].get("_chain") or {}).get("latest") == r["event_id"]]
    meta = {
        "workbook": {k: wb.get(k) for k in ("via", "url", "capture", "last_modified", "fetched_at", "sha256", "bytes",
                                            "raw_path", "used_cache", "stale", "errors", "dec_errors", "file")
                     if wb.get(k) is not None},
        "tabs": [{"tab": t["tab"], "rows": len(t["rows"])} for t in tabs],
        "rows": stats["rows"], "notices": len(notices), "duplicate_rows": stats["duplicate_rows"],
        "synthetic_ids": stats["synthetic_ids"], "website_rows": {"rows": len(website), "kept": len(web_keep),
                                                                    "dropped_as_copies": web_dropped},
        "chains_total": len(chains), "window_days": None if args.backfill else args.since, "backfill": args.backfill,
        "chains_written": sum(written_chains.values()), "chains_written_by_latest_status": dict(written_chains),
        "records_written": len(new_ids), "records_kept_from_earlier_runs": kept,
        "latest_notices_by_type": dict(Counter(r["event_type"] for r in latest_recs)),
        "latest_notices_water_match": dict(Counter(r["water_match"] for r in latest_recs)),
        "records_water_match": dict(Counter(r["water_match"] for r in records)),
        "time_basis": dict(Counter(b for n in all_notices for b in n["p"]["basis"].values())),
        "time_note": ("The workbook's clock changed: UTC from late May 2025, New York local time before, and the "
                      "DD/MON-formatted tabs shifted back by the UTC offset; each record's raw._time_basis says how "
                      "its times were read."),
        "credit": "NYS DEC Sewage Pollution Right to Know (NY-Alert notices), SPRTK_Data.xlsx",
        "caveat": "Data quality is not checked by DEC (SPRTK page).",
    }
    path_notes_to_meta(records, meta)
    path = write_events(SOURCE_ID, records, ok=True, error=None, meta=meta)
    print(f"ny-dec-sprtk: {len(notices)} notices in {len(tabs)} tabs ({wb.get('via')}"
          f"{', cached' if wb.get('used_cache') else ''}); {meta['chains_written']} chains / {len(new_ids)} records "
          f"written, {kept} kept from earlier runs; latest-notice water match {meta['latest_notices_water_match']} -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
