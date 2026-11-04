"""Receiving waters that have no openboatlaunch record, from OpenStreetMap (data/waters-extra.json).

    python -m ingest.waters_extra [--refresh] [--only slug,slug] [--offline]

openboatlaunch only keeps waters with a public launch, so many waters that take sewage (East Creek
in Rutland, the Mill River in Springfield, the Quequechan under Fall River, Back Cove in Portland)
have no record and their events cannot be placed or drawn. This module fetches each one from the
Overpass API (one query per water, 2-3 s apart; every response cached in data/raw/osm-waters/<key>.json
and reused unless --refresh) and writes rows in the shape of data/waters-ne.json plus:
  geometry   GeoJSON in WGS84 (MultiLineString for rivers, streams and canals; Polygon or
             MultiPolygon for bays, harbours and ponds), simplified to about 10 m
  source     "osm"; osm: the element ids used ("w123", "r456"; a way inside a used relation is
             covered by the relation's id); osm_timestamp: the data's age per Overpass
  aliases    other names the water goes by in OSM or in the discharge reports
  length_km  for line waters (area_km2 for areas)
Rows: launches and advisories are empty (none known here); charted is null (not checked).

The list (SPECS) comes from the state research reports plus every receiving water named by 20 or
more unplaced events (data/build/events/*.json with no water_slugs, grouped by state and name).
Before fetching, a spec is skipped when data/waters-ne.json already has that name in that state
with one of the spec's towns, or when its `skip` gives a reason (checked by hand; see SPECS).

Slugs follow openboatlaunch: <name>-<st>; when the name already exists in that state for another
water, <name>-<town>-<st> (east-creek-rutland-vt; east-creek-vt is the Orwell creek).

Geometry: the named waterway ways and waterway relations in the spec's search box (relations
bring the whole river), or the named natural=water/bay polygons for areas. Parts inside another
state's outline (Census cartographic boundaries, openboatlaunch's cached copy) are cut away.
Bays and harbours that OSM has only as a label node, or not at all (Mount Hope Bay, New Haven
Harbor, Boston Inner Harbor, Back Cove, Portland Harbor), are built from the OSM coastline: the
face holding the label node (or a hand-set anchor point) once closed by named bridges and by
straight lines between headlands (ends snapped to the coastline); the build refuses a face that
reaches the search box (not closed) or lies on the land side of the coastline. Each such record
says so in `note`. Mount Hope Bay is split along the MA/RI line (member ways of the OSM state
relations) and gives one record per state. Towns are the OSM admin_level=8 boundaries the kept
elements' vertices fall in (is_in, in the same query), limited to the record's state; the
spec's towns for coast-built bays and when OSM gives none (`towns_from` says which).
The output is rewritten every few waters (`partial: true`) so an interrupted run keeps its work.
"""
from __future__ import annotations

import argparse
import io
import json
import math
import re
import sys
import time
import zipfile
from pathlib import Path

import requests
from shapely.geometry import LineString, MultiLineString, MultiPolygon, Point, Polygon, mapping, shape
import numpy as np
import shapely
from shapely.ops import linemerge, polygonize, unary_union

from common import DATA_DIR, HEADERS, RAW_DIR, ROOT, now_iso, read_json, write_json

OVERPASS = "https://overpass-api.de/api/interpreter"
CACHE_DIR = RAW_DIR / "osm-waters"
OUT = DATA_DIR / "waters-extra.json"
# Census Bureau cartographic boundary file, states, 1:500,000, 2023 (public domain):
# https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_us_state_500k.zip. Looked for in data/raw/census/ (git-ignored),
# then in the sibling openboatlaunch project's data/raw/; when neither has it, downloaded once into data/raw/census/
# (states_zip()). Until 2026-11-04 only the sibling path was read, which a GitHub Actions runner does not have.
STATES_ZIP_NAME = "cb_2023_us_state_500k.zip"
STATES_ZIP_URL = f"https://www2.census.gov/geo/tiger/GENZ2023/shp/{STATES_ZIP_NAME}"
CENSUS_ZIP = RAW_DIR / "census" / STATES_ZIP_NAME
SIBLING_ZIP = ROOT.parent / "openboatlaunch" / "data" / "raw" / STATES_ZIP_NAME
STATES_ZIP = SIBLING_ZIP          # kept for older callers; read the outlines through states_zip()
STATES_ZIP_MEMBERS = ("cb_2023_us_state_500k.shp", "cb_2023_us_state_500k.dbf")   # what States and read_state_outlines read
STATES_ZIP_MAX_BYTES = 64 << 20   # the 2023 file is 3.2 MB (SHA-256 4a9b4f5c...7432 on 2026-11-04); a larger answer is not it


def states_zip(candidates=None, download: bool = True, url: str = STATES_ZIP_URL, dest=None, session=None) -> Path:
    """The Census state outlines zip: the first of candidates (data/raw/census/, then the sibling openboatlaunch
    path) that exists; otherwise the public file downloaded once from the Census Bureau into dest (data/raw/census/),
    written atomically, at most STATES_ZIP_MAX_BYTES, and checked to be a sound zip holding the .shp and .dbf
    (otherwise nothing is kept and the error is raised: the caller fails closed). FileNotFoundError when it is nowhere and download is False."""
    import requests
    cands = [Path(c) for c in (candidates if candidates is not None else (CENSUS_ZIP, SIBLING_ZIP))]
    for c in cands:
        if c.is_file():
            return c
    dest = Path(dest) if dest is not None else CENSUS_ZIP
    if not download:
        raise FileNotFoundError(f"{STATES_ZIP_NAME}: not in {', '.join(str(c) for c in cands)}")
    print(f"  Census state outlines: downloading {url} -> {dest}", flush=True)
    r = (session or requests).get(url, headers=HEADERS, timeout=(30, 120), stream=True)
    r.raise_for_status()
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".zip.tmp")
    size = 0
    try:
        with open(tmp, "wb") as fh:
            for chunk in r.iter_content(1 << 20):
                size += len(chunk)
                if size > STATES_ZIP_MAX_BYTES:
                    raise ValueError(f"{url} sent more than {STATES_ZIP_MAX_BYTES} bytes; not kept")
                fh.write(chunk)
        if not zipfile.is_zipfile(tmp):
            raise ValueError(f"{url} did not answer with a zip file")
        with zipfile.ZipFile(tmp) as z:
            missing = [m for m in STATES_ZIP_MEMBERS if m not in z.namelist()]
            bad = z.testzip()
        if missing or bad:
            raise ValueError(f"{url}: the zip lacks {', '.join(missing)}" if missing else f"{url}: {bad} is corrupt")
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    tmp.replace(dest)
    return dest
