"""Florida Department of Health Healthy Beaches: per-sample beach advisories -> data/build/events/fl-doh-beaches.json

Source
  Florida Department of Health, Florida Healthy Beaches Program (registry row fl-doh-healthy-beaches). Weekly or
  fortnightly enterococcus sampling at about 350 active coastal sampling points.
  - The points: ArcGIS layer https://services1.arcgis.com/CY1LXxl9zlJeBuRZ/arcgis/rest/services/
    FloridaBeachSamplingPoints/FeatureServer/0 (County, EPAbeachID, STORET_Sta, SPLocation, Active, SPLat, SPLong,
    Link). Only Active = Yes points are read.
  - The results: each point's Link opens the beach-detail page on floridahealth.gov, which embeds a Caspio data page
    (https://c0cqk120.caspio.com/dp/cb8a100027f4e6ea6cbc4260a71e) that takes the same query string (County,
    SPLocation, SPNo, SPLat, SPLong) and returns the point's samples, newest first, ten to a page: sample period ID,
    location, sample date, the enterococcus result (CFU/100 mL, sometimes blank) and "Advisory: Yes|No". The first
    page is read (about the last five months of samples); older samples stay from earlier runs.
  No licence is stated; credit "Florida Department of Health, Florida Healthy Beaches Program". The pages carry no
  personal data. One request every half second; a full pass (about 350 points) runs at most once every 20 hours
  (data/build/fl-doh-beaches-state.json), unless --force.

Records (beach_advisory; a beach record, never a sewage record)
  Per sampling point, in date order: a sample with Advisory Yes opens an advisory (or continues the open one); the next
  sample with Advisory No ends it: advisory_lifted, ended_at = that sample's date (day precision). One still open is
  advisory_active, source_updated_at = the date of its latest Advisory Yes sample (the status build stops colouring it
  14 days after). started_at is the sample date of the first Advisory Yes result (DOH issues the advisory when the
  laboratory result is known, usually one to three days after sampling: raw.start_basis). DOH's own advisory text and
  signs are not on the page: advice_text is null.
  event_id = fl-doh-beaches:<EPA beach id or county-location>:<sample period ID of the opening sample>.
  waterbody_text = the sampling location as DOH names it (a beach or street end); water_slugs stay empty until
  Florida's water records are built. Coordinates: the point's SPLat/SPLong.

Cadence: daily (results are posted within days of each weekly or fortnightly sample).
Run from pipeline/:  python -m ingest.fl_doh_beaches [--force] [--limit N] [--file saved.json]
  --file reads {"points": [point attributes ...], "pages": {"<County>|<SPLocation>": "<html>"}} instead of fetching.
"""
from __future__ import annotations

import argparse
import html as htmllib
import json
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit
from zoneinfo import ZoneInfo

import requests

from common import (BROWSER_HEADERS, BUILD_DIR, EVENTS_DIR, HEADERS, event, now_iso, read_json, write_events,
                    write_json)

SOURCE_ID = "fl-doh-beaches"
POINTS = ("https://services1.arcgis.com/CY1LXxl9zlJeBuRZ/arcgis/rest/services/FloridaBeachSamplingPoints/"
          "FeatureServer/0")
CASPIO = "https://c0cqk120.caspio.com/dp/cb8a100027f4e6ea6cbc4260a71e"
PAGE_URL = ("https://www.floridahealth.gov/community-environmental-public-health/environmental-public-health/"
            "water-quality/beach-water-quality/")
STATE_FILE = BUILD_DIR / "fl-doh-beaches-state.json"
TZ = ZoneInfo("America/New_York")
AUTHORITY = "Florida Department of Health (Florida Healthy Beaches Program)"
CREDIT = "Florida Department of Health, Florida Healthy Beaches Program"
POINT_FIELDS = ("FID", "County", "EPAbeachID", "STORET_Sta", "SPLocation", "Active", "SPLat", "SPLong", "Link")
MIN_HOURS = 20
START_BASIS = ("the sample date of the first result with an advisory; the Department of Health issues the advisory "
               "when the laboratory result is known, usually one to three days after sampling")

ROW_RE = re.compile(r'<tr[^>]*class="cbResultSetDataRow[^"]*"[^>]*>(.*?)</tr>', re.S)
CELL_RE = re.compile(r'<td[^>]*class="cbResultSetData[^"]*"[^>]*>(.*?)</td>', re.S)


