"""City of Clyde yearly CSO reports -> data/build/events/oh-clyde-cso-notification.json.

Source (registry oh-clyde-cso-notification; review 2026-11-08 P2-7)
  Clyde's CSO notification site (https://cso.clydeohio.org/) publishes a yearly report page per year,
  https://cso.clydeohio.org/templates/cso-report.php?year=<yyyy> (2017 on): a table of each overflow of the city's one
  combined sewer outfall ("on Raccoon Creek 500 feet north of McPherson Highway") with the date and time at start and
  at end, the cause, the rainfall before the start and in total (inches), the total CSO volume (million gallons) and
  two concentrations. A year with no overflow has an empty table (2024 and 2025).
  Read: only the table's event cells, matched as a run of start date, start time, end date, end time, cause, two
  rainfalls, volume and two concentrations (ROW). The page also names a staff member with an e-mail and phone: never
  read, never saved (the raw save is the parsed rows only).

Records
  - One cso record per row: source_record_id "<start, local YYYYMMDDTHHMM>"; started_at and ended_at the page's times
    in America/New_York (minute; raw.time_zone, raw.ended_at_precision minute); status ended. volume_gal from million
    gallons (estimate_flag unknown: the page does not say how it is measured); the cause, rainfalls and
    concentrations in raw.
  - Place: Clyde's permit OH0024686 and its one open CSO outfall in EPA's inventory, 010 on Raccoon Creek, at EPA's
    permitted-feature point (coord_source outfall_layer); the page's own description names the same creek.
  - Times: reported_at, published_at and source_updated_at null (the page gives none); fetched_at and
    raw._last_seen_in_source the poll. advice_text null (the page gives no advice).
  Privacy: the parsed fields hold no person; common.event runs strip_personal.

Failures: a year that fails is skipped and named in meta; if every year fails, ok=False keeps the previous records.
Run from pipeline/: python -m ingest.oh_clyde_cso [--file saved.html ... --out events.json]
Cadence: daily with the refresh (this year and last year; every year from 2017 when the archive is empty).
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from common import BUILD_DIR, HEADERS, event, now_iso, read_json, save_raw, write_events, write_json

SOURCE_ID = "oh-clyde-cso-notification"
URL = "https://cso.clydeohio.org/templates/cso-report.php"
PAGE_URL = "https://cso.clydeohio.org/"
FIRST_YEAR = 2017
TZ_NAME = "America/New_York"
TZ = ZoneInfo(TZ_NAME)
PERMIT, OUTFALL = "OH0024686", "010"
POINT = (41.31306, -82.98528)            # EPA's permitted-feature point for OH0024686 outfall 010
WATER = "Raccoon Creek"
STATE_PATH = BUILD_DIR / "oh-clyde-cso-state.json"
CREDIT = "City of Clyde, yearly CSO report"
MATERIAL = "combined sewage and stormwater"
NUM = r"(-?\d*\.?\d+|N/?A|)"
ROW = re.compile(r"(\d{1,2}/\d{1,2}/\d{4})\|(\d{1,2}:\d{2}\s*[AP]M)\|(\d{1,2}/\d{1,2}/\d{4})\|(\d{1,2}:\d{2}\s*[AP]M)\|"
                 r"([A-Za-z][A-Za-z /-]{0,40})\|" + r"\|".join([NUM] * 5), re.I)


def cells(page: str) -> str:
    """The page's table cell texts joined by '|' (scripts and styles dropped)."""
    t = re.sub(r"(?is)<script.*?</script>|<style.*?</style>", "", page)
    parts = [" ".join(html.unescape(x).split()) for x in re.split(r"<[^>]+>", t)]
    return "|".join(p for p in parts if p)


def parse(page: str) -> list[dict]:
    out = []
    for m in ROW.finditer(cells(page)):
        sd, stt, ed, et, cause, r1, r2, vol, tss, cbod = m.groups()
        out.append({"start_date": sd, "start_time": stt, "end_date": ed, "end_time": et, "cause": cause.strip(),
                    "rain_before_in": r1, "rain_total_in": r2, "volume_mg": vol, "tss_mg_l": tss, "cbod5_mg_l": cbod})
    return out