NE = ("MA", "CT", "RI", "NH", "VT", "ME", "NY")
LINE_KINDS = {"river", "stream", "canal"}
LINE_WATERWAYS = {"river", "stream", "canal", "drain", "ditch", "tidal_channel", "brook", "culvert"}
SIMPLIFY_M = 10.0
PAUSE_S = 2.5
CHECKPOINT_EVERY = 3

# name, state, kind, search box (south, west, north, east), towns from the reports; optional:
# osm_names (other OSM names), aliases (names in the reports), slug, split (states), skip (reason),
# exclude (OSM ids of same-named waters in the box that are not this one), continue_on (way ids of
# a lower reach OSM names otherwise; only the part below the junction is kept), note.
MOUNT_HOPE_COAST = {"cut_names": ["Mount Hope Bridge", "Sakonnet River Bridge", "Braga"]}

SPECS: list[dict] = [
    # ---- Vermont
    dict(name="East Creek", state="VT", kind="river", towns=["Rutland"], box=(43.57, -73.03, 43.76, -72.84),
         continue_on=[318654604],
         note="OSM names the reach below the Mendon Brook junction (through Rutland City to Otter Creek) "
              "Mendon Brook; USGS and the VT DEC reports call it East Creek, so that reach is included"),
    dict(name="Sleepers River", state="VT", kind="river", towns=["St. Johnsbury"], box=(44.38, -72.22, 44.56, -71.98)),
    dict(name="North Branch Winooski River", state="VT", kind="river", towns=["Montpelier"],
         box=(44.25, -72.66, 44.56, -72.47), osm_names=["Winooski River North Branch", "North Branch of the Winooski River"],
         aliases=["North Branch", "North Branch River"]),
    dict(name="Stevens Branch", state="VT", kind="river", towns=["Barre", "Montpelier"],
         box=(44.04, -72.63, 44.28, -72.44), osm_names=["Stevens Branch Winooski River"]),
    dict(name="Dog River", state="VT", kind="river", towns=["Northfield"], box=(43.98, -72.80, 44.28, -72.54)),
    dict(name="Ottauquechee River", state="VT", kind="river", towns=["Hartford", "Quechee"],
         box=(43.54, -72.90, 43.73, -72.32)),
    dict(name="White River", state="VT", kind="river", towns=["Hartford", "White River Junction"],
         box=(43.62, -72.97, 44.06, -72.29)),
    dict(name="Black River", state="VT", kind="river", towns=["Springfield"], box=(43.24, -72.82, 43.60, -72.40),
         aliases=["Black River (Springfield)"]),
    dict(name="Stevens Brook", state="VT", kind="stream", towns=["St. Albans"], box=(44.78, -73.18, 44.87, -73.03)),
    dict(name="Pine Street Barge Canal", state="VT", kind="canal", towns=["Burlington"],
         box=(44.445, -73.235, 44.48, -73.20), osm_names=["Barge Canal"], aliases=["Pine St Barge Canal"]),
    dict(name="Neshobe River", state="VT", kind="river", towns=["Brandon"], box=(43.74, -73.16, 43.91, -72.94)),
    dict(name="Castleton River", state="VT", kind="river", towns=["Fair Haven"], box=(43.55, -73.34, 43.69, -72.99)),
    # ---- Rhode Island
    dict(name="Woonasquatucket River", state="RI", kind="river", towns=["Providence", "Johnston"],
         box=(41.80, -71.63, 41.97, -71.39)),
    dict(name="Moshassuck River", state="RI", kind="river", towns=["Providence", "Pawtucket"],
         box=(41.81, -71.47, 41.94, -71.38)),
    dict(name="West River", state="RI", kind="river", towns=["Providence"], box=(41.82, -71.51, 41.91, -71.39)),
    dict(name="Bucklin Brook", state="RI", kind="stream", towns=["East Providence"], box=(41.77, -71.40, 41.87, -71.31)),
    dict(name="Mount Hope Bay", state="RI", kind="bay", towns=["Bristol", "Portsmouth", "Tiverton", "Warren"],
         split=["RI", "MA"], box=(41.60, -71.32, 41.76, -71.12), key="mount-hope-bay", coast=MOUNT_HOPE_COAST,
         note="OSM has Mount Hope Bay only as a label node: the polygon is the OSM coastline closed at the Mount "
              "Hope, Sakonnet River and Braga bridges, split at the MA/RI line (OSM state relations)"),
    # ---- Connecticut
    dict(name="Pequonnock River", state="CT", kind="river", towns=["Bridgeport"], box=(41.15, -73.27, 41.39, -73.13)),
    dict(name="West River", state="CT", kind="river", towns=["New Haven"], box=(41.25, -73.05, 41.46, -72.91)),
    dict(name="New Haven Harbor", state="CT", kind="bay", towns=["East Haven", "New Haven", "West Haven"],
         box=(41.21, -72.97, 41.32, -72.85),
         coast={"cut_names": ["Pearl Harbor Memorial Bridge", "Tomlinson Bridge", "Kimberly Avenue Bridge"],
                "cut_points": [((-72.9045, 41.2482), (-72.9520, 41.2550))]},
         note="OSM has New Haven Harbor only as a label node: the polygon is the OSM coastline closed at the "
              "I-95 (Pearl Harbor Memorial) and Tomlinson bridges and by a line from Lighthouse Point to "
              "Bradley Point (ends snapped to the coastline)"),
    dict(name="Naugatuck River", state="CT", kind="river", towns=["Waterbury", "Derby"], box=(41.30, -73.21, 41.93, -72.97)),
    dict(name="Park River", state="CT", kind="river", towns=["Hartford"], box=(41.70, -72.81, 41.87, -72.65),
         skip="park-river-ct exists (Hartford), a 0.3 km stub at the mouth; the open branches are added below"),
    dict(name="North Branch Park River", state="CT", kind="river", towns=["Hartford"], box=(41.74, -72.81, 41.90, -72.65),
         aliases=["Park River"]),
    dict(name="South Branch Park River", state="CT", kind="river", towns=["Hartford"], box=(41.68, -72.81, 41.79, -72.65),
         aliases=["Park River"]),
    dict(name="Mill River", state="CT", kind="river", towns=["New Haven", "Hamden"], box=(41.28, -72.95, 41.52, -72.86)),
    # CT receiving waters named by 20+ unplaced events (status.json, 2026-11-02)
    dict(name="Yellow Mill Pond", state="CT", kind="bay", towns=["Bridgeport"], box=(41.155, -73.19, 41.20, -73.15),
         osm_names=["Yellow Mill Channel"], aliases=["Yellow Mill Channel"], key="yellow-mill-pond-ct",
         coast={"anchor": (-73.1741, 41.1810), "all_bridges": True, "cut_names": [], "water_polygons": True,
                "cut_points": [((-73.1822, 41.1752), (-73.1766, 41.1738))]},
         note="Not in OSM by name: the OSM coastline water of Bridgeport Harbor's eastern arm, from the fork "
              "with the Pequonnock (a line across the channel mouth, ends snapped to the coastline) to the "
              "head of the pond"),
    dict(name="Piper Brook", state="CT", kind="stream", towns=["New Britain", "Newington"], box=(41.63, -72.82, 41.73, -72.62)),
    dict(name="Trout Brook", state="CT", kind="stream", towns=["West Hartford", "Hartford"], box=(41.69, -72.79, 41.81, -72.67),
         aliases=["Troutbrook"]),
    dict(name="Burr Creek", state="CT", kind="bay", towns=["Bridgeport"], box=(41.13, -73.24, 41.175, -73.20),
         coast={"all_bridges": True, "cut_names": [], "water_polygons": True},
         skip="OSM has only a label node; the creek is the head of Black Rock Harbor, inside the "
              "black-rock-harbor-ct polygon (alias there)"),
    dict(name="Johnson's Creek", state="CT", kind="stream", towns=["Bridgeport"], box=(41.155, -73.175, 41.195, -73.145),
         osm_names=["Johnsons Creek", "Johnson Creek"], key="johnsons-creek-ct"),
    dict(name="Hockanum River", state="CT", kind="river", towns=["Vernon", "Manchester"], box=(41.74, -72.66, 41.93, -72.38)),
    dict(name="Island Brook", state="CT", kind="stream", towns=["Bridgeport"], box=(41.18, -73.23, 41.24, -73.17)),
    dict(name="Black Rock Harbor", state="CT", kind="bay", towns=["Bridgeport"], aliases=["Burr Creek"],
         box=(41.13, -73.24, 41.175, -73.20),
         coast={"anchor": (-73.2210, 41.1500), "all_bridges": True, "cut_names": [], "water_polygons": True,
                "cut_points": [((-73.2290, 41.1438), (-73.2170, 41.1435))]},
         note="Not in OSM by name: the OSM coastline water north of a line from Black Rock to Fayerweather "
              "Island (ends snapped to the coastline), Burr Creek at its head included"),
    dict(name="Greenwich Harbor", state="CT", kind="bay", towns=["Greenwich"], box=(40.99, -73.655, 41.04, -73.60),
         coast={"all_bridges": True, "cut_names": [], "water_polygons": True,
                "cut_points": [((-73.6255, 41.0078), (-73.6186, 41.0110))]},
         note="OSM has Greenwich Harbor only as a label node: the OSM coastline water north of a line across "
              "the harbour mouth (ends snapped to the coastline)"),
    dict(name="Webster Brook", state="CT", kind="stream", towns=["New Britain", "Newington"], box=(41.63, -72.83, 41.71, -72.71)),
    dict(name="Mad River", state="CT", kind="river", towns=["Waterbury", "Wolcott"], box=(41.51, -73.06, 41.63, -72.94)),
    dict(name="Park River Conduit", state="CT", kind="river", towns=["Hartford"], box=(41.74, -72.72, 41.78, -72.65),
         osm_names=["Park River"], aliases=["Park River"],
         note="the buried Park River in Hartford (OSM ways named Park River, mostly culvert), from the "
              "North/South Branch confluence to the Connecticut; park-river-ct is a 0.3 km piece of it"),
    dict(name="Cove River", state="CT", kind="river", towns=["West Haven"], box=(41.24, -73.00, 41.31, -72.94)),
    dict(name="Byram River", state="CT", kind="river", towns=["Greenwich"], box=(40.98, -73.71, 41.16, -73.60)),
    # ---- Massachusetts
    dict(name="Mount Hope Bay", state="MA", kind="bay", towns=["Fall River", "Somerset", "Swansea"],
         split=["RI", "MA"], box=(41.60, -71.32, 41.76, -71.12), key="mount-hope-bay", coast=MOUNT_HOPE_COAST,
         note="OSM has Mount Hope Bay only as a label node: the polygon is the OSM coastline closed at the Mount "
              "Hope, Sakonnet River and Braga bridges, split at the MA/RI line (OSM state relations)"),
    dict(name="Mill River", state="MA", kind="river", towns=["Springfield"], box=(42.02, -72.61, 42.13, -72.47),
         aliases=["Mill R."]),
    dict(name="Chicopee River", state="MA", kind="river", towns=["Chicopee"], box=(42.13, -72.63, 42.20, -72.35),
         skip="chicopee-river-ma already runs from Three Rivers to the Connecticut (bbox west edge -72.623)"),
    dict(name="Nashua River", state="MA", kind="river", towns=["Lancaster"], box=(42.40, -71.72, 42.71, -71.53),
         skip="nashua-river-ma runs from the North/South Nashua confluence in Lancaster to the NH line"),
    dict(name="North Nashua River", state="MA", kind="river", towns=["Fitchburg", "Leominster", "Lancaster"],
         box=(42.44, -71.97, 42.66, -71.64)),
    dict(name="Quequechan River", state="MA", kind="river", towns=["Fall River"], box=(41.67, -71.18, 41.72, -71.09)),
    dict(name="Chelsea River", state="MA", kind="river", towns=["Chelsea", "Boston"], box=(42.37, -71.06, 42.41, -70.99),
         osm_names=["Chelsea Creek"], aliases=["Chelsea Creek"]),
    dict(name="Little River", state="MA", kind="river", towns=["Haverhill"], box=(42.76, -71.13, 42.88, -71.04)),
    dict(name="Boston Inner Harbor", state="MA", kind="bay", towns=["Boston"], box=(42.33, -71.08, 42.40, -70.98),
         osm_names=["Inner Harbor"], aliases=["Little Mystic Channel", "Reserved Channel"],
         coast={"anchor": (-71.042, 42.362),
                "cut_names": ["Tobin", "McArdle", "Chelsea Street Bridge", "Charlestown Bridge", "Northern Avenue",
                              "Moakley"],
                "cut_points": [((-71.0118, 42.3380), (-71.0170, 42.3550))]},
         note="Not in OSM by name: the polygon is the OSM sea between the coastline, the Charlestown, Tobin, "
              "McArdle/Chelsea Street and Fort Point Channel bridges and a line from Castle Island to Logan "
              "Airport (ends snapped to the coastline); it holds the Little Mystic and Reserved Channels"),
    dict(name="Fort Point Channel", state="MA", kind="canal", towns=["Boston"], box=(42.335, -71.07, 42.362, -71.045)),
    dict(name="Alewife Brook", state="MA", kind="stream", towns=["Cambridge", "Somerville", "Arlington"],
         box=(42.38, -71.17, 42.43, -71.11)),
    dict(name="Ten Mile River", state="MA", kind="river", towns=["Attleboro"], box=(41.79, -71.41, 42.06, -71.24)),
    dict(name="Punch Brook", state="MA", kind="stream", towns=["Fitchburg"], box=(42.55, -71.86, 42.62, -71.74),
         aliases=["Punch Brook Culvert"]),
    dict(name="Birch Brook", state="MA", kind="stream", towns=["Fitchburg"], box=(42.55, -71.86, 42.62, -71.74)),
    dict(name="Monatiquot River", state="MA", kind="river", towns=["Braintree"], box=(42.16, -71.08, 42.24, -70.95)),
    dict(name="Reserved Channel", state="MA", kind="canal", towns=["Boston"], box=(42.33, -71.06, 42.35, -71.02)),
    dict(name="Pawtucket Canal", state="MA", kind="canal", towns=["Lowell"], box=(42.62, -71.34, 42.66, -71.29)),
    dict(name="Little Mystic Channel", state="MA", kind="bay", towns=["Boston"], box=(42.37, -71.07, 42.39, -71.04),
         skip="not in OSM by name or shape; it lies inside the boston-inner-harbor-ma polygon (alias there)"),
    dict(name="Muddy River", state="MA", kind="river", towns=["Boston", "Brookline"], box=(42.32, -71.13, 42.36, -71.08)),
    dict(name="Spicket River", state="MA", kind="river", towns=["Lawrence", "Methuen"], box=(42.69, -71.23, 42.80, -71.13),
         aliases=["Spickett River"]),
    # ---- Maine
    dict(name="Back Cove", state="ME", kind="bay", towns=["Portland"], box=(43.66, -70.30, 43.70, -70.235),
         coast={"cut_names": ["Tukey"]},
         note="OSM has Back Cove only as a label node: the polygon is the OSM coastline closed at Tukey's Bridge"),
    dict(name="Portland Harbor", state="ME", kind="bay", towns=["Portland", "South Portland"],
         box=(43.61, -70.28, 43.68, -70.17),
         coast={"anchor": (-70.250, 43.652), "cut_names": ["Casco Bay Bridge"],
                "cut_points": [((-70.2225, 43.6515), (-70.2395, 43.6630))]},
         note="Not in OSM by name: the polygon is the OSM sea between the coastline, the Casco Bay Bridge "
              "(the Fore River above it is fore-river-me) and a line from Spring Point to Fish Point (ends "
              "snapped to the coastline)"),
    dict(name="Fore River", state="ME", kind="river", towns=["Portland"], box=(43.62, -70.32, 43.67, -70.20),
         skip="fore-river-me runs the whole estuary, Portland and South Portland shores (bbox -70.312..-70.200)"),
    dict(name="Capisic Brook", state="ME", kind="stream", towns=["Portland"], box=(43.65, -70.34, 43.71, -70.28)),
    dict(name="Little Androscoggin River", state="ME", kind="river", towns=["Mechanic Falls", "Auburn"],
         box=(44.05, -70.84, 44.43, -70.20)),
    dict(name="Sebasticook River", state="ME", kind="river", towns=["Winslow"], box=(44.50, -69.72, 44.92, -69.18)),
    dict(name="Kenduskeag Stream", state="ME", kind="river", towns=["Bangor"], box=(44.79, -69.17, 45.05, -68.76),
         skip="kenduskeag-stream-me reaches the Penobscot in Bangor (bbox east edge -68.768)"),
    dict(name="Jepson Brook", state="ME", kind="stream", towns=["Lewiston"], box=(44.05, -70.25, 44.14, -70.13)),
    dict(name="Goff Brook", state="ME", kind="stream", towns=["Lewiston"], box=(44.05, -70.25, 44.14, -70.13)),
    dict(name="Landing Brook", state="ME", kind="stream", towns=["Calais"], box=(45.11, -67.36, 45.23, -67.19)),
    dict(name="Souadabscook Stream", state="ME", kind="river", towns=["Hampden"], box=(44.74, -69.10, 44.83, -68.82),
         skip="souadabscook-stream-me exists (Hampden), from Carmel to the Penobscot"),
]