def text(s: str) -> str:
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def parse_page(page: str) -> list[dict]:
    """The sample rows of one Caspio page: [{period, location, date, enterococcus, advisory}]."""
    out = []
    for row in ROW_RE.findall(page or ""):
        cells = CELL_RE.findall(row)
        flat = " ".join(text(c) for c in cells)
        m_id = re.search(r"\bID:\s*(\d+)", flat)
        m_date = re.search(r"\bDate:\s*(\d{1,2})/(\d{1,2})/(\d{4})", flat)
        m_adv = re.search(r"\bAdvisory:\s*(Yes|No)\b", flat, re.I)
        m_loc = re.search(r"\bLocation:\s*(.*?)\s+Date:", flat)
        m_ent = re.search(r"Enterococcus Code \(Calc\):.*?if\s*\(\s*'([^']*)'", " ".join(cells), re.S)
        if not (m_id and m_date):
            continue
        mo, d, y = (int(x) for x in m_date.groups())
        out.append({"period": m_id.group(1), "location": m_loc.group(1).strip() if m_loc else None,
                    "date": f"{y:04d}-{mo:02d}-{d:02d}",
                    "enterococcus": m_ent.group(1).strip() if m_ent and m_ent.group(1).strip() else None,
                    "advisory": m_adv.group(1).capitalize() if m_adv else None})
    return out


def point_key(p: dict) -> str:
    return f"{p.get('County')}|{p.get('SPLocation')}"


def point_id(p: dict) -> str:
    if p.get("EPAbeachID"):
        base = str(p["EPAbeachID"]).strip()
        return f"{base}-{re.sub(r'[^a-z0-9]+', '-', str(p.get('SPLocation') or '').lower()).strip('-')}"
    return re.sub(r"[^a-z0-9]+", "-", f"{p.get('County')} {p.get('SPLocation')}".lower()).strip("-")


def day(d: str) -> str:
    y, m, dd = (int(x) for x in d.split("-"))
    return datetime(y, m, dd, tzinfo=TZ).isoformat()


def episodes(p: dict, samples: list[dict], fetched_at: str) -> list[dict]:
    samples = sorted({s["period"]: s for s in samples}.values(), key=lambda s: (s["date"], int(s["period"])))
    out, ep = [], None
    for s in samples:
        if s.get("advisory") == "Yes":
            if ep is None:
                ep = {"open": s, "samples": [], "last": s}
            ep["samples"].append(s)
            ep["last"] = s
        elif s.get("advisory") == "No" and ep is not None:
            ep["samples"].append(s)
            out.append(make(p, ep, s, fetched_at))
            ep = None
    if ep is not None:
        out.append(make(p, ep, None, fetched_at))
    return out


def make(p: dict, ep: dict, lift: dict | None, fetched_at: str) -> dict:
    o = ep["open"]
    lat, lon = p.get("SPLat"), p.get("SPLong")
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        lat = lon = None
    raw = {"county": p.get("County"), "epa_beach_id": p.get("EPAbeachID"), "storet_station": p.get("STORET_Sta"),
           "location": p.get("SPLocation"), "samples": ep["samples"], "start_basis": START_BASIS,
           "detail_page": p.get("Link")}
    status = "advisory_lifted" if lift else "advisory_active"
    return event(
        source_id=SOURCE_ID, source_record_id=f"{point_id(p)}:{o['period']}", fetched_at=fetched_at,
        source_url=p.get("Link") or PAGE_URL, event_type="beach_advisory", status=status,
        waterbody_text=p.get("SPLocation"), water_slugs=[], water_match="none", outfall_name=p.get("SPLocation"),
        lat=lat, lon=lon, coord_source="source" if lat is not None else None, coord_precision_m=10 if lat is not None else None,
        started_at=day(o["date"]), ended_at=day(lift["date"]) if lift else None, time_precision="day",
        reported_at=None, published_at=None, source_updated_at=day(ep["last"]["date"]),
        material="enterococcus bacteria above the state's beach action value", authority=AUTHORITY,
        advice_text=None, raw=raw,
    )


