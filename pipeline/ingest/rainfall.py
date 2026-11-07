"""Radar rainfall and forecast rainfall at every CSO outfall -> data/build/rainfall.json

This module is not a feed (it writes no events file); `make rainfall` runs it after the feeds and
build/status.py reads its output for the "discharge likely; no report received" caution
(docs/rain-likely.md). It never makes a discharge record.

    python -m ingest.rainfall [--force] [--no-qpf] [--limit N] [--points]

Points: every combined sewer outfall that is not closed in the outfall registry (every data/outfalls-*.json
through common.load_outfall_registry: the ECHO CSO inventory, national; plant outfalls never drive the caution),
data/build/ma-cso-outfalls.json (MassDEP layer) and data/build/me-cso-outfalls.json (Maine DEP layer), in the
live states (build/status.py states(): a state going live brings its outfalls with it), New Jersey's included
except the permits on the permittees' shared site (ingest/nj_cso_likely.py), which keep the site; rounded to 0.01
degree (about 1 km, the MRMS grid); one point serves every outfall in it.

Observed: NOAA MRMS radar-only QPE from the ImageServer `obs/mrms_qpe`
(https://mapservices.weather.noaa.gov/raster/rest/services/obs/mrms_qpe/ImageServer), product valid
end times "usually by 0:04 after the hour". Read as a grid (ingest/mrms_grid.py, since 2026-11-03): one
catalog `query`, one `exportImage` each of the 1-hour and 24-hour totals over a box around every point,
sampled here at each point (and the 48 and 72-hour totals when a permittee's history lacks the two
earlier 24-hour windows they imply), then one `identify` at the wettest point as a check: a few requests
an hour in place of one per point. When the grid read fails (or the check disagrees), the per-point path
of before runs as the fallback: one `identify` per point (1/3/6/12/24/48/72-hour totals), three at a
time, at most FALLBACK_MAX_CALLS points (one per permittee first, wettest first). Readings are kept per
clock hour (rainfall.json; --force rereads). Negative values are no data.

Unit (found 2026-11-07): the service describes its values as inches, but answers millimetres (identify at Bucklin
Point, RI, valid 2026-11-07T02:00Z: 1.6, 15.8, 26.7, 40.1, 51.3, 52.4, 52.4 for 1 to 72 hours; maxValues 118.7; the
Providence gauge 17.8 to 26.4 mm in the hour to 00:51Z), and already did on 2026-11-03 (the Calais export in
tests/fixtures: 3.8 to 7.3 where IEM's MRMS daily is 0.22 in). So every run decides the unit from the data
(decide_units), never from the description alone: a box maximum (the largest value in the grid blocks read, or in
the run's identify answers) over 50 for 24 hours (the US record, 49.69 in, Kauai, 2018) or 155 for 72 hours (the
world record, 154.7 in, La Reunion, 1980) is millimetres; the gauge check (gauge_check: airport gauges in the box from api.weather.gov, mm, against
identify at the wettest, at most four, where one had 2 mm or more; MRMS/gauge 0.4 to 2.5 is millimetres, the same
over 25.4 inches) decides when it has a verdict (a conflict with the bound divides nothing); else the unit last
determined (rainfall.json mrms.units_last_determined); before any, the stated inches. Millimetres are divided by
25.4 before anything uses them; rainfall.json mrms.units (and each reading's units_read) records the unit, the
basis and the evidence; the identify check compares in the same unit. Point readings stored before the check are
dropped and reread. The history's readings stored before it are rescaled once, every stored hour as millimetres
(repair_history_units, by any run or by --repair-units; the history then carries units_checked, repair 3, and
units_repair; a history an earlier version checked, which kept the hours before its first evidence, gets them rescaled
by repair_second_pass, the hours a later reading backfilled excepted by their provenance, history backfilled).

    python -m ingest.rainfall --repair-units     only the history repair (a second run changes nothing)

Forecast: NWS gridpoint quantitativePrecipitation (mm, 1-6 h periods) from api.weather.gov,
summed over the next 24 hours (a period counts in proportion to its overlap). The point's grid
cell comes from /points/{lat},{lon} once (data/build/nws-gridpoints.json; at most LOOKUP_MAX new
lookups a run); each grid cell is fetched at most every 3 hours (at most QPF_FETCH_MAX a run, the
oldest first). Shown as "rain expected", never as a discharge.

Requests: rainfall.json `requests` counts this run's calls by kind. Before the grid (2026-11-02, 319
New England points) a run made 319 identify calls and, every third hour, 196 forecast calls: about
BASELINE_REQUESTS_PER_HOUR an hour. The caps keep any run within twice that (tests/test_rain_grid.py).

History: data/build/rainfall-history.json keeps, per permittee, the hourly maximum 24-hour total
over its outfall points for the last 90 days (the rule's 48-hour tail and the map's replay need
it). The first reading also fills the two earlier 24-hour windows it implies (48 h - 24 h total
ending 24 h before, 72 h - 48 h ending 48 h before) when those hours are empty.

Raw responses: data/raw/noaa-mrms-qpe/<stamp>.json.gz (a grid run: the catalog answer, the box, each
product's object id, valid time, size and SHA-256, the identify check, the unit decided and the raw value
sampled at every point, as read; a per-point run: every identify answer), data/raw/nws-gauges/observations.json
(the gauge check's observations and identify answers, kept between runs) and data/raw/nws-qpf/<stamp>.json.gz (the QPF
layer and update time of each grid cell fetched). The grids themselves are not kept (about 0.5 MB
each); NOAA archives MRMS.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import sys
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import requests

from common import BUILD_DIR, DATA_DIR, HEADERS, RAW_DIR, load_outfall_registry, now_iso, read_json, save_raw, write_json
from ingest import mrms_grid as grid_mod

SOURCE_ID = "noaa-mrms-qpe-imageserver"
QPF_SOURCE_ID = "nws-api-gridpoint-qpf"
MRMS_URL = grid_mod.MRMS_URL
NWS = "https://api.weather.gov"
OUT = BUILD_DIR / "rainfall.json"
HISTORY = BUILD_DIR / "rainfall-history.json"
GRIDS = BUILD_DIR / "nws-gridpoints.json"
HOURS = (1, 3, 6, 12, 24, 48, 72)
GRID_HOURS = (1, 24)           # read as grids every hour
BACKFILL_HOURS = (48, 72)      # read as grids only when a permittee's history lacks the windows they imply
PRODUCT = "NOAA MRMS radar-only quantitative precipitation estimate, 1 km, 24-hour total (conus_QPE_24H)"
SHARED_SITE_STATES = ("NJ",)  # its permits on the permittees' shared site (ingest/nj_cso_likely.py) keep the site
# The radar product is the contiguous United States grid (conus_QPE_*: 20 to 55 N, 130 to 60 W). A live state outside it
# is not read: its points would have no value, and Juneau (58.3 N) with the pipeline row at Prudhoe Bay (70.26 N) would
# stretch the one export box from 5,575 x 1,648 to 8,146 x 3,883 pixels for every state (Alaska final audit,
# 2026-11-07). Its combined sewer permits stay in out/coverage.json rain_caution_states with covered false.
OUTSIDE_RADAR_GRID = frozenset({"AK", "HI", "PR", "VI", "GU", "AS", "MP"})
# a point's source tag by registry file (rainfall.json outfalls[].source; a national file: "echo-registry")
REGISTRY_SOURCE = {"data/outfalls-new-england.json": "echo", "data/outfalls-mid-atlantic.json": "echo-mid-atlantic",
                   "data/build/outfalls-reported.json": "reported-cso"}   # a combined sewer outfall the reports place
PRODUCT_READY_MIN = 5          # the hour's product is up by about 0:04
QPF_CACHE_H = 3
QPF_WINDOW_H = 24
GRID_RETRY_H = 24              # a failed /points lookup is retried after a day
HISTORY_DAYS = 90
MRMS_WORKERS = 3
MRMS_PAUSE_S = 0.2
NWS_PAUSE_S = 0.3
MIN_OK_SHARE = 0.8             # fewer fresh readings than this share of points: ok false
CHECK_TOLERANCE_IN = 0.011     # grid and identify at the same point and valid time differ by more: the grid is not used
# The unit (found 2026-11-07): the service describes its values as inches but was returning millimetres (identify at
# Bucklin Point, RI, valid 2026-11-07T02:00Z: 51.3 for 24 hours, 2.0 in; maxValues 118.7). The unit of every grid
# and identify answer is decided from the data (decide_units), never from the description alone.
MM_PER_IN = 25.4
# A box maximum over these, read as inches, is above every total ever recorded: millimetres (SOL wave2 P2-10: the
# limits sit above the records they cite, never below them). 24 hours: the US record, 49.69 in at Waipa Garden, Kauai,
# Hawaii, 14-15 April 2018 (NOAA NCEI State Climate Extremes Committee, 2019; above the contiguous record, 42 in at
# Alvin, Texas, 1979). 72 hours: the world record, 3,930 mm (154.7 in) at Cratere Commerson, La Reunion, 24-27
# February 1980 (WMO World Weather and Climate Extremes Archive). Thirty inches in a day is extreme, not impossible.
UNIT_BOUND_IN = {24: 50.0, 72: 155.0}
UNIT_BOUND_CITE = {24: "the US 24-hour record, 49.69 in, Waipa Garden, Kauai, Hawaii, 2018 (NOAA NCEI SCEC)",
                   72: "the world 72-hour record, 3,930 mm (154.7 in), Cratere Commerson, La Reunion, 1980 (WMO)"}
UNITS_FOUND = "2026-11-07"
UNIT_RULE = (f"unit decided from the data (found {UNITS_FOUND}): a box maximum over {UNIT_BOUND_IN[24]:g} (24 h, "
             f"{UNIT_BOUND_CITE[24]}) or {UNIT_BOUND_IN[72]:g} (72 h, {UNIT_BOUND_CITE[72]}) is millimetres, the "
             f"gauge check decides when it has a verdict, and when the two conflict nothing is divided (the safety "
             f"side) and the conflict is recorded; else the unit last determined; values in millimetres are divided "
             f"by {MM_PER_IN} before use")
# The gauge check (gauge_check): airport gauges, api.weather.gov /stations/{id}/observations (precipitation in mm),
# against MRMS identify at the same place; a fixed small list, used when inside the box.
GAUGES = {"KPVD": (41.72, -71.43), "KBOS": (42.36, -71.01), "KBDL": (41.94, -72.68), "KLGA": (40.78, -73.88),
          "KPHL": (39.87, -75.23), "KBWI": (39.17, -76.68), "KORD": (41.96, -87.93), "KDTW": (42.23, -83.33),
          "KATL": (33.63, -84.44), "KMIA": (25.79, -80.32), "KSEA": (47.44, -122.31), "KLAX": (33.94, -118.39),
          "KSFO": (37.62, -122.37)}
GAUGE_FIELDS = ((6, "precipitationLast6Hours"), (3, "precipitationLast3Hours"), (1, "precipitationLastHour"))
GAUGE_MIN_MM = 2.0             # a gauge with less in the window gives no verdict
GAUGE_IDENTIFY_MAX = 4         # identify calls a run for the gauge check (the wettest gauges)
GAUGE_EARLY = timedelta(minutes=20)   # observations from this long before the valid time up to it (an observation after
                                      # it, a special report, counts only from the routine report a few minutes before)
GAUGE_SETTLE = timedelta(minutes=20)  # observations fetched this long after the valid time are kept for it (the routine
                                      # report at :51 to :56 reaches api.weather.gov some minutes later)
GAUGE_TIMEOUT_S = 20                  # one attempt per station; the first failure skips the others (the run goes on)
GAUGE_RATIO_MM = (0.4, 2.5)    # MRMS / gauge in this range: millimetres; the same over 25.4: inches
GAUGE_CACHE = RAW_DIR / "nws-gauges" / "observations.json"
# Readings known to be millimetres before the check (repair_history_units): the unit from then on, until the bound
# says otherwise, is millimetres (the last unit determined).
KNOWN_MM_AT = {
    "2026-11-03T13:00:00Z": "exportImage of conus_QPE_24H valid 2026-11-03T13:00Z over Calais, Maine "
                            "(pipeline/tests/fixtures/mrms-qpe-24h-20261103T13Z.tif) and identify there: 3.8, 5.9 and "
                            "4.6 at three points, box maximum 7.3, where IEM's MRMS daily rainfall at 45.12, -67.38 is "
                            "0.02 in for 2026-11-02 and 0.22 in for 2026-11-03: millimetres",
}
REPAIR_VERSION = 3             # 1: hours before the first evidence kept as inches; 2: those rescaled, but never within
                               # 50 hours of the check; 3: those too, told from the readings' backfills by provenance
                               # (SOL wave2 P2-7)
BACKFILL_REACH_H = 50          # a reading after the check fills windows up to 48 hours before its valid time, which
                               # can be an hour before the check
BASELINE_REQUESTS_PER_HOUR = 384   # 319 identify + 196 forecast cells / 3 (2026-11-02, before the grid)
FALLBACK_MAX_CALLS = 350       # per-point identify calls when the grid fails
LOOKUP_MAX = 100               # new NWS /points lookups a run
QPF_FETCH_MAX = 250            # NWS gridpoint fetches a run
NWS_HEADERS = {**HEADERS, "Accept": "application/geo+json"}


# ---------------------------------------------------------------- time helpers

def parse_t(s) -> datetime | None:
    if not s:
        return None
    try:
        t = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def iso(t: datetime | None) -> str | None:
    return t.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z") if t else None


def hour_floor(t: datetime) -> datetime:
    return t.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


def parse_duration(s: str) -> timedelta | None:
    """ISO 8601 durations as the NWS writes them: PT1H, PT6H, P1D, P1DT6H, PT30M."""
    m = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?)?", s or "")
    if not m or not any(m.groups()):
        return None
    d, h, mi = (int(x) if x else 0 for x in m.groups())
    return timedelta(days=d, hours=h, minutes=mi)


# ---------------------------------------------------------------- requests

REQUEST_KINDS = (("/exportImage", "mrms_export"), ("/identify", "mrms_identify"), ("/query", "mrms_query"),
                 ("/points/", "nws_points"), ("/gridpoints/", "nws_gridpoints"), ("/stations/", "nws_stations"))


def request_kind(url: str) -> str:
    u = str(url)
    for part, kind in REQUEST_KINDS:
        if part in u:
            return kind
    return "other"


class CountingSession:
    """A requests session that counts every call by kind (retries included)."""

    def __init__(self, session):
        self.session = session
        self.headers = session.headers
        self.counts: Counter = Counter()
        self._lock = threading.Lock()

    def get(self, url, **kw):
        with self._lock:
            self.counts[request_kind(url)] += 1
        return self.session.get(url, **kw)

    def summary(self) -> dict:
        c = {k: self.counts.get(k, 0) for _, k in REQUEST_KINDS}
        if self.counts.get("other"):
            c["other"] = self.counts["other"]
        return {**c, "total": sum(c.values()), "noaa_mrms": sum(v for k, v in c.items() if k.startswith("mrms_")),
                "noaa_nws": sum(v for k, v in c.items() if k.startswith("nws_")),
                "baseline_per_hour": BASELINE_REQUESTS_PER_HOUR}


# ---------------------------------------------------------------- outfall points

def norm_oid(s) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(s or "").upper())


def point_key(lat: float, lon: float) -> str:
    return f"{round(float(lat), 2):.2f},{round(float(lon), 2):.2f}"


def radar_states(live: set[str] | None = None) -> set[str]:
    """The states whose combined sewer outfalls the radar reads: the live states (build/status.py states(), the
    one list the site's state pages and the export use) inside the radar grid (OUTSIDE_RADAR_GRID left out). In
    New Jersey the permits on the permittees' shared site are left to it (cso_outfalls); its other permits are read
    like any other state's."""
    if live is None:
        from build import status as status_mod
        live = status_mod.states()
    return {str(s).upper() for s in live} - OUTSIDE_RADAR_GRID


def cso_outfalls(live: set[str] | None = None) -> list[dict]:
    """Every combined sewer outfall not marked closed in a radar state (radar_states):
    {permit, outfall, state, name, lat, lon, water_slug, source}. The registry is every data/outfalls-*.json
    (common.load_outfall_registry, national; plant outfalls left out: they never drive the caution), then the
    MassDEP and Maine DEP layers; the MassDEP layer takes its water from the registry row of the same permit and
    outfall. New Jersey's permits on the permittees' shared site keep the site (ingest/nj_cso_likely.py); its other
    combined sewer permits are read here."""
    radar = radar_states(live)
    from build.rain_likely import shared_site_permits
    on_site = shared_site_permits(BUILD_DIR) if set(SHARED_SITE_STATES) & radar else set()
    registry = load_outfall_registry(DATA_DIR)
    by_po = {(o.get("npdes_permit"), norm_oid(o.get("outfall"))): o for o in registry}
    out, seen = [], set()

    def add(permit, outfall, state, name, lat, lon, slug, src, match=None, dist=None):
        if not permit or lat is None or lon is None:
            return
        key = (permit, norm_oid(outfall), round(float(lat), 4), round(float(lon), 4))
        if key in seen:
            return
        seen.add(key)
        out.append({"permit": permit, "outfall": str(outfall) if outfall not in (None, "") else None,
                    "state": state or permit[:2], "name": name, "lat": float(lat), "lon": float(lon),
                    "water_slug": slug, "water_match": match if slug else None,
                    "distance_m": dist if slug else None, "source": src})
    for o in registry:
        if (o.get("outfall_kind") or "cso") != "cso" or str(o.get("outfall_status") or "").startswith("CLS") \
                or o.get("rain_caution") is False:      # a lake reversal gate (data/outfalls-il.json): not rain-driven
            continue
        st = str(o.get("state") or str(o.get("npdes_permit") or "")[:2]).upper()
        if st not in radar or (st in SHARED_SITE_STATES and o.get("npdes_permit") in on_site):
            continue
        add(o.get("npdes_permit"), o.get("outfall"), st, o.get("permittee"), o.get("lat"), o.get("lon"),
            o.get("water_slug"), REGISTRY_SOURCE.get(o.get("_file"), "echo-registry"), o.get("match"), o.get("distance_m"))
    if "MA" in radar:
        ma = (read_json(BUILD_DIR / "ma-cso-outfalls.json", {}) or {}).get("outfalls") or {}
        for o in (ma.values() if isinstance(ma, dict) else ma):
            e = by_po.get((o.get("npdes"), norm_oid(o.get("outfall"))))
            if e and str(e.get("outfall_status") or "").startswith("CLS"):
                continue
            add(o.get("npdes"), o.get("outfall"), "MA", o.get("system"), o.get("lat"), o.get("lon"),
                (e or {}).get("water_slug"), "massdep-layer", (e or {}).get("match"))
    if "ME" in radar:
        for o in (read_json(BUILD_DIR / "me-cso-outfalls.json", {}) or {}).get("outfalls") or []:
            if str(o.get("status") or "").upper() == "CLOSED":
                continue
            add(o.get("permit"), o.get("outfall"), "ME", o.get("facility"), o.get("lat"), o.get("lon"),
                o.get("water_slug"), "me-dep-layer", o.get("echo_water_match") or o.get("water_match"))
    # an operator with open CSO outfalls but no outfall point in any source: its rainfall is read at its treatment
    # plant (its plant outfall row, else EPA's facility point), so its waters still get the caution (owner: err on
    # the side of safety, 2026-11-03); never for an operator with any outfall point
    pointed = {o["permit"] for o in out}
    pointless = {}
    for o in registry:
        st = str(o.get("state") or str(o.get("npdes_permit") or "")[:2]).upper()
        if ((o.get("outfall_kind") or "cso") == "cso" and not str(o.get("outfall_status") or "").startswith("CLS")
                and st in radar and not (st in SHARED_SITE_STATES and o.get("npdes_permit") in on_site)
                and o.get("npdes_permit") not in pointed):
            pointless.setdefault(o["npdes_permit"], st)
    plants = sorted((o for o in registry if o.get("outfall_kind") == "plant" and o.get("npdes_permit") in pointless
                     and o.get("lat") is not None and o.get("lon") is not None),
                    key=lambda o: (o.get("coords_from") == "facility", norm_oid(o.get("outfall")) or "~"))
    for o in plants:
        if o["npdes_permit"] in {x["permit"] for x in out}:
            continue                    # one plant point per operator
        add(o["npdes_permit"], o.get("outfall"), pointless[o["npdes_permit"]], o.get("permittee"), o["lat"], o["lon"],
            None, "plant-point")
    return out


def group_points(outfalls: list[dict]) -> dict[str, dict]:
    pts: dict[str, dict] = {}
    for o in outfalls:
        k = point_key(o["lat"], o["lon"])
        p = pts.setdefault(k, {"lat": round(o["lat"], 2), "lon": round(o["lon"], 2), "outfalls": [], "permits": [],
                               "states": []})
        p["outfalls"].append(f"{o['permit']}:{o['outfall'] or '?'}")
        for f, v in (("permits", o["permit"]), ("states", o["state"])):
            if v not in p[f]:
                p[f].append(v)
    return pts


# ---------------------------------------------------------------- the unit

def bound_verdict(maxima: dict) -> dict | None:
    """maxima {hours: the largest value read, in the service's unit}: millimetres when a 24-hour maximum is over the
    US 24-hour record or a 72-hour maximum over the world 72-hour record (UNIT_BOUND_IN, impossible as inches); None
    when the bound cannot tell."""
    over = {h: m for h, m in (maxima or {}).items() if h in UNIT_BOUND_IN and m is not None and m > UNIT_BOUND_IN[h]}
    if not over:
        return None
    h = min(over)
    return {"units_read": "mm", "basis": "physical_bound",
            "evidence": {"box_max": {f"h{k}": v for k, v in sorted(over.items())},
                         "bound_in": {f"h{k}": UNIT_BOUND_IN[k] for k in sorted(over)},
                         "text": f"the largest {h}-hour value read, {over[h]}, is over {UNIT_BOUND_IN[h]:g}, above "
                                 f"{UNIT_BOUND_CITE[h]}, impossible as inches: millimetres"}}


def decide_units(maxima: dict, last: dict | None = None, gauge: dict | None = None) -> dict:
    """The unit of this run's MRMS values: {units_read: "mm" | "in", factor (divide by it for inches), basis,
    evidence, box_max}. The gauge check (gauge_check) decides when it has a verdict; then the physical bound; else
    the last unit determined (last: rainfall.json mrms.units_last_determined); else the service's stated inches.
    When the gauge check reads inches and the box maximum is over the bound, the evidence conflicts (SOL wave2 P2-10):
    nothing is divided (dividing would cut every genuine reading, a 0.2 in among them, to a twenty-fifth: err on the
    side of safety), both pieces are recorded, and the run's unit (basis "conflict") is not kept as the last
    determined one."""
    box_max = {f"h{h}": v for h, v in sorted((maxima or {}).items()) if v is not None}
    b = bound_verdict(maxima)
    gv = (gauge or {}).get("verdict")
    if gv == "in" and b:
        d = {"units_read": "in", "basis": "conflict",
             "evidence": {"gauge_check": {k: v for k, v in gauge.items() if k != "pairs"},
                          "physical_bound": b["evidence"]},
             "conflict": f"the gauge check read inches ({gauge.get('text')}) but {b['evidence']['text']}; nothing is "
                         f"divided (the safety side) and the unit is not kept as determined"}
    elif gv in ("mm", "in"):
        d = {"units_read": gv, "basis": "gauge_check", "evidence": {k: v for k, v in gauge.items() if k != "pairs"}}
    elif b:
        d = dict(b)
    elif last and last.get("units_read") in ("mm", "in"):
        d = {"units_read": last["units_read"], "basis": "last_determined",
             "evidence": {"determined_at": last.get("determined_at"), "basis": last.get("basis")}}
    else:
        d = {"units_read": "in", "basis": "service_description",
             "evidence": {"text": "no unit determined yet: the service's stated inches"}}
    d["factor"] = MM_PER_IN if d["units_read"] == "mm" else 1.0
    d["box_max"] = box_max
    return d


def to_inches(v, factor: float):
    return None if v is None else round(float(v) / factor, 2)


def trim_observations(d: dict) -> list[dict]:
    """[{t, h1, h3, h6}] in millimetres from an api.weather.gov observations answer (a value in another unit is
    left out)."""
    out = []
    for f in (d or {}).get("features") or []:
        pr = f.get("properties") or {}
        row = {"t": pr.get("timestamp")}
        for h, field in GAUGE_FIELDS:
            q = pr.get(field) or {}
            v = q.get("value")
            row[f"h{h}"] = float(v) if v is not None and str(q.get("unitCode") or "").endswith(":mm") else None
        if row["t"]:
            out.append(row)
    return out


def gauge_window(obs: list[dict], valid_time: datetime) -> dict | None:
    """The gauge's amount for the window ending near the MRMS valid time: of the observations from GAUGE_EARLY before
    the valid time up to it, the longest window with at least GAUGE_MIN_MM, taking the largest value of that window
    (the routine report; a special report before it holds the amount since the last routine one, a little less, and
    rows without precipitation, such as the five-minute rows, are passed over): {obs_time, hours, gauge_mm}; None when
    no gauge rain. Observations after the valid time are left out: a special report there holds only the minutes
    since the routine report (review 2026-11-07)."""
    near = [o for o in obs if parse_t(o.get("t")) and valid_time - GAUGE_EARLY <= parse_t(o["t"]) <= valid_time]
    for h, _ in GAUGE_FIELDS:
        vals = [(o[f"h{h}"], o["t"]) for o in near if o.get(f"h{h}") is not None]
        if vals:
            v, t = max(vals)
            if v >= GAUGE_MIN_MM:
                return {"obs_time": t, "hours": h, "gauge_mm": v}
    return None


def gauge_verdict(pairs: list[dict]) -> dict:
    """The MRMS values at the gauges (as read) against the gauges (mm), summed: a ratio near 1 is millimetres,
    near 1/25.4 inches; anything else, or no pair, gives no verdict."""
    use = [p for p in pairs if p.get("mrms_as_read") is not None]
    if not use:
        return {"verdict": None, "text": "skipped: no gauge in the box had 2 mm or more"}
    g, m = sum(p["gauge_mm"] for p in use), sum(p["mrms_as_read"] for p in use)
    r = m / g
    lo, hi = GAUGE_RATIO_MM
    v = "mm" if lo <= r <= hi else "in" if lo / MM_PER_IN <= r <= hi / MM_PER_IN else None
    return {"verdict": v, "ratio": round(r, 3), "gauge_mm": round(g, 1), "mrms_as_read": round(m, 2),
            "gauges": [p["station"] for p in use],
            "text": f"MRMS {round(m, 2)} against {round(g, 1)} mm at {len(use)} gauge(s) "
                    f"({', '.join(p['station'] for p in use)}): ratio {r:.3f}, "
                    + ({"mm": "millimetres", "in": "inches"}.get(v) or "no verdict")}


def gauge_check(session, box: dict, valid_time: str, now: datetime) -> dict:
    """Once a run: the observations of the GAUGES inside the box from GAUGE_EARLY before the valid time to it (kept in
    GAUGE_CACHE per valid time, refetched when fetched less than GAUGE_SETTLE after it; one attempt each, and the
    first failure skips the stations left, so api.weather.gov being down costs one timeout), and MRMS identify at the wettest (at most GAUGE_IDENTIFY_MAX,
    kept per valid time) where a gauge had at least GAUGE_MIN_MM: {verdict, ratio, ..., pairs, fetched}."""
    vt = parse_t(valid_time)
    cache = read_json(GAUGE_CACHE, {}) or {}
    obs_c, idf_c = cache.setdefault("observations", {}), cache.setdefault("identify", {})
    inside = [st for st, (la, lo) in sorted(GAUGES.items())
              if box["ymin"] <= la <= box["ymax"] and box["xmin"] <= lo <= box["xmax"]]
    if not inside:
        return {"verdict": None, "text": "skipped: no gauge of the list in the box", "valid_time": valid_time,
                "gauges_in_box": [], "fetched": 0, "errors": {}, "pairs": []}
    fetched, errors, wet, down = 0, {}, [], False
    for st in inside:
        c = obs_c.get(st) or {}
        if not (c.get("valid_time") == valid_time and parse_t(c.get("fetched_at"))
                and parse_t(c["fetched_at"]) >= vt + GAUGE_SETTLE):
            if down:
                errors[st] = "skipped: api.weather.gov failed for an earlier station this run"
                continue
            try:
                r = session.get(f"{NWS}/stations/{st}/observations", headers=NWS_HEADERS, timeout=GAUGE_TIMEOUT_S,
                                params={"start": iso(vt - GAUGE_EARLY), "end": iso(vt)})
                r.raise_for_status()
                c = obs_c[st] = {"valid_time": valid_time, "fetched_at": iso(now), "observations": trim_observations(r.json())}
                fetched += 1
            except Exception as e:  # noqa: BLE001
                errors[st] = f"{type(e).__name__}: {e}"[:200]
                down = True
                continue
        w = gauge_window(c.get("observations") or [], vt)
        if w:
            wet.append({"station": st, **w})
    wet.sort(key=lambda p: (-p["gauge_mm"], p["station"]))
    pairs = []
    for p in wet[:GAUGE_IDENTIFY_MAX]:
        c = idf_c.get(p["station"]) or {}
        if c.get("valid_time") != valid_time:
            la, lo = GAUGES[p["station"]]
            try:
                m = parse_identify(identify(session, la, lo))
            except Exception as e:  # noqa: BLE001
                errors[p["station"]] = f"identify: {type(e).__name__}: {e}"[:200]
                continue
            c = idf_c[p["station"]] = {"valid_time": m.get("valid_time"),
                                       **{f"h{h}": m.get(f"h{h}") for h, _ in GAUGE_FIELDS}}
        if c.get("valid_time") == valid_time:
            pairs.append({**p, "mrms_as_read": c.get(f"h{p['hours']}")})
    write_json(GAUGE_CACHE, cache)
    out = gauge_verdict(pairs)
    return {**out, "valid_time": valid_time, "gauges_in_box": inside, "fetched": fetched, "errors": errors,
            "pairs": pairs}


# ---------------------------------------------------------------- MRMS: per point (the fallback)

def parse_identify(d: dict) -> dict:
    """{valid_time, h1 ... h72, problems}: Values pair with the catalog items in order; each item is
    named conus_QPE_<NN>H. Accumulations must not shrink with the window (a check on the pairing)."""
    vals = (d.get("properties") or {}).get("Values") or []
    feats = (d.get("catalogItems") or {}).get("features") or []
    out, valid, problems = {f"h{h}": None for h in HOURS}, [], []
    if not feats and d.get("value") is not None and len(vals) <= 1:
        problems.append("no catalog items in the answer")
    for i, f in enumerate(feats):
        a = f.get("attributes") or {}
        m = re.search(r"QPE_(\d+)H", str(a.get("name") or ""))
        if not m or i >= len(vals):
            continue
        h = int(m.group(1))
        try:
            v = float(vals[i])
        except (TypeError, ValueError):
            v = None
        if v is not None and (v < 0 or v != v):
            v = None                         # negative pixels are no data
        if h in HOURS:
            out[f"h{h}"] = round(v, 2) if v is not None else None
        if a.get("idp_validendtime"):
            valid.append(int(a["idp_validendtime"]))
    if valid:
        out["valid_time"] = iso(datetime.fromtimestamp(max(valid) / 1000, UTC))
        if len(set(valid)) > 1:
            problems.append("catalog items have different valid times; the latest is used")
    else:
        out["valid_time"] = None
        problems.append("no valid time in the answer")
    seq = [out[f"h{h}"] for h in HOURS if out[f"h{h}"] is not None]
    if any(b + 0.005 < a for a, b in zip(seq, seq[1:])):
        problems.append("accumulations shrink with the window: values and catalog items may be mispaired")
    out["problems"] = problems
    return out


def identify(session, lat: float, lon: float) -> dict:
    params = {"geometry": json.dumps({"x": lon, "y": lat, "spatialReference": {"wkid": 4326}}),
              "geometryType": "esriGeometryPoint", "returnGeometry": "false", "returnCatalogItems": "true",
              "f": "json"}
    last = None
    for attempt in range(2):
        try:
            r = session.get(f"{MRMS_URL}/identify", params=params, timeout=30)
            r.raise_for_status()
            d = r.json()
            if "error" in d:
                raise ValueError(f"service error {d['error']}")
            return d
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 + 3 * attempt)
    raise last