# ---------------------------------------------------------------- helpers

def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def norm(s: str) -> str:
    s = re.sub(r"[^a-z0-9 ]", " ", str(s).lower())
    return " ".join({"st": "saint"}.get(t, t) for t in s.split())


def load_ne() -> list[dict]:
    return (read_json(DATA_DIR / "waters-ne.json") or {}).get("waters", [])


def existing(spec: dict, ne: list[dict]) -> dict | None:
    """The waters-ne row with this name in this state listing one of the spec's towns."""
    towns = {norm(t) for t in spec["towns"]}
    for w in ne:
        if w["state"] == spec["state"] and norm(w["name"]) == norm(spec["name"]) \
                and towns & {norm(t) for t in w.get("towns") or []}:
            return w
    return None


def make_slug(spec: dict, state: str, ne: list[dict]) -> str:
    if spec.get("slug"):
        return spec["slug"]
    base = f"{slugify(spec['name'])}-{state.lower()}"
    taken = {w["slug"] for w in ne}
    same_name = any(w["state"] == state and norm(w["name"]) == norm(spec["name"]) for w in ne)
    if base in taken or same_name:
        return f"{slugify(spec['name'])}-{slugify(spec['towns'][0])}-{state.lower()}"
    return base


class States:
    """Census 1:500,000 state outlines (shoreline-clipped), from states_zip() (data/raw/census/, the sibling
    openboatlaunch copy, or the Census Bureau's file downloaded once)."""

    def __init__(self):
        import shapefile
        z = zipfile.ZipFile(states_zip())
        stem = "cb_2023_us_state_500k"
        r = shapefile.Reader(shp=io.BytesIO(z.read(f"{stem}.shp")), dbf=io.BytesIO(z.read(f"{stem}.dbf")))
        self.shapes = {}
        for sr in r.iterShapeRecords():
            if sr.record["STUSPS"] in NE:
                self.shapes[sr.record["STUSPS"]] = shape(sr.shape.__geo_interface__)

    def nearest(self, lon: float, lat: float) -> str:
        pt = Point(lon, lat)
        return min(self.shapes, key=lambda s: self.shapes[s].distance(pt))

    def shore_state(self, geom) -> str:
        """The state with the most land within about 500 m of a piece of water (its shores)."""
        ring = geom.buffer(0.006)
        return max(self.shapes, key=lambda s: ring.intersection(self.shapes[s]).area
                   if self.shapes[s].intersects(ring) else 0.0)

    def clip(self, geom, state: str):
        """Cut away the parts inside another state's land outline (water outside every outline,
        such as a river mouth past the generalised coast, stays)."""
        others = [g for s, g in self.shapes.items() if s != state and g.intersects(geom)]
        return geom.difference(unary_union(others)) if others else geom

    def bbox(self, state: str):
        return self.shapes[state].bounds


