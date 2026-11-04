"""CT DEEP bypass and CSO reporting archives, 2016-07 to 2021-11 -> data/build/events/ct-deep-archive.json.

Source
------
Two hosted feature services in CT DEEP's ArcGIS Online organisation (FjPcSmEFuDYlIdKC), the
archive of the reporting system DEEP used before the QAlert/Zoho Performance Dashboard
(ingest/ct_deep.py) took over on 2021-12-01. Both are frozen (no new events after 2021-11-30)
and carry no licence text.

  Bypass_Reporting_Archive_deepgis/FeatureServer/0  (layer deepgis.WPLR.BYPASS_ARCHIVE): SSOs and
      bypasses, START_DATETIME 2016-07-05 to 2021-11-30, about 2,956 records.
  CSO_Reporting_Archive_deepgis/FeatureServer/0     (layer deepgis.WPLR.CSO_ARCHIVE): CSO reports by
      regulator group, 2016-07 to 2021-11-26, about 3,986 records.

Request mechanics: plain ArcGIS REST queries, no login: where=1=1, outSR=4326,
returnGeometry=true, orderByFields=OBJECTID, resultOffset/resultRecordCount pages of 1,000 (the
layers' maxRecordCount). outFields lists every field except the personal ones (USER_NAME,
EMAIL, PHONE_NUMBER, Creator, Editor), so reporter names, emails and phones are never
downloaded; free text (COMMENTS, NOTES, BYPASS_DISCOVERY) is also scrubbed of phone numbers and
email addresses. Every response page is saved with save_raw().

Normalisation (docs/plan.md section 3)
- event_type by layer: the CSO layer -> cso; the bypass layer -> sso, or plant_bypass when the
  incident type is an NPDES permitted bypass or the location is "Treatment Plant" (the same rule
  as ingest/ct_deep.py, so the two files agree).
- Coordinates: the feature geometry (projected to WGS84 by the server), not the LATITUDE /
  LONGITUDE attribute columns, which often hold the form's default point (41.12598367,
  -73.39137436). A geometry that is itself that default point is not used (coordinates null,
  noted in raw._dww_note): the pin was never moved, so it says nothing about the location.
- Times: the date fields are epoch milliseconds, read as UTC (hosted-service storage) and
  written in America/New_York; minute precision. Dates before 2000 (the CSO layer has a few
  "175x" values) are kept as a parse_error with started_at null.
- Status: ended when a stop time is given, else unknown (the archive is closed: a report with
  no stop time is not evidence of an ongoing discharge).
- Volume: FINAL_VOLUME when it parses, else the binned ESTIMATED_VOLUME / CSO_VOLUME ("51 - 500
  gallons", "20,001 - 50,000 gallons"), which is a range: volume_text kept, volume_gal null.
- Waters: RECEIVING_WATER_BODY matched by name within CT (ingest/ct_deep.match_ct_waters); a
  bypass with REACH_WATER_BODY "No" gets no slug. reported_at = CreationDate and
  source_updated_at = EditDate where the layer has them. No advice text in either layer.

Cadence: none needed (frozen archive); run once, or again only if DEEP republishes the layers.

Run from pipeline/: python -m ingest.ct_deep_archive
"""
from __future__ import annotations

import json
import sys
import time
from collections import Counter
from datetime import UTC, datetime, timedelta

import requests

from common import HEADERS, event, now_iso, save_raw, write_events
from ingest.ct_deep import (TZ, clean, discharger_for, match_ct_waters, midnight_end, scrub, volume)

SOURCE_ID = "ct-deep-archive"
BASE = "https://services1.arcgis.com/FjPcSmEFuDYlIdKC/arcgis/rest/services"
LAYERS = {
    "bypass": f"{BASE}/Bypass_Reporting_Archive_deepgis/FeatureServer/0",
    "cso": f"{BASE}/CSO_Reporting_Archive_deepgis/FeatureServer/0",
}
PERSONAL = {"USER_NAME", "EMAIL", "PHONE_NUMBER", "Creator", "Editor"}
DEFAULT_POINT = (41.12598, -73.39137)   # the reporting form's default pin (5 dp)
PAGE = 1000


