"""Florida DEP algal bloom sampling: blooms observed or toxins found per sampled site -> data/build/events/fl-dep-habs.json

Source
  Florida Department of Environmental Protection, Algal Bloom Sampling Status (registry row fl-dep-algal-bloom): the
  public view layer https://services1.arcgis.com/nRHtyn3uE1kyzoYc/arcgis/rest/services/AlgalBloom_Final_View/FeatureServer/0
  ("Florida Algal Bloom Site Visits"; about 6,800 visits, edited daily; no key, no licence stated; credit "Florida
  Department of Environmental Protection, Algal Bloom Sampling"). One row per site visit: SampleDateTime (true UTC:
  visits fall 07:00-14:00 Eastern), MonitoringGroupPublicFacing (the DEP office or water management district),
  County, esrignss_latitude/longitude, BloomObserved (Yes/No), AlgalIDResult (dominant taxa), ToxinPresent
  (Yes/No/Pending), Microcystin, OtherToxin, CyanobacteriaDominant, locationString (the site), EditDate.
  Requested fields only: the layer's Comments (free text) and PicURL (field photographs) are never asked for.
  A site named by a street address ("Example Lake - 12 Example Lane", often a resident's dock) is published without
  its house number (common.strip_house_numbers); its visits are still grouped by the name DEP gives.

Records (hab_advisory: a bloom record, the plum category; never a sewage record)
  This is DEP's sampling result, not a health advisory: the Department of Health issues health alerts separately,
  and the record says so (raw.basis). A site is the visit's locationString (case, spacing and punctuation ignored),
  or its point to four decimals when the name is blank. Per site, in time order, a visit with BloomObserved Yes or
  ToxinPresent Yes opens an episode (or continues the open one; raw.visits keeps each visit's results); a later
  visit with BloomObserved No and ToxinPresent not Yes or Pending ends it: advisory_lifted, ended_at = that visit's
  time. An episode still open is advisory_active, with source_updated_at = its latest positive visit (the status
  build stops colouring it 14 days after that); one whose latest positive visit is over 90 days old with no later
  visit is status unknown (raw.note: no later visit reported). Visits with no bloom and no toxin that open nothing
  are counted in meta.visits_without_bloom.
  event_id = fl-dep-habs:<globalid of the opening visit>. started_at = the opening visit's time (minute).
  waterbody_text = the site name before " - " and without its bracketed station code ("Lake George - Center (LEO)"
  -> "Lake George"); water_slugs stay empty until Florida's water records are built.

Cadence: daily (DEP edits the layer every day; results follow a visit by days to weeks).
Run from pipeline/:  python -m ingest.fl_dep_habs [--file saved.json]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from common import (BUILD_DIR, EVENTS_DIR, HEADERS, ROOT, event, now_iso, path_notes_to_meta, read_json, save_raw,
                    strip_house_numbers, write_events, write_json)

SOURCE_ID = "fl-dep-habs"
LAYER = ("https://services1.arcgis.com/nRHtyn3uE1kyzoYc/arcgis/rest/services/AlgalBloom_Final_View/FeatureServer/0")
PAGE_URL = "https://floridadep.gov/AlgalBloom"
STATE_FILE = BUILD_DIR / "fl-dep-habs-state.json"
TZ = ZoneInfo("America/New_York")
AUTHORITY = "Florida Department of Environmental Protection (Algal Bloom Sampling)"
CREDIT = "Florida Department of Environmental Protection, Algal Bloom Sampling Status"
FIELDS = ("objectid", "globalid", "SampleDateTime", "MonitoringGroupPublicFacing", "County", "esrignss_latitude",
          "esrignss_longitude", "BloomObserved", "MeterReadingsOnly", "SampleDepthDesc", "AnalyzedBy", "AlgalIDResult",
          "ToxinPresent", "Microcystin", "OtherToxin", "locationString", "EditDate", "CyanobacteriaDominant")
STALE_DAYS = 90
BASIS = ("Florida DEP observed an algal bloom, or found an algal toxin, in a sample at this site. This is a sampling "
         "result, not a health advisory; the Florida Department of Health issues health alerts separately.")
FL_BOX = (-87.7, 24.3, -79.8, 31.1)


def utc_time(ms) -> datetime | None:
    if ms in (None, ""):
        return None
    try:
        return datetime.fromtimestamp(float(ms) / 1000, UTC).astimezone(TZ)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def iso(t):
    return t.isoformat() if t else None


def site_key(a: dict) -> str:
    name = re.sub(r"[^a-z0-9]+", " ", str(a.get("locationString") or "").lower()).strip()
    if name:
        return name
    lat, lon = a.get("esrignss_latitude"), a.get("esrignss_longitude")
    return f"point {round(lat, 4)} {round(lon, 4)}" if lat is not None and lon is not None else f"oid {a.get('objectid')}"


def water_name(loc: str | None) -> str | None:
    s = re.sub(r"\s*\([^)]*\)\s*$", "", str(loc or "")).strip()
    s = s.split(" - ")[0].strip()
    return s or None


def yes(v) -> bool:
    return str(v or "").strip().lower() == "yes"


def positive(a: dict) -> bool:
    return yes(a.get("BloomObserved")) or yes(a.get("ToxinPresent"))


def negative(a: dict) -> bool:
    return str(a.get("BloomObserved") or "").strip().lower() == "no" and \
        str(a.get("ToxinPresent") or "").strip().lower() not in ("yes", "pending")


def visit(a: dict) -> dict:
    t = utc_time(a.get("SampleDateTime"))
    return {"time": iso(t), "globalid": a.get("globalid"), "bloom_observed": a.get("BloomObserved"),
            "toxin_present": a.get("ToxinPresent"), "microcystin": a.get("Microcystin"), "other_toxins": a.get("OtherToxin"),
            "taxa": a.get("AlgalIDResult"), "cyanobacteria_dominant": a.get("CyanobacteriaDominant"),
            "sample_depth": a.get("SampleDepthDesc"), "group": a.get("MonitoringGroupPublicFacing"),
            "edited": iso(utc_time(a.get("EditDate")))}


def build(features: list[dict], fetched_at: str, now: datetime | None = None) -> tuple[list[dict], dict]:
    now = now or datetime.now(UTC)
    sites = defaultdict(list)
    for a in features:
        if a.get("SampleDateTime") is None:
            continue
        sites[site_key(a)].append(a)
    records, quiet = [], 0
    for key, vs in sites.items():
        vs.sort(key=lambda a: (a["SampleDateTime"], a.get("objectid") or 0))
        ep = None
        for a in vs:
            if positive(a):
                if ep is None:
                    ep = {"open": a, "visits": [], "last_pos": a}
                ep["visits"].append(visit(a))
                ep["last_pos"] = a
            elif ep is not None and negative(a):
                ep["visits"].append(visit(a))
                records.append(make(ep, a, key, fetched_at, now))
                ep = None
            elif ep is not None:
                ep["visits"].append(visit(a))
            else:
                quiet += 1
        if ep is not None:
            records.append(make(ep, None, key, fetched_at, now))
    records.sort(key=lambda r: (r.get("started_at") or "", r["event_id"]), reverse=True)
    stats = {"visits": len(features), "sites": len(sites), "visits_without_bloom": quiet,
             "by_status": dict(Counter(r["status"] for r in records))}
    return records, stats


def make(ep: dict, lift: dict | None, key: str, fetched_at: str, now: datetime) -> dict:
    a = ep["open"]
    last = ep["last_pos"]
    start, last_t = utc_time(a.get("SampleDateTime")), utc_time(last.get("SampleDateTime"))
    # a site named by a street address ("Sample Lake - 12 Sample Lane") is often a resident's dock: the house number
    # is not published (common.strip_house_numbers); the visits are grouped by the site as DEP names it
    site = strip_house_numbers(a["locationString"]) if isinstance(a.get("locationString"), str) else a.get("locationString")
    if site != a.get("locationString"):
        key = site_key({**a, "locationString": site})
    raw = {"site": site, "site_key": key, "county": a.get("County"),
           "group": a.get("MonitoringGroupPublicFacing"), "visits": ep["visits"], "basis": BASIS}
    if lift is not None:
        status, ended = "advisory_lifted", iso(utc_time(lift.get("SampleDateTime")))
        raw["ended_at_basis"] = "the next visit found no bloom and no toxin"
    elif last_t and now - last_t > timedelta(days=STALE_DAYS):
        status, ended = "unknown", None
        raw["note"] = f"no later visit reported (latest bloom or toxin result {last_t.date().isoformat()})"
    else:
        status, ended = "advisory_active", None
    lat, lon = a.get("esrignss_latitude"), a.get("esrignss_longitude")
    if lat is None or lon is None or not (FL_BOX[0] <= lon <= FL_BOX[2] and FL_BOX[1] <= lat <= FL_BOX[3]):
        if lat is not None:
            raw["_coords_rejected"] = {"lat": lat, "lon": lon, "why": "not in Florida"}
        lat = lon = None
    taxa = "; ".join(dict.fromkeys(v["taxa"] for v in ep["visits"] if v.get("taxa") and v["taxa"] != "not received"))
    return event(
        source_id=SOURCE_ID, source_record_id=str(a.get("globalid") or a.get("objectid")), fetched_at=fetched_at,
        source_url=f"{LAYER}/query?where=globalid%3D%27{a.get('globalid')}%27&outFields={','.join(FIELDS)}&f=json",
        event_type="hab_advisory", status=status,
        waterbody_text=water_name(site), water_slugs=[], water_match="none",
        outfall_name=site,
        lat=lat, lon=lon, coord_source="source" if lat is not None else None, coord_precision_m=10 if lat is not None else None,
        started_at=iso(start), ended_at=ended, time_precision="minute",
        reported_at=None, published_at=None, source_updated_at=iso(last_t),
        material=f"algal bloom ({taxa})" if taxa else "algal bloom",
        authority=AUTHORITY, advice_text=None, raw=raw,
    )


def query_layer(sess: requests.Session) -> list[dict]:
    feats, offset = [], 0
    while True:
        params = {"where": "1=1", "outFields": ",".join(FIELDS), "returnGeometry": "false", "orderByFields": "objectid",
                  "resultOffset": offset, "resultRecordCount": 2000, "f": "json"}
        r = sess.get(f"{LAYER}/query", params=params, timeout=(15, 120))
        r.raise_for_status()
        d = r.json()
        if "error" in d:
            raise RuntimeError(f"ArcGIS error: {d['error']}")
        got = [f.get("attributes") or {} for f in d.get("features") or []]
        feats += got
        if not got or (not d.get("exceededTransferLimit") and len(got) < 2000) or offset > 200_000:
            break
        offset += len(got)
    return feats


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--file", help="read this saved query response instead of the layer")
    args = ap.parse_args(argv)
    fetched_at = now_iso()
    try:
        if args.file:
            d = json.loads(Path(args.file).read_text())
            features = [f.get("attributes") or {} for p in (d.get("pages") or [d]) for f in p.get("features") or []]
        else:
            sess = requests.Session()
            sess.headers.update(HEADERS)
            features = query_layer(sess)
    except Exception as e:  # noqa: BLE001
        write_events(SOURCE_ID, [], ok=False, error=f"{type(e).__name__}: {e}")
        print(f"{SOURCE_ID}: FAILED {e}", file=sys.stderr)
        return 1
    features = [{k: a.get(k) for k in FIELDS} for a in features]
    state = read_json(STATE_FILE, {}) or {}
    raw_path = state.get("raw_path")
    if not args.file:
        sha = hashlib.sha256(json.dumps(features, sort_keys=True).encode()).hexdigest()
        if sha != state.get("sha256"):
            raw_path = str(save_raw(SOURCE_ID, json.dumps({"layer": LAYER, "features": features}), "json").relative_to(ROOT))
            state = {"sha256": sha, "raw_path": raw_path}
        state["fetched_at"] = fetched_at
        write_json(STATE_FILE, state)
    records, stats = build(features, fetched_at)
    meta = {**stats, "layer": LAYER, "raw_path": raw_path, "credit": CREDIT, "basis": BASIS,
            "registry_ids": ["fl-dep-algal-bloom"]}
    path_notes_to_meta(records, meta)
    path = write_events(SOURCE_ID, records, ok=True, error=None, meta=meta)
    print(f"{SOURCE_ID}: {stats['visits']} visits at {stats['sites']} sites -> {len(records)} bloom records "
          f"{stats['by_status']} -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