def to_m(geom, lat0: float):
    k = np.array([111_320.0 * math.cos(math.radians(lat0)), 110_574.0])
    return shapely.transform(geom, lambda c: c * k), k


def simplify(geom, tol_m: float = SIMPLIFY_M):
    """Simplify to about tol_m metres in a local equirectangular projection; 6 decimals."""
    gm, k = to_m(geom, geom.centroid.y)
    g = shapely.transform(gm.simplify(tol_m, preserve_topology=True), lambda c: np.round(c / k, 6))
    return g if g.is_valid else g.buffer(0)


def length_km(geom) -> float:
    return to_m(geom, geom.centroid.y)[0].length / 1000


def area_km2(geom) -> float:
    return to_m(geom, geom.centroid.y)[0].area / 1e6


def as_multiline(geom) -> MultiLineString | None:
    parts = []
    for g in getattr(geom, "geoms", [geom]):
        if isinstance(g, LineString) and not g.is_empty:
            parts.append(g)
        elif isinstance(g, MultiLineString):
            parts.extend(p for p in g.geoms if not p.is_empty)
    return MultiLineString(parts) if parts else None


def as_areas(geom):
    polys = []
    for g in getattr(geom, "geoms", [geom]):
        if isinstance(g, Polygon) and not g.is_empty:
            polys.append(g)
        elif isinstance(g, MultiPolygon):
            polys.extend(p for p in g.geoms if not p.is_empty)
    if not polys:
        return None
    return polys[0] if len(polys) == 1 else MultiPolygon(polys)


