"""City of Bowling Green CSO events table -> data/build/events/oh-bowling-green-cso-events.json.

Source (registry oh-bowling-green-cso-events; research/oh/report.md section 2.3)
  The city's public table of combined sewer overflow events (a PHPRunner list page):
  https://gis.bgohio.org/cso_events/dbo_cso_events_list.php, read with pagesize=500 so one page holds every row. Each
  row: LOCATION ("MERCER - POE RD"), BEGIN_DATE and BEGIN_TIME, END_DATE and END_TIME (the city's wall clock),
  RAINFALL_BEFORE_EVENT (inches, as typed: "1.20\"" or ".95") and ESTIMATED_DISCHARGE (million gallons). 37 rows on
  2026-11-08, 2019 to 2026-07-21, all at the one location. No point, no receiving water, no person.
  The fields are read from the cells' own ids (edit<n>_<FIELD>); nothing else on the page is read.

Records
  - One cso record per row: source_record_id "<location slug>:<begin, local YYYYMMDDTHHMM>"; started_at and ended_at
    the row's begin and end in America/New_York (minute; raw.time_zone, raw.ended_at_precision minute); status
    ended (every row has an end; a row without one would be status unknown, ended_at null). volume_gal from million
    gallons, estimate_flag estimated (the city's column says "estimated"); raw.rainfall_in the rainfall as typed.
  - Place: EPA's CSO inventory lists one combined sewer outfall for Bowling Green's permit (OH0024139, outfall 002,
    "North Branch Portage River", its own permitted-feature point near Mercer and Poe roads): the records carry that
    permit and outfall, the outfall's receiving water and its point (coord_source "outfall_layer"), and
    raw.place_basis says so. The plant's point is never used.
  - Times: reported_at, published_at and source_updated_at null (the table gives none); fetched_at and
    raw._last_seen_in_source the poll.
  Privacy: the table holds no person; only the fields above are kept; common.event runs strip_personal.

Failures: a failed request or a page with no rows writes ok=False and keeps the previous records.
Run from pipeline/: python -m ingest.oh_bowling_green_cso [--file saved.html --out events.json]
Cadence: daily with the refresh.
"""
from __future__ import annotations

import argparse
import html
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from common import HEADERS, event, now_iso, write_events

SOURCE_ID = "oh-bowling-green-cso-events"
URL = "https://gis.bgohio.org/cso_events/dbo_cso_events_list.php"
PARAMS = {"pagesize": 500}
FIELDS = ("LOCATION", "BEGIN_DATE", "BEGIN_TIME", "END_DATE", "END_TIME", "RAINFALL_BEFORE_EVENT", "ESTIMATED_DISCHARGE")
TZ_NAME = "America/New_York"
TZ = ZoneInfo(TZ_NAME)
PERMIT = "OH0024139"
OUTFALL = {"outfall": "002", "water": "North Branch Portage River", "lat": 41.38525, "lon": -83.62972}
CREDIT = "City of Bowling Green, CSO events"
MATERIAL = "combined sewage and stormwater"
CELL = re.compile(r'<span id="edit(\d+)_([A-Z_]+)"\s*>(.*?)</span>', re.S)


def parse(page: str) -> list[dict]:
    rows: dict[str, dict] = defaultdict(dict)
    for rid, field, v in CELL.findall(page):
        if field in FIELDS:
            rows[rid][field] = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", v)).split()) or None
    return [r for r in rows.values() if r.get("BEGIN_DATE")]


def local(d: str | None, t: str | None) -> datetime | None:
    if not d:
        return None
    for fmt in ("%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %I:%M %p"):
        try:
            return datetime.strptime(f"{d} {t or ''}".strip(), fmt).replace(tzinfo=TZ)
        except ValueError:
            continue
    return None


def number(v) -> float | None:
    m = re.search(r"\d*\.?\d+", str(v or ""))
    return float(m.group(0)) if m else None


def to_record(r: dict, now: str) -> dict | None:
    st = local(r.get("BEGIN_DATE"), r.get("BEGIN_TIME"))
    if st is None:
        return None
    end = local(r.get("END_DATE"), r.get("END_TIME"))
    loc = r.get("LOCATION") or "unknown location"
    key = f"{re.sub(r'[^a-z0-9]+', '-', loc.lower()).strip('-')}:{st.strftime('%Y%m%dT%H%M')}"
    mg = number(r.get("ESTIMATED_DISCHARGE"))
    raw = {"row": r, "time_zone": TZ_NAME, "state": "OH", "rainfall_in": r.get("RAINFALL_BEFORE_EVENT"),
           "_last_seen_in_source": now,
           "place_basis": (f"EPA's CSO inventory lists one combined sewer outfall for permit {PERMIT} (outfall "
                           f"{OUTFALL['outfall']}, {OUTFALL['water']}); the table names the location "
                           f"\"{loc}\" and gives no point")}
    if end:
        raw["ended_at_precision"] = "minute"
    return event(
        source_id=SOURCE_ID, source_record_id=key, event_type="cso", status="ended" if end else "unknown",
        discharger_name="City of Bowling Green", npdes_permit=PERMIT, outfall_id=OUTFALL["outfall"],
        outfall_name=loc.title(), waterbody_text=OUTFALL["water"],
        lat=OUTFALL["lat"], lon=OUTFALL["lon"], coord_source="outfall_layer",
        started_at=st.isoformat(), ended_at=end.isoformat() if end else None, time_precision="minute",
        reported_at=None, published_at=None, source_updated_at=None, fetched_at=now, material=MATERIAL,
        volume_gal=int(round(mg * 1_000_000)) if mg else None,
        volume_text=f"{r.get('ESTIMATED_DISCHARGE')} million gallons (estimated)" if r.get("ESTIMATED_DISCHARGE") else None,
        estimate_flag="estimated" if mg else "unknown", authority=CREDIT,
        advice_text=None,                        # the table gives no advice
        source_url=URL, raw=raw)


def run(page: str, now: str) -> tuple[list[dict], dict]:
    rows = parse(page)
    recs = [x for x in (to_record(r, now) for r in rows) if x]
    recs.sort(key=lambda x: (x["started_at"] or "", x["event_id"]), reverse=True)
    return recs, {"registry_ids": [SOURCE_ID], "url": URL, "rows": len(rows), "credit": CREDIT}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    now = now_iso()
    if a.file:
        if not a.out:
            ap.error("--file needs --out")
        recs, meta = run(Path(a.file).read_text(errors="replace"), now)
        write_events(SOURCE_ID, recs, meta=meta, path=Path(a.out))
        print(f"{SOURCE_ID}: {len(recs)} records (file) -> {a.out}")
        return 0
    try:
        r = requests.get(URL, params=PARAMS, headers=HEADERS, timeout=(20, 180))
        r.raise_for_status()
        recs, meta = run(r.text, now)
        if not recs:
            raise ValueError("no rows in the table")
    except (requests.RequestException, ValueError) as e:
        write_events(SOURCE_ID, [], ok=False, error=f"table: {type(e).__name__}: {e}")
        print(f"{SOURCE_ID}: FAILED {e}", file=sys.stderr)
        return 1
    path = write_events(SOURCE_ID, recs, meta=meta)
    print(f"{SOURCE_ID}: {len(recs)} records -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