def local(d: str, t: str) -> datetime | None:
    try:
        return datetime.strptime(f"{d} {t.replace(' ', '')}", "%m/%d/%Y %I:%M%p").replace(tzinfo=TZ)
    except ValueError:
        return None


def to_record(r: dict, now: str) -> dict | None:
    st, end = local(r["start_date"], r["start_time"]), local(r["end_date"], r["end_time"])
    if st is None:
        return None
    try:
        mg = float(r["volume_mg"])
    except (TypeError, ValueError):
        mg = None
    raw = {"row": r, "time_zone": TZ_NAME, "state": "OH", "_last_seen_in_source": now,
           "place_basis": (f"Clyde has one combined sewer outfall, on {WATER}; EPA lists it as {PERMIT} outfall {OUTFALL} "
                           "with its own permitted-feature point")}
    if end:
        raw["ended_at_precision"] = "minute"
    return event(
        source_id=SOURCE_ID, source_record_id=st.strftime("%Y%m%dT%H%M"), event_type="cso",
        status="ended" if end else "unknown", discharger_name="City of Clyde", npdes_permit=PERMIT, outfall_id=OUTFALL,
        outfall_name="Clyde CSO, Raccoon Creek", waterbody_text=WATER, lat=POINT[0], lon=POINT[1],
        coord_source="outfall_layer", started_at=st.isoformat(), ended_at=end.isoformat() if end else None,
        time_precision="minute", reported_at=None, published_at=None, source_updated_at=None, fetched_at=now,
        material=MATERIAL, volume_gal=int(round(mg * 1_000_000)) if mg and mg > 0 else None,
        volume_text=f"{r['volume_mg']} million gallons" if mg else None, estimate_flag="unknown",
        authority=CREDIT, advice_text=None, source_url=f"{URL}?year={st.year}", raw=raw)


def run(rows_by_year: dict[int, list[dict]], now: str, state_path: Path) -> tuple[list[dict], dict]:
    state = read_json(state_path, {}) or {}
    years = state.setdefault("years", {})
    for y, rows in rows_by_year.items():
        years[str(y)] = {"rows": rows, "read_at": now}
    write_json(state_path, state)
    recs = [x for v in years.values() for x in (to_record(r, v["read_at"]) for r in v["rows"]) if x]
    recs.sort(key=lambda x: (x["started_at"] or "", x["event_id"]), reverse=True)
    return recs, {"registry_ids": [SOURCE_ID], "years_read": sorted(years), "credit": CREDIT}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", action="append", help="saved yearly pages (the year is read from the page's title)")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    now = now_iso()
    if a.file:
        if not a.out:
            ap.error("--file needs --out")
        by_year = {}
        for f in a.file:
            page = Path(f).read_text(errors="replace")
            m = re.search(r"(\d{4}) (?:Annual )?CSO Report", page)
            by_year[int(m.group(1)) if m else 0] = parse(page)
        out = Path(a.out)
        recs, meta = run(by_year, now, out.with_suffix(".state.json"))
        write_events(SOURCE_ID, recs, meta=meta, path=out)
        print(f"{SOURCE_ID}: {len(recs)} records (file) -> {out}")
        return 0
    state = read_json(STATE_PATH, {}) or {}
    this = datetime.now(TZ).year
    years = range(FIRST_YEAR, this + 1) if not state.get("years") else (this - 1, this)
    by_year, failed = {}, []
    for y in years:
        try:
            r = requests.get(URL, params={"year": y}, headers=HEADERS, timeout=(20, 90))
            r.raise_for_status()
            by_year[y] = parse(r.text)          # the page itself is never saved: it names a staff contact
        except requests.RequestException as e:
            failed.append(f"{y}: {type(e).__name__}")
    if not by_year:
        write_events(SOURCE_ID, [], ok=False, error="every year failed: " + "; ".join(failed))
        print(f"{SOURCE_ID}: FAILED", file=sys.stderr)
        return 1
    save_raw(SOURCE_ID, json.dumps(by_year), "json")
    recs, meta = run(by_year, now, STATE_PATH)
    meta["years_failed"] = failed
    path = write_events(SOURCE_ID, recs, meta=meta)
    print(f"{SOURCE_ID}: {len(recs)} records -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