# ---------------------------------------------------------------- Overpass

def name_regex(names: list[str]) -> str:
    return "^(" + "|".join(re.sub(r"([.^$|()\[\]{}*+?\\])", r"\\\1", n).replace('"', '\\"') for n in names) + ")$"


def build_query(spec: dict) -> str:
    s, w, n, e = spec["box"]
    bb = f"{s},{w},{n},{e}"
    rx = name_regex([spec["name"]] + list(spec.get("osm_names") or []))
    tail = []
    if spec.get("coast"):   # a bay OSM has only as a label: its coastline and the bridges that close it
        tail += ['make section name="coast";\nout;', f'way["natural"="coastline"]({bb});\nout geom;']
        if spec["coast"].get("cut_names") or spec["coast"].get("all_bridges"):
            # unanchored: "Tukey" finds "Tukey's Bridge"; all_bridges fetches every named bridge in the
            # box (the build uses only those matching cut_names), so cuts can be chosen offline
            cut_rx = "." if spec["coast"].get("all_bridges") else name_regex(spec["coast"]["cut_names"])[1:-1]
            tail += ['make section name="cuts";\nout;', f'way["bridge"]["name"~"{cut_rx}",i]({bb});\nout geom;']
    if (spec.get("coast") or {}).get("water_polygons"):   # unnamed water areas (a pond OSM left unnamed)
        tail += ['make section name="ponds";\nout;',
                 f'(way["natural"="water"]({bb});relation["natural"="water"]({bb}););\nout geom;']
    if spec.get("split"):   # the state line: member ways of the state relations in the box
        tail += ['make section name="border";\nout;',
                 f'rel["boundary"="administrative"]["admin_level"="4"]({bb})->.st;\nway(r.st)({bb});\nout geom;']
    border = "\n".join(tail)
    extra = f'  way(id:{",".join(map(str, spec["continue_on"]))});\n' if spec.get("continue_on") else ""
    return f"""[out:json][timeout:300];
(
  way["waterway"]["name"~"{rx}",i]({bb});
  relation["waterway"]["name"~"{rx}",i]({bb});
  relation["type"="waterway"]["name"~"{rx}",i]({bb});
  way["natural"~"^(water|bay|strait)$"]["name"~"{rx}",i]({bb});
  relation["natural"~"^(water|bay|strait)$"]["name"~"{rx}",i]({bb});
  node["natural"~"^(bay|strait)$"]["name"~"{rx}",i]({bb});
{extra})->.w;
.w out geom;
foreach.w->.x(
  (.x; .x >>;)->.m;
  node.m->.n;
  .n is_in->.a;
  (rel(pivot.a)["boundary"="administrative"]["admin_level"="8"];
   way(pivot.a)["boundary"="administrative"]["admin_level"="8"];)->.t;
  .x out ids;
  .t out tags center;
);
{border}
"""


