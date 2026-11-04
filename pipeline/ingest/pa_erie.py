"""City of Erie Bureau of Sewers CSO monitoring (Great Lakes CSO notice) -> data/build/events/pa-erie.json.

Source: https://telog.erie.pa.us/CSO.Monitoring/ (site by Process and Data Automation, LLC; Telog
meters; no key, no licence stated). Erie (PA0026301) is the one Pennsylvania permittee under the
federal Great Lakes rule, 40 CFR 122.38 (public notice of CSO discharges to the Great Lakes Basin).
- Report: GET /CSO.Monitoring/Report?startDate=M/D/YYYY 12:00:00 AM&endDate=M/D/YYYY 12:00:00 AM
  returns a server-rendered table: CSO Site (meter id), Date Event Started, Date Event Ended,
  Discharge (Gallons). Any date range works; the end date is midnight at the start of that day, so
  the request runs to tomorrow. Records split at every flow gap (many short rows per storm).
- Map: GET /CSO.Monitoring/Map embeds one marker per monitored CSO: lat, lng, title (= the meter
  id), location ("CSO 003 - Front Stre"), status Active/Inactive, NPDES number, receiving stream
  ("Mill Creek Tube"), affected body of water ("Lake Erie").

Record rules:
- One cso record per table row: source_record_id = meter id + start minute; status ended when the
  row has an end, else ongoing. outfall_id from the map's location ("CSO 003" -> "003"), coordinates
  from the map marker (coord_source source).
- "Discharge (Gallons)": values run from 0.00004 to 306 for storms that elsewhere make millions of
  gallons, so the unit is unconfirmed (perhaps millions of gallons). volume_text keeps the value with
  the column label, volume_gal is null, raw.volume_note says why.
- Times carry no zone: read as America/New_York (an ambiguous fall-back hour is read as the first).
- water_slugs: the map's affected water "Lake Erie" and receiving stream "Mill Creek" by name
  (water_match "name"). Mill Creek (piped through the Mill Creek Tube) has no openboatlaunch record,
  so the slug is Lake Erie's only; waterbody_text keeps both names.
- advice_window null: the City posts no advice period (the Great Lakes rule sets none).
- The default run asks for the last 30 days; `--backfill` from 2025-01-01. Records are merged with
  the previous file, so a short window never drops older rows. Raw report and map pages are saved
  when their parsed content changes.

Run from pipeline/: python -m ingest.pa_erie [--backfill] [--days N]
Cadence: hourly (the map is real time; the report has no lag that we know of).
"""
from __future__ import annotations

import argparse
import hashlib
import html as htmllib
import json
import re
import sys
from collections import Counter
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests

from common import EVENTS_DIR, HEADERS, event, read_json, save_raw, write_events
from ingest import pa_waters

SOURCE_ID = "pa-erie"
BASE = "https://telog.erie.pa.us/CSO.Monitoring"
REPORT_URL = f"{BASE}/Report"
MAP_URL = f"{BASE}/Map"
TZ = ZoneInfo("America/New_York")
DEFAULT_DAYS = 30
BACKFILL_FROM = date(2025, 1, 1)
DISCHARGER = {"discharger_id": "pa-erie", "discharger_name": "City of Erie Bureau of Sewers",
              "npdes_permit": "PA0026301"}
AUTHORITY = "City of Erie CSO monitoring report (Great Lakes rule 40 CFR 122.38)"
VOLUME_NOTE = ("The column is labelled 'Discharge (Gallons)', but values run from 0.00004 to about 306 per "
               "event; the unit is unconfirmed (it may be millions of gallons), so no gallon figure is given.")
TZ_NOTE = "The report states no time zone; times are read as America/New_York."
ERIE = (-80.0774, 42.1262)


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", s or "")).replace("\xa0", " ")).strip()


