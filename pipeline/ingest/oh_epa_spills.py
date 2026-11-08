"""Ohio EPA spills layer (Office of Emergency Response), sewage rows -> data/build/events/oh-epa-spills-opendata.json.

Source (registry oh-epa-spills-opendata; research/oh/report.md section 2.2)
  https://geo.epa.ohio.gov/arcgis/rest/services/EmergResponse/Spills2_OpenData/MapServer, no token, "updated daily":
  layer 0 Spills_CurrentYear and layer 1 Spills_PreviousYears (from 2017). Every incident called in to Ohio EPA's
  emergency response line, with a case number, the reported product, amount and unit, the spill's day (spilldom,
  spillmonthnum, spillyear), the county, the report time (reporteddate), a point (latitude, longitude), the Ohio EPA
  district, the city or township ("28/CHESTER TWP": Ohio's county number, then the place) and the waterway ("25 -
  Alum Creek": the county number, then the water; "NULL" when none). No operator, no start time, no end.
  Credit: "Office of Emergency Response, Ohio Environmental Protection Agency"; no licence is stated.

  Rows kept (where clause, rules only): reportedproduct "SEWAGE HUMAN", "SEWAGE SLUDGE / BIOSOLIDS" and "WASTE
  WATER" (on 2026-11-08: 71, 31 and 20 in 2026; 620, 166 and 238 in 2017 to 2025). WASTE WATER is kept because the
  layer says nothing about whose or what kind of wastewater it is (98 of its 258 rows name a stream, amounts reach
  765,000 gallons): it may be a sewer release, so it is shown with the product stated (raw.product_note), never
  read as an industrial discharge. Not kept: "AIR ODOR SEWAGE" (3 and 23: an odour, not a discharge), manure, fats
  and grease, lime and other non-sewage sludges. The product code is the whole rule (the layer carries no free text).
  Fields read: objectid, casenumber, reportedproduct, reportedamount, reporteduom, recovamount, recovunit, spilldom,
  spillmonthnum, spillyear, county, reporteddate, latitude, longitude, oepadist, city_twn, waterway. Not read:
  spillmonth and spilldoy (copies of the day), locatedxy (a flag), recovproducttype. No field names a person.

Records (a supplementary source)
  - One sso record per case: source_record_id the case number; status unknown; started_at the spill's day
    (time_precision day, read in America/New_York, raw.time_zone); ended_at null (the layer gives no end: never
    invented); reported_at the time of the call (reporteddate: Ohio's wall clock stored as if UTC, read in
    America/New_York, raw.time_note); published_at and
    source_updated_at null (not given); raw._last_seen_in_source the poll.
  - material from the product ("human sewage", "sewage sludge / biosolids", or waste water with its uncertainty); volume_gal when the unit is gallons and
    the amount is above zero, else volume_text keeps what was given ("not given" for 0 with no unit).
  - Place: the layer's point (coord_source source, raw.county the county). waterbody_text the waterway with its
    county number cut ("Alum Creek"); "NULL", "UNNAMED" and "99 - UNNAMED" are no water (raw.waterway_note). A
    report whose point lies outside the county it gives (15 of 1,121 on 2026-11-08, 3 of them outside Ohio) keeps
    the point in raw.point_not_used only and is placed by its county and named water (Ohio go-live audit P3-4). A
    report with a named water is placed on it, county-aware (pipeline/build/status.py COUNTY_STATES, the county of
    the report's point); one without is placed from its point by the status build's rules. Never geocoded from the
    place text.
  - raw.limits on every record: what the layer does and does not say (the call-in reports only, no operator, no
    start or end, the waterway mostly empty). advice_text null: the layer gives no advice.
  Privacy: only the fields above are requested; the raw save holds only them; common.event runs strip_personal.

Failures: a failed request writes ok=False and keeps the previous records.
Run from pipeline/: python -m ingest.oh_epa_spills [--file layer0.json --file layer1.json --out events.json]
Cadence: daily (with the refresh; the layer is updated daily).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from common import DATA_DIR, HEADERS, event, now_iso, read_json, save_raw, write_events

SOURCE_ID = "oh-epa-spills-opendata"
SERVICE = "https://geo.epa.ohio.gov/arcgis/rest/services/EmergResponse/Spills2_OpenData/MapServer"
LAYERS = (0, 1)
SAFE_FIELDS = ["objectid", "casenumber", "reportedproduct", "reportedamount", "reporteduom", "recovamount", "recovunit",
               "spilldom", "spillmonthnum", "spillyear", "county", "reporteddate", "latitude", "longitude", "oepadist",
               "city_twn", "waterway"]
WHERE = ("reportedproduct LIKE 'SEWAGE HUMAN%' OR reportedproduct LIKE 'SEWAGE SLUDGE%' OR "
         "reportedproduct LIKE 'WASTE WATER%'")
PRODUCTS = {"SEWAGE HUMAN": "human sewage", "SEWAGE SLUDGE / BIOSOLIDS": "sewage sludge / biosolids",
            "WASTE WATER": ("waste water (Ohio EPA's product code; it may be treated or untreated sewage or industrial "
                            "wastewater)")}
PRODUCT_NOTES = {
    "WASTE WATER": ("Ohio EPA's product code says waste water, not sewage: the layer does not say whose or what kind; "
                    "kept as a possible sewage release, with the product stated"),
    "SEWAGE SLUDGE / BIOSOLIDS": ("sewage sludge or biosolids: a spill from a truck, a tank or land application is "
                                  "not a sewer overflow, though it is counted with the sewage reports"),
}
TIME_NOTE = ("reporteddate read as Ohio's wall clock: the layer stores the Eastern time of the call in the "
             "milliseconds' UTC fields (it declares no time zone; read as UTC, the calls would fall four to five hours "
             "early, before Ohio's office hours)")
TZ_NAME = "America/New_York"
PAGE_SIZE = 1000
CREDIT = "Office of Emergency Response, Ohio Environmental Protection Agency"
AUTHORITY = "Ohio EPA, Office of Emergency Response (a spill called in to the state)"
LIMITS = ("A spill called in to Ohio EPA's emergency response line. The layer gives the spill's day, the report time "
          "and a point; it names no operator and gives no start time and no end, and it holds only the incidents "
          "called in, not every sewer overflow reported to Ohio EPA.")
NO_WATER = re.compile(r"^(?:null|none|unnamed|unknown|n/?a|)$", re.I)


def clean(v) -> str | None:
    s = " ".join(str(v if v is not None else "").split())
    return None if not s or s.upper() == "NULL" else s


def waterway(v) -> tuple[str | None, str | None]:
    """'25 - Alum Creek' -> ('Alum Creek', None); 'NULL', 'UNNAMED', '99 - UNNAMED' -> (None, why)."""
    s = clean(v)
    if not s:
        return None, "the layer names no waterway"
    name = re.sub(r"^\d{1,2}\s*-\s*", "", s).strip()
    if NO_WATER.match(name):
        return None, f"the layer's waterway reads {s!r}: no water named"
    return name.title() if name.isupper() else name, None


def place_name(v) -> str | None:
    s = clean(v)
    return re.sub(r"^\d{1,2}/", "", s).title() if s else None


def fetch(sess) -> dict[int, list[dict]]:
    out = {}
    for lid in LAYERS:
        feats, last = [], 0
        while True:
            r = sess.get(f"{SERVICE}/{lid}/query", timeout=(20, 300),
                         params={"where": f"({WHERE}) AND objectid > {last}", "outFields": ",".join(SAFE_FIELDS),
                                 "orderByFields": "objectid ASC", "resultRecordCount": PAGE_SIZE,
                                 "returnGeometry": "false", "f": "json"})
            r.raise_for_status()
            d = r.json()
            if "error" in d:
                raise ValueError(f"layer {lid} answered an error: {d['error']}")
            got = d.get("features") or []
            feats += got
            if not got or (len(got) < PAGE_SIZE and not d.get("exceededTransferLimit")):
                break
            last = max(f["attributes"]["objectid"] for f in got)
        out[lid] = [{k: (f.get("attributes") or {}).get(k) for k in SAFE_FIELDS} for f in feats]
    return out


def rows_of(doc) -> list[dict]:
    """A saved answer: either the layer's JSON or the filtered row list this module saves."""
    if isinstance(doc, list):
        return [{k: r.get(k) for k in SAFE_FIELDS} for r in doc]
    if not isinstance(doc.get("features"), list):
        raise ValueError("no features list in the layer's answer")
    return [{k: (f.get("attributes") or {}).get(k) for k in SAFE_FIELDS} for f in doc["features"]]