def fetch(spec: dict, refresh: bool, offline: bool) -> tuple[dict, bool]:
    """(Overpass response, fetched now). Cached per water in data/raw/osm-waters/<key>.json."""
    key = spec.get("key") or f"{slugify(spec['name'])}-{spec['state'].lower()}"
    path = CACHE_DIR / f"{key}.json"
    q = build_query(spec)
    if path.exists() and not refresh:
        d = json.loads(path.read_text())
        if d.get("_query") == q or offline:   # a changed spec (names, box, extra ways) refetches
            return d, False
    if offline:
        return None, False
    for attempt in range(6):
        try:
            r = requests.post(OVERPASS, data={"data": q}, headers=HEADERS, timeout=360)
        except requests.RequestException as ex:
            print(f"  {key}: {ex}; retrying")
            time.sleep(10 * (attempt + 1))
            continue
        if r.status_code in (429, 502, 503, 504):
            print(f"  {key}: HTTP {r.status_code}; waiting", flush=True)
            time.sleep(30 * (attempt + 1))
            continue
        r.raise_for_status()
        d = r.json()
        if d.get("remark") and "error" in d["remark"].lower():
            print(f"  {key}: remark {d['remark'][:160]}; retrying")
            time.sleep(20 * (attempt + 1))
            continue
        d["_query"] = q
        d["_fetched_at"] = now_iso()
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(d))
        return d, True
    print(f"  {key}: Overpass failed; left out this run", flush=True)
    return None, False


def is_cached(spec: dict, key: str, refresh: bool) -> bool:
    p = CACHE_DIR / f"{key}.json"
    return p.exists() and not refresh and json.loads(p.read_text()).get("_query") == build_query(spec)


def bridge_name_ok(spec: dict, el: dict) -> bool:
    names = (spec.get("coast") or {}).get("cut_names") or []
    name = (el.get("tags") or {}).get("name") or ""
    return any(n.lower() in name.lower() for n in names)


def parse(d: dict, spec: dict | None = None):
    """Split the response into water elements, the towns each one touches, and the extra sections
    (coast: coastline ways; cuts: closing bridges; border: state-line ways) as lists of lines."""
    features, towns, extra = [], {}, {"coast": [], "cuts": [], "border": [], "ponds": []}
    current, section = None, None
    for el in d.get("elements", []):
        tags = el.get("tags") or {}
        if el["type"] == "section":
            section = tags.get("name")
            continue
        if section == "ponds":
            _, areas, _ = element_geoms(el)
            extra["ponds"].extend((osm_id(el), a) for a in areas if not a.is_empty)
            continue
        if section in extra:
            if section == "cuts" and spec is not None and not bridge_name_ok(spec, el):
                continue
            c = way_coords(el.get("geometry"))
            if len(c) >= 2:
                extra[section].append((osm_id(el), LineString(c)))
            continue
        if not tags and set(el) <= {"type", "id"}:
            current = (el["type"], el["id"])
            towns.setdefault(current, [])
            continue
        if tags.get("boundary") == "administrative" and tags.get("admin_level") == "8" and current:
            c = el.get("center") or {}
            towns[current].append((tags.get("name"), c.get("lon"), c.get("lat")))
        else:
            features.append(el)
    return features, towns, extra


def extend(line: LineString, m: float = 150.0) -> LineString:
    """The line lengthened by m metres at both ends (a bridge's ends may stop short of the coast)."""
    c = list(line.coords)
    k = m / 111_000

    def out(a, b):
        dx, dy = a[0] - b[0], (a[1] - b[1])
        n = math.hypot(dx, dy) or 1
        return (a[0] + dx / n * k, a[1] + dy / n * k)
    return LineString([out(c[0], c[1])] + c + [out(c[-1], c[-2])])


def snapped_cut(a, b, shore) -> LineString:
    """A closing line between two headlands given roughly (lon, lat): each end moved to the nearest
    point of the OSM coastline, then lengthened 60 m onto the land."""
    from shapely.ops import nearest_points
    pa = nearest_points(shore, Point(a))[0]
    pb = nearest_points(shore, Point(b))[0]
    return extend(LineString([pa, pb]), 60.0)


def coast_face(coast: list, cuts: list, anchors: list, box, cut_points=()) -> tuple:
    """(polygon, coastline ids) of the water face holding the bay's label node: the coastline,
    closed by the bridges, by straight lines between named headlands (cut_points, snapped to the
    coastline) and by the search box; None when the face reaches the box (not closed)."""
    s, w, n, e = box
    frame = Polygon([(w, s), (e, s), (e, n), (w, n)]).exterior
    shore = unary_union([ln for _, ln in coast])
    closers = [extend(ln) for _, ln in cuts] + [snapped_cut(a, b, shore) for a, b in cut_points]
    noded = unary_union([ln for _, ln in coast] + closers + [frame])
    for f in polygonize(noded):
        if any(f.contains(a) for a in anchors):
            if f.exterior.distance(frame) < 1e-9 or not is_water(f, coast):
                return None, []   # leaks to the box edge, or the anchor is on land
            ids = [i for i, ln in coast if ln.distance(f) < 1e-6]
            return f, ids
    return None, []


def is_water(face, coast: list) -> bool:
    """OSM draws coastline with the land on the left: the face is water when the points just right
    of its coastline segments fall inside it more often than the points just left."""
    eps = 2e-6
    edge = face.boundary.buffer(1e-7)
    votes = 0
    for _, ln in coast:
        if not ln.intersects(edge):
            continue
        c = list(ln.coords)
        for (x1, y1), (x2, y2) in zip(c, c[1:]):
            dx, dy = x2 - x1, y2 - y1
            n = math.hypot(dx, dy)
            mid = Point((x1 + x2) / 2, (y1 + y2) / 2)
            if not n or not edge.contains(mid):
                continue
            right = Point(mid.x + dy / n * eps, mid.y - dx / n * eps)
            left = Point(mid.x - dy / n * eps, mid.y + dx / n * eps)
            votes += face.contains(right) - face.contains(left)
    return votes > 0


def way_coords(geometry) -> list:
    return [(p["lon"], p["lat"]) for p in geometry or [] if p]