def parse_report(html: str) -> list[dict]:
    i = html.find('id="reportCreated"')
    block = html[i:] if i >= 0 else html
    t = re.search(r"<table[^>]*>(.*?)</table>", block, re.S)
    if not t:
        return []
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", t.group(1), re.S)
    out, head = [], None
    for r in rows:
        cells = [_clean(c) for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", r, re.S)]
        if not cells:
            continue
        if re.search(r"<th", r):
            head = cells
            continue
        if head and len(cells) == len(head):
            out.append(dict(zip(head, cells)))
        else:
            out.append({"_cells": cells})
    return out


def parse_map(html: str) -> dict:
    """meter id -> marker {lat, lng, title, location, status, npdesNumber, receivingStream, affectedBodyOfWater}."""
    out = {}
    for m in re.finditer(r"addLeafletCsoMarker\(\{(.*?)\}\);", html, re.S):
        body = m.group(1)
        f = {k: v for k, v in re.findall(r"(\w+):\s*'([^']*)'", body)}
        for k, v in re.findall(r"(lat|lng):\s*(-?[\d.]+)", body):
            f[k] = float(v)
        site = (f.get("title") or "").strip()
        if site:
            out[site] = f
    return out


def parse_time(s: str | None) -> datetime | None:
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %I:%M %p", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=TZ)
        except ValueError:
            pass
    raise ValueError(f"unreadable time {s!r}")


def outfall_of(location: str | None) -> str | None:
    m = re.match(r"\s*CSO\s*0*(\d+)", location or "", re.I)
    return f"{int(m.group(1)):03d}" if m else None


def waters_for(marker: dict) -> tuple[list[str], str, dict]:
    names = [n for n in (marker.get("affectedBodyOfWater"), re.sub(r"\s+Tube$", "", marker.get("receivingStream") or "")) if n]
    names = names or ["Lake Erie", "Mill Creek"]
    pt = (marker["lng"], marker["lat"]) if marker.get("lat") is not None else ERIE
    slugs, missing = [], []
    for n in names:
        s = pa_waters.named(n, pt)
        if s is None:
            missing.append(n)
        elif s not in slugs:
            slugs.append(s)
    return slugs, "name" if slugs else "none", {"names": names, "without_water_record": missing}


def to_record(row: dict, markers: dict, url: str) -> dict:
    site = (row.get("CSO Site") or "").strip()
    mk = markers.get(site) or {}
    problems = []
    try:
        start = parse_time(row.get("Date Event Started"))
        end = parse_time(row.get("Date Event Ended"))
    except ValueError as e:
        start = end = None
        problems.append(str(e))
    if start is None and not problems:
        problems.append("no start time")
    if start and end and end < start:
        problems.append("end before start")
    rid = f"{site or 'nosite'}-{start:%Y%m%dT%H%M}" if start else \
        f"{site or 'nosite'}-unparsed-{hashlib.sha1(json.dumps(row, sort_keys=True).encode()).hexdigest()[:10]}"
    slugs, how, wnote = waters_for(mk)
    vol = (row.get("Discharge (Gallons)") or "").strip()
    stream = mk.get("receivingStream") or "Mill Creek Tube"
    affected = mk.get("affectedBodyOfWater") or "Lake Erie"
    return event(
        source_id=SOURCE_ID, source_record_id=rid,
        event_type="unknown" if problems and start is None else "cso",
        status=("ended" if end else "ongoing") if start else "unknown", **DISCHARGER,
        outfall_id=outfall_of(mk.get("location")), outfall_name=(mk.get("location") or "").strip() or None,
        waterbody_text=f"{stream} to {affected}", water_slugs=slugs, water_match=how,
        lat=mk.get("lat"), lon=mk.get("lng"), coord_source="source" if mk.get("lat") is not None else None,
        started_at=start.isoformat() if start else None, ended_at=end.isoformat() if end else None,
        time_precision="minute",
        material=None, volume_gal=None,
        volume_text=f"{vol} (column 'Discharge (Gallons)'; unit unconfirmed)" if vol else None,
        estimate_flag="unknown", authority=AUTHORITY, advice_text=None, advice_window_hours=None,
        advice_window_basis=None, source_url=url,
        raw={"row": row, "meter_id": site, "map_marker": {k: v for k, v in mk.items() if k != "icon"} or None,
             "volume_note": VOLUME_NOTE, "timezone_note": TZ_NOTE, "water_placement": wnote},
        parse_error="; ".join(problems) if problems else None,
    )


def report_url(d0: date, d1: date) -> tuple[str, dict]:
    fmt = lambda d: f"{d.month}/{d.day}/{d.year} 12:00:00 AM"
    return REPORT_URL, {"startDate": fmt(d0), "endDate": fmt(d1)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", action="store_true", help="from 2025-01-01")
    ap.add_argument("--days", type=int, default=DEFAULT_DAYS)
    args = ap.parse_args(argv)
    today = datetime.now(TZ).date()
    d0 = BACKFILL_FROM if args.backfill else today - timedelta(days=args.days)
    d1 = today + timedelta(days=1)
    sess = requests.Session()
    sess.headers.update(HEADERS)
    prev = read_json(EVENTS_DIR / f"{SOURCE_ID}.json", {}) or {}
    map_err = None
    try:
        r = sess.get(MAP_URL, timeout=60)
        r.raise_for_status()
        markers = parse_map(r.text)
        if not markers:
            raise ValueError("no markers on the map page")
        if (prev.get("meta") or {}).get("markers") != markers:
            save_raw(SOURCE_ID, r.text, "map.html")
    except Exception as e:
        map_err = f"map: {e}"
        markers = (prev.get("meta") or {}).get("markers") or {}
    url, params = report_url(d0, d1)
    try:
        r = sess.get(url, params=params, timeout=120)
        r.raise_for_status()
        rows = parse_report(r.text)
        if "reportCreated" not in r.text:
            raise ValueError("report table missing (layout changed?)")
    except Exception as e:
        write_events(SOURCE_ID, [], ok=False, error=f"report: {e}")
        print(f"pa-erie: FAILED {e}", file=sys.stderr)
        return 1
    full_url = r.url
    sig = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
    if (prev.get("meta") or {}).get("last_report_hash") != sig:
        save_raw(SOURCE_ID, r.text, f"report-{d0:%Y%m%d}-{d1:%Y%m%d}.html")
    fresh = [to_record(row, markers, full_url) for row in rows if "_cells" not in row]
    odd = [row for row in rows if "_cells" in row]
    for row in odd:
        fresh.append(event(source_id=SOURCE_ID, source_record_id="odd-" + hashlib.sha1(json.dumps(row).encode()).hexdigest()[:10],
                           event_type="unknown", **DISCHARGER, authority=AUTHORITY, source_url=full_url, raw={"row": row},
                           parse_error="table row with an unexpected number of cells"))
    ids = Counter(x["event_id"] for x in fresh)
    seen = Counter()
    for x in fresh:   # two rows with one meter and start minute: keep both
        if ids[x["event_id"]] > 1:
            seen[x["event_id"]] += 1
            x["event_id"] += f"-{seen[x['event_id']]}"
            x["source_record_id"] = x["event_id"].split(":", 1)[1]
    by_id = {x["event_id"]: x for x in prev.get("records", [])}
    window_from = datetime(d0.year, d0.month, d0.day, tzinfo=TZ).isoformat()
    for x in prev.get("records", []):   # older rows outside this window stay; rows inside it are replaced
        if (x.get("started_at") or "") >= window_from:
            by_id.pop(x["event_id"], None)
    by_id.update({x["event_id"]: x for x in fresh})
    records = sorted(by_id.values(), key=lambda x: x["started_at"] or "", reverse=True)
    meta = {"window": [d0.isoformat(), d1.isoformat()], "rows_in_window": len(rows), "odd_rows": len(odd),
            "records_total": len(records), "markers": markers, "map_error": map_err, "last_report_hash": sig,
            "volume_note": VOLUME_NOTE, "timezone_note": TZ_NOTE,
            "rows_by_meter": dict(Counter((row.get("CSO Site") or "").strip() for row in rows)),
            "covers_permits": [DISCHARGER["npdes_permit"]], "statewide": False}
    path = write_events(SOURCE_ID, records, ok=True, error=map_err, meta=meta)
    c = Counter((x["event_type"], x["status"]) for x in records)
    print(f"pa-erie: {len(rows)} rows {d0}..{d1}; {len(records)} records {dict(c)} -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
