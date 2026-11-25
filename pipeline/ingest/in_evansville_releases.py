"""Evansville Water and Sewer Utility SSO/CSSR history -> in-evansville-releases.

The utility's map uses GET /Location/SearchCSSR/MM.DD.YYYY/MM.DD.YYYY/*,
returning {Success: true, Result: "[...JSON rows...]"}. No REST layer or paging
token exists. Read the full range and each calendar year, reconciling the ID
and source-value sets before saving anything. Windows can return the same ID
(including rows with conflicting start/end years). Conflicting copies or a
short read fail closed; missing historical records remain in our history.

One record per Id, updated in place, with prior source values in _revisions.
Times are unzoned local clocks, interpreted in America/Chicago (Evansville);
Has* flags determine precision. Ambiguous/nonexistent DST hours and ends
before starts stay unknown. entered is a database entry stamp, not evidence
of publication, receipt or last update; those three fields remain null.

The endpoint cannot select fields. Keep every published field and the source's
coordinate precision. Ground and storm-sewer wording stays in waterbody_text so
the resolver can classify records that name no receiving water. Generic private
waters and other unresolved areas remain in raw only; no water reach is inferred.

VolumeReleased is the source's gallons, without a measured/estimated claim.
DurationHrs stays the source's figure; we compute no volume or end. The live
19-outfall CSO status endpoint is a separate source and is never fetched here.
Existing Indiana monthly totals are separate aggregate series, not event
counts; Fort Wayne reports another utility. No cross-source match is assumed.

Run from pipeline/: python -m ingest.in_evansville_releases [--file query.json]
Hourly; complete history since 2015, including late entries and revisions.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import sys
import time
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from common import (BUILD_DIR, EVENTS_DIR, HEADERS, ROOT, error_detail, error_text,
                    event, now_iso, read_json, save_raw, write_events, write_json)

SOURCE_ID = "in-evansville-releases"
PAGE_URL = "https://cso.ewsu.com/"
QUERY = PAGE_URL + "Location/SearchCSSR/"
AUTHORITY = "Evansville Water and Sewer Utility"
STATE_FILE = BUILD_DIR / f"{SOURCE_ID}-state.json"
TZ = ZoneInfo("America/Chicago")
TIME_BASIS = "We read the utility's unzoned local times in Central time (America/Chicago), including daylight saving time."
REQUIRED_FIELDS = {"Id", "StartDate", "StartDateTime", "StartTime", "EndDate", "EndDateTime", "EndTime",
                   "HasStartDate", "HasStartTime", "HasEndDate", "HasEndTime", "VolumeReleased",
                   "CauseDescription", "AffectedArea", "EventReasonID"}
# Keep the other source area texts, including ground/street/storm-sewer terms:
# status.no_receiving_water reads those words without asserting water was not reached.
# These generic areas still give no water name the resolver can use.
UNRESOLVED_AREAS = {"Garage Floor", "Detention Basin", "Storm Retention Pond",
                    "Garage Floor Drain / Private Lake", "Ground/Private Lake"}
# Reader annotations are not source columns when replaying saved event history.
ROW_ANNOTATIONS = {"ended_at_precision", "time_zone", "_time_basis", "_placement",
                   "source_entered_at", "entry_time_basis", "_water_note",
                   "coordinate_precision_basis", "_coordinate_note", "_first_seen_at",
                   "_last_seen_in_source", "_revisions", "operator_basis",
                   "_missing_from_source_since", "_withheld_fields"}


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if math.isfinite(value) else None


def safe_row(row: dict) -> dict:
    """Validate the stable source identity; retain all published values."""
    if type(row.get("Id")) is not int or row["Id"] <= 0:
        raise ValueError("release has no valid numeric identity")
    return copy.deepcopy({k: v for k, v in row.items() if k not in ROW_ANNOTATIONS})


def query_url(start: date, end: date) -> str:
    return f"{QUERY}{start:%m.%d.%Y}/{end:%m.%d.%Y}/*"


def decode(payload: dict) -> list[dict]:
    if not isinstance(payload, dict) or payload.get("Success") is not True or payload.get("HasWarning"):
        raise ValueError("release query did not report unqualified success")
    if not isinstance(payload.get("Result"), str):
        raise ValueError("release query has no encoded result")
    rows = json.loads(payload["Result"])
    if not isinstance(rows, list) or any(not isinstance(r, dict) or not REQUIRED_FIELDS <= r.keys() for r in rows):
        raise ValueError("release query has a malformed row or missing core fields")
    return [safe_row(r) for r in rows]


def indexed(rows: list[dict]) -> dict[int, dict]:
    out = {}
    for row in rows:
        if row["Id"] in out and out[row["Id"]] != row:
            raise ValueError("conflicting copies of a release identity")
        out[row["Id"]] = row
    return out


def fetch_rows(sess, until: date, first_year=2015, pause=.25) -> tuple[list[dict], dict]:
    """Reconcile a whole-history read with overlapping year windows; no silent paging loss."""
    start = date(first_year, 1, 1)
    if until <= start:
        raise ValueError("release query range is empty")
    queries = []

    def get(lo, hi):
        url = query_url(lo, hi)
        r = sess.get(url, timeout=(15, 60))
        r.raise_for_status()
        rows = decode(r.json())
        queries.append({"url": url, "rows": len(rows)})
        return rows

    whole = indexed(get(start, until))
    if not whole:
        raise ValueError("release history is unexpectedly empty")
    partition = []
    for year in range(first_year, until.year + 1):
        lo, hi = date(year, 1, 1), min(date(year + 1, 1, 1), until)
        if lo >= hi:
            continue
        if pause:
            time.sleep(pause)
        partition.extend(get(lo, hi))
    by_id = indexed(partition)
    if by_id != whole:
        raise ValueError("release history and year windows disagree; partial or changing read")
    return list(by_id.values()), {"queries": queries, "partition_rows": len(partition),
                                  "unique_rows": len(by_id), "completeness": "Full history equals the union of year windows."}


def local_time(value: str | None) -> datetime | None:
    if value is None:
        return None
    dt = datetime.fromisoformat(value)
    a, b = dt.replace(tzinfo=TZ, fold=0), dt.replace(tzinfo=TZ, fold=1)
    if a.utcoffset() != b.utcoffset() or a.astimezone(UTC).astimezone(TZ).replace(tzinfo=None) != dt:
        raise ValueError("local time is ambiguous or nonexistent at daylight saving transition")
    return a


def source_time(row, prefix, problems):
    if row.get(f"Has{prefix}Date") is not True:
        return None, None
    try:
        day = row.get(f"{prefix}Date")
        if not day:
            raise ValueError("missing date")
        if row.get(f"Has{prefix}Time") is not True:
            return local_time(day[:10] + "T00:00:00"), "day"
        stamp = row.get(f"{prefix}DateTime")
        clock = row.get(f"{prefix}Time")
        if not stamp or not clock or stamp != day[:10] + "T" + clock:
            raise ValueError("date and time components disagree")
        precision = "minute" if stamp.endswith(":00") else "second"
        return local_time(stamp), precision
    except (ValueError, TypeError, AttributeError):
        problems.append(f"{prefix} time is missing, inconsistent or ambiguous")
        return None, None


def to_record(source_row: dict, fetched_at: str, prev: dict | None = None) -> dict:
    raw = safe_row(source_row)
    problems = []
    start, precision = source_time(raw, "Start", problems)
    end, end_precision = source_time(raw, "End", problems)
    if start and end and (end.date() < start.date() if end_precision == "day" else end < start):
        problems.append("Source end is before start; end left unknown")
        end = None
    raw["ended_at_precision"] = end_precision if end else None
    raw["time_zone"] = "America/Chicago"
    raw["_time_basis"] = TIME_BASIS
    raw["_placement"] = "named_water_only"
    raw["source_entered_at"] = None
    if raw.get("entered"):
        try:
            raw["source_entered_at"] = local_time(raw["entered"]).isoformat()
        except (ValueError, TypeError, AttributeError):
            problems.append("Source entry time could not be read")
    raw["entry_time_basis"] = "The utility's database entry time; publication and receipt times are not given."
    area = raw.get("AffectedArea")
    area = area if isinstance(area, str) else None
    water = area if area and area not in UNRESOLVED_AREAS else None
    if not water:
        raw["_water_note"] = "The affected area names no receiving water."
    vol = number(raw.get("VolumeReleased"))
    if vol is None and raw.get("VolumeReleased") is not None:
        problems.append("Source volume is not a finite number; gallons left unknown")
    if vol is not None and vol < 0:
        problems.append("Source volume is negative; gallons left unknown")
        vol = None
    lat, lon = number(raw.get("Latitude")), number(raw.get("Longitude"))
    raw["coordinate_precision_basis"] = "We retain the source's coordinate precision."
    if lat is None or lon is None or not (37.7 <= lat <= 38.3 and -87.9 <= lon <= -87.2):
        lat = lon = None
        raw["_coordinate_note"] = "No usable source point in the Evansville area."
    prior = (prev or {}).get("raw") or {}
    raw["_first_seen_at"] = prior.get("_first_seen_at") or fetched_at
    raw["_last_seen_in_source"] = fetched_at
    revisions = copy.deepcopy(prior.get("_revisions") or [])
    if prev and safe_row(prior) != safe_row(source_row):
        revisions.append({"observed_at": prev.get("fetched_at"), "superseded_at": fetched_at,
                          "row": safe_row(prior)})
    if revisions:
        raw["_revisions"] = revisions
    is_utility = raw.get("EWSUSystem") is True
    raw["operator_basis"] = "EWSU system as reported by the utility." if is_utility else "The record does not identify an EWSU-owned system."
    citation_day = start.date() if start else date(2015, 1, 1)
    citation_end = citation_day + timedelta(days=1) if start else date.fromisoformat(fetched_at[:10]) + timedelta(days=1)
    return event(source_id=SOURCE_ID, source_record_id=str(raw["Id"]), fetched_at=fetched_at,
                 event_type="sso" if start else "unknown", status="ended" if start and end else "unknown",
                 authority=AUTHORITY, source_url=query_url(citation_day, citation_end),
                 discharger_id="in-city-of-evansville" if is_utility else None,
                 discharger_name=AUTHORITY if is_utility else None,
                 started_at=start.isoformat() if start else None, ended_at=end.isoformat() if end else None,
                 time_precision=precision, waterbody_text=water,
                 lat=lat, lon=lon, coord_source="source" if lat is not None else None,
                 coord_precision_m=100 if lat is not None else None,
                 volume_gal=vol, volume_text=f"{vol} gallons" if vol is not None else None,
                 raw=raw, parse_error="; ".join(problems) or None)


def build(rows, fetched_at, previous):
    old = {r["event_id"]: r for r in previous}
    unique = indexed([safe_row(r) for r in rows])
    records = [to_record(a, fetched_at, old.get(f"{SOURCE_ID}:{oid}")) for oid, a in unique.items()]
    seen = {r["event_id"] for r in records}
    kept = 0
    for eid, prev in old.items():
        if eid in seen:
            continue
        prev = copy.deepcopy(prev)
        prev.setdefault("raw", {}).setdefault("_missing_from_source_since", fetched_at)
        records.append(prev)
        kept += 1
    records.sort(key=lambda r: (r.get("started_at") or "", r["event_id"]), reverse=True)
    return records, {"source_rows": len(unique), "kept_from_earlier_runs": kept,
                     "counts_by_year": dict(sorted(Counter(r["started_at"][:4] for r in records if r["started_at"]).items())),
                     "parse_errors": sum(bool(r["parse_error"]) for r in records)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--file", help="read a saved query envelope or source row array")
    args = ap.parse_args(argv)
    fetched_at = now_iso()
    try:
        if args.file:
            payload = json.loads(Path(args.file).read_text())
            rows = [safe_row(r) for r in payload] if isinstance(payload, list) else decode(payload)
            meta = {"local_file": True}
        else:
            with requests.Session() as sess:
                sess.headers.update(HEADERS)
                rows, meta = fetch_rows(sess, datetime.now(TZ).date() + timedelta(days=1))
        if not rows:
            raise ValueError("release history is unexpectedly empty")
        previous = (read_json(EVENTS_DIR / f"{SOURCE_ID}.json", {}) or {}).get("records", [])
        records, stats = build(rows, fetched_at, previous)
        state = read_json(STATE_FILE, {}) or {}
        raw_bytes = json.dumps(sorted(rows, key=lambda r: r["Id"]), sort_keys=True, ensure_ascii=False).encode()
        digest = hashlib.sha256(raw_bytes).hexdigest()
        if digest != state.get("sha256"):
            state = {"sha256": digest, "raw_path": str(save_raw(SOURCE_ID, raw_bytes, "json").relative_to(ROOT))}
        state["fetched_at"] = fetched_at
        write_json(STATE_FILE, state)
        meta.update(stats, raw_path=state["raw_path"], registry_ids=[SOURCE_ID], credit=AUTHORITY, time_basis=TIME_BASIS)
        write_events(SOURCE_ID, records, meta=meta)
    except Exception as exc:  # noqa: BLE001 - a failed fetch never empties history
        write_events(SOURCE_ID, [], ok=False, error=error_text(exc))
        print(f"{SOURCE_ID}: FAILED {error_detail(exc)}", file=sys.stderr)
        return 1
    print(f"{SOURCE_ID}: {len(rows)} rows, {stats['kept_from_earlier_runs']} retained, {stats['parse_errors']} records for review")
    return 0


if __name__ == "__main__":
    sys.exit(main())