def spill_day(a: dict) -> tuple[str | None, str]:
    """(the spill's day, its basis): the layer's spill day; without one (two rows of 2021 give day 0), the report's
    local day, the spill having been on or before it."""
    try:
        return date(int(a["spillyear"]), int(a["spillmonthnum"]), int(a["spilldom"])).isoformat(), \
            "the spill's day as the layer gives it (no time of day)"
    except (TypeError, ValueError, KeyError):
        pass
    try:
        d = wall_clock(a["reporteddate"])
        if d is None:
            raise ValueError
        return d.date().isoformat(), "the layer gives no spill day: the day of the report (the spill was on or before it)"
    except (TypeError, ValueError, KeyError):
        return None, "the layer gives no spill day and no report time"


def wall_clock(ms) -> datetime | None:
    """reporteddate as Ohio's wall clock: the layer stores the Eastern time of the call as if it were UTC (it declares
    no dateFieldsTimeReference; read as UTC the calls peak at 08:00 to 17:00Z, Ohio's office hours, and 25 calls would
    fall on the day before the spill), so the milliseconds' UTC fields are the Eastern hour typed (TIME_NOTE)."""
    try:
        v = float(ms)
    except (TypeError, ValueError):
        return None
    if v <= 0:
        return None
    return datetime.fromtimestamp(v / 1000, UTC).replace(tzinfo=ZoneInfo(TZ_NAME))