def utility_key(label: str | None) -> str | None:
    """CSO-layer utility labels ('City of Bridgeport WPCA - West Side WPCF', 'The Metropolitan
    District') -> the ingest/ct_deep.DISCHARGERS key."""
    l = (label or "").lower()
    for words, key in ((("bridgeport", "west"), "bridgeport west side"), (("bridgeport", "east"), "bridgeport east side"),
                       (("metropolitan district",), "mdc"), (("norwich",), "norwich"), (("new haven",), "greater new haven"),
                       (("waterbury",), "waterbury"), (("norwalk",), "norwalk")):
        if all(w in l for w in words):
            return key
    return None


def get(session: requests.Session, url: str, params: dict) -> dict:
    last = None
    for attempt in range(4):
        try:
            r = session.get(url, params=params, timeout=120)
            if r.status_code == 200:
                d = r.json()
                if "error" not in d:
                    return d | {"_content": r.content}
                last = f"ArcGIS error {d['error']}"
            else:
                last = f"HTTP {r.status_code}"
        except (requests.RequestException, ValueError) as e:
            last = f"{type(e).__name__}: {e}"
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"{url}: {last}")


def fetch_layer(session: requests.Session, name: str) -> list[dict]:
    url = LAYERS[name]
    meta = get(session, url, {"f": "json"})
    save_raw(SOURCE_ID, meta.pop("_content"), f"{name}-layer.json")
    fields = [f["name"] for f in meta["fields"] if f["name"] not in PERSONAL]
    feats, offset = [], 0
    while True:
        d = get(session, f"{url}/query", {"where": "1=1", "outFields": ",".join(fields), "returnGeometry": "true",
                                          "outSR": 4326, "orderByFields": "OBJECTID", "resultOffset": offset,
                                          "resultRecordCount": PAGE, "f": "json"})
        save_raw(SOURCE_ID, d.pop("_content"), f"{name}-o{offset:05d}.json")
        batch = d.get("features") or []
        feats += batch
        print(f"  {name}: offset {offset} -> {len(batch)}", file=sys.stderr)
        if len(batch) < PAGE and not d.get("exceededTransferLimit"):
            break
        offset += len(batch)
        if not batch:
            break
    return feats


def ms_iso(v) -> tuple[str | None, str | None]:
    """(iso in America/New_York, error)"""
    if v is None:
        return None, None
    try:
        dt = datetime.fromtimestamp(v / 1000, UTC)
    except (TypeError, ValueError, OverflowError, OSError):
        return None, f"bad date value {v!r}"
    if dt.year < 2000:
        return None, f"date out of range ({dt.date().isoformat()})"
    return dt.astimezone(TZ).replace(microsecond=0).isoformat(), None


FUTURE_START_H = 24        # build/status.py FUTURE_START_H, the same limit: its start sets no status
MAX_DURATION_DAYS = 366


def date_notes(started: str | None, ended: str | None, fetched: str) -> list[str]:
    """Notes for dates the source cannot mean, kept as written: a start more than FUTURE_START_H hours after the fetch
    time ("start is in the future as published"), and a stop more than a year after the start (bypass-35964743: started
    2017-05-15, stopped 2107-05-15)."""
    notes = []
    st = datetime.fromisoformat(started) if started else None
    if st and st > datetime.fromisoformat(fetched.replace("Z", "+00:00")) + timedelta(hours=FUTURE_START_H):
        notes.append(f"start is in the future as published: {started} is more than {FUTURE_START_H} hours after the "
                     f"record was fetched ({fetched}); kept as written")
    if st and ended and datetime.fromisoformat(ended) > st + timedelta(days=MAX_DURATION_DAYS):
        notes.append(f"stop is more than a year after the start as published ({ended}); kept as written")
    return notes


