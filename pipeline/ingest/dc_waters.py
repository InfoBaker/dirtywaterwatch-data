"""Washington DC water records (data/waters-dc.json) and the District outline (builder, not a feed).

    python -m ingest.dc_waters [--offline] [--only slug,slug]

openboatlaunch has no DC waters (it has potomac-river-md, potomac-river-va and anacostia-river-md for
the Bladensburg reach only), so DC Water's overflows have nothing to be placed on. research/dc/waters-dc.json
(2026-11-02) proposes the records with their NHD names, GNIS ids and aliases; this module builds them in
the shape of data/waters-extra.json (slug, name, kind, state, towns, bbox, wikidata, charted, area_km2,
length_km, launches, advisories, aliases, source, fetched_at, towns_from, note, geometry) plus gnis_id,
reachcodes and nhd_fcodes, the same extras data/waters-nhd.json carries.

Geometry, per record with a GNIS id: the USGS National Map NHD flowlines (hydro.nationalmap.gov NHD
MapServer layer 6, 1:24,000, the layer the research used; NHDPlus V2.1 on the EPA MapServer is 1:100,000
and has no Piney Branch, Hickey Run or Pope Branch, and numbers GNIS ids without their leading zeros)
with that GNIS id in the District's envelope, cut to the District outline (DC GIS boundary, layer 10:
it takes in the Potomac to the Virginia shore, as DC's own boundary does; the Census cartographic outline
is clipped at the shoreline and would cut the river away), merged and simplified to about 10 m.
Source "nhd". Kind "channel" in the research becomes "bay" (the Washington Channel is a tidal channel
of the Potomac; the status code fills no tidal water and knows no kind "channel").

Not built, listed under `skipped` with the reason (a record without a real geometry would be invented):
Tidal Basin and Kingman Lake (DC GIS names only a hydrography centerline, no NHD name or polygon) and the
Soapstone Valley stream (no NHD name, a hundred unnamed storm-sewer-scale flowlines in the park, the
name still to be confirmed with NPS/DC GIS). The three SSOs DC Water reported to "soapstone" stay
unplaced until it is.

Every response is kept: one bundle per run in data/raw/dc-waters/<stamp>.json (save_raw) with the
boundary and each flowline response. --offline rebuilds from the newest bundle, else from the research
copies in research/dc/raw/ (flowlines-dc-named.json, dcgis/dc-boundary.json).

district_polygon() / in_district() are used by ingest/echo_sewer_overflow_events.py to tell the Potomac
Interceptor rows (in Montgomery County, Maryland) from rows in the District: the boundary is read from
data/raw/dc-waters/boundary-dcgis.json, else fetched once from DC GIS (and kept there), else the
research copy.

Wiring (not done here): status.py's load_waters globs data/waters-*.json, so this file is already read as
an ordinary water file; it carries no `extra: true`. The coordinator adds "waters-dc.json" to
status.EXTRA_WATER_FILES (so it is tagged extra like waters-extra and waters-nhd) and to the export's
water loader, and drops the DC targets from the NHD receiving-waters build (waters_from_nhd) so the same
slug is not built twice.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from functools import lru_cache
from pathlib import Path

import requests
from shapely.geometry import LineString, MultiLineString, Point, Polygon, mapping
from shapely.ops import linemerge, unary_union

from common import DATA_DIR, HEADERS, RAW_DIR, ROOT, now_iso, read_json, save_raw, write_json

RESEARCH = ROOT / "research" / "dc" / "waters-dc.json"
RESEARCH_FLOWLINES = ROOT / "research" / "dc" / "raw" / "nhd" / "flowlines-dc-named.json"
RESEARCH_BOUNDARY = ROOT / "research" / "dc" / "raw" / "dcgis" / "dc-boundary.json"
OUT = DATA_DIR / "waters-dc.json"
CACHE_DIR = RAW_DIR / "dc-waters"
BOUNDARY_CACHE = CACHE_DIR / "boundary-dcgis.json"

NHD_FLOWLINES = "https://hydro.nationalmap.gov/arcgis/rest/services/nhd/MapServer/6/query"
DC_BOUNDARY = ("https://maps2.dcgis.dc.gov/dcgis/rest/services/DCGIS_DATA/"
               "Administrative_Other_Boundaries_WebMercator/MapServer/10/query")
SOURCE = ("USGS National Map NHD flowlines (hydro.nationalmap.gov NHD MapServer layer 6) cut to the "
          "District of Columbia GIS boundary (DC GIS Administrative_Other_Boundaries layer 10); "
          "names, aliases and slugs from research/dc/waters-dc.json (pipeline/ingest/dc_waters.py)")
PAUSE_S = 0.5
SIMPLIFY_DEG = 0.0001          # about 10 m at DC's latitude
STATE = "DC"
TOWNS = ["Washington"]
# The research kinds that status.py does not know. "channel": a tidal channel of the Potomac.
KIND_MAP = {"channel": "bay"}
# Why a proposed water has no record here (checked 2026-11-02; see the module docstring).
SKIP_REASONS = {
    "tidal-basin-dc": "DC GIS names only a hydrography centerline (type 4210/4220); no NHD name and no named "
                      "water polygon (layer 24 polygons carry no names), so no real geometry",
    "kingman-lake-dc": "DC GIS names only a hydrography centerline; no NHD name and no named water polygon",
    "soapstone-valley-run-dc": "no NHD name; about a hundred unnamed storm-drain-scale NHD flowlines in "
                               "Soapstone Valley Park; the stream's name is still to be confirmed with NPS/DC GIS",
}
STATION_CODE = re.compile(r"^[A-Z]{1,3}-\d")


# ---------------------------------------------------------------- fetch

def get_json(url: str, params: dict, tries: int = 3, timeout: int = 90) -> dict:
    err: Exception | None = None
    for i in range(tries):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
            r.raise_for_status()
            d = r.json()
            if isinstance(d, dict) and d.get("error"):
                raise RuntimeError(f"service error {d['error']}")
            return d
        except (requests.RequestException, ValueError, RuntimeError) as e:
            err = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"{url}: {type(err).__name__}: {err}")


def fetch_boundary() -> dict:
    return get_json(DC_BOUNDARY, {"where": "1=1", "outFields": "CITY_NAME", "returnGeometry": "true",
                                  "outSR": "4326", "f": "json"}, tries=2, timeout=30)   # short: the ECHO ingester waits on it


def fetch_flowlines(gnis_id: str, bounds: tuple) -> dict:
    x0, y0, x1, y1 = bounds
    return get_json(NHD_FLOWLINES, {
        "where": f"gnis_id='{gnis_id}'", "geometry": f"{x0 - .01},{y0 - .01},{x1 + .01},{y1 + .01}",
        "geometryType": "esriGeometryEnvelope", "inSR": "4326", "spatialRel": "esriSpatialRelIntersects",
        "outFields": "gnis_name,gnis_id,ftype,fcode,permanent_identifier,reachcode",
        "returnGeometry": "true", "outSR": "4326", "f": "json"})


# ---------------------------------------------------------------- the District

def polygon_from_esri(d: dict) -> Polygon:
    """The District outline from an ESRI JSON polygon response (one ring)."""
    rings = [r for f in d.get("features", []) for r in (f.get("geometry") or {}).get("rings", [])]
    if not rings:
        raise ValueError("no rings in the boundary response")
    polys = sorted((Polygon(r) for r in rings), key=lambda p: p.area, reverse=True)
    poly = unary_union([p if p.is_valid else p.buffer(0) for p in polys])
    return poly if poly.is_valid else poly.buffer(0)


@lru_cache(maxsize=1)
def district_boundary() -> dict:
    """The boundary response: kept copy, else DC GIS (kept), else the research copy."""
    for path in (BOUNDARY_CACHE,):
        d = read_json(path)
        if d and d.get("features"):
            return d
    try:
        d = fetch_boundary()
        if d.get("features"):
            write_json(BOUNDARY_CACHE, d)
            return d
    except RuntimeError as e:
        print(f"warn: DC boundary fetch failed ({e}); using the research copy", file=sys.stderr)
    return read_json(RESEARCH_BOUNDARY, {}) or {}


@lru_cache(maxsize=1)
def district_polygon() -> Polygon:
    return polygon_from_esri(district_boundary())


def in_district(lat: float, lon: float, poly: Polygon | None = None) -> bool:
    """True when the point lies inside the District outline (the Potomac to the Virginia shore included)."""
    return (poly or district_polygon()).intersects(Point(lon, lat))


# ---------------------------------------------------------------- geometry

def length_km(geom) -> float:
    import math
    total = 0.0
    for g in getattr(geom, "geoms", [geom]):
        pts = list(g.coords)
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            total += math.hypot((x1 - x0) * 111.32 * math.cos(math.radians((y0 + y1) / 2)), (y1 - y0) * 110.57)
    return total


def clip_paths(paths: list, poly: Polygon):
    """ESRI polyline paths -> one MultiLineString of the parts inside poly, merged, simplified (~10 m),
    coordinates to 6 decimals; None when nothing lies inside."""
    parts = []
    for p in paths:
        if len(p) < 2:
            continue
        g = LineString(p).intersection(poly)
        parts.extend(x for x in getattr(g, "geoms", [g]) if isinstance(x, LineString) and not x.is_empty)
    if not parts:
        return None
    merged = unary_union(parts)
    if not isinstance(merged, LineString):
        merged = linemerge(merged)
    lines = [x for x in getattr(merged, "geoms", [merged]) if isinstance(x, LineString) and not x.is_empty]
    out = []
    for ln in lines:
        s = ln.simplify(SIMPLIFY_DEG, preserve_topology=False)
        if not s.is_empty and len(s.coords) >= 2:
            out.append(LineString([(round(x, 6), round(y, 6)) for x, y in s.coords]))
    return MultiLineString(out) if out else None


def clean_aliases(spec: dict) -> list[str]:
    """The research source_aliases without annotations and station codes, without the water's own name
    and case or space duplicates ('Rock Creek ' and 'ROCK CREEK' are the name)."""
    own = {spec["name"].lower(), (spec.get("nhd_gnis_name") or "").lower()}
    seen, out = set(own), []
    for a in spec.get("source_aliases") or []:
        a = re.sub(r"\s*\((?:SOBE text|ARK|PRK|Swim Guide|DC GIS)\)\s*$", "", a or "").strip()
        if not a or STATION_CODE.match(a) or ", " in a and all(STATION_CODE.match(x.strip()) for x in a.split(",")):
            continue
        if a.lower() not in seen:
            seen.add(a.lower())
            out.append(a)
    return out


def build_record(spec: dict, geom, features: list[dict], fetched_at: str) -> dict:
    b = geom.bounds
    reach = sorted({f["attributes"].get("reachcode") for f in features if f["attributes"].get("reachcode")})
    fcodes = sorted({f["attributes"].get("fcode") for f in features if f["attributes"].get("fcode")})
    note = f"NHD flowlines with GNIS id {spec['gnis_id']} ('{spec['nhd_gnis_name']}'), {len(features)} features cut to the District"
    if spec.get("note"):
        note += "; " + spec["note"].strip()
    return {
        "slug": spec["proposed_slug"],
        "name": spec["name"],
        "kind": KIND_MAP.get(spec["kind"], spec["kind"]),
        "state": STATE,
        "towns": list(TOWNS),
        "bbox": [round(b[0], 5), round(b[1], 5), round(b[2], 5), round(b[3], 5)],
        "wikidata": spec.get("wikidata"),
        "charted": None,
        "area_km2": None,
        "length_km": round(length_km(geom), 2),
        "launches": [],
        "advisories": [],
        "aliases": clean_aliases(spec),
        "source": "nhd",
        "gnis_id": spec["gnis_id"],
        "reachcodes": reach,
        "nhd_fcodes": fcodes,
        "fetched_at": fetched_at,
        "towns_from": "the District of Columbia is one municipality",
        "note": note,
        "geometry": mapping(geom),
    }


# ---------------------------------------------------------------- main

def research_specs() -> list[dict]:
    d = read_json(RESEARCH)
    if not d:
        raise RuntimeError(f"{RESEARCH} is missing")
    return d["waters"]


def latest_bundle() -> dict | None:
    files = sorted(CACHE_DIR.glob("2*.json")) if CACHE_DIR.exists() else []
    return read_json(files[-1]) if files else None


def research_flowline_responses(specs: list[dict]) -> dict[str, dict]:
    """flowline responses per GNIS id from the research copy (features of every named water in the envelope)."""
    d = read_json(RESEARCH_FLOWLINES, {}) or {}
    by_id: dict[str, list] = {}
    for f in d.get("features", []):
        by_id.setdefault(f["attributes"].get("gnis_id"), []).append(f)
    return {s["gnis_id"]: {"features": by_id.get(s["gnis_id"], []), "via": "research copy"} for s in specs if s.get("gnis_id")}


def build(specs: list[dict], responses: dict[str, dict], poly: Polygon, fetched_at: str, only: set[str] | None = None):
    recs, skipped, missing = [], [], []
    for s in specs:
        slug = s["proposed_slug"]
        if only and slug not in only:
            continue
        if slug in SKIP_REASONS or not s.get("gnis_id"):
            skipped.append({"slug": slug, "name": s["name"], "reason": SKIP_REASONS.get(slug, "no GNIS id, so no NHD geometry")})
            continue
        feats = (responses.get(s["gnis_id"]) or {}).get("features") or []
        paths = [p for f in feats for p in (f.get("geometry") or {}).get("paths", [])]
        geom = clip_paths(paths, poly)
        if geom is None:
            missing.append({"slug": slug, "name": s["name"], "gnis_id": s["gnis_id"], "reason": "no NHD flowline inside the District"})
            continue
        recs.append(build_record(s, geom, feats, fetched_at))
    return recs, skipped, missing


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--offline", action="store_true", help="no network: the newest saved bundle, else the research copies")
    ap.add_argument("--only", help="comma-separated slugs")
    a = ap.parse_args(argv)
    specs = research_specs()
    only = set(a.only.split(",")) if a.only else None
    fetched_at, via, problems = now_iso(), "live", []
    poly = district_polygon()
    responses: dict[str, dict] = {}
    if a.offline:
        bundle = latest_bundle()
        if bundle:
            responses, fetched_at, via = bundle["flowlines"], bundle["fetched_at"], "saved bundle"
        else:
            responses, via = research_flowline_responses(specs), "research copy"
    else:
        bounds = poly.bounds
        for s in specs:
            if not s.get("gnis_id") or s["proposed_slug"] in SKIP_REASONS or (only and s["proposed_slug"] not in only):
                continue
            try:
                responses[s["gnis_id"]] = fetch_flowlines(s["gnis_id"], bounds)
            except RuntimeError as e:
                problems.append(f"{s['proposed_slug']}: {e}")
            time.sleep(PAUSE_S)
        if responses:
            p = save_raw("dc-waters", json.dumps({"fetched_at": fetched_at, "source": NHD_FLOWLINES, "boundary": district_boundary(),
                                                 "flowlines": responses}), "json")
            print(f"dc-waters: raw kept in {p.relative_to(ROOT)}")
        else:
            print("warn: no flowline response; using the research copy", file=sys.stderr)
            responses, via = research_flowline_responses(specs), "research copy"
    recs, skipped, missing = build(specs, responses, poly, fetched_at, only)
    if only:   # a partial run adds to the file, never shortens it
        prev = (read_json(OUT, {}) or {}).get("waters", [])
        recs = [*(r for r in prev if r["slug"] not in {x["slug"] for x in recs}), *recs]
    problems += [f"{m['slug']}: {m['reason']}" for m in missing]
    write_json(OUT, {
        "source": SOURCE, "built": now_iso(), "via": via, "partial": bool(only), "count": len(recs),
        "note": "Washington DC receiving waters (openboatlaunch has none). Same row shape as waters-extra.json plus "
                "gnis_id, reachcodes and nhd_fcodes; launches and advisories empty, charted not checked.",
        "skipped": skipped, "missing": missing, "problems": problems, "waters": recs})
    print(f"dc-waters: {len(recs)} records ({via}), {len(skipped)} skipped, {len(missing)} missing -> {OUT.relative_to(ROOT)}")
    return 1 if problems and not recs else 0


if __name__ == "__main__":
    sys.exit(main())