def element_geoms(el: dict) -> tuple[list, list, set]:
    """(lines, areas, member way ids) for one OSM element."""
    tags = el.get("tags") or {}
    lines, areas, members = [], [], set()
    if el["type"] == "node":
        return lines, areas, members
    if el["type"] == "way":
        c = way_coords(el.get("geometry"))
        if len(c) < 2:
            return lines, areas, members
        ww = tags.get("waterway")
        if ww in LINE_WATERWAYS:
            lines.append(LineString(c))
        elif len(c) >= 4 and c[0] == c[-1]:
            areas.append(Polygon(c).buffer(0))
        elif ww:
            pass   # dam, weir, lock gate: not the water
        else:
            lines.append(LineString(c))
        return lines, areas, members
    # relation
    mem = [m for m in el.get("members", []) if m.get("type") == "way" and m.get("geometry")]
    members = {m["ref"] for m in mem}
    if tags.get("type") == "multipolygon" or tags.get("natural") in ("water", "bay", "strait"):
        outer = [LineString(way_coords(m["geometry"])) for m in mem if m.get("role") in ("outer", "") and len(m["geometry"]) >= 2]
        inner = [LineString(way_coords(m["geometry"])) for m in mem if m.get("role") == "inner" and len(m["geometry"]) >= 2]
        po = unary_union(list(polygonize(linemerge(outer)))) if outer else None
        if po is not None and not po.is_empty:
            if inner:
                pi = unary_union(list(polygonize(linemerge(inner))))
                po = po.difference(pi)
            areas.append(po.buffer(0))
    else:   # type=waterway: the river's ways
        for m in mem:
            if m.get("role", "") in ("", "main_stream", "side_stream", "main"):
                c = way_coords(m["geometry"])
                if len(c) >= 2:
                    lines.append(LineString(c))
    return lines, areas, members


def osm_id(el: dict) -> str:
    return {"node": "n", "way": "w", "relation": "r"}[el["type"]] + str(el["id"])


def clean_town(name: str | None) -> str | None:
    if not name:
        return None
    return re.sub(r"^(Town|City|Village) of ", "", name.strip())


# ---------------------------------------------------------------- build

def downstream_part(line: LineString, named, tol_m: float = 15.0):
    """The part of an OSM waterway (drawn in the flow direction) below the first vertex that
    touches the named water: where OSM gives the lower reach another name."""
    tol = tol_m / 111_000
    coords = list(line.coords)
    for i, c in enumerate(coords):
        if named.distance(Point(c)) <= tol:
            return LineString(coords[i:]) if len(coords) - i >= 2 else None
    return None


def build_records(spec: dict, d: dict, states: States, ne: list[dict]) -> list[dict]:
    rec = build_record(spec, d, states, ne)
    return [rec] if rec else []


def build_record(spec: dict, d: dict, states: States, ne: list[dict]) -> dict | None:
    features, towns_by_el, sections = parse(d, spec)
    border = [ln for _, ln in sections["border"]]
    state = spec["state"]
    exclude = set(spec.get("exclude") or [])
    cont = {f"w{i}" for i in spec.get("continue_on") or []}
    per_el, rel_members, extra = [], set(), []
    for el in features:
        if osm_id(el) in exclude:
            continue
        lines, areas, members = element_geoms(el)
        if osm_id(el) in cont:
            extra.append((el, lines))
            continue
        if el["type"] == "relation":
            rel_members |= members
        per_el.append((el, lines, areas))
    has_lines = any(l for _, l, _ in per_el)
    has_areas = any(a for _, _, a in per_el)
    closure_ids = []
    if spec.get("coast") and not has_areas and not has_lines:   # only a label node: build from the coast
        anchors = [(el, Point(el["lon"], el["lat"])) for el in features if el["type"] == "node"]
        if spec["coast"].get("anchor"):   # no label node: a point in the water, set by hand
            anchors = [(None, Point(spec["coast"]["anchor"]))]
        if not anchors:
            return None
        face, coast_ids = coast_face(sections["coast"], sections["cuts"], [p for _, p in anchors], spec["box"],
                                     spec["coast"].get("cut_points", ()))
        if face is None:
            return None
        per_el = [(anchors[0][0] or {"type": "node", "id": 0, "tags": {}}, [], [face])]
        closure_ids = coast_ids + [i for i, ln in sections["cuts"] if extend(ln).intersects(face.buffer(1e-6))]
        has_areas = True
    use = "lines" if has_lines and (spec["kind"] in LINE_KINDS or not has_areas) else "areas"
    if use == "areas" and not has_areas:
        return None

    kept, ids, towns, wikidata = [], set(), set(), []
    for el, lines, areas in per_el:
        parts = lines if use == "lines" else areas
        if not parts:
            continue
        g = unary_union(parts)
        g = split_state(g, border, states, state) if spec.get("split") else states.clip(g, state)
        if g.is_empty:
            continue
        kept.append(g)
        if not (el["type"] == "way" and el["id"] in rel_members) and el["id"]:
            ids.add(osm_id(el))
        if (el.get("tags") or {}).get("wikidata"):
            wikidata.append((el["type"] == "relation", el["tags"]["wikidata"]))
        for name, lon, lat in towns_by_el.get((el["type"], el["id"]), []):
            if name and lon is not None and states.nearest(lon, lat) == state:
                towns.add(clean_town(name))
    if not kept:
        return None
    ids.update(closure_ids)
    if spec.get("coast"):
        towns = set(spec["towns"])   # the label node's is_in names one town; the shore towns are listed
    named = unary_union(kept)
    for el, lines in extra:   # a lower reach OSM names otherwise: only below the junction
        for ln in lines:
            part = downstream_part(ln, named)
            if part is not None:
                kept.append(states.clip(part, state))
                ids.add(osm_id(el))
                towns.update(spec["towns"])
    geom = unary_union(kept)
    geom = as_multiline(linemerge(as_multiline(geom))) if use == "lines" else as_areas(geom)
    if geom is None or geom.is_empty:
        return None
    geom = simplify(geom)
    geom = as_multiline(geom) if use == "lines" else as_areas(geom)
    if closure_ids:   # list only the coastline and bridge ways along this state's piece
        lines = dict(sections["coast"] + sections["cuts"])
        near = geom.buffer(0.0005)
        ids = {i for i in ids if i not in lines or lines[i].intersects(near)}
    b = geom.bounds
    wikidata.sort(key=lambda x: not x[0])
    wd = wikidata[0][1] if wikidata else None
    return {
        "slug": make_slug(spec, state, ne),
        "name": spec["name"],
        "kind": spec["kind"],
        "state": state,
        "towns": sorted(t for t in towns if t) or sorted(spec["towns"]),
        "bbox": [round(b[0], 5), round(b[1], 5), round(b[2], 5), round(b[3], 5)],
        "wikidata": wd,
        "charted": None,
        "area_km2": round(area_km2(geom), 3) if use == "areas" else None,
        "length_km": round(length_km(geom), 2) if use == "lines" else None,
        "launches": [],
        "advisories": [],
        "aliases": list(dict.fromkeys(list(spec.get("osm_names") or []) + list(spec.get("aliases") or []))),
        "source": "osm",
        "osm": sorted(ids, key=lambda x: (x[0], int(x[1:]))),
        "osm_timestamp": (d.get("osm3s") or {}).get("timestamp_osm_base"),
        "fetched_at": d.get("_fetched_at"),
        "towns_from": "spec (shore towns)" if spec.get("coast") else "osm admin_level=8" if towns else "research reports",
        "note": spec.get("note"),
        "geometry": mapping(geom),
    }