def report_time(ms) -> str | None:
    t = wall_clock(ms)
    return t.isoformat(timespec="seconds") if t else None


def volume(a: dict) -> tuple[int | None, str | None]:
    amt, uom = a.get("reportedamount"), clean(a.get("reporteduom"))
    if isinstance(amt, (int, float)) and amt > 0:
        if uom and uom.upper() in ("GAL", "GALLONS"):
            return int(round(amt)), f"{amt:g} gallons"
        return None, f"{amt:g} {uom.lower() if uom else '(no unit given)'}"
    return None, "not given" if not uom or uom.upper() in ("NULL", "UNK") else f"0 {uom.lower()}"


COUNTIES = DATA_DIR / "reference" / "oh-counties.json"
_OUTLINES: list = []


def point_county(lat, lon) -> str | None:
    """The Ohio county (its name without "County") whose Census outline holds the point, or None (outside Ohio)."""
    if not _OUTLINES:
        from shapely.geometry import shape
        doc = read_json(COUNTIES, {}) or {}
        _OUTLINES.extend((re.sub(r"\s+County$", "", c["county"]), shape(c["geometry"])) for c in doc.get("counties") or [])
    from shapely.geometry import Point
    pt = Point(float(lon), float(lat))
    return next((n for n, g in _OUTLINES if g.covers(pt)), None)