def needs_mrms(prev: dict | None, now: datetime, force: bool) -> bool:
    """One reading per point per clock hour, once the hour's product is up."""
    if force or not prev or not prev.get("fetched_at"):
        return True
    ready = hour_floor(now - timedelta(minutes=PRODUCT_READY_MIN))
    fetched = parse_t(prev["fetched_at"])
    return fetched is None or hour_floor(fetched - timedelta(minutes=PRODUCT_READY_MIN)) < ready


def fallback_order(points: dict[str, dict], todo: list[str], cap: int) -> list[str]:
    """The points the per-point fallback reads, at most cap: first one point per permittee (its wettest at
    the last reading), then the others, wettest first."""
    def wet(k):
        v = ((points[k].get("mrms") or {}).get("h24"))
        return -1.0 if v is None else float(v)
    todo_set = set(todo)
    by_permit = defaultdict(list)
    for k in todo:
        for p in points[k]["permits"]:
            by_permit[p].append(k)
    first: list[str] = []
    for p in sorted(by_permit):
        k = sorted(by_permit[p], key=lambda x: (-wet(x), x))[0]
        if k not in first:
            first.append(k)
    rest = sorted(todo_set - set(first), key=lambda x: (-wet(x), x))
    return (sorted(first, key=lambda x: (-wet(x), x)) + rest)[:max(0, cap)]