def normalise(layer: str, feat: dict, fetched: str, code_labels: dict | None = None) -> dict:
    a = dict(feat.get("attributes") or {})
    g = feat.get("geometry") or {}
    notes, errors = [], []
    raw = scrub({k: v for k, v in a.items() if k not in PERSONAL})
    raw["_layer"] = LAYERS[layer]
    oid = a.get("OBJECTID")
    if oid is None:
        errors.append("no OBJECTID")
    if layer == "cso":
        start_v, stop_v = a.get("START_FLOW_DATETIME"), a.get("STOP_FLOW_DATETIME")
        label = clean(a.get("UTILITY_LABEL"))
        if not label and (code_labels or {}).get(a.get("UTILITY_NAME")):
            label = code_labels[a["UTILITY_NAME"]]
            notes.append(f"UTILITY_LABEL blank: utility from UTILITY_NAME code {a['UTILITY_NAME']}, "
                         f"which every labelled row of this layer gives as {label!r}")
        town = clean(a.get("CSO_TOWN"))
        etype = "cso"
        outfall = clean(a.get("REGULATOR"))
        wtext = clean(a.get("RECEIVING_WATER_BODY"))
        reach = None
        vol, vtext, vflag = volume(None, a.get("CSO_VOLUME"))
        material = None
    else:
        start_v, stop_v = a.get("START_DATETIME"), a.get("STOP_DATETIME")
        label = clean(a.get("UTILITY_NAME"))
        town = clean(a.get("REPORTING_TOWN"))
        itype = " ".join(x for x in (clean(a.get("INCIDENT_TYPE1")), clean(a.get("INCIDENT_TYPE2"))) if x)
        loc = clean(a.get("BYPASS_LOCATION"))
        etype = "plant_bypass" if ("permitted" in itype.lower() or (loc or "").lower() == "treatment plant") else "sso"
        outfall = ", ".join(x for x in (loc, clean(a.get("STREET_ADDRESS"))) if x) or None
        wtext = clean(a.get("RECEIVING_WATER_BODY"))
        reach = clean(a.get("REACH_WATER_BODY"))
        vol, vtext, vflag = volume(a.get("FINAL_VOLUME"), a.get("ESTIMATED_VOLUME"), None, a.get("BYPASS_VOLUME_EST"))
        material = clean(a.get("BYPASS_TYPE"))
    started, e1 = ms_iso(start_v)
    ended, e2 = ms_iso(stop_v)
    if e1:
        errors.append(f"start: {e1}")
    if e2:
        errors.append(f"stop: {e2}")
    if start_v is None:
        errors.append("no start time")
    ended, mnote = midnight_end(started, ended)      # a date-only stop (00:00, no STOP_TIME) on the start's day
    if mnote:
        notes.append(mnote.replace("end given", "stop given"))
    if started and ended and datetime.fromisoformat(ended) < datetime.fromisoformat(started):
        notes.append("stop is before start in the source")
    notes += date_notes(started, ended, fetched)
    status = "ended" if ended else "unknown"

    lat = lon = None
    try:
        x, y = float(g["x"]), float(g["y"])
        if (round(y, 5), round(x, 5)) == DEFAULT_POINT:
            notes.append("geometry is the reporting form's default point (41.12598, -73.39137): not used")
        elif 40.9 <= y <= 42.1 and -73.8 <= x <= -71.7:
            lat, lon = round(y, 6), round(x, 6)
        else:
            notes.append(f"geometry outside Connecticut ({y:.5f}, {x:.5f}): not used")
    except (KeyError, TypeError, ValueError):
        notes.append("no geometry")

    slugs = []
    if wtext:
        if reach and reach.lower() == "no":
            notes.append("source says the discharge did not reach a waterbody (REACH_WATER_BODY: No): no water assigned")
        else:
            slugs, wnotes = match_ct_waters(wtext, town)
            notes += wnotes
            if not slugs:
                notes.append(f"receiving water {wtext!r} has no matching water record")

    key = utility_key(label)
    did, dname, npdes = discharger_for(key or label)
    if key:
        dname = label
    reported, _ = ms_iso(a.get("CreationDate"))
    updated, _ = ms_iso(a.get("EditDate"))
    if notes:
        raw["_dww_note"] = notes
    return event(
        source_id=SOURCE_ID, source_record_id=f"{layer}-{oid}", event_type=etype, status=status,
        discharger_id=did, discharger_name=dname, npdes_permit=npdes, outfall_name=outfall,
        waterbody_text=wtext, water_slugs=slugs, water_match="name" if slugs else "none",
        lat=lat, lon=lon, coord_source="source" if lat is not None else None,
        started_at=started, ended_at=ended, time_precision="minute" if started else None,
        reported_at=reported, source_updated_at=updated, fetched_at=fetched,
        material=material, volume_gal=vol, volume_text=vtext, estimate_flag=vflag,
        authority=f"{dname or label or town or 'Permittee not named'} (CT DEEP reporting archive 2016-2021)",
        source_url=LAYERS[layer], raw=raw, parse_error="; ".join(errors) or None,
    )