def to_record(a: dict, now: str, rows: int = 1, products: list | None = None) -> dict | None:
    case = clean(a.get("casenumber"))
    if not case:
        return None
    product = clean(a.get("reportedproduct")) or ""
    start, start_basis = spill_day(a)
    water, why = waterway(a.get("waterway"))
    gal, vtext = volume(a)
    lat, lon = a.get("latitude"), a.get("longitude")
    county = clean(a.get("county"))
    off_county = None
    if isinstance(lat, (int, float)) and lat and isinstance(lon, (int, float)) and county:
        here = point_county(lat, lon)
        if here is None or here.lower() != county.lower():
            # Ohio go-live audit P3-4: the point is not in the county the report gives (17 of 1,121; 3 outside Ohio):
            # the point is kept in raw only, and the report is placed by its county and named water
            off_county = {"lat": lat, "lon": lon, "point_county": here or "outside Ohio"}
            lat = lon = None
    rec_amt = a.get("recovamount")
    raw = {"case": case, "product": product, "county": county, "district": clean(a.get("oepadist")),
           "place": place_name(a.get("city_twn")), "waterway": clean(a.get("waterway")),
           "reported_amount": a.get("reportedamount"), "reported_unit": clean(a.get("reporteduom")),
           "recovered": (f"{rec_amt:g} {(clean(a.get('recovunit')) or '').lower()}".strip()
                         if isinstance(rec_amt, (int, float)) and rec_amt > 0 else None),
           "time_zone": TZ_NAME, "time_note": TIME_NOTE, "state": "OH", "limits": LIMITS, "_last_seen_in_source": now,
           "start_basis": start_basis, "end_note": "the layer gives no end"}
    if rows > 1:
        raw["case_rows"] = rows
        raw["case_products"] = products
    if why:
        raw["waterway_note"] = why
    if off_county:
        where = ("outside Ohio" if off_county["point_county"] == "outside Ohio"
                 else f"in {off_county['point_county']} County")
        raw["point_not_used"] = {**off_county, "why": (f"the layer's point lies {where}, not in {county} County, the "
                                                         "county the report gives: placed by its county and named water")}
    note = PRODUCT_NOTES.get(product.upper())
    if note:
        raw["product_note"] = note
    return event(
        source_id=SOURCE_ID, source_record_id=case, event_type="sso", status="unknown",
        waterbody_text=water,
        lat=lat if isinstance(lat, (int, float)) and lat else None,
        lon=lon if isinstance(lon, (int, float)) and lon else None,
        coord_source="source" if isinstance(lat, (int, float)) and lat else None,
        started_at=start, ended_at=None, time_precision="day",
        reported_at=report_time(a.get("reporteddate")), published_at=None, source_updated_at=None, fetched_at=now,
        material=PRODUCTS.get(product.upper(), product.lower() or None), volume_gal=gal, volume_text=vtext,
        estimate_flag="unknown", authority=AUTHORITY, advice_text=None,
        source_url=SERVICE, raw=raw)


def run(layers: dict[int, list[dict]], now: str) -> tuple[list[dict], dict]:
    cases: dict[str, list[dict]] = {}
    for lid in LAYERS:          # a case can have a row per product line: one record per case, the first row's fields
        for a in layers.get(lid, []):
            cases.setdefault(clean(a.get("casenumber")) or "", []).append(a)
    recs = []
    for case, rows in cases.items():
        prods = sorted({clean(a.get("reportedproduct")) or "" for a in rows})
        r = to_record(rows[0], now, len(rows), prods) if case else None
        if r:
            recs.append(r)
    recs.sort(key=lambda r: (r["started_at"] or "", r["event_id"]), reverse=True)
    meta = {"registry_ids": [SOURCE_ID], "service": SERVICE, "where": WHERE, "credit": CREDIT, "limits": LIMITS,
            "rows": {str(k): len(v) for k, v in layers.items()}}
    return recs, meta


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", action="append", help="saved answers, layer 0 then layer 1 (needs --out)")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    now = now_iso()
    if a.file:
        if not a.out:
            ap.error("--file needs --out")
        layers = {lid: rows_of(json.loads(Path(f).read_text())) for lid, f in zip(LAYERS, a.file)}
        recs, meta = run(layers, now)
        write_events(SOURCE_ID, recs, meta=meta, path=Path(a.out))
        print(f"{SOURCE_ID}: {len(recs)} records (file) -> {a.out}")
        return 0
    sess = requests.Session()
    sess.headers.update(HEADERS)
    try:
        layers = fetch(sess)
    except (requests.RequestException, ValueError, KeyError) as e:
        write_events(SOURCE_ID, [], ok=False, error=f"layers: {type(e).__name__}: {e}")
        print(f"{SOURCE_ID}: FAILED {e}", file=sys.stderr)
        return 1
    save_raw(SOURCE_ID, json.dumps(layers), "json")
    recs, meta = run(layers, now)
    path = write_events(SOURCE_ID, recs, meta=meta)
    print(f"{SOURCE_ID}: {len(recs)} records -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
