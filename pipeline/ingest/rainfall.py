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
degree (about 1 km, the MRMS grid); one point serves every outfall in it. Each point belongs to its state's radar
region (mrms_grid.region_of: Alaska, Hawaii, the Caribbean for Puerto Rico and the Virgin Islands, the conus for every
other state).

Observed: NOAA MRMS radar-only QPE from the ImageServer `obs/mrms_qpe`
(https://mapservices.weather.noaa.gov/raster/rest/services/obs/mrms_qpe/ImageServer), product valid
end times "usually by 0:04 after the hour". Read as a grid (ingest/mrms_grid.py, since 2026-11-03): one
catalog `query`, then one `exportImage` each of the 1-hour and 24-hour totals per tile (since 2026-11-14: the
20-degree squares that hold points, each box shrunk to its points and under the service's size limits; at most
eight tiles for the contiguous United States, seven for the 2,384 points of 2026-11-14), sampled here at each point (and the 48 and 72-hour totals when a
permittee's history lacks the two earlier 24-hour windows they imply), then one `identify` at the wettest point
as a check: a few dozen requests an hour at most in place of one per point. A point outside the radar grid
(mrms_grid.CONUS_EXTENT: a coordinate error, such as the Ohio outfall registered at 83.99 E that stretched the one
box of before over the limit from 2026-11-08) is left out and listed (mrms.outside_grid). When a tile's 24-hour
export fails, its points, and when the grid read fails (or the check disagrees), every point, go to the per-point
path of before, the fallback: one `identify` per point (1/3/6/12/24/48/72-hour totals), three at a time, at most
FALLBACK_MAX_CALLS points (one per permittee first, wettest first). Readings are kept per clock hour
(rainfall.json; --force rereads). Negative values are no data.

Regions (since 2026-11-15, read_region): the service publishes four grids, conus_QPE_*, alaska_QPE_*, hawaii_QPE_* and
carib_QPE_* (research/mrms/regions-2026-11-15.md: each stored in Web Mercator, updated in the same hourly cycle, its
0.01 degree export equal to identify at Juneau and San Juan). Each region with points is read on its own, the same way:
one catalog query serves every region, then its own tiles (at most two for Alaska, one for Puerto Rico), its own unit,
its own check at its wettest point and its own per-point fallback (at most REGION_FALLBACK_MAX_CALLS outside the
conus), its readings citing its own product (product_name). rainfall.json mrms.regions holds each region's points,
freshness, product time, fallback, requests and (outside the conus) grid and unit; mrms.grid, mrms.units and
mrms.fallback stay the conus's. A point outside its region's grid is left out and listed (mrms.outside_grid). Where
MRMS answers no coverage (-3: no radar sees the place, as at Prudhoe Bay) at a point never read, the point is outside
radar coverage: listed (mrms.outside_coverage), never fresh, no reading to show, never a failed tile or a fallback, and
not counted for the exit code; at a point read before it is an outage, its reading missing and counted
(points[].no_coverage.read_before).

Outside a grid: Guam, American Samoa and the Northern Mariana Islands have none in the service (OUTSIDE_RADAR_GRID):
their combined sewer permits would stay covered false in out/coverage.json. Hawaii has a grid but no combined sewer
outfall (2026-11-15): nothing is read there until one is registered. Puerto Rico's are read once it is live
(radar_states follows the live states).

State and exit code: a point's reading is this hour's (fresh, is_fresh) when it was fetched in this product hour,
has a 24-hour value, and is valid no more than FRESH_LAG_H hour before this hour's product (an answer of no data, or
an old product, is not; an identify answer is dated by its 24-hour total, parse_identify). A reading of an older
product never replaces a newer one stored (the answer stays in the raw file). Each region is judged on its own:
readings_ok when at least MIN_OK_SHARE of its points (those outside radar coverage left out) have this hour's reading;
its product's own hour is recorded (mrms.regions[].product_valid_time) and one older than FRESH_LAG_H is said loudly
(stale_product, STALE on the summary line, in `error`). rainfall.json `ok` is true only when every region's readings
are and no region's per-point fallback was needed; a fallback, even one that read every point it needed, sets ok
false, names itself (and its region) in `error`, the region's fallback and the summary line (FALLBACK), and holds
last_ok_at. The exit code is non-zero only when readings are missing or stale (in some region, fewer than
MIN_OK_SHARE fresh: mrms.readings_ok). A permittee whose newest reading is older than the rain caution's stale window
(permit_summary, shown_hours) shows no reading, never an old total as this hour's. The forecast's deferrals (QPF_FETCH_MAX, LOOKUP_MAX) are by design and never fail the stage.

Unit (found 2026-11-07): the service describes its values as inches, but answers millimetres (identify at Bucklin
Point, RI, valid 2026-11-07T02:00Z: 1.6, 15.8, 26.7, 40.1, 51.3, 52.4, 52.4 for 1 to 72 hours; maxValues 118.7; the
Providence gauge 17.8 to 26.4 mm in the hour to 00:51Z), and already did on 2026-11-03 (the Calais export in
tests/fixtures: 3.8 to 7.3 where IEM's MRMS daily is 0.22 in). So every run decides the unit from the data
(decide_units, once per region, from that region's evidence and its own last determination; outside the conus its
whole-region statistics, mrms_grid.statistics, and its own gauges, REGION_GAUGES, beside its few pixels; each regional
grid answered millimetres on 2026-11-15: alaska_QPE_24H 93.3, carib_QPE_72H 292), never from the description alone:
a box maximum (the largest value in the grid blocks read, or in
the run's identify answers) over 50 for 24 hours (the US record, 49.69 in, Kauai, 2018) or 155 for 72 hours (the
world record, 154.7 in, La Reunion, 1980) is millimetres; the gauge check (gauge_check: airport gauges in the box from api.weather.gov, mm, against
identify at the wettest, at most four, where one had 2 mm or more; MRMS/gauge 0.4 to 2.5 is millimetres, the same
over 25.4 inches) decides when it has a verdict (a conflict with the bound divides nothing); else the unit last
determined (rainfall.json mrms.units_last_determined); before any, the stated inches. Millimetres are divided by
25.4 before anything uses them (one unit a run: when a failed tile's points are read by identify, the unit is decided
from the grid's values and theirs together before the identify check compares at it, mrms.units.with_fallback when
that changed it); rainfall.json mrms.units
(and each reading's units_read) records the unit, the basis and the evidence; the identify check compares in the same
unit. Point readings stored before the check are
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

Requests: rainfall.json `requests` counts this run's calls by kind (and mrms.regions[].requests each region's; outside
the conus one statistics request a region an hour, and its gauge's observations). Before the grid (2026-11-02, 319
New England points) a run made 319 identify calls and, every third hour, 196 forecast calls: about
BASELINE_REQUESTS_PER_HOUR an hour. The caps keep any run within twice that (tests/test_rain_grid.py).

History: data/build/rainfall-history.json keeps, per permittee, the hourly maximum 24-hour total
over its outfall points for the last 90 days (the rule's 48-hour tail and the map's replay need
it). The first reading also fills the two earlier 24-hour windows it implies (48 h - 24 h total
ending 24 h before, 72 h - 48 h ending 48 h before) when those hours are empty.

Raw responses: data/raw/noaa-mrms-qpe/<stamp>.json.gz (a grid run: the catalog answer, the tiles and their boxes,
each product's object id, valid time and each tile's size and SHA-256 (a rejected answer's too, with the reason), the
identify check, the unit decided and the raw value sampled at every point, as read; a per-point run, or a failed
tile's points: every identify answer; a grid read failed or discarded: what it had read, grid_rejected), data/raw/nws-gauges/observations.json
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
from common import error_text
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


def product_name(region: str = "conus") -> str:
    """The product a reading cites: its region's 24-hour item (mrms_grid.REGIONS)."""
    return PRODUCT if region == "conus" else PRODUCT.replace("conus_QPE_24H", grid_mod.item_name(24, region))

SHARED_SITE_STATES = ("NJ",)  # its permits on the permittees' shared site (ingest/nj_cso_likely.py) keep the site
# The radar product has four regional grids (mrms_grid.REGIONS: conus, alaska, hawaii, carib, each read from its own
# catalog items since 2026-11-15; Alaska, Hawaii, Puerto Rico and the Virgin Islands were not read before). Guam,
# American Samoa and the Northern Mariana Islands have no grid in the service: a live one is not read, and its combined
# sewer permits stay in out/coverage.json rain_caution_states with covered false.
OUTSIDE_RADAR_GRID = frozenset({"GU", "AS", "MP"})
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
# Each region outside the conus has its own gauge list (api.weather.gov /stations, coordinates read 2026-11-15), used
# only for that region's gauge check (its extent as the box): its airport, beside its outfalls
REGION_GAUGES = {"alaska": {"PAJN": (58.35, -134.58)},      # Juneau International Airport
                 "carib": {"TJSJ": (18.45, -66.00)},       # San Juan, Luis Munoz Marin International Airport
                 "hawaii": {"PHNL": (21.33, -157.94)}}     # Honolulu, Daniel K. Inouye International Airport
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
FALLBACK_MAX_CALLS = 350       # per-point identify calls when the grid fails (the conus)
REGION_FALLBACK_MAX_CALLS = 25 # the same in each other region (a few dozen points at most)
FRESH_LAG_H = 1                # a reading is this hour's (fresh) when fetched this hour, with a 24-hour value, valid no
                               # more than this many hours before this hour's product (one posted late); older is stale
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
                 ("/computeStatisticsHistograms", "mrms_statistics"),
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
    one list the site's state pages and the export use) with a radar grid (OUTSIDE_RADAR_GRID left out; a state goes
    to its region's grid, mrms_grid.region_of). In
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
                               "states": [], "region": grid_mod.region_of(o["state"])})
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


def gauge_check(session, box: dict, valid_time: str, now: datetime, gauges: dict | None = None) -> dict:
    """Once a run (once a region): the observations of the GAUGES (or the gauges given: a region's own list,
    REGION_GAUGES) inside the box from GAUGE_EARLY before the valid time to it (kept in
    GAUGE_CACHE per valid time, refetched when fetched less than GAUGE_SETTLE after it; one attempt each, and the
    first failure skips the stations left, so api.weather.gov being down costs one timeout), and MRMS identify at the wettest (at most GAUGE_IDENTIFY_MAX,
    kept per valid time) where a gauge had at least GAUGE_MIN_MM: {verdict, ratio, ..., pairs, fetched}."""
    vt = parse_t(valid_time)
    cache = read_json(GAUGE_CACHE, {}) or {}
    obs_c, idf_c = cache.setdefault("observations", {}), cache.setdefault("identify", {})
    gauges = GAUGES if gauges is None else gauges
    inside = [st for st, (la, lo) in sorted(gauges.items())
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
                errors[st] = f"{error_text(e)}"[:200]
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
            la, lo = gauges[p["station"]]
            try:
                m = parse_identify(identify(session, la, lo))
            except Exception as e:  # noqa: BLE001
                errors[p["station"]] = f"identify: {error_text(e)}"[:200]
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

def parse_identify(d: dict, region: str | None = None) -> dict:
    """{valid_time, h1 ... h72, problems}: Values pair with the catalog items in order; each item is
    named <region>_QPE_<NN>H. With region, only that region's items are read (where two grids overlap, as carib and
    conus south of 25 N, identify answers both). Accumulations must not shrink with the window (a check on the pairing).
    valid_time is the 24-hour total's own product time (it drives the caution, the freshness and the history; else the
    latest); an accumulation of another hour is left out, as the grid leaves it out (review 2026-11-15, P1-1).
    no_coverage: true when the 24-hour item holds MRMS's no coverage (mrms_grid.NO_COVERAGE; h24 is then None)."""
    vals = (d.get("properties") or {}).get("Values") or []
    feats = (d.get("catalogItems") or {}).get("features") or []
    out, valid, problems = {f"h{h}": None for h in HOURS}, [], []
    vt_of: dict[int, int] = {}
    if not feats and d.get("value") is not None and len(vals) <= 1:
        problems.append("no catalog items in the answer")
    nocov = False
    for i, f in enumerate(feats):
        a = f.get("attributes") or {}
        if region and not str(a.get("name") or "").startswith(f"{region}_QPE_"):
            continue
        m = re.search(r"QPE_(\d+)H", str(a.get("name") or ""))
        if not m or i >= len(vals):
            continue
        h = int(m.group(1))
        try:
            v = float(vals[i])
        except (TypeError, ValueError):
            v = None
        if v is not None and (v < 0 or v != v):
            nocov = nocov or (h == 24 and v == grid_mod.NO_COVERAGE)
            v = None                         # negative pixels are no data
        if h in HOURS:
            out[f"h{h}"] = round(v, 2) if v is not None else None
        if a.get("idp_validendtime"):
            valid.append(int(a["idp_validendtime"]))
            vt_of[h] = int(a["idp_validendtime"])
    if valid:
        ref = vt_of.get(24) or max(valid)
        out["valid_time"] = iso(datetime.fromtimestamp(ref / 1000, UTC))
        if len(set(valid)) > 1:
            off = sorted(h for h, t in vt_of.items() if t != ref and h in HOURS)
            for h in off:
                out[f"h{h}"] = None
            problems.append(f"catalog items have different valid times; the {'24-hour total' if 24 in vt_of else 'latest'}"
                            f"'s ({out['valid_time']}) is used and the {', '.join(f'{h}-hour' for h in off) or 'no'} "
                            f"total(s) of another hour left out")
    else:
        out["valid_time"] = None
        problems.append("no valid time in the answer")
    seq = [out[f"h{h}"] for h in HOURS if out[f"h{h}"] is not None]
    if any(b + 0.005 < a for a, b in zip(seq, seq[1:])):
        problems.append("accumulations shrink with the window: values and catalog items may be mispaired")
    out["problems"] = problems
    if nocov and out["h24"] is None:
        out["no_coverage"] = True
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


def is_fresh(m: dict | None, now: datetime) -> bool:
    """Whether a point's reading is this hour's: fetched in this product hour (needs_mrms), with a 24-hour value, and
    valid no more than FRESH_LAG_H hours before this hour's product. An answer of no data, or an old product, is not."""
    if not m or needs_mrms(m, now, False) or m.get("h24") is None:
        return False
    vt = parse_t(m.get("valid_time"))
    expected = hour_floor(now - timedelta(minutes=PRODUCT_READY_MIN))
    return vt is not None and vt >= expected - timedelta(hours=FRESH_LAG_H)


def fallback_order(points: dict[str, dict], todo: list[str], cap: int) -> list[str]:
    """The points the per-point fallback reads, at most cap: first one point per permittee (its wettest at
    the last reading), then the others, wettest first. Points read only for the separate sewer caution ("sso:"
    keys, build/rain_sso.py) come after every combined sewer point, and its keys never change the combined sewer
    points' order (review 2026-11-16 P1-4)."""
    def sso(p) -> bool:
        return str(p).startswith("sso:")
    if not any(sso(p) for k in todo for p in points[k]["permits"]):
        return _fallback_order(points, todo, cap)
    only = [k for k in todo if points[k]["permits"] and all(sso(p) for p in points[k]["permits"])]
    rest = [k for k in todo if k not in set(only)]
    stripped = {k: {**points[k], "permits": [p for p in points[k]["permits"] if not sso(p)]} for k in rest}
    return (_fallback_order(stripped, rest, cap) + _fallback_order(points, only, cap))[:max(0, cap)]


def _fallback_order(points: dict[str, dict], todo: list[str], cap: int) -> list[str]:
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


class GridReadError(ValueError):
    """The grid read failed as a whole; evidence keeps what was read (the catalog answer, the tiles, each export's
    size and SHA-256, accepted or rejected) for the raw file."""

    def __init__(self, msg: str, evidence: dict | None = None):
        super().__init__(msg)
        self.evidence = evidence or {}


def export_tile(session, objectid: int, box: dict, log: list | None = None) -> tuple[bytes, "grid_mod.Grid"]:
    """One tile's export, read and checked against the box asked for; one retry (a second failure raises). Each
    rejected attempt is appended to log: {attempt, bytes, sha256 (when an answer came), error}."""
    last = None
    for attempt in range(2):
        b = None
        try:
            b = grid_mod.export(session, objectid, box)
            g = grid_mod.Grid(b)
            geo = grid_mod.check_georef(g, box)
            if geo:
                raise ValueError("; ".join(geo))
            return b, g
        except Exception as e:  # noqa: BLE001
            last = e
            b = b if b is not None else getattr(e, "content", None)      # an error answer's body (ExportError)
            if log is not None:
                log.append({"attempt": attempt + 1, "bytes": len(b) if b else None,
                            "sha256": hashlib.sha256(b).hexdigest() if b else None,
                            "error": f"{error_text(e)}"[:300]})
            if attempt == 0:
                time.sleep(2)
    raise last


def read_grid(session, points: dict[str, dict], hours, region: str = "conus", cat: tuple | None = None,
              seen=None) -> dict:
    """One catalog query (or cat: (parsed, answer) of a query that asked for this region's items among others), then
    each accumulation of the region's grid exported tile by tile (mrms_grid.tiles: the 20-degree squares that hold
    points, each box shrunk to its points, every box under the service's limits) and sampled at every point of the
    tile. Returns {values: {key: {h1, h24, ...}}, maxima: {hours: the largest value read}, valid_time, products,
    tiles, tiles_failed: {tile: error}, failed_points, no_coverage (the points where MRMS answers no coverage), box
    (around the tiles read), problems, catalog, region}, the values in the service's unit as read (run() decides the
    unit and converts). A tile whose 24-hour export fails twice, is not where it was asked, or has no 24-hour value at
    any of its points is failed: its points get no grid value and are listed in failed_points (run() reads them by
    point, the fallback); a tile whose points all answer no coverage and were never read (seen: the points read before,
    read_before) is not failed: those points are outside radar coverage, which no fallback changes. Raises when the
    catalog cannot be read, every tile fails, or the tiles read have no 24-hour value at most of their points (those
    outside radar coverage left out of the count)."""
    names = [grid_mod.item_name(h, region) for h in hours]
    cat, cat_raw = grid_mod.catalog(session, names) if cat is None else cat
    n24 = grid_mod.item_name(24, region)
    if n24 not in cat:
        raise GridReadError(f"{n24} not in the catalog answer", {"catalog": cat_raw})
    vt = cat[n24]["valid_time"]
    pts = {k: (p["lat"], p["lon"]) for k, p in points.items()}
    tiles = grid_mod.tiles(pts)
    values: dict[str, dict] = {k: {} for k in points}
    products, problems, maxima = {}, [], {}
    use = [24]
    seen = set(seen or ())
    no_cov: set[str] = set()
    for h in hours:
        name = grid_mod.item_name(h, region)
        c = cat.get(name)
        if not c:
            problems.append(f"{name}: not in the catalog answer")
            continue
        if c["valid_time"] != vt:
            problems.append(f"{name} is valid to {c['valid_time']}, the 24-hour total to {vt}: not used")
            continue
        products[str(h)] = {"item": name, "objectid": c["objectid"], "valid_time": c["valid_time"], "bytes": 0,
                            "tiles": {}}
        if h != 24:
            use.append(h)
    failed: dict[str, str] = {}
    for t in tiles:
        for h in use:                    # the 24-hour total first: a tile without it is failed, its others not read
            name = grid_mod.item_name(h, region)
            log: list = []
            b = g = None
            try:
                b, g = export_tile(session, cat[name]["objectid"], t["box"], log)
                got = grid_mod.sample(g, {k: pts[k] for k in t["keys"]})
                dark = grid_mod.no_coverage(g, {k: pts[k] for k in t["keys"]}) if h == 24 else set()
                if h == 24 and all(v is None for v in got.values()) and not set(got) <= dark - seen:
                    raise ValueError(f"no 24-hour value at any of its {len(got)} point(s)")
                no_cov |= dark
            except Exception as e:  # noqa: BLE001
                if b is not None:        # an answer received and read, then rejected: its bytes and hash kept too
                    log.append({"attempt": len(log) + 1, "bytes": len(b), "sha256": hashlib.sha256(b).hexdigest(),
                                **(g.meta() if g is not None else {}), "error": f"{error_text(e)}"[:300]})
                err = f"{name}: {error_text(e)}"[:300]
                products[str(h)].setdefault("rejected", {})[t["tile"]] = log
                if h == 24:
                    failed[t["tile"]] = err
                    break
                problems.append(f"tile {t['tile']} {err}")
                continue
            for k, v in got.items():
                values[k][f"h{h}"] = v
            mx = [x for x in [g.max_read(), *got.values()] if x is not None]
            if mx:
                maxima[h] = max(mx) if maxima.get(h) is None else max(maxima[h], *mx)
            maxima.setdefault(h, None)
            pr = products[str(h)]
            pr["bytes"] += len(b)
            pr["tiles"][t["tile"]] = {"bytes": len(b), "sha256": hashlib.sha256(b).hexdigest(), **g.meta(),
                                      **({"rejected": log} if log else {})}
    tile_rows = [{"tile": t["tile"], "box": t["box"], "points": len(t["keys"]),
                  **({"error": failed[t["tile"]]} if t["tile"] in failed else {})} for t in tiles]
    evidence = {"catalog": cat_raw, "valid_time": vt, "tiles": tile_rows, "products": products}
    if len(failed) == len(tiles):
        raise GridReadError(f"every grid tile failed ({len(tiles)}): "
                            + "; ".join(f"{k}: {v}" for k, v in failed.items()), evidence)
    failed_points = sorted(k for t in tiles if t["tile"] in failed for k in t["keys"])
    read_keys = [k for t in tiles if t["tile"] not in failed for k in t["keys"]]
    counted = [k for k in read_keys if k not in no_cov - seen]            # outside radar coverage: not counted
    missing = sum(1 for k in counted if values[k].get("h24") is None)
    if missing > (1 - MIN_OK_SHARE) * len(counted):
        evidence["values"] = {k: [values[k].get(f"h{h}") for h in use] for k in read_keys}
        evidence["hours"] = use
        raise GridReadError(f"the 24-hour grid has no value at {missing} of {len(counted)} points", evidence)
    if missing:
        problems.append(f"no 24-hour value at {missing} point(s)")
    if no_cov:
        problems.append(f"no radar coverage (MRMS {grid_mod.NO_COVERAGE:g}) at {len(no_cov)} point(s), "
                        f"{len(no_cov & seen)} of them read before (an outage): "
                        + ", ".join(sorted(no_cov)[:10]))
    if failed:
        problems.append(f"{len(failed)} of {len(tiles)} grid tile(s) failed, their {len(failed_points)} point(s) read "
                        f"by point: " + "; ".join(f"{k}: {v}" for k, v in failed.items())[:400])
    shrink = [k for k, v in values.items() if None not in (v.get("h1"), v.get("h24")) and v["h1"] > v["h24"] + 0.005]
    if shrink:
        problems.append(f"1-hour total above the 24-hour total at {len(shrink)} point(s), e.g. {shrink[0]}")
    for k in failed_points:
        values.pop(k, None)
    return {"values": values, "maxima": maxima, "valid_time": vt, "products": products, "tiles": tile_rows,
            "tiles_failed": failed, "failed_points": failed_points, "no_coverage": sorted(no_cov),
            "box": grid_mod.union_box(t["box"] for t in tiles if t["tile"] not in failed),
            "problems": problems, "catalog": cat_raw, "region": region}


def check_grid(session, grid: dict, points: dict[str, dict], factor: float = 1.0, region: str | None = None) -> dict:
    """identify at the wettest point: the grid's value there must be identify's (same valid time; the region's items
    only). The grid's values are in inches (converted); identify's answer is converted with the same factor before the
    comparison (both come from the same service in the same unit)."""
    vals = grid["values"]
    k = max(sorted(vals), key=lambda x: vals[x].get("h24") if vals[x].get("h24") is not None else -1.0)
    out = {"point": k, "grid_h24": vals[k].get("h24")}
    d = identify(session, points[k]["lat"], points[k]["lon"])
    m = parse_identify(d, region)
    out.update(identify_h24=to_inches(m["h24"], factor), identify_h24_as_read=m["h24"],
               identify_valid_time=m["valid_time"], factor=factor, answer=d)
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


def shown_hours() -> float:
    """How old a permittee's newest reading may be and still be shown as its reading (permit_summary): the rain
    caution's own stale window (rules.json rain_likely.rainfall_stale_hours, build/rain_likely.py settings, and the hour
    it allows beyond it)."""
    from build.rain_likely import settings
    return float(settings(read_json(DATA_DIR / "rules.json", {}) or {})["rainfall_stale_hours"]) + 1


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


def shown_permits(permits: dict[str, dict], now: datetime) -> dict[str, dict]:
    """The permittees as rainfall.json shows them: one whose newest reading is older than shown_hours() (its region's
    product stopped, its points lost radar coverage, its reads failed) shows no reading (valid_time and the totals
    None, as a permittee never read), never an old total as if it were this hour's; that reading stays under
    last_reading, and the row keeps its product and how it was read (a caution still in its tail cites them). The
    history is built from permit_summary's rows, before this (review 2026-11-15 P1-1)."""
    shown = timedelta(hours=shown_hours())
    out = {}
    for permit, row in permits.items():
        vt = parse_t(row.get("valid_time"))
        if vt is not None and vt < now - shown:
            row = {**row, "last_reading": {"valid_time": row["valid_time"], "h24": row["h24"],
                                           "h24_point": row["h24_point"],
                                           "why": f"older than {shown.total_seconds() / 3600:g} hours: not shown as "
                                                  f"this hour's"}}
            row.update({f"h{h}": None for h in HOURS})
            row.update(valid_time=None, h24_point=None, points_reporting=0)
        out[permit] = row
    return out


# ---------------------------------------------------------------- run

def run_gauge_check(session, box, valid_time, now, gauges: dict | None = None) -> dict:
    """gauge_check, never failing the run."""
    try:
        return gauge_check(session, box, valid_time, now, gauges)
    except Exception as e:  # noqa: BLE001
        return {"verdict": None, "text": f"skipped: {error_text(e)}"[:300]}


def read_before(p: dict) -> bool:
    """Whether the radar has seen the point: a reading is stored for it, or one was when MRMS first answered no coverage
    there (no_coverage.read_before). MRMS's no coverage at such a point is an outage, its reading missing; at a point
    never read, the place is outside radar coverage (listed, never fresh, not counted for the exit code)."""
    return bool(p.get("mrms")) or bool((p.get("no_coverage") or {}).get("read_before"))


def outage_now(p: dict) -> bool:
    """Whether the radar's newest word at a point read before is no coverage: its no_coverage mark is as new as its
    stored reading or newer. The reading stays (the history and the citation keep it) but is never fresh and never
    shown as the permittee's this hour (review 2026-11-15, pass 2)."""
    nc, m = p.get("no_coverage") or {}, p.get("mrms") or {}
    a, b = parse_t(nc.get("valid_time")), parse_t(m.get("valid_time"))
    return a is not None and b is not None and a >= b


def region_statistics(session, g: dict, region: str) -> dict:
    """Unit evidence beyond the few pixels around a region's points: its 24-hour item (the one exported; g: the grid
    read, or {"products": {"24": {item, objectid, valid_time}}} from the catalog when the grid read failed) over its
    whole extent (mrms_grid.statistics, one request); never failing the run."""
    p = (g.get("products") or {}).get("24") or {}
    try:
        st = grid_mod.statistics(session, p["objectid"], grid_mod.REGIONS[region])
        return {"item": p.get("item"), "objectid": p.get("objectid"), "valid_time": p.get("valid_time"),
                "extent": grid_mod.REGIONS[region], **st}
    except Exception as e:  # noqa: BLE001
        return {"item": p.get("item"), "objectid": p.get("objectid"), "error": f"{error_text(e)}"[:300]}


def read_region(session, region: str, points: dict[str, dict], keys: list[str], todo: list[str], hours: list[int],
                now: datetime, last_units: dict | None, point_only: bool = False, cap: int = FALLBACK_MAX_CALLS,
                cat: tuple | None = None) -> dict:
    """One region's hour (mrms_grid.REGIONS): its points (keys) read from its own grid (read_grid, the first attempt on
    cat, the catalog answer the regions share), a failed tile's points (or, when its grid read fails or is discarded,
    every point to read, todo) by identify, at most cap calls, the region's items only (parse_identify); one unit for
    the region (decide_units, unchanged), from its grid's values, its fallback's answers and, outside the conus, its
    statistics (region_statistics: its own few pixels seldom tell), with its own gauges (REGION_GAUGES; the conus: the
    GAUGES in its tiles' box) and its own last determination; the check at its wettest point; and its readings stored
    in points (an older product never replaces a newer reading). Returns {g, units, check, fallback, grid_info, raw,
    answers, got, failed, dark (key: valid time where MRMS answered no coverage), valued (key: valid time, read with a 24-hour
    value), problems, sampled, read}."""
    conus = region == "conus"
    tag = "" if conus else f"{region}: "
    prod = product_name(region)
    gauges = None if conus else (REGION_GAUGES.get(region) or {})
    answers, got, failed, dark, problems = {}, {}, {}, {}, []
    raw: dict = {}
    grid_info: dict = {"used": False}
    fallback = {"used": False, "reason": None}
    g, rejected, chk, errs, units, stats = None, [], None, [], None, None
    calls, asked, left = 0, set(), set()
    seen = {k for k in keys if read_before(points[k])}

    def fetch(k):
        p = points[k]
        try:
            d = identify(session, p["lat"], p["lon"])
            time.sleep(MRMS_PAUSE_S)
            return k, d, None
        except Exception as e:  # noqa: BLE001
            return k, None, f"{error_text(e)}"[:300]

    def by_point(ks):
        """identify at the points of ks not asked yet this run (fallback_order, within what is left of cap)."""
        nonlocal calls
        ks = [k for k in ks if k not in answers and k not in failed]
        order = fallback_order(points, ks, cap - calls)
        calls += len(order)
        asked.update(ks)
        left.difference_update(order)
        left.update(set(ks) - set(order))
        with ThreadPoolExecutor(max_workers=MRMS_WORKERS) as pool:
            for k, d, err in pool.map(fetch, order):
                if err:
                    failed[k] = err
                    continue
                answers[k] = d
                m = parse_identify(d, region)
                m["fetched_at"] = iso(datetime.now(UTC))
                m["read"], m["product"] = "point", prod
                for pr in m.pop("problems"):
                    problems.append(f"{tag}{k}: {pr}")
                nocov = m.pop("no_coverage", False)
                if not m.get("valid_time"):
                    failed[k] = "no valid time"
                elif m.get("h24") is None:
                    if nocov:
                        dark[k] = m["valid_time"]
                    if not nocov or k in seen:       # no data, or a radar outage: the last reading stays, not fresh
                        failed[k] = "no 24-hour value in the answer"
                else:
                    got[k] = m

    def fb_maxima():
        return {h: max((m[f"h{h}"] for m in got.values() if m.get(f"h{h}") is not None), default=None)
                for h in UNIT_BOUND_IN}

    def with_stats(maxima):
        """The grid's maxima with the region's largest 24-hour value (statistics) beside them."""
        v = (stats or {}).get("max")
        if v is None or v < 0:
            return maxima
        return {**maxima, 24: max(x for x in (maxima.get(24), v) if x is not None)}

    if todo and not point_only:
        for attempt in range(2):           # a product replaced between the query and the export: query again
            try:
                g = read_grid(session, {k: points[k] for k in keys}, hours, region, cat if attempt == 0 else None,
                              seen)
                break
            except Exception as e:  # noqa: BLE001
                errs.append(f"{error_text(e)}"[:300])
                if getattr(e, "evidence", None):
                    rejected.append({"error": errs[-1], **e.evidence})
                g = None
                time.sleep(2 + 3 * attempt)
        if g is not None:
            gauge = run_gauge_check(session, g["box"] if conus else grid_mod.REGIONS[region], g["valid_time"], now,
                                    gauges)
            if not conus:
                stats = region_statistics(session, g, region)
            if g["tiles_failed"]:
                # a failed tile's points (as todo has them, --force included); the grid's other points are not reread
                fallback = {"used": True, "reason": f"{len(g['tiles_failed'])} of {len(g['tiles'])} grid tile(s) "
                                                    f"failed: " + "; ".join(g["tiles_failed"].values())[:300]}
                by_point([k for k in todo if k in set(g["failed_points"])])
            # one unit for the region, decided (decide_units) from every value read, the grid's and the fallback's,
            # before the check compares at it
            gm = with_stats(g["maxima"])
            grid_only = decide_units(gm, last_units, gauge)
            fm = fb_maxima() if got else {}
            both = {h: max([x for x in (gm.get(h), fm.get(h)) if x is not None], default=None)
                    for h in set(gm) | set(fm)}
            units = decide_units(both, last_units, gauge)
            units["gauge_check"] = gauge
            if stats is not None:
                units["statistics"] = stats
            if (units["units_read"], units["basis"]) != (grid_only["units_read"], grid_only["basis"]):
                units["with_fallback"] = (f"decided with the per-point fallback's answers (the grid's alone: "
                                          f"{grid_only['units_read']}, {grid_only['basis']})")
                problems.append(f"{tag}the unit decided with the per-point fallback's answers: {units['units_read']} "
                                f"({units['basis']}); the grid's alone gave {grid_only['units_read']} "
                                f"({grid_only['basis']})")
            conv = {k: {f: to_inches(x, units["factor"]) for f, x in v.items()} for k, v in g["values"].items()}
            try:
                chk = check_grid(session, {**g, "values": conv}, points, units["factor"], region)
            except Exception as e:  # noqa: BLE001
                chk = {"result": f"skipped: identify failed ({error_text(e)})"[:300]}
            if chk.get("result") == "differs":
                errs.append(f"check at {chk['point']}: grid {chk['grid_h24']} in, identify {chk['identify_h24']} in")
                rejected.append({"error": errs[-1], "check": chk, "units": units, "hours": hours,
                                 **{k: g[k] for k in ("catalog", "valid_time", "tiles", "products")},
                                 "values": {k: [v.get(f"h{h}") for h in hours] for k, v in g["values"].items()}})
                g, units = None, None
        if g is None:
            grid_info = {"used": False, "errors": errs,
                         **({"check": {k: v for k, v in chk.items() if k != "answer"}} if chk else {})}
            fallback = {"used": True, "reason": "grid read failed: " + "; ".join(errs)[:400]}
            problems.append(f"{tag}grid read failed; per-point fallback: " + "; ".join(errs)[:400])
            by_point(todo)
    elif todo:
        by_point(todo)                     # --points: the per-point path by choice, not a fallback
    if got and units is None:              # the per-point path alone: the unit from every answer of the run
        vt_got = max(m["valid_time"] for m in got.values())
        c24 = (cat or ({}, {}))[0].get(grid_mod.item_name(24, region)) if not conus else None
        if c24 and stats is None:          # a region's identify answers alone seldom tell: its statistics, from the
            stats = region_statistics(session, {"products": {"24": {"item": grid_mod.item_name(24, region), **c24}}},
                                      region)     # catalog's 24-hour item, as the grid's would have been
        if conus:
            try:
                box = grid_mod.grid_box([(points[k]["lat"], points[k]["lon"]) for k in got])
            except ValueError:
                box = None
            gauge = run_gauge_check(session, box, vt_got, now) if box else None
        else:
            gauge = run_gauge_check(session, grid_mod.REGIONS[region], vt_got, now, gauges)
        units = decide_units(with_stats(fb_maxima()), last_units, gauge)
        units["gauge_check"] = gauge
        if stats is not None:
            units["statistics"] = stats
    if left:
        problems.append(f"{tag}per-point fallback capped at {cap} calls: {len(left)} point(s) keep their last reading")
    if asked:
        fallback.update(points=len(asked), cap=cap, called=calls, read=len(got), failed=calls - len(got),
                        left=len(left))

    # storage: a reading of an older product than the one stored never replaces it (the answers stay in the raw file)
    older, valued, read, sampled = [], {}, None, 0

    def newer_stored(k, vt) -> bool:
        a, b = parse_t((points[k].get("mrms") or {}).get("valid_time")), parse_t(vt)
        return a is not None and b is not None and a > b
    if g is not None:
        fetched_at = iso(datetime.now(UTC))
        for k, v in g["values"].items():
            if v.get("h24") is None:
                continue
            sampled += 1
            valued[k] = g["valid_time"]
            if newer_stored(k, g["valid_time"]):
                older.append(k)
                continue
            points[k]["mrms"] = {**{f"h{h}": to_inches(v.get(f"h{h}"), units["factor"]) for h in hours},
                                 "valid_time": g["valid_time"], "fetched_at": fetched_at, "read": "grid",
                                 "product": prod, "units_read": units["units_read"]}
        for k in g["no_coverage"]:
            dark.setdefault(k, g["valid_time"])
        problems.extend(f"{tag}{x}" for x in g["problems"])
        read = "grid"
        raw = {"read": "grid", "catalog": g["catalog"], "box": g["box"], "tiles": g["tiles"],
               "products": g["products"], "check": chk, "hours": hours, "units": units,
               "values": {k: [v.get(f"h{h}") for h in hours] for k, v in g["values"].items()}}
        grid_info = {"used": True, "valid_time": g["valid_time"], "box": g["box"], "tiles": g["tiles"],
                     "tiles_read": len(g["tiles"]) - len(g["tiles_failed"]), "tiles_failed": g["tiles_failed"],
                     "products": g["products"], "sampled": sampled,
                     "check": {k: v for k, v in (chk or {}).items() if k != "answer"}, "errors": errs}
    for k, m in got.items():
        for h in HOURS:
            m[f"h{h}"] = to_inches(m.get(f"h{h}"), units["factor"])
        m["units_read"] = units["units_read"]
        valued[k] = m["valid_time"]
        if newer_stored(k, m["valid_time"]):
            older.append(k)
            continue
        points[k]["mrms"] = m
    if older:
        problems.append(f"{tag}{len(older)} point(s) answered with an older product than the reading stored; the "
                        f"newer kept (e.g. {older[0]})")
    if answers:
        if read is None:
            read, sampled = "point", len(answers)
            raw = {"read": "point", "answers": answers, "grid": grid_info, "units": units}
        else:                               # a failed tile's points, beside the grid's
            sampled += len(answers)
            raw["fallback"] = {"answers": answers, **{k: v for k, v in fallback.items() if k != "used"}}
    if rejected:                            # what a failed or discarded grid read had read (hashes, the check)
        raw = {"read": read, "grid": grid_info, **raw, "grid_rejected": rejected}
    return {"g": g, "units": units, "check": chk, "fallback": fallback, "grid_info": grid_info, "raw": raw,
            "answers": answers, "got": got, "failed": failed, "dark": dark, "valued": valued, "problems": problems,
            "sampled": sampled, "read": read}


def read_separate(session, points: dict[str, dict], keys: list[str], todo: list[str], hist_old: dict | None,
                  now: datetime, point_only: bool, limit: int | None, cat: tuple | None, res: dict[str, dict],
                  last_units: dict | None, prev_regions: dict) -> dict:
    """The separate sewer caution's points (keys: every permit an "sso:" key, build/rain_sso.py), read after the
    combined sewer points and apart from them, so they never change a combined sewer reading: each region's own tiles
    over these points alone (read_region), the 48 and 72-hour grids only when their own history lacks the windows,
    the unit last decided this hour for the region's combined sewer points as the last determined one, and at most
    what the combined sewer fallback left of its cap. The catalog answer is shared when it holds the items they need.
    Returns {res: {region: read_region's result, with its requests}, regions: [regions read]}."""
    out: dict[str, dict] = {}
    for r in grid_mod.REGIONS:
        ks = [k for k in keys if points[k]["region"] == r]
        if not ks:
            continue
        td = [k for k in todo if k in set(ks)]
        hrs = list(GRID_HOURS) + (list(BACKFILL_HOURS) if td and not point_only and backfill_needed(
            hist_old, {p for k in ks for p in points[k]["permits"]}, now) else [])
        names = {grid_mod.item_name(h, r) for h in hrs}
        own_cat = cat if cat is not None and names <= set(cat[0]) else None
        done = res.get(r) or {}
        last = done.get("units") or (last_units if r == "conus" else (prev_regions.get(r) or {}).get("units_last_determined"))
        cap = FALLBACK_MAX_CALLS if r == "conus" else REGION_FALLBACK_MAX_CALLS
        cap = (cap if limit is None else min(limit, cap)) - int((done.get("fallback") or {}).get("called") or 0)
        before = Counter(session.counts)
        out[r] = read_region(session, r, points, ks, td, hrs, now, last, point_only, max(0, cap), own_cat)
        out[r]["requests"] = dict(sorted((session.counts - before).items()))
    return {"res": out, "regions": list(out)}


def separate_summary(sep: dict, points: dict[str, dict], sso_only: set[str], outside: list[str], uncovered: list[str],
                     dimmed: set[str], unreadable: list[str], now: datetime) -> dict | None:
    """rainfall.json mrms.separate_sewers: the separate sewer points' own figures (read_separate), none when there
    are none."""
    from build.rain_sso import is_key
    if not sso_only:
        return None
    unc = set(uncovered)
    counted = [k for k in sso_only if not points[k].get("outside_grid") and k not in unc]
    fresh = [k for k in counted if is_fresh(points[k].get("mrms"), now) and k not in dimmed]
    regs = {}
    for r, x in sep["res"].items():
        gi = x["grid_info"] or {}
        regs[r] = {"read": x["read"], "fetched": x["sampled"], "failed": x["failed"], "fallback": x["fallback"],
                   "units": {k: v for k, v in (x["units"] or {}).items() if k in ("units_read", "basis", "factor")},
                   "tiles": [t["tile"] for t in gi.get("tiles") or []], "tiles_failed": gi.get("tiles_failed") or {},
                   "check": gi.get("check") or {}, "requests": x["requests"], "problems": x["problems"][:20]}
    return {"doc": "the points of the separate sewer operators' past rain-driven reports (build/rain_sso.py), read "
                   "after the combined sewer points in tiles of their own; none of these figures is in the ones above",
            "points": len(sso_only), "readable": len(counted) + len(uncovered), "outside_grid": outside,
            "outside_coverage": uncovered, "fresh": len(fresh), "counted": len(counted),
            "readings_ok": len(fresh) >= MIN_OK_SHARE * len(counted),
            "unreadable_permits": [p for p in unreadable if is_key(p)], "regions": regs}


def run(force: bool = False, qpf: bool = True, limit: int | None = None, now: datetime | None = None,
        point_only: bool = False, session=None) -> dict:
    now = now or datetime.now(UTC)
    prev = read_json(OUT, {}) or {}
    from build import rain_sso
    # the separate sewer operators of rules.rain_likely.separate_sewers, read at the points of their past rain-driven
    # reports under "sso:<operator>" (build/rain_sso.py); none with its switch off
    sso_points = rain_sso.live_points()
    radar = radar_states() if sso_points else set()
    outfalls = cso_outfalls() + [o for o in sso_points if o["state"] in radar]
    points = group_points(outfalls)
    old_points = prev.get("points") or {}
    for k, p in points.items():                # keep the last readings until replaced
        for f in ("mrms", "qpf", "no_coverage"):
            if (old_points.get(k) or {}).get(f):
                p[f] = old_points[k][f]
        if p.get("mrms") and not p["mrms"].get("units_read"):
            del p["mrms"]                      # read before the unit was checked (2026-11-07): reread, never kept
    # a point outside its region's radar grid (a coordinate error in a registry, such as a longitude with its sign
    # flipped) has no value there and would stretch a box for nothing: it is never read and never counted as missing
    outside = sorted(k for k, p in points.items()
                     if not grid_mod.in_extent(p["lat"], p["lon"], grid_mod.REGIONS[p["region"]]))
    for k in outside:
        points[k].pop("mrms", None)
        points[k].pop("no_coverage", None)
        points[k]["outside_grid"] = True
    readable = [k for k in points if not points[k].get("outside_grid")]
    # the separate sewer caution's points (every permit an "sso:" key, build/rain_sso.py): read in a pass of their own
    # after the combined sewer points' (read_separate below), never in the combined sewer tiles, unit, check, fallback,
    # forecast places or counts (review 2026-11-16, the switch-on pass); a point a combined sewer permittee also has is
    # a combined sewer point
    sso_only = {k for k, p in points.items() if p["permits"] and all(rain_sso.is_key(x) for x in p["permits"])}
    cso_readable = [k for k in readable if k not in sso_only]
    prev_mrms = prev.get("mrms") or {}
    prev_regions = prev_mrms.get("regions") or {}
    last_units = prev_mrms.get("units_last_determined")
    # a point whose newest answer is no coverage (outage_now) is asked again every run, not only in the next product hour
    # (its stored reading's fetch time would hold it back: review 2026-11-15, pass 3)
    todo = [k for k in readable if needs_mrms(points[k].get("mrms"), now, force) or outage_now(points[k])]
    base = session or requests.Session()
    base.headers.update(HEADERS)
    session = CountingSession(base)
    hist_old, hist_repair = repair_history_units(read_json(HISTORY), now)   # once: readings before the check
    if not last_units and hist_repair.get("last_unit") == "mm":   # the repair's unit is the last one determined
        last_units = {"units_read": "mm", "basis": "history_repair", "determined_at": iso(now),
                      "evidence": {k: hist_repair.get(k) for k in ("first_hour_over_bound", "largest_before", "ranges")}}

    # each region with points (mrms_grid.REGIONS, in its order): its grid hours (the 48 and 72-hour totals when one of
    # its permittees' history lacks the windows they imply), one catalog query for every region's items, then each
    # region read on its own (read_region): its tiles, its unit, its check, its fallback
    regions = [r for r in grid_mod.REGIONS if any(points[k]["region"] == r for k in cso_readable)]
    keys_of = {r: [k for k in cso_readable if points[k]["region"] == r] for r in regions}
    todo_of = {r: [k for k in todo if points[k]["region"] == r and k not in sso_only] for r in regions}
    hours_of = {r: list(GRID_HOURS) + (list(BACKFILL_HOURS) if todo_of[r] and not point_only and backfill_needed(
        hist_old, {p for k in keys_of[r] for p in points[k]["permits"] if not rain_sso.is_key(p)}, now) else []) for r in regions}
    cat, problems = None, []
    names = [grid_mod.item_name(h, r) for r in regions if todo_of[r] and not point_only for h in hours_of[r]]
    if names:
        try:
            cat = grid_mod.catalog(session, names)
        except Exception as e:  # noqa: BLE001
            problems.append(f"catalog query failed, each region queries its own: {error_text(e)}"[:300])
    res: dict[str, dict] = {}
    for r in regions:
        before = Counter(session.counts)
        cap = FALLBACK_MAX_CALLS if r == "conus" else REGION_FALLBACK_MAX_CALLS
        last = last_units if r == "conus" else (prev_regions.get(r) or {}).get("units_last_determined")
        res[r] = read_region(session, r, points, keys_of[r], todo_of[r], hours_of[r], now, last, point_only,
                             cap if limit is None else min(limit, cap), cat)
        res[r]["requests"] = dict(sorted((session.counts - before).items()))
    sep = read_separate(session, points, [k for k in readable if k in sso_only], todo, hist_old, now, point_only,
                        limit, cat, res, last_units, prev_regions)
    c = res.get("conus") or {}
    units, grid_info = c.get("units"), c.get("grid_info") or {"used": False}
    read = next((res[r]["read"] for r in regions if res[r]["read"]), None)
    sampled = sum(x["sampled"] for x in res.values())
    failed: dict[str, str] = {}
    for x in res.values():
        failed.update(x["failed"])
        problems.extend(x["problems"])
    raw = dict(c.get("raw") or {})
    reg_raw = {r: x["raw"] for r, x in res.items() if r != "conus" and x["raw"]}
    if reg_raw:
        raw["regions"] = reg_raw
    sep_raw = {r: x["raw"] for r, x in sep["res"].items() if x["raw"]}
    if sep_raw:
        raw["separate_sewers"] = sep_raw
    if raw:
        save_raw("noaa-mrms-qpe", gzip.compress(json.dumps(raw).encode()), "json.gz")

    # radar coverage: a point where MRMS answered no coverage this run is marked (no_coverage: since, the latest valid
    # time, and whether it had been read then, read_before), the mark kept until a value is read there. A marked point
    # never read is outside radar coverage: listed, never fresh, not counted for the exit code (it has no reading to
    # show as dry). One read before is an outage: its reading missing, counted; while the outage is the newest answer
    # there (outage_now), its stored reading stays (the history and the citation keep it) but is never fresh and never
    # shown. The mark goes only with a value at least as new as it (an older product never clears it).
    dark_now, valued = {}, {}
    for x in [*res.values(), *sep["res"].values()]:
        dark_now.update(x["dark"])
        valued.update(x["valued"])
    for k in readable:
        nc = points[k].get("no_coverage")
        if k in valued and (not nc or (parse_t(valued[k]) or now) >= (parse_t(nc.get("valid_time")) or now)):
            points[k].pop("no_coverage", None)
        elif k in dark_now:
            nc = nc or {"since": iso(now), "read_before": bool(points[k].get("mrms"))}
            newest = max((t for t in (dark_now[k], nc.get("valid_time")) if parse_t(t)), key=parse_t)
            points[k]["no_coverage"] = {**nc, "valid_time": newest, "seen_at": iso(now)}
    dimmed = {k for k in readable if outage_now(points[k])}
    uncovered = sorted(k for k in readable if points[k].get("no_coverage") and not read_before(points[k]))

    # forecast: point -> grid cell (kept), each cell at most every QPF_CACHE_H hours
    qpf_info = {"service": f"{NWS}/gridpoints/{{wfo}}/{{x}},{{y}} quantitativePrecipitation", "window_hours": QPF_WINDOW_H,
                "fetched": 0, "cached": 0, "failed": {}, "lookups": 0, "lookups_deferred": 0, "deferred": 0}
    grids_cache = read_json(GRIDS, {}) or {}
    grid_data = prev.get("grids") or {}
    if qpf:
        # a point only the separate sewer caution reads ("sso:" keys, build/rain_sso.py) comes after every combined
        # sewer point for the lookups and its cell after every combined sewer cell for the fetches: it never takes a
        # place under LOOKUP_MAX or QPF_FETCH_MAX that a combined sewer point needs, and never reorders them (the
        # cells are already deferred each hour, 2026-11-15: 366 of 1,366 due)
        for k, p in sorted(points.items(), key=lambda kp: kp[0] in sso_only):     # stable: the order otherwise kept
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
                grids_cache[k] = {"grid": None, "failed_at": iso(now), "error": f"{error_text(e)}"[:200]}
            qpf_info["lookups"] += 1
            time.sleep(NWS_PAUSE_S)
        write_json(GRIDS, grids_cache)
        cells = sorted({(grids_cache.get(k) or {}).get("grid") for k in points} - {None})
        cso_cells = {(grids_cache.get(k) or {}).get("grid") for k in points if k not in sso_only}
        oldest = datetime.min.replace(tzinfo=UTC)
        due = [c for c in cells if force or (parse_t((grid_data.get(c) or {}).get("fetched_at")) or oldest)
               <= now - timedelta(hours=QPF_CACHE_H)]
        due.sort(key=lambda c: (c not in cso_cells, parse_t((grid_data.get(c) or {}).get("fetched_at")) or oldest, c))
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
                qpf_info["failed"][cell] = f"{error_text(e)}"[:200]
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

    vts = [parse_t((p.get("mrms") or {}).get("valid_time")) for k, p in points.items()
           if p.get("mrms") and k not in sso_only]
    valid_time = max(vts) if vts else None
    # per region (freshness judged against the region's own product: is_fresh, and its catalog hour): readings_ok when
    # at least MIN_OK_SHARE of its points (those outside radar coverage left out) have this hour's reading. The run's
    # readings_ok (the exit code): every region's. ok (the source's state): that, and no region's grid needing the
    # per-point fallback; a fallback is never ok, even when it reads every point it needs. The forecast's deferrals
    # (QPF_FETCH_MAX, LOOKUP_MAX) are by design and never fail either.
    expected = hour_floor(now - timedelta(minutes=PRODUCT_READY_MIN))
    unc_set = set(uncovered)
    regions_out: dict[str, dict] = {}
    fresh: list[str] = []
    reasons: list[str] = []
    for r in regions:
        x, prv, conus = res[r], prev_regions.get(r) or {}, r == "conus"
        ks = keys_of[r]
        counted = [k for k in ks if k not in unc_set]
        fr = [k for k in counted if is_fresh(points[k].get("mrms"), now) and k not in dimmed]
        fresh += fr
        rv = [parse_t(points[k]["mrms"].get("valid_time")) for k in ks if points[k].get("mrms")]
        rvt = max((t for t in rv if t), default=None)
        pv = (x["g"] or {}).get("valid_time") if x["g"] else None
        if pv is None and (x["got"] or x["dark"]):   # no grid: the newest 24-hour product the identify answers gave
            pv = iso(max(parse_t(t) for t in [*(m["valid_time"] for m in x["got"].values()), *x["dark"].values()]))
        if pv is None and not todo_of[r]:
            pv = prv.get("product_valid_time")        # nothing to read this hour: the product read earlier this hour
        stale = parse_t(pv) is not None and parse_t(pv) < expected - timedelta(hours=FRESH_LAG_H)
        fb = x["fallback"]
        pfb = (prev_mrms.get("fallback") if conus else prv.get("fallback")) or {}
        same = (prev_mrms.get("valid_time") == iso(valid_time)) if conus else (prv.get("valid_time") == iso(rvt))
        if not todo_of[r] and pfb.get("used") and same:
            # nothing to read this hour: the readings are the earlier run's, its fallback included
            fb = {**pfb, "carried_from": prev.get("fetched_at")}
        rok = len(fr) >= MIN_OK_SHARE * len(counted)
        o = {"points": len(ks) + sum(1 for k in outside if points[k]["region"] == r and k not in sso_only),
             "readable": len(ks),
             "outside_grid": [k for k in outside if points[k]["region"] == r and k not in sso_only],
             "outside_coverage": [k for k in ks if k in unc_set], "counted": len(counted), "fresh": len(fr),
             "valid_time": iso(rvt), "product_valid_time": pv, "stale_product": stale, "readings_ok": rok,
             "read": x["read"], "fetched": x["sampled"], "failed": len(x["failed"]), "fallback": fb,
             "requests": x["requests"], "product": product_name(r)}
        if not conus:
            u = x["units"]
            if u:
                u = {**u, "determined_at": iso(now), "service_states": "inches", "rule": UNIT_RULE}
            o.update(grid=x["grid_info"], units=u or prv.get("units"),
                     units_last_determined=u if u and u["basis"] in ("physical_bound", "gauge_check")
                     else prv.get("units_last_determined"))
        regions_out[r] = o
        where = "the radar grid" if conus else f"the {r} radar grid"
        if not rok:
            reasons.append(f"{'' if conus else r + ': '}{len(fr)} of {len(counted)} points in {where} have this hour's "
                           f"reading; {len(x['failed'])} failed"
                           + (f" (e.g. {next(iter(x['failed'].values()))})" if x["failed"] else "")
                           + (f"; its product is valid to {pv}, older than this hour's by more than {FRESH_LAG_H} h"
                              if stale else ""))
        if fb["used"]:
            reasons.append(f"{'' if conus else r + ': '}per-point fallback ({fb['reason']}): {fb.get('read', 0)} of "
                           f"{fb.get('points', 0)} point(s) read by identify, {fb.get('left', 0)} left at the cap of "
                           f"{fb.get('cap', FALLBACK_MAX_CALLS if conus else REGION_FALLBACK_MAX_CALLS)}")
        elif not rok and x["grid_info"].get("errors"):
            reasons.append(f"{'' if conus else r + ': '}" + "; ".join(x["grid_info"]["errors"])[:300])
        if stale:
            problems.append(f"{'' if conus else r + ': '}the product is valid to {pv}, more than {FRESH_LAG_H} h "
                            f"before this hour's ({iso(expected)}): its readings are not this hour's")
    fallback = (regions_out.get("conus") or {}).get("fallback") or {"used": False, "reason": None}
    readings_ok = bool(cso_readable) and all(o["readings_ok"] for o in regions_out.values())
    ok = readings_ok and not any(o["fallback"]["used"] for o in regions_out.values())
    error = None if ok else "; ".join(reasons)[:600]
    # the source's own figures are the combined sewer points' (the separate sewer points' are under separate_sewers)
    sso_outside, sso_uncovered = [k for k in outside if k in sso_only], [k for k in uncovered if k in sso_only]
    outside, uncovered = [k for k in outside if k not in sso_only], [k for k in uncovered if k not in sso_only]
    if outside:
        problems.append(f"{len(outside)} point(s) outside the radar grid, not read: "
                        + ", ".join(f"{k} ({', '.join(points[k]['outfalls'][:3])})" for k in outside[:10]))
    if uncovered:
        problems.append(f"{len(uncovered)} point(s) without radar coverage (MRMS {grid_mod.NO_COVERAGE:g} where no "
                        f"reading was ever had), not read: "
                        + ", ".join(f"{k} ({', '.join(points[k]['outfalls'][:3])})" for k in uncovered[:10]))
    # a permittee with no point the radar can read (every point outside its grid or outside radar coverage) is not a
    # rain permittee: never listed as one the caution covers (review 2026-11-15 P1-3), named in mrms.unreadable_permits
    # (a permittee with one such point and others read keeps every outfall: the caution colours the waters below each)
    unreadable_pts = set(outside) | set(uncovered) | set(sso_outside) | set(sso_uncovered)
    rows = permit_summary(points, outfalls)
    unreadable = sorted(p for p, row in rows.items() if all(k in unreadable_pts for k in row["points"]))
    for p in unreadable:
        del rows[p]
    # shown: the points whose radar now answers no coverage (outage_now) left out of the totals; a permittee left with
    # none keeps its product and how it was read, and its reading under last_reading (a caution in its tail cites them)
    view = {k: ({f: v for f, v in p.items() if f != "mrms"} if k in dimmed else p) for k, p in points.items()}
    shown = permit_summary(view, outfalls)
    for p, row in shown.items():
        full = rows.get(p)
        if full and row["h24"] is None and full["h24"] is not None:
            row.update(product=full["product"], read=full["read"],
                       last_reading={"valid_time": full["valid_time"], "h24": full["h24"],
                                     "h24_point": full["h24_point"],
                                     "why": "the radar answers no coverage at its points now: not shown as this hour's"})
    permits = shown_permits({p: shown[p] for p in rows}, now)
    counts = session.summary()
    if units:
        units = {**units, "determined_at": iso(now), "service_states": "inches", "rule": UNIT_RULE}
    last_determined = units if units and units["basis"] in ("physical_bound", "gauge_check") else last_units
    cso_outfalls_read = [o for o in outfalls if not rain_sso.is_key(o["permit"])]
    sep_out = separate_summary(sep, points, sso_only, sso_outside, sso_uncovered, dimmed, unreadable, now)
    out = {
        "source_id": SOURCE_ID, "fetched_at": now_iso(), "ok": ok, "error": error,
        "last_ok_at": now_iso() if ok else prev.get("last_ok_at"),
        "mrms": {"service": MRMS_URL, "product": "NOAA MRMS radar-only quantitative precipitation estimate, 1 km, "
                                                 "1-hour and 24-hour totals (grid); 1/3/6/12/24/48/72-hour "
                                                 "(per-point fallback); in inches, converted from millimetres when the "
                                                 "service's values are millimetres (units); each point from its "
                                                 "region's grid (regions: conus, alaska, hawaii, carib)",
                 "units": units or prev_mrms.get("units"), "units_last_determined": last_determined,
                 "history_units_repair": hist_repair if hist_repair.get("changed") else prev_mrms.get("history_units_repair"),
                 "credit": "NOAA National Weather Service, Multi-Radar Multi-Sensor (MRMS)",
                 "read": read, "grid": grid_info,
                 "valid_time": iso(valid_time), "points": len(points) - len(sso_only),
                 "outfalls": len(cso_outfalls_read),
                 "permits": sum(1 for p in permits if not rain_sso.is_key(p)),
                 "states": sorted({o["state"] for o in cso_outfalls_read}),
                 "readable": len(cso_readable), "outside_grid": outside, "outside_coverage": uncovered,
                 "unreadable_permits": [p for p in unreadable if not rain_sso.is_key(p)],
                 "fetched": sampled, "fresh": len(fresh), "readings_ok": readings_ok, "fallback": fallback,
                 "failed": failed, "problems": problems[:50], "regions": regions_out,
                 **({"separate_sewers": sep_out} if sep_out else {})},
        "qpf": {**qpf_info, "credit": "NOAA National Weather Service, api.weather.gov gridpoint forecast",
                "grids": len(grid_data)},
        "requests": counts,
        "points": points, "permits": permits, "grids": grid_data,
    }
    write_json(OUT, out)
    if any(r.get("valid_time") for r in rows.values()):
        write_history(update_history(hist_old, rows, now))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--force", action="store_true", help="reread every point and grid cell now")
    ap.add_argument("--no-qpf", action="store_true", help="skip the NWS forecast")
    ap.add_argument("--limit", type=int, help="at most N per-point MRMS calls in each region this run (the fallback)")
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
    print(summary_line(out, time.time() - t0))
    wet = sorted(((rr.get("h24") or 0, p) for p, rr in out["permits"].items()), reverse=True)[:5]
    print("  wettest 24 h:", ", ".join(f"{p} {v:.2f} in" for v, p in wet))
    for line in out["mrms"]["problems"][:5]:
        print("  problem:", line[:300])
    return exit_code(out)


def summary_line(out: dict, seconds: float) -> str:
    """The run's one line: how the radar was read (the conus grid's tiles and exports, then each other region's: its
    tiles, exports, readings fresh of its points and its product's time; a fallback said loudly, FALLBACK, and a stale
    product, STALE), the readings fresh of the points in the radar grids (those outside radar coverage named), the
    forecast, and this run's requests by kind."""
    m, q, r = out["mrms"], out["qpf"], out["requests"]
    gi, fb = m.get("grid") or {}, m.get("fallback") or {}
    regs = m.get("regions") or {}
    cx = regs.get("conus") or {}
    rq = cx.get("requests") or {}
    if gi.get("used"):
        how = (f"read by grid ({gi.get('tiles_read')} of {len(gi.get('tiles') or [])} tiles, "
               f"{rq.get('mrms_export', 0) if cx else r['mrms_export']} exports), {gi.get('sampled')} sampled from "
               f"the grid")
    elif cx or not regs:
        how = f"read by {(cx.get('read') if cx else m['read']) or 'nothing'}, {cx.get('fetched', m['fetched'])} sampled"
    else:
        how = "conus: no point"
    if fb.get("used"):
        how += (f"; FALLBACK per point ({fb.get('reason')}): {fb.get('read', 0)} of {fb.get('points', 0)} read, "
                f"{fb.get('left', 0)} left at the cap of {fb.get('cap')}")[:400]
    if cx.get("stale_product"):
        how += f"; STALE product valid {cx.get('product_valid_time')}"
    for name, x in regs.items():
        if name == "conus":
            continue
        g, xr, xf = x.get("grid") or {}, x.get("requests") or {}, x.get("fallback") or {}
        part = (f"{name} by grid ({g.get('tiles_read')} of {len(g.get('tiles') or [])} tiles, "
                f"{xr.get('mrms_export', 0)} exports, {xr.get('mrms_statistics', 0)} statistics)" if g.get("used")
                else f"{name} by {x.get('read') or 'nothing'}")
        part += f", {x.get('fresh')} fresh of {x.get('counted')}"
        if x.get("outside_coverage"):
            part += f" ({len(x['outside_coverage'])} without radar coverage)"
        part += f", valid {x.get('valid_time')}"
        if x.get("stale_product"):
            part += f", STALE product valid {x.get('product_valid_time')}"
        if xf.get("used"):
            part += (f", FALLBACK per point ({xf.get('reason')}): {xf.get('read', 0)} of {xf.get('points', 0)} "
                     f"read, {xf.get('left', 0)} left at the cap of {xf.get('cap')}")[:300]
        how += "; " + part
    outside = f", {len(m['outside_grid'])} outside the radar grid" if m.get("outside_grid") else ""
    nocov = f" ({len(m['outside_coverage'])} without radar coverage)" if m.get("outside_coverage") else ""
    stats = f", {r['mrms_statistics']} statistics" if r.get("mrms_statistics") else ""
    return (f"rainfall: {m['points']} points ({m['outfalls']} outfalls, {m['permits']} permittees, "
            f"{','.join(m['states'])}{outside}), {how}, {m['fresh']} fresh of {m['readable']}{nocov}, "
            f"{len(m['failed'])} failed, valid {m['valid_time']}; QPF {q['grids']} grid cells ({q['fetched']} fetched, "
            f"{q['cached']} cached, {q['deferred']} deferred, {q['lookups']} lookups, {q['lookups_deferred']} lookups "
            f"deferred, {len(q['failed'])} failed); requests {r['total']} (MRMS {r['noaa_mrms']}: {r['mrms_query']} "
            f"query, {r['mrms_export']} export, {r['mrms_identify']} identify{stats}; NWS {r['noaa_nws']}); "
            f"ok={out['ok']} readings_ok={m['readings_ok']}"
            + (f"; separate sewer points {ss['fresh']} fresh of {ss['counted']} ("
               + ", ".join(f"{r} by {x['read'] or 'nothing'}, {x['requests'].get('mrms_export', 0)} exports"
                           + (f", FALLBACK {x['fallback'].get('read', 0)} read" if x['fallback'].get('used') else "")
                           for r, x in ss["regions"].items()) + ")" if (ss := m.get("separate_sewers")) else "")
            + f" in {seconds:.0f} s")


def exit_code(out: dict) -> int:
    """Non-zero only when readings are missing or stale: in some region, fewer than MIN_OK_SHARE of its points in the
    radar grid (those outside radar coverage left out) have this hour's reading. A fallback that read what it needed says so in ok and the summary line, not in the exit code; the
    forecast's deferrals never fail the stage."""
    return 0 if (out.get("mrms") or {}).get("readings_ok") else 1


if __name__ == "__main__":
    sys.exit(main())