def split_state(geom, border: list, states: States, state: str):
    """The part of a water on `state`'s side of the state line: the water cut by the state-line ways,
    each piece going to the state with the most shore around it."""
    pieces = [geom]
    if border:
        faces = polygonize(unary_union([geom.boundary] + border))
        pieces = [f for f in faces if geom.contains(f.representative_point())] or [geom]
    keep = [p for p in pieces if states.shore_state(p) == state]
    return unary_union(keep) if keep else Polygon()


# ---------------------------------------------------------------- main

def validate(recs: list[dict], states: States) -> list[str]:
    problems = []
    for r in recs:
        g = shape(r["geometry"]) if r.get("geometry") else None
        if g is None or g.is_empty:
            problems.append(f"{r['slug']}: empty geometry")
            continue
        sb = states.bbox(r["state"])
        b = g.bounds
        tol = 0.02
        if b[0] < sb[0] - tol or b[1] < sb[1] - tol or b[2] > sb[2] + tol or b[3] > sb[3] + tol:
            problems.append(f"{r['slug']}: geometry {tuple(round(x, 3) for x in b)} outside {r['state']} bbox")
    return problems


def write_output(recs, skipped, missing, partial: bool, problems=()) -> None:
    write_json(OUT, {
        "source": "OpenStreetMap via the Overpass API (pipeline/ingest/waters_extra.py); data (c) OpenStreetMap contributors, ODbL",
        "built": now_iso(),
        "partial": partial,
        "count": len(recs),
        "note": "Receiving waters with no openboatlaunch record. Same row shape as waters-ne.json plus geometry, "
                "source, osm ids, aliases and length_km; launches and advisories empty, charted not checked.",
        "skipped": skipped,
        "missing": missing,
        "problems": list(problems),
        "waters": recs,
    })


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--refresh", action="store_true", help="refetch even when a cached response exists")
    ap.add_argument("--offline", action="store_true", help="use only cached responses (uncached waters are listed as missing)")
    ap.add_argument("--only", help="comma-separated spec keys or slugs to (re)build; others kept from the last output")
    args = ap.parse_args(argv)

    ne = load_ne()
    states = States()
    only = set((args.only or "").split(",")) - {""}
    prev_all = {r["slug"]: r for r in (read_json(OUT) or {}).get("waters", [])}
    prev = prev_all if only else {}

    recs, skipped, missing = [], [], []
    last_fetch, done = 0.0, 0
    for spec in SPECS:
        key = spec.get("key") or f"{slugify(spec['name'])}-{spec['state'].lower()}"
        ex = existing(spec, ne)
        if spec.get("skip") or ex:
            skipped.append({"name": spec["name"], "state": spec["state"],
                            "reason": spec.get("skip") or f"exists as {ex['slug']} ({', '.join(ex['towns'])})"})
            continue
        if only and key not in only and make_slug(spec, spec["state"], ne) not in only:
            recs.extend(r for r in prev.values() if r["state"] == spec["state"] and r["name"] == spec["name"])
            continue
        if not args.offline:
            wait = PAUSE_S - (time.time() - last_fetch)
            if wait > 0 and not is_cached(spec, key, args.refresh):
                time.sleep(wait)
        d, fetched = fetch(spec, args.refresh, args.offline)
        done += 1
        if d is None:
            missing.append({"name": spec["name"], "state": spec["state"],
                            "reason": "not fetched yet (--offline)" if args.offline else "Overpass request failed"})
            continue
        if fetched:
            last_fetch = time.time()
            print(f"fetched {key}: {len(d.get('elements', []))} elements", flush=True)
        got = build_records(spec, d, states, ne)
        if not got:
            missing.append({"name": spec["name"], "state": spec["state"], "reason": "no named geometry in OSM"})
        recs.extend(got)
        if done % CHECKPOINT_EVERY == 0:   # progress survives an interrupted run
            have = {r["slug"] for r in recs}
            write_output(recs + [r for r in prev_all.values() if r["slug"] not in have], skipped, missing, partial=True)

    seen, dupes = set(), []
    for r in recs:
        if r["slug"] in seen:
            dupes.append(r["slug"])
        seen.add(r["slug"])
    problems = validate(recs, states) + [f"duplicate slug {s}" for s in dupes]

    write_output(recs, skipped, missing, partial=False, problems=problems)

    print(f"\n{'slug':38} {'name':28} {'kind':7} {'st':2} {'size':>11}  towns / osm")
    for r in recs:
        size = f"{r['length_km']:.1f} km" if r.get("length_km") is not None else f"{r['area_km2']:.3f} km2"
        ids = r["osm"]
        print(f"{r['slug']:38} {r['name'][:28]:28} {r['kind']:7} {r['state']:2} {size:>11}  "
              f"{'; '.join(r['towns'][:6])}{' …' if len(r['towns']) > 6 else ''} | "
              f"{' '.join(ids[:6])}{f' +{len(ids) - 6}' if len(ids) > 6 else ''}")
    print(f"\n{len(recs)} records -> {OUT.relative_to(ROOT)}")
    for s in skipped:
        print(f"skipped {s['name']} ({s['state']}): {s['reason']}")
    for m in missing:
        print(f"MISSING {m['name']} ({m['state']}): {m['reason']}")
    for p in problems:
        print(f"PROBLEM {p}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
