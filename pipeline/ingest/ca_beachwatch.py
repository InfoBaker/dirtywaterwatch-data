"""California Beach Watch advisories (beach postings and closures) -> data/build/events/ca-beachwatch-advisories.json

Source
  State Water Resources Control Board, Beach Watch: "Beach Advisories (Postings and Closures) and Beach Water Quality
  Monitoring" on data.ca.gov (package beach-water-quality-postings-and-closures), resource "Beach Posting and Closures-
  Advisories" (d5cd6a23-829c-426d-a63e-689a55a3db9c; CKAN datastore, about 35,700 advisories since 1985). County health
  agencies enter their postings and closures; the Board compiles them. Licence: Open Data Commons Attribution
  (ODC-By). Credit "California State Water Resources Control Board, Beach Watch (data.ca.gov)". The table is months
  behind (newest advisory 2026-03-06 when read on 2026-11-04): history, not current status.
  Law: the county health officer must post and close a beach after a known untreated sewage release (Health and
  Safety Code 115885, 17 CCR 7958) and post it when bacteria exceed the standards (17 CCR 7958); the law asks the
  officer for a hotline, not a web page.

What is read (privacy)
  Only FIELDS are asked for (datastore `fields`): the advisory's id, type, cause, dates and times, extent, the area's
  description, the substance and volume, the county, the station's and beach's names and points, the water body. Never
  asked for: the advisory's contact person, the entering user's id, "ActionBy", the comments and action descriptions
  (typed by staff, they can name people), the agency's street address and cost fields. The area description passes
  common.scrub_text and loses street house numbers; common.strip_personal runs on every raw (in event()).

Records (category beach: beach_closure or beach_advisory; never a sewage discharge record)
  - Key: "Advisory id". AdvisoryType Closure -> beach_closure; Posting -> beach_advisory; Rain -> rain_advisory. The
    cause (Sewage Spill, Combined Sewer Overflow, Line Break, Pump Station Failure, Blockage ... , Bacterial Standards
    Violation, Rain, Other - Tijuana River Associated) is raw.cause, and raw.sewage_cause is true for the causes that
    are sewer failures.
  - started_at: DateofAdvisory with TimeofAdvisory (Pacific; a date alone is day precision); ended_at: DateOpened with
    TimeOpened. An end -> advisory_lifted; none -> advisory_active, with source_updated_at the date the table is
    current to (its newest advisory start or reopening, not its last_modified: the table is months behind), so the
    status build stops colouring it 14 days after that. An end before
    the start is not used.
  - Point: the station's upper point, else the beach's. waterbody_text: the water body name; outfall_name: the beach
    and station.

Reading (what each run costs): one package_show (about 18 KB) each hour; when the table's last_modified changed (about
monthly), the advisories that began in the last WINDOW_DAYS (two years) through datastore_search_sql (about 1 MB).
`--backfill` reads every advisory since 1985 (about 36,000 rows, 15 MB) once.
Run from pipeline/:  python -m ingest.ca_beachwatch [--file saved.json] [--backfill]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from common import (BUILD_DIR, EVENTS_DIR, HEADERS, event, now_iso, path_notes_to_meta, read_json, scrub_text,
                    strip_house_numbers, write_events, write_json)
from ingest import ca_datagov

SOURCE_ID = "ca-beachwatch-advisories"
PACKAGE = "beach-water-quality-postings-and-closures"
RESOURCE = "d5cd6a23-829c-426d-a63e-689a55a3db9c"
PAGE = f"https://data.ca.gov/dataset/{PACKAGE}"
STATE_FILE = BUILD_DIR / "ca-beachwatch-state.json"
AUTHORITY = "California State Water Resources Control Board (Beach Watch), from the county health agencies"
CREDIT = "California State Water Resources Control Board, Beach Watch (data.ca.gov), ODC-By"
TZ = ZoneInfo("America/Los_Angeles")
WINDOW_DAYS = 730
FIELDS = ["Advisory id", "AdvisoryType", "AdvisoryCause", "DateofAdvisory", "TimeofAdvisory", "DateOpened",
          "TimeOpened", "Extent", "StartofExtent", "StartOfExtentType", "EndofExtent", "EndOfExtentType", "Source",
          "DescriptionofArea", "SubstanceName", "SubstanceVolume", "SubstanceUnit", "County", "Regional Board",
          "Station_Name", "Station_Description", "Station_UpperLat", "Station_UpperLon", "Beach_Name",
          "Beach_UpperLat", "Beach_UpperLon", "WaterBodyName", "WaterBodyType", "Beach_AgencyName",
          "Advisory Record Create Date"]
TYPES = {"closure": "beach_closure", "posting": "beach_advisory", "rain": "rain_advisory"}
SEWAGE_CAUSE = re.compile(r"sewage|sewer|line break|pump station|blockage|grease|roots|infiltration|lift station|"
                          r"overflow|tijuana", re.I)
BOUNDS = (-124.6, 32.4, -114.0, 42.1)
RULES_VERSION = 2          # a run whose table is unchanged still rebuilds the records when this changes


def clean(v) -> str:
    return " ".join(str(v if v is not None else "").split())


def fnum(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def local(d, t) -> tuple[datetime | None, bool]:
    """(Pacific datetime, has a time of day) from a date and an optional 'HH:MM'."""
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", clean(d))
    if not m:
        return None, False
    y, mo, dd = map(int, m.groups())
    tm = re.match(r"^(\d{1,2}):(\d{2})", clean(t))
    try:
        if tm and int(tm.group(1)) < 24:
            return datetime(y, mo, dd, int(tm.group(1)), int(tm.group(2)), tzinfo=TZ), True
        return datetime(y, mo, dd, tzinfo=TZ), False
    except ValueError:
        return None, False


def build_record(row: dict, fetched_at: str, confirmed: str | None) -> dict:
    a = {k: row.get(k) for k in FIELDS}
    if a.get("DescriptionofArea"):
        a["DescriptionofArea"] = strip_house_numbers(scrub_text(clean(a["DescriptionofArea"])), street_word_only=True)
    raw = {"advisory": {k.replace(" ", "_"): v for k, v in a.items()}, "_first_seen_at": fetched_at}
    key = clean(a.get("Advisory id")).split(".")[0]
    etype = TYPES.get(clean(a.get("AdvisoryType")).lower(), "beach_advisory")
    cause = clean(a.get("AdvisoryCause")) or None
    raw["cause"] = cause
    raw["sewage_cause"] = bool(cause and SEWAGE_CAUSE.search(cause))
    start, st_time = local(a.get("DateofAdvisory"), a.get("TimeofAdvisory"))
    end, en_time = local(a.get("DateOpened"), a.get("TimeOpened"))
    if start and end and end < start:
        raw["_end_not_used"] = f"the reopening ({end.isoformat()}) is before the advisory's start"
        end = None
    precision = "minute" if (st_time and (end is None or en_time)) else "day"
    if precision == "day":
        start = start.replace(hour=0, minute=0) if start else None
        end = end.replace(hour=0, minute=0) if end else None
    status = "advisory_lifted" if end else "advisory_active"
    lat = fnum(a.get("Station_UpperLat")) or fnum(a.get("Beach_UpperLat"))
    lon = fnum(a.get("Station_UpperLon")) or fnum(a.get("Beach_UpperLon"))
    if lat is not None and lon is not None and lon > 0 and BOUNDS[0] <= -lon <= BOUNDS[2]:
        lon = -lon
    if lat is None or lon is None or not (BOUNDS[1] <= lat <= BOUNDS[3] and BOUNDS[0] <= lon <= BOUNDS[2]):
        lat = lon = None
    beach, station = clean(a.get("Beach_Name")), clean(a.get("Station_Description")) or clean(a.get("Station_Name"))
    name = " - ".join(dict.fromkeys(x for x in (beach, station) if x)) or None
    vol, unit = fnum(a.get("SubstanceVolume")), clean(a.get("SubstanceUnit")).lower()
    created = clean(a.get("Advisory Record Create Date"))[:19] or None
    reported = datetime.fromisoformat(created).replace(tzinfo=TZ).isoformat() if created else None
    text = {"beach_closure": "Beach closed", "beach_advisory": "Beach posted with a warning",
            "rain_advisory": "Rain advisory"}[etype] + (f" (cause given: {cause})" if cause else "")
    return event(
        source_id=SOURCE_ID, source_record_id=key, event_type=etype, status=status,
        outfall_name=name, waterbody_text=clean(a.get("WaterBodyName")) or None, lat=lat, lon=lon,
        coord_source="source" if lat is not None else None,
        started_at=start.isoformat() if start else None, ended_at=end.isoformat() if end else None,
        time_precision=precision if start or end else None, reported_at=reported, published_at=None,
        source_updated_at=None if end else confirmed, fetched_at=fetched_at,
        volume_gal=int(vol) if vol and unit in ("gallons", "gal", "gallon") else None,
        volume_text=f"{clean(a.get('SubstanceVolume'))} {a.get('SubstanceUnit')}" if vol else None,
        authority=f"{clean(a.get('Beach_AgencyName')) or 'County health agency'} via Beach Watch", advice_text=text,
        source_url=f"{PAGE}/resource/{RESOURCE}", raw=raw)


def as_of(rows: list[dict]) -> str | None:
    """The date the table is current to: its newest advisory start or reopening (it is months behind, so its
    last_modified is not a confirmation that an advisory is still open)."""
    ds = [clean(r.get(k))[:10] for r in rows for k in ("DateofAdvisory", "DateOpened") if clean(r.get(k))]
    return max(ds) if ds else None


def build(rows: list[dict], fetched_at: str, confirmed: str | None, prev: list[dict]) -> tuple[list[dict], dict]:
    old = {r["event_id"]: r for r in prev}
    recs, seen = [], set()
    for row in rows:
        r = build_record(row, fetched_at, confirmed)
        if r["event_id"] in seen:
            continue
        seen.add(r["event_id"])
        p = old.get(r["event_id"])
        if p:
            r["raw"]["_first_seen_at"] = (p.get("raw") or {}).get("_first_seen_at") or r["raw"]["_first_seen_at"]
        recs.append(r)
    kept = [r for eid, r in old.items() if eid not in seen]       # outside this read's window: kept as they were
    recs += kept
    recs.sort(key=lambda r: (r.get("started_at") or "", r["event_id"]), reverse=True)
    stats = {"rows_read": len(rows), "kept_from_earlier_runs": len(kept),
             "by_type": dict(Counter(r["event_type"] for r in recs)),
             "by_status": dict(Counter(r["status"] for r in recs)),
             "sewage_cause": sum(1 for r in recs if (r.get("raw") or {}).get("sewage_cause")),
             "newest_advisory": max((r.get("started_at") or "" for r in recs), default=None), "current_to": confirmed}
    return recs, stats


def main(argv=None) -> int:
    from build import redact
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--file", help="read a saved datastore answer (or a list of rows) instead of data.ca.gov")
    ap.add_argument("--backfill", action="store_true", help="read every advisory since 1985")
    args = ap.parse_args(argv)
    fetched_at = now_iso()
    state = read_json(STATE_FILE, {}) or {}
    prev = read_json(EVENTS_DIR / f"{SOURCE_ID}.json", {}) or {}
    sess = requests.Session()
    sess.headers.update(HEADERS)
    try:
        if args.file:
            d = json.loads(Path(args.file).read_text())
            rows = d if isinstance(d, list) else (d.get("result") or {}).get("records") or d.get("records") or []
            rows = [{k: x.get(k) for k in FIELDS} for x in rows]
            modified = None
        else:
            modified = ca_datagov.resource_modified(sess, PACKAGE, RESOURCE)
            if not args.backfill and modified and modified == state.get("modified") and prev.get("records") \
                    and state.get("rules") == RULES_VERSION:
                meta = {**(prev.get("meta") or {}), "checked_at": fetched_at}
                write_events(SOURCE_ID, prev["records"], ok=True, error=None, meta=meta)
                print(f"{SOURCE_ID}: table unchanged since {modified}; {len(prev['records'])} records kept")
                return 0
            if args.backfill:
                rows = ca_datagov.search(sess, RESOURCE, FIELDS)
            else:
                since = (datetime.now(TZ) - timedelta(days=WINDOW_DAYS)).date().isoformat()
                rows = ca_datagov.sql(sess, RESOURCE, FIELDS, f"\"DateofAdvisory\" >= '{since}'")
        if not rows:
            raise RuntimeError("the table answered no rows")
    except Exception as e:  # noqa: BLE001
        write_events(SOURCE_ID, [], ok=False, error=f"{type(e).__name__}: {e}")
        print(f"{SOURCE_ID}: FAILED {e}", file=sys.stderr)
        return 1
    confirmed = as_of(rows)
    recs, stats = build(rows, fetched_at, confirmed, prev.get("records") or [])
    recs = redact.redact_events(recs)
    if not args.file:
        state.update(modified=modified, rules=RULES_VERSION, fetched_at=fetched_at, **({"backfill": fetched_at} if args.backfill else {}))
        write_json(STATE_FILE, state)
    meta = {**stats, "table_modified": modified, "page": PAGE, "credit": CREDIT, "license": "ODC-By",
            "registry_ids": [SOURCE_ID], "window_days": WINDOW_DAYS, "backfill": state.get("backfill"),
            "time_basis": "Pacific local time as the table gives it",
            "caveat": ("Beach Watch is compiled from the counties' entries and is months behind: an advisory shown "
                       "as open may have been lifted since the table was last updated.")}
    path_notes_to_meta(recs, meta)
    path = write_events(SOURCE_ID, recs, ok=True, error=None, meta=meta)
    print(f"{SOURCE_ID}: {stats['rows_read']} rows, {len(recs)} records {stats['by_type']} {stats['by_status']}; "
          f"newest {stats['newest_advisory']} -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