def main(argv=None) -> int:
    fetched = now_iso()
    s = requests.Session()
    s.headers.update(HEADERS)
    feats = {}
    try:
        for layer in LAYERS:
            feats[layer] = fetch_layer(s, layer)
    except Exception as e:
        print(f"ct_deep_archive: fetch failed: {type(e).__name__}: {e}", file=sys.stderr)
        write_events(SOURCE_ID, [], ok=False, error=f"{type(e).__name__}: {e}")
        return 1
    # CSO layer: UTILITY_NAME is a code; learn its label from the rows that carry both (one label per code)
    seen = {}
    for f in feats.get("cso", []):
        a = f.get("attributes") or {}
        if clean(a.get("UTILITY_LABEL")) and a.get("UTILITY_NAME") is not None:
            seen.setdefault(a["UTILITY_NAME"], set()).add(utility_key(a["UTILITY_LABEL"]) or a["UTILITY_LABEL"])
    code_labels = {}
    for code, keys in seen.items():
        if len(keys) == 1:
            labels = Counter(clean((f.get("attributes") or {}).get("UTILITY_LABEL")) for f in feats["cso"]
                             if (f.get("attributes") or {}).get("UTILITY_NAME") == code)
            labels.pop(None, None)
            code_labels[code] = labels.most_common(1)[0][0]
    records = []
    for layer, fs in feats.items():
        for f in fs:
            try:
                records.append(normalise(layer, f, fetched, code_labels))
            except Exception as e:  # never drop a record
                a = (f.get("attributes") or {})
                records.append(event(source_id=SOURCE_ID, source_record_id=f"{layer}-{a.get('OBJECTID')}", fetched_at=fetched,
                                     source_url=LAYERS[layer], authority="CT DEEP reporting archive 2016-2021",
                                     raw=scrub({k: v for k, v in a.items() if k not in PERSONAL}),
                                     parse_error=f"{type(e).__name__}: {e}"))
    records.sort(key=lambda r: (r.get("started_at") or "", r["event_id"]), reverse=True)
    meta = {"layers": LAYERS, "features": {k: len(v) for k, v in feats.items()}, "cso_utility_codes": code_labels,
            "counts": {"by_type": dict(Counter(r["event_type"] for r in records)),
                       "by_status": dict(Counter(r["status"] for r in records)),
                       "with_coords": sum(r["lat"] is not None for r in records),
                       "with_slugs": sum(bool(r["water_slugs"]) for r in records),
                       "parse_errors": sum(bool(r["parse_error"]) for r in records)}}
    path = write_events(SOURCE_ID, records, ok=True, meta=meta)
    print(f"ct_deep_archive: {len(records)} records -> {path}", file=sys.stderr)
    print(json.dumps(meta["counts"]), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
