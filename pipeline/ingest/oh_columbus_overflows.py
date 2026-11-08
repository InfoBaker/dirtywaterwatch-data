"""City of Columbus sewer overflow discharge information (SSO and CSO) -> data/build/events/oh-columbus-sewer-overflow.json.

Source (registry oh-columbus-sewer-overflow; research/oh/report.md section 2.3, where the city's page answered 403 on
2026-11-03; it answered 200 on 2026-11-08 at its new address under Columbus Water & Power)
  The city's "Sewer Overflow Discharge Information (SSOCSO)" map and dashboard (https://columbus.maps.arcgis.com/apps/
  dashboards/24f57525213544e7b1ed6da19baf36a1, linked as "View Overflow Map" from the city's Sewer Overflow FAQs) read
  the service https://maps2.columbus.gov/arcgis/rest/services/Applications/SSOCSO/MapServer, no token:
    layer 0 "Overflow Location": 52 discharge points (DISCHARGE, OVERFLOW_TYPE, LABEL, DISCHARGELOCATION, NODEID);
    table 2 "Events": one row per overflow the city recorded (8,542 on 2026-11-08: 4,462 CSO, 4,080 SSO, 2002 to
    2026-09-29), with DISCHARGE_ID, TYPE, DISCHARGE_LOCATION, RELIEF_LOCATION, INSPECTION_DATE ("04/01/2026"),
    INSPECTION_YEAR, VOLUME (the dashboard's column title: "Volume (MG)"; empty on 3,800 rows) and NPDES_ID (Ohio
    EPA's outfall station code, "4PF00001006", on CSO rows).
  Fields read: those above. Not read: table 1 (annual counts, derived from table 2), POINT_X, POINT_Y and GLOBALID
  (copies and keys). No field names a person; DISCHARGE_LOCATION is a description of the outfall ("Rush Run at 36
  inch storm sewer r/o 1234 Example Springs"): a house number in it is cut (oh_neorsd_cso.scrub_location).

Records
  - One record per event row: event_type cso or sso from TYPE; source_record_id "<type>-<discharge id>:<date>" and,
    where the city lists more than one row for a site on one day (749 such groups), ":<station suffix>" (CSO rows),
    else ":<relief location>", with "-<n>" only if those still repeat (stable if the city inserts a row).
  - started_at the inspection date (day precision, America/New_York, raw.time_zone): the day the city found the
    overflow; it occurred on or before that day (raw.start_basis, and the authority line says so). No end: the table
    gives none, so none is invented (status unknown).
  - volume_gal from million gallons where VOLUME is given (estimate_flag unknown: the city does not say how it is
    measured); raw.volume_mg as given.
  - Operator: every row (SSO rows too) carries the City of Columbus's operator id (OPERATOR_ID). Permit and outfall
    by Ohio EPA's station code (STATION_PERMITS): "4PF00000<nnn>" is outfall nnn of OH0024732 (Jackson Pike; all 28
    suffixes are open CSO outfalls of that permit in EPA's inventory) and "4PF00001006" is outfall 006 of OH0024741
    (Southerly; its only CSO outfall in EPA's inventory). raw.permit_basis says so. SSO rows carry no station code:
    no permit, outfall_id "SSO <discharge id>".
  - Place: the site's point from layer 0 by discharge id and type, a site typed "CSO/SSO" serving both (coord_source
    source; all 50 sites with events have one), else EPA's permitted-feature point for the paired outfall (coord_source outfall_layer; never a plant's
    point); waterbody_text the water the location text starts with ("Scioto River at ...", "Alum Creek at ..."), else
    none (a ditch or a manhole is no named water). A site with neither is kept and placed nowhere.
  - advice_text the city's own words in its overflow map's description, quoted; the site's notes stay in raw.
  - Times: reported_at, published_at and source_updated_at null (the table gives none); fetched_at and
    raw._last_seen_in_source the poll. The city's item says the data is updated at least once a month, usually after
    the 15th, so a record can arrive weeks after the overflow.
  Privacy: only the fields above are requested; a house number in the location texts is cut before the raw save and
  before the records (scrubbed); common.event runs strip_personal.

Failures: a failed request writes ok=False and keeps the previous records.
Run from pipeline/: python -m ingest.oh_columbus_overflows [--points points.json --events e0.json [e1.json ...] --out x]
Cadence: daily with the refresh.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import requests

from common import DATA_DIR, HEADERS, event, now_iso, save_raw, write_events
from ingest.oh_neorsd_cso import scrub_location

SOURCE_ID = "oh-columbus-sewer-overflow"
SERVICE = "https://maps2.columbus.gov/arcgis/rest/services/Applications/SSOCSO/MapServer"
DASHBOARD = "https://columbus.maps.arcgis.com/apps/dashboards/24f57525213544e7b1ed6da19baf36a1"
POINT_FIELDS = ["OBJECTID", "DISCHARGE", "OVERFLOW_TYPE", "LABEL", "DISCHARGELOCATION", "NODEID"]
EVENT_FIELDS = ["OBJECTID", "DISCHARGE_ID", "TYPE", "DISCHARGE_LOCATION", "RELIEF_LOCATION", "INSPECTION_DATE",
                "INSPECTION_YEAR", "VOLUME", "NPDES_ID"]
TZ_NAME = "America/New_York"
PAGE = 1000
CREDIT = "City of Columbus, Sewer Overflow Discharge Information (SSOCSO)"
AUTHORITY = f"{CREDIT}; dated by the day the overflow was found at inspection"
START_NOTE = "the day the city found the overflow at inspection: it occurred on or before this day"
# the city's own words in its overflow map's description (read 2026-11-08), quoted as the record's advice
ADVICE = ("To avoid any possible health effects from a sewer overflow, please avoid contact with the water near an SSO "
          "or CSO discharge location, particularly after a rain storm.")
WATER_AT = re.compile(r"^((?:[A-Z][\w.'-]*\s+){0,3}(?:River|Creek|Run|Brook|Ditch|Fork|Lake|Reservoir|Ravine))\b"
                      r"(?=\s+(?:at|@|from|near|by|below|above|and|n/o|s/o|e/o|w/o|r/o)\b|\s*[,&/]|\s*$)")


def water_of(loc: str | None) -> str | None:
    m = WATER_AT.match((loc or "").strip())
    return m.group(1) if m and not re.match(r"(?i)^ditch\b", m.group(1)) else None


def _get(sess, url: str, params: dict) -> dict:
    r = sess.get(url, params={**params, "f": "json"}, timeout=(20, 300))
    r.raise_for_status()
    d = r.json()
    if "error" in d:
        raise ValueError(f"{url} answered an error: {d['error'].get('message')}")
    return d


def fetch(sess) -> tuple[list[dict], list[dict]]:
    pts = _get(sess, f"{SERVICE}/0/query", {"where": "1=1", "outFields": ",".join(POINT_FIELDS), "outSR": 4326})
    points = [scrubbed({**{k: (f.get("attributes") or {}).get(k) for k in POINT_FIELDS},
                        "_lat": (f.get("geometry") or {}).get("y"), "_lon": (f.get("geometry") or {}).get("x")})
              for f in pts.get("features") or []]
    events, off = [], 0
    while True:           # offset paging (the table answers an error to an object-id cursor past its first page)
        d = _get(sess, f"{SERVICE}/2/query", {"where": "1=1", "outFields": ",".join(EVENT_FIELDS),
                                              "orderByFields": "OBJECTID ASC", "resultOffset": off,
                                              "resultRecordCount": PAGE})
        got = d.get("features") or []
        events += [scrubbed({k: (f.get("attributes") or {}).get(k) for k in EVENT_FIELDS}) for f in got]
        if len(got) < PAGE:
            break
        off += PAGE
        if off > 200_000:
            raise ValueError("more than 200,000 rows: paging is not ending")
    return points, events


LOCATION_FIELDS = ("DISCHARGE_LOCATION", "RELIEF_LOCATION", "DISCHARGELOCATION")


def scrubbed(row: dict) -> dict:
    """The row with a house number cut from its location texts, before anything is saved (review P2-5)."""
    return {k: (scrub_location(v) if k in LOCATION_FIELDS and isinstance(v, str) else v) for k, v in row.items()}


def rows_of(doc, fields) -> list[dict]:
    if isinstance(doc, list):
        return [scrubbed(r) for r in doc]
    out = []
    for f in doc.get("features") or []:
        a = {k: (f.get("attributes") or {}).get(k) for k in fields}
        g = f.get("geometry")
        if g:
            a["_lat"], a["_lon"] = g.get("y"), g.get("x")
        out.append(scrubbed(a))
    return out


# Ohio EPA's station codes in NPDES_ID name the permit and outfall (read from public records, 2026-11-08): every
# "4PF00000<nnn>" suffix (28 of them, 004 to 051) is an open CSO outfall of OH0024732 (Jackson Pike) in EPA's
# inventory, and "4PF00001006", the only 4PF00001 code, is the only CSO outfall EPA lists for OH0024741 (Southerly).
STATION_PERMITS = {"4PF00000": "OH0024732", "4PF00001": "OH0024741"}
OPERATOR_ID = "oh-jackson-pike-water-resource-recovery-facility-oh0024732"     # City of Columbus (both permits)


def station_outfall(code) -> tuple[str | None, str | None]:
    m = re.fullmatch(r"(4PF0000[01])(\d{3})", str(code or "").strip())
    return (STATION_PERMITS[m.group(1)], m.group(2)) if m else (None, None)


def epa_points() -> dict[tuple[str, str], dict]:
    """EPA's permitted-feature points of the two permits' outfalls (never a facility point)."""
    try:
        rows = json.loads((DATA_DIR / "outfalls-us.json").read_text())["outfalls"]
    except (OSError, ValueError, KeyError):
        return {}
    return {(r["npdes_permit"], r["outfall"]): r for r in rows if r.get("npdes_permit") in STATION_PERMITS.values()
            and r.get("coords_from") == "permitted_feature" and r.get("lat") is not None}


def _slug(s) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", str(s or "").lower())).strip("-")


def day_of(v) -> str | None:
    try:
        return datetime.strptime(str(v or "").strip(), "%m/%d/%Y").date().isoformat()
    except ValueError:
        return None


def run(points: list[dict], events: list[dict], now: str, epa: dict | None = None) -> tuple[list[dict], dict]:
    epa = epa_points() if epa is None else epa
    where = {}
    for p in points:
        try:
            num = int(p["DISCHARGE"])
        except (TypeError, ValueError, KeyError):
            continue
        # a site the city types "CSO/SSO" (CSO/SSO 1 at the Greenlawn dam, CSO/SSO 6 north of S.R. 104) is the
        # point of both its CSO and its SSO rows (Ohio go-live audit P2-3: 705 SSO rows had no point)
        for typ in str(p.get("OVERFLOW_TYPE") or "").upper().split("/"):
            if typ.strip():
                where.setdefault((num, typ.strip()), p)
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for e in events:
        groups[(str(e.get("TYPE") or "").upper(), e.get("DISCHARGE_ID"), e.get("INSPECTION_DATE"))].append(e)
    recs = []
    for (typ, did, _), rows in groups.items():
        rows.sort(key=lambda e: e.get("OBJECTID") or 0)
        seen: dict[str, int] = defaultdict(int)
        for e in rows:
            day = day_of(e.get("INSPECTION_DATE"))
            if typ not in ("CSO", "SSO") or did is None or not day:
                continue
            key = f"{typ.lower()}-{did}:{day}"
            if len(rows) > 1:      # one site, one day, several rows: told apart by the station, else the relief point
                tag = str(e.get("NPDES_ID") or "").strip()[-3:] or _slug(e.get("RELIEF_LOCATION")) or "row"
                seen[tag] += 1
                key += f":{tag}" + (f"-{seen[tag]}" if seen[tag] > 1 else "")
            p = where.get((int(did), typ)) or {}
            permit, outfall = station_outfall(e.get("NPDES_ID"))
            ep = epa.get((permit, outfall)) if permit else None
            loc = scrub_location(e.get("DISCHARGE_LOCATION"))
            relief = scrub_location(e.get("RELIEF_LOCATION")) or None
            vol = e.get("VOLUME")
            gal = int(round(vol * 1_000_000)) if isinstance(vol, (int, float)) and vol > 0 else None
            if p.get("_lat") is not None:
                lat, lon, cs = p["_lat"], p["_lon"], "source"
            elif ep:
                lat, lon, cs = ep["lat"], ep["lon"], "outfall_layer"
            else:
                lat = lon = cs = None
            raw = {"row": {**{k: e.get(k) for k in EVENT_FIELDS}, "DISCHARGE_LOCATION": loc, "RELIEF_LOCATION": relief},
                   "time_zone": TZ_NAME, "state": "OH", "_last_seen_in_source": now,
                   "start_basis": START_NOTE, "end_note": "the table gives no end", "volume_mg": vol,
                   "ohio_epa_station": e.get("NPDES_ID") or None, "site_label": p.get("LABEL")}
            if permit:
                raw["permit_basis"] = (f"Ohio EPA station {e.get('NPDES_ID')} is outfall {outfall} of {permit} "
                                       "(STATION_PERMITS)")
            if cs == "outfall_layer":
                raw["place_note"] = "the city's map gives no point for this site: EPA's point for the outfall"
            elif cs is None:
                raw["place_note"] = "the city's map gives no point for this discharge site"
            recs.append(event(
                source_id=SOURCE_ID, source_record_id=key, event_type=typ.lower(), status="unknown",
                discharger_id=OPERATOR_ID, discharger_name="City of Columbus", npdes_permit=permit,
                outfall_id=outfall or f"{typ} {did}", outfall_name=loc, waterbody_text=water_of(loc),
                lat=lat, lon=lon, coord_source=cs,
                started_at=day, ended_at=None, time_precision="day", reported_at=None, published_at=None,
                source_updated_at=None, fetched_at=now,
                material="combined sewage and stormwater" if typ == "CSO" else "sanitary sewage",
                volume_gal=gal, volume_text=f"{vol:g} million gallons" if gal else None, estimate_flag="unknown",
                authority=AUTHORITY, advice_text=ADVICE, source_url=DASHBOARD, raw=raw))
    recs.sort(key=lambda r: (r["started_at"] or "", r["event_id"]), reverse=True)
    meta = {"registry_ids": [SOURCE_ID], "service": SERVICE, "points": len(points), "rows": len(events),
            "credit": CREDIT}
    return recs, meta


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--points")
    ap.add_argument("--events", nargs="+")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    now = now_iso()
    if a.points:
        if not (a.events and a.out):
            ap.error("--points needs --events and --out")
        pts = rows_of(json.loads(Path(a.points).read_text()), POINT_FIELDS)
        evs = [r for f in a.events for r in rows_of(json.loads(Path(f).read_text()), EVENT_FIELDS)]
        recs, meta = run(pts, evs, now)
        write_events(SOURCE_ID, recs, meta=meta, path=Path(a.out))
        print(f"{SOURCE_ID}: {len(recs)} records (file) -> {a.out}")
        return 0
    sess = requests.Session()
    sess.headers.update(HEADERS)
    try:
        pts, evs = fetch(sess)
        if not evs:
            raise ValueError("the events table answered no rows")
    except (requests.RequestException, ValueError) as e:
        write_events(SOURCE_ID, [], ok=False, error=f"service: {type(e).__name__}: {e}")
        print(f"{SOURCE_ID}: FAILED {e}", file=sys.stderr)
        return 1
    save_raw(SOURCE_ID, json.dumps({"points": pts, "events": evs}), "json")
    recs, meta = run(pts, evs, now)
    path = write_events(SOURCE_ID, recs, meta=meta)
    print(f"{SOURCE_ID}: {len(recs)} records -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