# ---------------------------------------------------------------- MRMS: the grid

def backfill_needed(hist: dict | None, permits: set[str], now: datetime) -> bool:
    """True when a permittee's history has no value 24 or 48 hours before this hour's product (a first
    reading, or a gap): the 48 and 72-hour grids then fill those windows."""
    hist = hist or {}
    start = parse_t(hist.get("start"))
    series = hist.get("permits") or {}
    expected = hour_floor(now - timedelta(minutes=PRODUCT_READY_MIN))
    for p in permits:
        arr = series.get(p)
        if not arr or start is None:
            return True
        for back in (24, 48):
            i = int(((expected - timedelta(hours=back)) - start).total_seconds() // 3600)
            if not (0 <= i < len(arr)) or arr[i] is None:
                return True
    return False


def read_grid(session, points: dict[str, dict], hours) -> dict:
    """One catalog query and one export per accumulation, sampled at every point. Returns {values: {key:
    {h1, h24, ...}}, maxima: {hours: the box maximum}, valid_time, products, box, problems, catalog}, the values in the
    service's unit as read (run() decides the unit and converts); raises when the 24-hour grid cannot be
    read, is not where it was asked, or has no value at most points."""
    names = [grid_mod.item_name(h) for h in hours]
    cat, cat_raw = grid_mod.catalog(session, names)
    n24 = grid_mod.item_name(24)
    if n24 not in cat:
        raise ValueError(f"{n24} not in the catalog answer")
    vt = cat[n24]["valid_time"]
    box = grid_mod.grid_box([(p["lat"], p["lon"]) for p in points.values()])
    pts = {k: (p["lat"], p["lon"]) for k, p in points.items()}
    values: dict[str, dict] = {k: {} for k in points}
    products, problems, maxima = {}, [], {}
    for h in hours:
        name = grid_mod.item_name(h)
        c = cat.get(name)
        if not c:
            problems.append(f"{name}: not in the catalog answer")
            continue
        if c["valid_time"] != vt:
            problems.append(f"{name} is valid to {c['valid_time']}, the 24-hour total to {vt}: not used")
            continue
        try:
            b = grid_mod.export(session, c["objectid"], box)
            g = grid_mod.Grid(b)
            geo = grid_mod.check_georef(g, box)
            if geo:
                raise ValueError("; ".join(geo))
            got = grid_mod.sample(g, pts)
        except Exception as e:  # noqa: BLE001
            if h == 24:
                raise
            problems.append(f"{name}: {type(e).__name__}: {e}"[:300])
            continue
        for k, v in got.items():
            values[k][f"h{h}"] = v
        mx = [x for x in [g.max_read(), *got.values()] if x is not None]
        maxima[h] = max(mx) if mx else None
        products[str(h)] = {"item": name, "objectid": c["objectid"], "valid_time": c["valid_time"], "bytes": len(b),
                            "sha256": hashlib.sha256(b).hexdigest(), **g.meta()}
    missing = sum(1 for v in values.values() if v.get("h24") is None)
    if missing > (1 - MIN_OK_SHARE) * len(values):
        raise ValueError(f"the 24-hour grid has no value at {missing} of {len(values)} points")
    if missing:
        problems.append(f"no 24-hour value at {missing} point(s)")
    shrink = [k for k, v in values.items() if None not in (v.get("h1"), v.get("h24")) and v["h1"] > v["h24"] + 0.005]
    if shrink:
        problems.append(f"1-hour total above the 24-hour total at {len(shrink)} point(s), e.g. {shrink[0]}")
    return {"values": values, "maxima": maxima, "valid_time": vt, "products": products, "box": box,
            "problems": problems, "catalog": cat_raw}


def check_grid(session, grid: dict, points: dict[str, dict], factor: float = 1.0) -> dict:
    """identify at the wettest point: the grid's value there must be identify's (same valid time). The grid's
    values are in inches (converted); identify's answer is converted with the same factor before the comparison
    (both come from the same service in the same unit)."""
    vals = grid["values"]
    k = max(sorted(vals), key=lambda x: vals[x].get("h24") if vals[x].get("h24") is not None else -1.0)
    out = {"point": k, "grid_h24": vals[k].get("h24")}
    d = identify(session, points[k]["lat"], points[k]["lon"])
    m = parse_identify(d)
    out.update(identify_h24=to_inches(m["h24"], factor), identify_h24_as_read=m["h24"],
               identify_valid_time=m["valid_time"], answer=d)
    m["h24"] = out["identify_h24"]
    if m["valid_time"] != grid["valid_time"]:
        out["result"] = "skipped: the product changed between the grid and the check"
    elif m["h24"] is None or vals[k].get("h24") is None:
        out["result"] = "skipped: no value at the point"
    elif abs(m["h24"] - vals[k]["h24"]) > CHECK_TOLERANCE_IN:
        out["result"] = "differs"
    else:
        out["result"] = "agrees"
    return out


# ---------------------------------------------------------------- NWS QPF

def qpf_next(values: list, now: datetime, hours: int = QPF_WINDOW_H) -> dict:
    """Sum of the forecast periods over [now, now + hours] in inches; a period counts in proportion
    to its overlap. values: [[start iso, duration iso, mm], ...]. Periods without a value are skipped
    and counted; covered_hours says how much of the window the forecast reaches."""
    t0, t1 = now, now + timedelta(hours=hours)
    total, covered, missing = 0.0, 0.0, 0
    for start, dur, mm in values:
        a, d = parse_t(start), parse_duration(dur)
        if a is None or d is None or d.total_seconds() <= 0:
            continue
        b = a + d
        ov = (min(b, t1) - max(a, t0)).total_seconds()
        if ov <= 0:
            continue
        if mm is None:
            missing += 1
            continue
        total += float(mm) * ov / d.total_seconds()
        covered += ov / 3600
    return {"in_24h": round(total / 25.4, 2), "covered_hours": round(covered, 1), "missing_periods": missing,
            "from": iso(t0), "to": iso(t1)}


def trim_qpf(d: dict) -> dict:
    p = d.get("properties") or {}
    q = p.get("quantitativePrecipitation") or {}
    vals = []
    for v in q.get("values") or []:
        vt = str(v.get("validTime") or "")
        if "/" in vt:
            a, dur = vt.split("/", 1)
            vals.append([a, dur, v.get("value")])
    uom = q.get("uom") or ""
    if vals and "mm" not in uom:
        raise ValueError(f"unexpected QPF unit {uom!r}")
    return {"update_time": p.get("updateTime"), "uom": uom, "values": vals}


def window_values(values: list, now: datetime) -> list:
    """The forecast periods a run within the cache time can still need: those overlapping
    [now, now + cache + window]. The whole layer is in the raw file."""
    t1 = now + timedelta(hours=QPF_CACHE_H + QPF_WINDOW_H + 1)
    out = []
    for start, dur, mm in values:
        a, d = parse_t(start), parse_duration(dur)
        if a is not None and d is not None and a + d > now and a < t1:
            out.append([start, dur, mm])
    return out


def nws_get(session, url: str) -> dict:
    last = None
    for attempt in range(3):
        try:
            r = session.get(url, headers=NWS_HEADERS, timeout=45)
            if r.status_code in (500, 502, 503, 504):
                raise requests.HTTPError(f"HTTP {r.status_code}")
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 + 4 * attempt)
    raise last