def caspio_params(p: dict) -> dict:
    q = dict(parse_qsl(urlsplit(p.get("Link") or "").query, keep_blank_values=True))
    if not q:
        q = {"County": p.get("County"), "SPLocation": p.get("SPLocation"), "SPNo": "", "SPLat": p.get("SPLat"),
             "SPLong": p.get("SPLong")}
    return q


def fetch(limit: int | None = None) -> tuple[list[dict], dict, list[str]]:
    sess = requests.Session()
    sess.headers.update(HEADERS)
    r = sess.get(f"{POINTS}/query", params={"where": "Active='Yes'", "outFields": ",".join(POINT_FIELDS),
                                            "returnGeometry": "false", "f": "json"}, timeout=(15, 60))
    r.raise_for_status()
    pts = [f["attributes"] for f in r.json().get("features") or []]
    if limit:
        pts = pts[:limit]
    pages, errors = {}, []
    bsess = requests.Session()
    bsess.headers.update(BROWSER_HEADERS)
    for p in pts:
        try:
            pr = bsess.get(CASPIO, params=caspio_params(p), timeout=(15, 60))
            pr.raise_for_status()
            pages[point_key(p)] = pr.text
        except Exception as e:  # noqa: BLE001
            errors.append(f"{point_key(p)}: {type(e).__name__}")
        time.sleep(0.5)
    return pts, pages, errors


def build(points: list[dict], pages: dict, prev_records: list[dict], fetched_at: str) -> tuple[list[dict], dict]:
    records, seen, samples_n, read = [], set(), 0, 0
    for p in points:
        page = pages.get(point_key(p))
        if page is None:
            continue
        rows = parse_page(page)
        read += 1
        samples_n += len(rows)
        # samples kept from earlier runs for this point (older than the first page)
        old = [s for r in prev_records if r.get("raw", {}).get("county") == p.get("County")
               and r.get("raw", {}).get("location") == p.get("SPLocation") for s in r["raw"].get("samples") or []]
        for rec in episodes(p, rows + old, fetched_at):
            seen.add(rec["event_id"])
            records.append(rec)
    kept = 0
    for r in prev_records:
        if r["event_id"] not in seen:
            records.append(r)
            kept += 1
    records.sort(key=lambda r: (r.get("started_at") or "", r["event_id"]), reverse=True)
    return records, {"points": len(points), "points_read": read, "samples_read": samples_n, "kept_from_earlier_runs": kept,
                     "by_status": dict(Counter(r["status"] for r in records))}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--file")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--limit", type=int)
    args = ap.parse_args(argv)
    fetched_at = now_iso()
    state = read_json(STATE_FILE, {}) or {}
    if not args.file and not args.force and state.get("full_pass_at"):
        last = datetime.fromisoformat(state["full_pass_at"].replace("Z", "+00:00"))
        if datetime.now(UTC) - last < timedelta(hours=MIN_HOURS):
            print(f"{SOURCE_ID}: last full pass {state['full_pass_at']}; next after {MIN_HOURS} h (use --force)")
            return 0
    try:
        if args.file:
            d = json.loads(Path(args.file).read_text())
            points, pages, errors = d["points"], d["pages"], []
        else:
            points, pages, errors = fetch(args.limit)
        if points and not pages:
            raise RuntimeError("no result page could be read")
    except Exception as e:  # noqa: BLE001
        write_events(SOURCE_ID, [], ok=False, error=f"{type(e).__name__}: {e}")
        print(f"{SOURCE_ID}: FAILED {e}", file=sys.stderr)
        return 1
    prev = (read_json(EVENTS_DIR / f"{SOURCE_ID}.json", {}) or {}).get("records", [])
    records, stats = build(points, pages, prev, fetched_at)
    if not args.file:
        state.update({"fetched_at": fetched_at, "page_errors": errors[:50]})
        if not args.limit:
            state["full_pass_at"] = fetched_at
        write_json(STATE_FILE, state)
    meta = {**stats, "page_errors": len(errors), "points_layer": POINTS, "results_page": CASPIO, "credit": CREDIT,
            "registry_ids": ["fl-doh-healthy-beaches"]}
    path = write_events(SOURCE_ID, records, ok=True, error=None, meta=meta)
    print(f"{SOURCE_ID}: {stats['points_read']}/{stats['points']} points, {stats['samples_read']} samples -> "
          f"{len(records)} advisory records {stats['by_status']} ({len(errors)} page errors) -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
