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
product's object id, valid time, size and SHA-256, the identify check and the raw value sampled at
every point; a per-point run: every identify answer) and data/raw/nws-qpf/<stamp>.json.gz (the QPF
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

from common import BUILD_DIR, DATA_DIR, HEADERS, load_outfall_registry, now_iso, read_json, save_raw, write_json
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
# a point's source tag by registry file (rainfall.json outfalls[].source; a national file: "echo-registry")
REGISTRY_SOURCE = {"data/outfalls-ne.json": "echo", "data/outfalls-mid-atlantic.json": "echo-mid-atlantic",
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
                 ("/points/", "nws_points"), ("/gridpoints/", "nws_gridpoints"))


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
    one list the site's state pages and the export use). In New Jersey the permits on the permittees' shared site
    are left to it (cso_outfalls); its other permits are read like any other state's."""
    if live is None:
        from build import status as status_mod
        live = status_mod.states()
    return {str(s).upper() for s in live}


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
        if (o.get("outfall_kind") or "cso") != "cso" or str(o.get("outfall_status") or "").startswith("CLS"):
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
    {h1, h24, ...}}, valid_time, products, box, problems, catalog}; raises when the 24-hour grid cannot be
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
    products, problems = {}, []
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
    return {"values": values, "valid_time": vt, "products": products, "box": box, "problems": problems,
            "catalog": cat_raw}


def check_grid(session, grid: dict, points: dict[str, dict]) -> dict:
    """identify at the wettest point: the grid's value there must be identify's (same valid time)."""
    vals = grid["values"]
    k = max(sorted(vals), key=lambda x: vals[x].get("h24") if vals[x].get("h24") is not None else -1.0)
    out = {"point": k, "grid_h24": vals[k].get("h24")}
    d = identify(session, points[k]["lat"], points[k]["lon"])
    m = parse_identify(d)
    out.update(identify_h24=m["h24"], identify_valid_time=m["valid_time"], answer=d)
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
    for p, r in permits.items():
        vt = parse_t(r.get("valid_time"))
        if vt is None:
            continue
        arr = series.setdefault(p, [None] * n)

        def put(t, v, overwrite=True):
            i = int((hour_floor(t) - start).total_seconds() // 3600)
            if 0 <= i < n and v is not None and (overwrite or arr[i] is None):
                arr[i] = round(max(0.0, v), 2)
        put(vt, r.get("h24"))
        if r.get("h48") is not None and r.get("h24") is not None:
            put(vt - timedelta(hours=24), r["h48"] - r["h24"], overwrite=False)
        if r.get("h72") is not None and r.get("h48") is not None:
            put(vt - timedelta(hours=48), r["h72"] - r["h48"], overwrite=False)
    series = {p: a for p, a in series.items() if any(v is not None for v in a)}
    return {"updated_at": iso(now), "start": iso(start), "step_hours": 1, "count": n,
            "units": "inches: the largest NOAA MRMS radar-only 24-hour total over the permittee's outfall points, "
                     "for the 24 hours ending at each hour (UTC)",
            "source": MRMS_URL, "permits": series}


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
    todo = [k for k, p in points.items() if needs_mrms(p.get("mrms"), now, force)]
    base = session or requests.Session()
    base.headers.update(HEADERS)
    session = CountingSession(base)
    raw, failed, problems = {}, {}, []
    grid_info: dict = {"used": False}
    read, sampled = None, 0
    hist_old = read_json(HISTORY)

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
            try:
                chk = check_grid(session, g, points)
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
                                     "fetched_at": fetched_at, "read": "grid", "product": PRODUCT}
            problems.extend(g["problems"])
            read = "grid"
            raw = {"read": "grid", "catalog": g["catalog"], "box": g["box"], "products": g["products"],
                   "check": chk, "hours": hours,
                   "values": {k: [v.get(f"h{h}") for h in hours] for k, v in g["values"].items()}}
            grid_info = {"used": True, "valid_time": g["valid_time"], "box": g["box"], "products": g["products"],
                         "check": {k: v for k, v in (chk or {}).items() if k != "answer"}, "errors": errs}
        else:
            grid_info = {"used": False, "errors": errs}
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
                    points[k]["mrms"] = m
                else:
                    failed[k] = "no valid time"
        if answers:
            read, sampled = "point", len(answers)
            raw = {"read": "point", "answers": answers, "grid": grid_info}
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
    out = {
        "source_id": SOURCE_ID, "fetched_at": now_iso(), "ok": ok, "error": error,
        "last_ok_at": now_iso() if ok else prev.get("last_ok_at"),
        "mrms": {"service": MRMS_URL, "product": "NOAA MRMS radar-only quantitative precipitation estimate, 1 km, "
                                                 "1-hour and 24-hour totals in inches (grid); 1/3/6/12/24/48/72-hour "
                                                 "(per-point fallback)",
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
        hist = update_history(hist_old, permits, now)
        tmp = HISTORY.with_suffix(".json.tmp")          # compact: about 2,000 numbers per permittee
        tmp.write_text(json.dumps(hist, separators=(",", ":")))
        tmp.replace(HISTORY)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--force", action="store_true", help="reread every point and grid cell now")
    ap.add_argument("--no-qpf", action="store_true", help="skip the NWS forecast")
    ap.add_argument("--limit", type=int, help="at most N per-point MRMS calls this run (the fallback)")
    ap.add_argument("--points", action="store_true", help="per-point identify calls instead of the grid")
    a = ap.parse_args()
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