# ---------------------------------------------------------------- history

def update_history(hist: dict | None, permits: dict[str, dict], now: datetime) -> dict:
    """Per permittee, the hourly maximum 24-hour total (inches) for the last HISTORY_DAYS days, as
    arrays aligned on a shared start hour. permits[p] = {valid_time, h24, h48, h72} (maxima over the
    permittee's points at the latest valid time). A first reading fills the two earlier windows it
    implies when they are empty."""
    start = hour_floor(now) - timedelta(hours=HISTORY_DAYS * 24 - 1)
    n = HISTORY_DAYS * 24
    old = hist or {}
    old_start = parse_t(old.get("start"))
    shift = int((start - old_start).total_seconds() // 3600) if old_start else 0
    series = {}
    for p, arr in (old.get("permits") or {}).items():
        new = [None] * n
        for i, v in enumerate(arr):
            j = i - shift
            if 0 <= j < n:
                new[j] = v
        series[p] = new
    # provenance (SOL wave2 P2-7): the hours each permittee's array holds from a 48 or 72-hour total (a backfill,
    # already in inches), as against its own hour's reading; a reading for the hour itself replaces the mark
    backfilled = {p: {h for h in hs if parse_t(h) and parse_t(h) >= start}
                  for p, hs in (old.get("backfilled") or {}).items()}
    for p, r in permits.items():
        vt = parse_t(r.get("valid_time"))
        if vt is None:
            continue
        arr = series.setdefault(p, [None] * n)
        filled = backfilled.setdefault(p, set())

        def put(t, v, overwrite=True):
            i = int((hour_floor(t) - start).total_seconds() // 3600)
            if 0 <= i < n and v is not None and (overwrite or arr[i] is None):
                arr[i] = round(max(0.0, v), 2)
                (filled.discard if overwrite else filled.add)(iso(start + timedelta(hours=i)))
        put(vt, r.get("h24"))
        if r.get("h48") is not None and r.get("h24") is not None:
            put(vt - timedelta(hours=24), r["h48"] - r["h24"], overwrite=False)
        if r.get("h72") is not None and r.get("h48") is not None:
            put(vt - timedelta(hours=48), r["h72"] - r["h48"], overwrite=False)
    series = {p: a for p, a in series.items() if any(v is not None for v in a)}
    backfilled = {p: sorted(hs) for p, hs in sorted(backfilled.items()) if hs and p in series}
    out = {"updated_at": iso(now), "start": iso(start), "step_hours": 1, "count": n,
           "units": "inches: the largest NOAA MRMS radar-only 24-hour total over the permittee's outfall points, "
                    "for the 24 hours ending at each hour (UTC); the service's values converted from millimetres "
                    "when they are millimetres (rainfall.json mrms.units)",
           "units_checked": old.get("units_checked") or {"from": iso(hour_floor(now)), "rule": UNIT_RULE,
                                                          "repair": REPAIR_VERSION},
           "source": MRMS_URL, "permits": series}
    if backfilled:
        out["backfilled"] = backfilled
    # from this hour on every backfill is marked: an unmarked hour after it is the hour's own reading
    out["backfilled_since"] = old.get("backfilled_since") or (iso(start) if not old.get("permits")
                                                              else iso(hour_floor(now)))
    if old.get("units_repair"):
        out["units_repair"] = old["units_repair"]
    return out


def repair_second_pass(hist: dict, now: datetime) -> tuple[dict, dict]:
    """A history an earlier repair checked (version 1 or 2) may still hold millimetres labelled as inches: version 1
    kept the hours before its first millimetre hour (every answer of the service seen is millimetres: review
    2026-11-07, P1-1), and version 2 rescaled those but never within BACKFILL_REACH_H hours of the check, where a
    reading after the check may have filled an empty hour from a 48 or 72-hour total, already in inches (SOL wave2
    P2-7). Every hour before the first range version 1 rescaled (else before the check) is an original reading in
    millimetres, rescaled here exactly once, unless the history's provenance (backfilled) marks it a backfill. An hour
    within BACKFILL_REACH_H hours of the check that the provenance does not mark is an original when the marks are
    complete since the check (backfilled_since at or before it); otherwise it cannot be told apart: it is left as
    stored (the larger reading: the safety side), listed in units_repair.third_pass.unresolved, and the history is
    not marked repaired (units_checked.repair) while one such hour is in the window."""
    chk, rep1 = hist["units_checked"], hist.get("units_repair") or {}
    start, frm = parse_t(hist.get("start")), parse_t(chk.get("from"))
    if start is None or frm is None or not rep1.get("hours_kept_as_inches"):
        chk["repair"] = REPAIR_VERSION
        return hist, {"changed": False, "reason": "nothing kept as inches"}
    ranges = rep1.get("ranges") or []
    first = parse_t(ranges[0][0]) if ranges else None
    cut = hour_floor(min(t for t in (first, frm) if t))      # before it: originals or backfills, never rescaled
    reach = frm - timedelta(hours=BACKFILL_REACH_H)          # before it: no backfill can reach, originals only
    third = rep1.get("third_pass") or {}
    sp = rep1.get("second_pass") or {}
    done = [parse_t(x) for x in (third.get("rescaled_before"),
                                 sp.get("before") if (chk.get("repair") or 1) >= 2 else None) if x]
    done_before = max(done) if done else None                # every original before it is rescaled already
    marks = {p: set(hs) for p, hs in (hist.get("backfilled") or {}).items()}
    since = parse_t(hist.get("backfilled_since"))
    complete = since is not None and since <= frm             # every backfill since the check is marked
    hours, values, unresolved, held = set(), 0, {}, set()
    for p, a in hist["permits"].items():
        for i, v in enumerate(a):
            t = start + timedelta(hours=i)
            if t >= cut:
                break
            if v is None or (done_before and t < done_before):
                continue
            if iso(t) in marks.get(p, ()):
                continue                                     # a backfill: inches already
            if t < reach or complete:
                a[i] = round(v / MM_PER_IN, 2)
                hours.add(i)
                values += 1
            elif v:
                unresolved.setdefault(p, []).append(iso(t))
                held.add(i)
    report = {"changed": bool(values), "at": iso(now), "hours_rescaled": len(hours), "values_rescaled": values,
              "rescaled_before": iso(max([min(cut, reach) if unresolved else cut] + ([done_before] if done_before else []))),
              "unresolved": unresolved, "hours_unresolved": len(held),
              "rule": "every hour stored before the first millimetre hour is millimetres too (no answer of the service "
                      "has been seen in inches), except the hours a later reading filled from a 48 or 72-hour total "
                      "(backfilled); an hour within 50 hours of the check without that provenance is left as stored "
                      "(the larger reading) until it can be told apart"}
    rep1["third_pass"] = report
    hist["units_repair"] = rep1
    chk["repair"] = REPAIR_VERSION if not unresolved else min(chk.get("repair") or 1, REPAIR_VERSION - 1)
    return hist, report


def repair_history_units(hist: dict | None, now: datetime, known: dict | None = None) -> tuple[dict | None, dict]:
    """Readings stored before the unit check (a history without units_checked) are rescaled to inches: every hour is
    millimetres (no answer of the service has been seen in inches; review 2026-11-07, P1-1). The hours over the
    24-hour bound and the readings known to be millimetres (KNOWN_MM_AT) are recorded as the evidence. Every value
    (the hourly maxima and the earlier windows filled from the 48 and 72-hour totals alike) is divided by 25.4. A
    history the first version checked (units_checked without repair 2) gets repair_second_pass. Returns (history,
    report); the history then carries units_checked (repair 2) and units_repair (what was changed), so a second run
    changes nothing."""
    known = KNOWN_MM_AT if known is None else known
    if not hist or not hist.get("permits"):
        return hist, {"changed": False, "reason": "no history"}
    if hist.get("units_checked"):
        if (hist["units_checked"].get("repair") or 1) < REPAIR_VERSION:
            return repair_second_pass(hist, now)
        return hist, {"changed": False, "reason": f"already checked (inches from {hist['units_checked'].get('from')})",
                      "units_repair": hist.get("units_repair")}
    start = parse_t(hist.get("start"))
    if start is None:
        return hist, {"changed": False, "reason": "no start hour"}
    series = hist["permits"]
    n = max(len(a) for a in series.values())
    known_i = sorted((int((hour_floor(parse_t(t)) - start).total_seconds() // 3600), t) for t in known if parse_t(t))
    unit = "mm"
    mm_hours, kept, bound_hours, values, ranges = [], 0, [], 0, []
    max_before = max_after = None
    for i in range(n):
        col = [a[i] for a in series.values() if i < len(a) and a[i] is not None]
        if any(j == i for j, _ in known_i):
            unit = "mm"
        if not col:
            continue
        mx = max(col)
        max_before = mx if max_before is None else max(max_before, mx)
        if mx > UNIT_BOUND_IN[24]:
            unit = "mm"
            bound_hours.append(i)
        if unit != "mm":
            kept += 1
            max_after = mx if max_after is None else max(max_after, mx)
            continue
        mm_hours.append(i)
        for a in series.values():
            if i < len(a) and a[i] is not None:
                a[i] = round(a[i] / MM_PER_IN, 2)
                values += 1
        mx2 = max(a[i] for a in series.values() if i < len(a) and a[i] is not None)
        max_after = mx2 if max_after is None else max(max_after, mx2)
        if ranges and ranges[-1][1] == i - 1:
            ranges[-1][1] = i
        else:
            ranges.append([i, i])
    at = lambda i: iso(start + timedelta(hours=i))  # noqa: E731
    report = {"changed": bool(mm_hours), "at": iso(now), "hours_rescaled": len(mm_hours), "values_rescaled": values,
              "hours_kept_as_inches": kept, "ranges": [[at(a), at(b)] for a, b in ranges],
              "hours_over_bound": len(bound_hours), "first_hour_over_bound": at(bound_hours[0]) if bound_hours else None,
              "largest_before": max_before, "largest_after": max_after, "bound_in": UNIT_BOUND_IN[24],
              "evidence": {t: known[t] for _, t in known_i}, "last_unit": unit or "in",
              "rule": "every hour stored before the check is millimetres: no answer of the service has been seen in "
                      "inches (the hours over the bound and the readings known to be millimetres are the evidence)"}
    hist["units_repair"] = report
    hist["units_checked"] = {"from": iso(hour_floor(now)), "rule": UNIT_RULE, "repair": REPAIR_VERSION}
    return hist, report


def write_history(hist: dict) -> None:
    tmp = HISTORY.with_suffix(".json.tmp")          # compact: about 2,000 numbers per permittee
    tmp.write_text(json.dumps(hist, separators=(",", ":")))
    tmp.replace(HISTORY)


def permit_summary(points: dict[str, dict], outfalls: list[dict]) -> dict[str, dict]:
    """Per permittee: its points, the maxima at the latest valid time, how the wettest was read (grid
    or point) and from which product, and its forecast maximum."""
    by_permit = defaultdict(list)
    for k, p in points.items():
        for permit in p["permits"]:
            by_permit[permit].append(k)
    names, states, outs = {}, {}, defaultdict(list)
    for o in outfalls:
        names.setdefault(o["permit"], o.get("name"))
        states.setdefault(o["permit"], o.get("state"))
        outs[o["permit"]].append({"outfall": o["outfall"], "water_slug": o.get("water_slug"),
                                  "water_match": o.get("water_match"), "distance_m": o.get("distance_m"),
                                  "point": point_key(o["lat"], o["lon"]),
                                  "source": o["source"]})
    out = {}
    for permit, keys in sorted(by_permit.items()):
        readings = [(k, points[k].get("mrms") or {}) for k in keys]
        vts = [parse_t(m.get("valid_time")) for _, m in readings if m.get("valid_time")]
        vt = max(vts) if vts else None
        cur = [(k, m) for k, m in readings if vt and parse_t(m.get("valid_time")) == vt]
        row = {"name": names.get(permit), "state": states.get(permit), "points": sorted(keys),
               "outfalls": outs.get(permit, []), "valid_time": iso(vt),
               "points_reporting": len(cur), "points_total": len(keys)}
        for h in HOURS:
            vals = [(m.get(f"h{h}"), k) for k, m in cur if m.get(f"h{h}") is not None]
            row[f"h{h}"] = max(vals)[0] if vals else None
            if h == 24:
                row["h24_point"] = max(vals)[1] if vals else None
        wettest = dict(cur).get(row["h24_point"]) or {}
        row["read"] = wettest.get("read") or ("point" if wettest else None)
        if outs.get(permit) and all(x["source"] == "plant-point" for x in outs[permit]):
            row["read"] = "plant_point"     # the treatment plant's point: the outfalls' own locations are not published
        row["product"] = wettest.get("product") or (PRODUCT if wettest else None)
        q = [((points[k].get("qpf") or {}).get("in_24h"), k) for k in keys
             if (points[k].get("qpf") or {}).get("in_24h") is not None]
        row["qpf_24h_in"] = max(q)[0] if q else None
        row["qpf_point"] = max(q)[1] if q else None
        row["qpf_update_time"] = (points[row["qpf_point"]].get("qpf") or {}).get("update_time") if q else None
        out[permit] = row
    return out


# ---------------------------------------------------------------- run

def run_gauge_check(session, box, valid_time, now) -> dict:
    """gauge_check, never failing the run."""
    try:
        return gauge_check(session, box, valid_time, now)
    except Exception as e:  # noqa: BLE001
        return {"verdict": None, "text": f"skipped: {type(e).__name__}: {e}"[:300]}


def run(force: bool = False, qpf: bool = True, limit: int | None = None, now: datetime | None = None,
        point_only: bool = False, session=None) -> dict:
    now = now or datetime.now(UTC)
    prev = read_json(OUT, {}) or {}
    outfalls = cso_outfalls()
    points = group_points(outfalls)
    old_points = prev.get("points") or {}
    for k, p in points.items():                # keep the last readings until replaced
        for f in ("mrms", "qpf"):
            if (old_points.get(k) or {}).get(f):
                p[f] = old_points[k][f]
        if p.get("mrms") and not p["mrms"].get("units_read"):
            del p["mrms"]                      # read before the unit was checked (2026-11-07): reread, never kept
    prev_mrms = prev.get("mrms") or {}
    last_units = prev_mrms.get("units_last_determined")
    units: dict | None = None
    todo = [k for k, p in points.items() if needs_mrms(p.get("mrms"), now, force)]
    base = session or requests.Session()
    base.headers.update(HEADERS)
    session = CountingSession(base)
    raw, failed, problems = {}, {}, []
    grid_info: dict = {"used": False}
    read, sampled = None, 0
    hist_old, hist_repair = repair_history_units(read_json(HISTORY), now)   # once: readings before the check
    if not last_units and hist_repair.get("last_unit") == "mm":   # the repair's unit is the last one determined
        last_units = {"units_read": "mm", "basis": "history_repair", "determined_at": iso(now),
                      "evidence": {k: hist_repair.get(k) for k in ("first_hour_over_bound", "largest_before", "ranges")}}

    # the grid: every point from one export per accumulation
    if todo and not point_only:
        hours = list(GRID_HOURS)
        if backfill_needed(hist_old, {p for k in points for p in points[k]["permits"]}, now):
            hours += list(BACKFILL_HOURS)
        g, chk, errs = None, None, []
        for attempt in range(2):           # a product replaced between the query and the export: query again
            try:
                g = read_grid(session, points, hours)
                break
            except Exception as e:  # noqa: BLE001
                errs.append(f"{type(e).__name__}: {e}"[:300])
                g = None
                time.sleep(2 + 3 * attempt)
        if g is not None:
            gauge = run_gauge_check(session, g["box"], g["valid_time"], now)
            units = decide_units(g["maxima"], last_units, gauge)
            units["gauge_check"] = gauge
            g["values_as_read"] = g["values"]
            g["values"] = {k: {f: to_inches(x, units["factor"]) for f, x in v.items()} for k, v in g["values"].items()}
            try:
                chk = check_grid(session, g, points, units["factor"])
            except Exception as e:  # noqa: BLE001
                chk = {"result": f"skipped: identify failed ({type(e).__name__}: {e})"[:300]}
            if chk.get("result") == "differs":
                errs.append(f"check at {chk['point']}: grid {chk['grid_h24']} in, identify {chk['identify_h24']} in")
                g = None
        if g is not None:
            fetched_at = iso(datetime.now(UTC))
            for k, v in g["values"].items():
                if v.get("h24") is None:
                    continue
                sampled += 1
                points[k]["mrms"] = {**{f"h{h}": v.get(f"h{h}") for h in hours}, "valid_time": g["valid_time"],
                                     "fetched_at": fetched_at, "read": "grid", "product": PRODUCT,
                                     "units_read": units["units_read"]}
            problems.extend(g["problems"])
            read = "grid"
            raw = {"read": "grid", "catalog": g["catalog"], "box": g["box"], "products": g["products"],
                   "check": chk, "hours": hours, "units": units,
                   "values": {k: [v.get(f"h{h}") for h in hours] for k, v in g["values_as_read"].items()}}
            grid_info = {"used": True, "valid_time": g["valid_time"], "box": g["box"], "products": g["products"],
                         "check": {k: v for k, v in (chk or {}).items() if k != "answer"}, "errors": errs}
        else:
            grid_info = {"used": False, "errors": errs}
            units = None
            problems.append("grid read failed; per-point fallback: " + "; ".join(errs)[:400])
        todo = [k for k in todo if needs_mrms(points[k].get("mrms"), now, False)] if g is not None else todo

    # the per-point path: the fallback (or --points)
    if todo and read is None:
        cap = FALLBACK_MAX_CALLS if limit is None else min(limit, FALLBACK_MAX_CALLS)
        order = fallback_order(points, todo, cap)
        skipped = len(todo) - len(order)
        if skipped:
            problems.append(f"per-point fallback capped at {cap} calls: {skipped} point(s) keep their last reading")
        answers = {}

        def fetch(k):
            p = points[k]
            try:
                d = identify(session, p["lat"], p["lon"])
                time.sleep(MRMS_PAUSE_S)
                return k, d, None
            except Exception as e:  # noqa: BLE001
                return k, None, f"{type(e).__name__}: {e}"[:300]
        got: dict[str, dict] = {}
        with ThreadPoolExecutor(max_workers=MRMS_WORKERS) as pool:
            for k, d, err in pool.map(fetch, order):
                if err:
                    failed[k] = err
                    continue
                answers[k] = d
                m = parse_identify(d)
                m["fetched_at"] = iso(datetime.now(UTC))
                m["read"], m["product"] = "point", PRODUCT
                for pr in m.pop("problems"):
                    problems.append(f"{k}: {pr}")
                if m.get("valid_time"):
                    got[k] = m
                else:
                    failed[k] = "no valid time"
        if got:                                 # the unit from every answer of the run, then inches
            maxima = {h: max((m[f"h{h}"] for m in got.values() if m.get(f"h{h}") is not None), default=None)
                      for h in UNIT_BOUND_IN}
            try:
                box = grid_mod.grid_box([(points[k]["lat"], points[k]["lon"]) for k in got])
            except ValueError:
                box = None
            gauge = run_gauge_check(session, box, max(m["valid_time"] for m in got.values()), now) if box else None
            units = decide_units(maxima, last_units, gauge)
            units["gauge_check"] = gauge
            for k, m in got.items():
                for h in HOURS:
                    m[f"h{h}"] = to_inches(m.get(f"h{h}"), units["factor"])
                m["units_read"] = units["units_read"]
                points[k]["mrms"] = m
        if answers:
            read, sampled = "point", len(answers)
            raw = {"read": "point", "answers": answers, "grid": grid_info, "units": units}
    if raw:
        save_raw("noaa-mrms-qpe", gzip.compress(json.dumps(raw).encode()), "json.gz")

    # forecast: point -> grid cell (kept), each cell at most every QPF_CACHE_H hours
    qpf_info = {"service": f"{NWS}/gridpoints/{{wfo}}/{{x}},{{y}} quantitativePrecipitation", "window_hours": QPF_WINDOW_H,
                "fetched": 0, "cached": 0, "failed": {}, "lookups": 0, "lookups_deferred": 0, "deferred": 0}
    grids_cache = read_json(GRIDS, {}) or {}
    grid_data = prev.get("grids") or {}
    if qpf:
        for k, p in points.items():
            g = grids_cache.get(k)
            if g and (g.get("grid") or (parse_t(g.get("failed_at")) or now) > now - timedelta(hours=GRID_RETRY_H)):
                continue
            if qpf_info["lookups"] >= LOOKUP_MAX:
                qpf_info["lookups_deferred"] += 1
                continue
            try:
                d = nws_get(session, f"{NWS}/points/{p['lat']:.4f},{p['lon']:.4f}")
                pr = d.get("properties") or {}
                grids_cache[k] = {"grid": f"{pr['gridId']}/{pr['gridX']},{pr['gridY']}", "checked": iso(now)}
            except Exception as e:  # noqa: BLE001
                grids_cache[k] = {"grid": None, "failed_at": iso(now), "error": f"{type(e).__name__}: {e}"[:200]}
            qpf_info["lookups"] += 1
            time.sleep(NWS_PAUSE_S)
        write_json(GRIDS, grids_cache)
        cells = sorted({(grids_cache.get(k) or {}).get("grid") for k in points} - {None})
        oldest = datetime.min.replace(tzinfo=UTC)
        due = [c for c in cells if force or (parse_t((grid_data.get(c) or {}).get("fetched_at")) or oldest)
               <= now - timedelta(hours=QPF_CACHE_H)]
        due.sort(key=lambda c: (parse_t((grid_data.get(c) or {}).get("fetched_at")) or oldest, c))
        qpf_info["cached"] = len(cells) - len(due)
        qpf_info["deferred"] = max(0, len(due) - QPF_FETCH_MAX)
        raw_q = {}
        for cell in due[:QPF_FETCH_MAX]:
            try:
                t = trim_qpf(nws_get(session, f"{NWS}/gridpoints/{cell}"))
                raw_q[cell] = t
                grid_data[cell] = {**t, "values": window_values(t["values"], now), "fetched_at": iso(datetime.now(UTC))}
                qpf_info["fetched"] += 1
            except Exception as e:  # noqa: BLE001
                qpf_info["failed"][cell] = f"{type(e).__name__}: {e}"[:200]
            time.sleep(NWS_PAUSE_S)
        if raw_q:
            save_raw("nws-qpf", gzip.compress(json.dumps(raw_q).encode()), "json.gz")
        for k, p in points.items():
            cell = (grids_cache.get(k) or {}).get("grid")
            g = grid_data.get(cell) if cell else None
            if g:
                p["qpf"] = {"grid": cell, "update_time": g.get("update_time"), "fetched_at": g.get("fetched_at"),
                            **qpf_next(g.get("values") or [], now)}
        grid_data = {c: g for c, g in grid_data.items() if c in cells}

    fresh = [k for k, p in points.items() if not needs_mrms(p.get("mrms"), now, False)]
    vts = [parse_t((p.get("mrms") or {}).get("valid_time")) for p in points.values() if p.get("mrms")]
    valid_time = max(vts) if vts else None
    ok = bool(points) and len(fresh) >= MIN_OK_SHARE * len(points)
    error = None if ok else (f"{len(fresh)} of {len(points)} points have this hour's reading; "
                             f"{len(failed)} failed (e.g. {next(iter(failed.values()), '')})"
                             + ("; " + "; ".join(grid_info.get("errors") or [])[:300] if grid_info.get("errors") else ""))
    permits = permit_summary(points, outfalls)
    counts = session.summary()
    if units:
        units = {**units, "determined_at": iso(now), "service_states": "inches", "rule": UNIT_RULE}
    last_determined = units if units and units["basis"] in ("physical_bound", "gauge_check") else last_units
    out = {
        "source_id": SOURCE_ID, "fetched_at": now_iso(), "ok": ok, "error": error,
        "last_ok_at": now_iso() if ok else prev.get("last_ok_at"),
        "mrms": {"service": MRMS_URL, "product": "NOAA MRMS radar-only quantitative precipitation estimate, 1 km, "
                                                 "1-hour and 24-hour totals (grid); 1/3/6/12/24/48/72-hour "
                                                 "(per-point fallback); in inches, converted from millimetres when the "
                                                 "service's values are millimetres (units)",
                 "units": units or prev_mrms.get("units"), "units_last_determined": last_determined,
                 "history_units_repair": hist_repair if hist_repair.get("changed") else prev_mrms.get("history_units_repair"),
                 "credit": "NOAA National Weather Service, Multi-Radar Multi-Sensor (MRMS)",
                 "read": read, "grid": grid_info,
                 "valid_time": iso(valid_time), "points": len(points), "outfalls": len(outfalls),
                 "permits": len(permits), "states": sorted({o["state"] for o in outfalls}),
                 "fetched": sampled, "fresh": len(fresh),
                 "failed": failed, "problems": problems[:50]},
        "qpf": {**qpf_info, "credit": "NOAA National Weather Service, api.weather.gov gridpoint forecast",
                "grids": len(grid_data)},
        "requests": counts,
        "points": points, "permits": permits, "grids": grid_data,
    }
    write_json(OUT, out)
    if any(r.get("valid_time") for r in permits.values()):
        write_history(update_history(hist_old, permits, now))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--force", action="store_true", help="reread every point and grid cell now")
    ap.add_argument("--no-qpf", action="store_true", help="skip the NWS forecast")
    ap.add_argument("--limit", type=int, help="at most N per-point MRMS calls this run (the fallback)")
    ap.add_argument("--points", action="store_true", help="per-point identify calls instead of the grid")
    ap.add_argument("--repair-units", action="store_true",
                    help="only rescale the history's readings stored before the unit check (also done by any run)")
    a = ap.parse_args()
    if a.repair_units:
        hist, rep = repair_history_units(read_json(HISTORY), datetime.now(UTC))
        if rep.get("changed"):
            write_history(hist)
        print("rainfall --repair-units:", json.dumps({k: v for k, v in rep.items() if k != "evidence"}))
        return 0
    t0 = time.time()
    out = run(force=a.force, qpf=not a.no_qpf, limit=a.limit, point_only=a.points)
    m, q, r = out["mrms"], out["qpf"], out["requests"]
    wet = sorted(((rr.get("h24") or 0, p) for p, rr in out["permits"].items()), reverse=True)[:5]
    print(f"rainfall: {m['points']} points ({m['outfalls']} outfalls, {m['permits']} permittees, "
          f"{','.join(m['states'])}), read by {m['read'] or 'nothing'}, {m['fetched']} sampled, {m['fresh']} fresh, "
          f"{len(m['failed'])} failed, valid {m['valid_time']}; QPF {q['grids']} grid cells ({q['fetched']} fetched, "
          f"{q['cached']} cached, {q['deferred']} deferred, {q['lookups']} lookups, {q['lookups_deferred']} lookups "
          f"deferred, {len(q['failed'])} failed); requests {r['total']} (MRMS {r['noaa_mrms']}, NWS {r['noaa_nws']}); "
          f"ok={out['ok']} in {time.time() - t0:.0f} s")
    print("  wettest 24 h:", ", ".join(f"{p} {v:.2f} in" for v, p in wet))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
