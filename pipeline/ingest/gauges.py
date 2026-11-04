"""Conditions beside the status: the nearest USGS gauge on each tracked water and its latest readings.
This module is not a feed: it writes no events file, and nothing here changes a status (docs/plan.md section 1).

    python -m ingest.gauges            # choose gauges, refresh readings older than 15 minutes, write
    python -m ingest.gauges --force    # refetch every state's readings now

Which gauge (the first rule that gives one):
  1. openboatlaunch's join, for waters that came from it: the gauges its launches on this water carry
     (../openboatlaunch/out/launch/<slug>.json `gauge`: the nearest live USGS gauge on the same-named
     river within 25 km, or a lake gauge on the lake itself within 10 km; tidal launches get none).
  2. the hydrography gauge table (data/build/gauges-by-river.json, built by build/reaches.py): a gauge
     on the river of the same name, within GAUGE_TABLE_KM.
  3. waters no launch ever placed a gauge for (data/waters-extra.json and waters with no launches):
     openboatlaunch's own rule applied to the water itself (its gauge list, the gauge's name must put it
     on this river or lake, 25 km for rivers and 10 km for lakes).
  Otherwise none. Among the candidates, the one nearest the water's wastewater outlets is chosen (else
  nearest its launches, else nearest the water's outline), and the distance says which.

Readings: the USGS Water Data OGC API latest-continuous collection, one call per state for discharge
00060, gage height 00065, water temperature 00010, specific conductance 00095 and turbidity 63680 (FNU).
The readings are kept in data/build/gauge-readings.json and a state is refetched only when its copy is
older than 15 minutes. A reading older than 12 hours is not shown.
Flood categories: NOAA National Water Prediction Service /gauges/<lid> (the lid from openboatlaunch's
gauge list or its NWPS list within 300 m; the detail must name the same USGS gauge), cached 7 days.
High flow: above the gauge's 90th percentile of daily mean discharge (USGS daily collection, statistic
00003, the last ten full years), computed once per gauge and kept a year (data/build/gauge-flow-stats.json).
Thresholds: data/rules.json yellow.conditions (cold under 15 C, turbid over 200 NTU).

Writes data/build/conditions.json:
  {"built", "thresholds", "readings": {state: {fetched_at, ok, error}}, "counts",
   "waters": {slug: {gauge_id, gauge_name, gauge_from, distance_km, distance_from, flow_cfs, stage_ft,
                     temp_c, turbidity_ntu, turbidity_unit, conductance, conductance_unit, time, times,
                     flow_p90_cfs, nwps, flags: {cold, turbid, high_flow}, source_url, fetched_at}}}
"""
from __future__ import annotations

import argparse
import math
import os
import re
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import requests

from common import BUILD_DIR, DATA_DIR, HEADERS, ROOT, now_iso, read_json, write_json

OBL_DIR = Path(os.environ.get("OBL_DIR", ROOT.parent / "openboatlaunch"))
OBL_LAUNCH_DIR = OBL_DIR / "out" / "launch"
OBL_GAUGE_STATES = ("CT", "MA", "ME", "NH", "RI", "VT", "NY")

OGC = "https://api.waterdata.usgs.gov/ogcapi/v1/collections"
LATEST = f"{OGC}/latest-continuous/items"
DAILY = f"{OGC}/daily/items"
NWPS = "https://api.water.noaa.gov/nwps/v1/gauges/"
USGS_PAGE = "https://waterdata.usgs.gov/monitoring-location/{site}/"
NWS_PAGE = "https://water.noaa.gov/gauges/{lid}"

STATE_FIPS = {"CT": "09", "MA": "25", "ME": "23", "NH": "33", "RI": "44", "VT": "50", "NY": "36"}
PARAMS = {"00060": "flow", "00065": "stage", "00010": "temp", "00095": "conductance", "63680": "turbidity"}

CONDITIONS = BUILD_DIR / "conditions.json"
READINGS = BUILD_DIR / "gauge-readings.json"
FLOW_STATS = BUILD_DIR / "gauge-flow-stats.json"
FLOOD = BUILD_DIR / "gauge-flood.json"
GAUGES_BY_RIVER = BUILD_DIR / "gauges-by-river.json"

REFRESH_MIN = 15             # a state's readings are refetched when older than this
MAX_AGE_H = 12               # a reading older than this is not shown
STATS_DAYS = 365             # the 90th percentile is recomputed after a year
STATS_RETRY_H = 24           # a failed percentile fetch is retried after a day
STATS_MIN_DAYS = 3 * 365     # fewer daily values than this: no percentile
STATS_YEARS = 10
FLOOD_DAYS = 7
GAUGE_RIVER_KM = 25.0        # openboatlaunch's limits (build/conditions.py there)
GAUGE_LAKE_KM = 10.0
GAUGE_TABLE_KM = 50.0
NWPS_M = 300
PAUSE_S = 0.3

RIVER_KINDS = {"river", "stream", "canal"}
STILL_KINDS = {"lake", "pond", "reservoir"}
STREAM_TYPES = {"ST", "ST-TS", "ST-CA", "ST-DCH"}
LEVEL_PARAMS = {"62614", "62615"}

_session: requests.Session | None = None


def session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update(HEADERS)
        if os.environ.get("usgs_api_key"):          # optional free key; raises the USGS rate limit
            _session.headers["X-Api-Key"] = os.environ["usgs_api_key"]
    return _session


def km(lon1, lat1, lon2, lat2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371.0088 * 2 * math.asin(min(1.0, math.sqrt(a)))


def parse_time(s) -> datetime | None:
    try:
        t = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return t if t.tzinfo else None


def fnum(v) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) and x > -999 else None


def thresholds(rules: dict | None = None) -> dict:
    rules = rules if rules is not None else (read_json(DATA_DIR / "rules.json") or {})
    c = ((rules.get("yellow") or {}).get("conditions")) or {}
    return {"cold_water_c": c.get("cold_water_c", 15), "turbid_ntu": c.get("turbid_ntu", 200)}


# ---------------------------------------------------------------- names (openboatlaunch's rule, ported)

STOP = {"lake", "river", "pond", "reservoir", "creek", "brook", "stream", "the", "and", "near", "fork",
        "north", "south", "east", "west", "big", "little", "upper", "lower", "branch", "bay", "harbor",
        "harbour", "cove", "middle", "main", "canal", "ditch", "run", "mill", "outlet", "inlet"}
PLACE = re.compile(r"(?i:\s(?:at|near|nr|below|blw|bl|bel|above|abv|ab|in|us|ds|@|"
                   r"(?:north|south|east|west|[nsew]|[ns][ew]|(?:north|south)(?:east|west))\s+of)\.?\s|,)")
KINDS = {"river": "river", "r": "river", "rv": "river", "riv": "river", "creek": "creek", "ck": "creek",
         "cr": "creek", "crk": "creek", "brook": "brook", "brk": "brook", "bk": "brook", "run": "run",
         "branch": "branch", "kill": "kill", "lake": "lake", "lk": "lake", "pond": "lake", "reservoir": "lake",
         "res": "lake", "canal": "canal", "ditch": "canal"}


def words(name: str | None) -> set[str]:
    s = (name or "").lower().replace("&", " and ")
    s = re.sub(r"\bst\.?\s", "saint ", s)
    s = re.sub(r"\bmt\.?\s", "mount ", s)
    return {w for w in re.findall(r"[a-z]+", s) if w not in STOP and len(w) > 2}


def kinds(name: str | None) -> set[str]:
    ws = re.findall(r"[a-z]+", (name or "").lower())
    ks = {KINDS[w] for w in ws if w in KINDS}
    return ks - {"lake"} if "outlet" in ws else ks


def on_water(water: str | None, gauge: str, lake: bool = False) -> bool:
    """Whether a gauge's name puts it on the water: the water's words among the words before the
    gauge's place ('MERRIMACK RIVER AT NASHUA, NH' is not on the Nashua River) and no other kind of
    water there (Big Elk Creek is not the Elk River). `lake`: a USGS lake site, named for the stream
    its dam holds at the place the lake may be named for."""
    ww = words(water)
    s = re.sub(r"[()]", r" \g<0> ", gauge or "")
    m = PLACE.search(s)
    part, place = (s[:m.start()], s[m.end():]) if m else (s, "")
    alias = re.search(r"\(([^()]*)\)\s*$", gauge or "")
    wk, gk = kinds(water), kinds(part)
    if ww and ww <= words(part) | words(alias and alias.group(1)):
        return (lake and ww == words(part)) or not (wk and gk and not wk & gk)
    below = m and re.match(r"(?i)\s(?:below|blw|bl|bel|ds)\b", m.group())
    return bool(lake and ww and gk and "lake" not in gk and not below and ww <= words(place))


QUALIFIERS = {"north", "south", "east", "west", "upper", "lower", "middle", "little", "big"}
SHORT_DIR = {"n": "north", "s": "south", "e": "east", "w": "west", "no": "north", "so": "south"}


def qualifiers(name: str | None) -> set[str]:
    """The words that make one river another of the same name: North Nashua is not the Nashua, the
    South Branch Park River is not the North Branch, the Little Androscoggin is not the Androscoggin.
    Only the part of a gauge's name before its place counts ('near South Paris' is a place)."""
    s = re.sub(r"[()]", r" \g<0> ", name or "")
    m = PLACE.search(s)
    ws = re.findall(r"[a-z]+", (s[:m.start()] if m else s).lower())
    out = set()
    for i, w in enumerate(ws):
        if w in QUALIFIERS:
            out.add(w)
        elif w in SHORT_DIR and (i == 0 or (i + 1 < len(ws) and ws[i + 1] in {"br", "branch", "fork", "fk"})):
            out.add(SHORT_DIR[w])
    return out


def same_river(water: str | None, gauge: str | None) -> bool:
    return qualifiers(water) == qualifiers(gauge)


ABBR = {"r": "River", "riv": "River", "nr": "near", "blw": "below", "bl": "below", "bel": "below", "ab": "above",
        "abv": "above", "br": "Branch", "bk": "Brook", "brk": "Brook", "ck": "Creek", "crk": "Creek",
        "res": "Reservoir", "trib": "Tributary", "lk": "Lake", "hwy": "Highway", "rd": "Road", "jct": "Junction"}
SMALL = {"at", "near", "below", "above", "of", "the", "and", "in", "on", "to", "from"}


def pretty_name(name: str | None) -> str:
    """USGS station names for people: 'CONNECTICUT R BELOW INDIAN STREAM NR PITTSBURG, NH' ->
    'Connecticut River below Indian Stream near Pittsburg, NH'. Mixed-case names keep their case;
    the usual abbreviations are spelled out either way."""
    s = re.sub(r"\s+", " ", (name or "").strip())
    if not s:
        return ""
    shout = s == s.upper()
    toks = s.split(" ")
    out: list[str] = []
    for i, tok in enumerate(toks):
        pre, core, post = re.match(r"^([^A-Za-z0-9]*)(.*?)([.,;:)]*)$", tok).groups()
        low = core.lower()
        if not core:
            out.append(tok)
        elif low in ABBR and (shout or core.isupper() or post.startswith(".") or low in {"nr", "blw", "abv"}):
            word = ABBR[low]
            out.append(pre + (word.capitalize() if i == 0 else word) + (post[1:] if post.startswith(".") else post))
        elif not shout:
            out.append(tok)
        elif re.fullmatch(r"[A-Z]{2}", core) and low not in SMALL and (i == len(toks) - 1 or (out and out[-1].endswith(","))):
            out.append(tok)                                   # a state code
        elif low in SMALL and i > 0:
            out.append(pre + low + post)
        else:
            out.append(pre + "-".join(x[:1].upper() + x[1:].lower() for x in core.split("-")) + post)
    return " ".join(out)


# ---------------------------------------------------------------- inputs

def load_waters() -> dict[str, dict]:
    from build import status as status_mod
    return status_mod.load_waters()


def outfall_points() -> dict[str, list[tuple[float, float]]]:
    """Wastewater outlets per water slug (the registry the water pages list)."""
    d = read_json(DATA_DIR / "outfalls-ne.json", {}) or {}
    out: dict[str, list[tuple[float, float]]] = {}
    for o in d.get("outfalls", []):
        lon, lat = fnum(o.get("lon")), fnum(o.get("lat"))
        if o.get("water_slug") and lon is not None and lat is not None:
            out.setdefault(o["water_slug"], []).append((lon, lat))
    return out


def obl_gauges() -> dict[str, dict]:
    """openboatlaunch's live-gauge lists (data/build/<ST>/gauges.json there): id -> row."""
    out = {}
    for st in OBL_GAUGE_STATES:
        for g in read_json(OBL_DIR / "data" / "build" / st / "gauges.json", []) or []:
            if g.get("id") and g.get("lat") is not None and g.get("lon") is not None:
                out.setdefault(str(g["id"]), {**g, "state": st})
    return out


def obl_launch(slug: str) -> dict | None:
    try:
        return read_json(OBL_LAUNCH_DIR / f"{slug}.json")
    except Exception:
        return None


def table_gauges() -> dict[str, list[dict]]:
    return ((read_json(GAUGES_BY_RIVER, {}) or {}).get("rivers")) or {}


def norm_river(s: str | None) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z ]", " ", (s or "").lower())).strip()


def nwps_list() -> list[dict]:
    return read_json(OBL_DIR / "data" / "build" / "nwps_gauges.json", []) or []


# ---------------------------------------------------------------- choosing the gauge

def reference_points(w: dict, outfalls: list, launches: list):
    """What the distance is measured from: the water's outlets, else its launches, else its outline."""
    if outfalls:
        return "outfall", outfalls
    if launches:
        return "launch", launches
    return "water", None


def distance_to(g: dict, frm: str, pts, geom) -> float | None:
    if g.get("lat") is None or g.get("lon") is None:
        return None
    if pts:
        return min(km(g["lon"], g["lat"], x, y) for x, y in pts)
    if geom is not None:
        from shapely.geometry import Point
        from shapely.ops import nearest_points
        try:
            q = nearest_points(geom, Point(g["lon"], g["lat"]))[0]
        except Exception:
            return None
        return km(g["lon"], g["lat"], q.x, q.y)
    return None


def candidates_from_launches(w: dict, gauges: dict) -> tuple[list[dict], list[tuple[float, float]], bool]:
    """openboatlaunch's join: the gauges its launches on this water carry, and the launch positions.
    The third value says whether any launch file was read (the join ran for this water)."""
    cands, pts, seen, ran = [], [], set(), False
    for s in w.get("launches") or []:
        d = obl_launch(s)
        if not d:
            continue
        ran = True
        if fnum(d.get("lon")) is not None and fnum(d.get("lat")) is not None:
            pts.append((float(d["lon"]), float(d["lat"])))
        g = d.get("gauge")
        if not isinstance(g, dict) or not g.get("id") or str(g["id"]) in seen:
            continue
        seen.add(str(g["id"]))
        row = gauges.get(str(g["id"])) or {}
        cands.append({"site": str(g["id"]), "name": row.get("name") or g.get("name"), "lat": row.get("lat"),
                      "lon": row.get("lon"), "params": sorted(set(g.get("params") or row.get("params") or [])),
                      "nwps": g.get("nwps") or row.get("nwps"), "type": row.get("type"), "state": row.get("state"),
                      "from": "openboatlaunch"})
    return cands, pts, ran


def candidates_from_table(w: dict, table: dict) -> list[dict]:
    if w.get("kind") not in RIVER_KINDS:
        return []
    name = norm_river(w.get("name"))
    for river, rows in table.items():
        if norm_river(river) == name:
            return [{"site": r["site"], "name": r.get("name"), "lat": r.get("lat"), "lon": r.get("lon"), "params": [],
                     "nwps": None, "type": "ST", "from": "hydrography"} for r in rows if r.get("site")]
    return []


def candidates_by_name(w: dict, gauges: dict) -> list[dict]:
    kind = w.get("kind")
    if kind in RIVER_KINDS:
        rows = [g for g in gauges.values() if g.get("type") in STREAM_TYPES and on_water(w.get("name"), g["name"])]
    elif kind in STILL_KINDS:
        rows = [g for g in gauges.values() if (g.get("type") == "LK" or set(g.get("params") or []) & LEVEL_PARAMS)
                and on_water(w.get("name"), g["name"], g.get("type") == "LK")]
    else:
        return []
    return [{"site": str(g["id"]), "name": g["name"], "lat": g["lat"], "lon": g["lon"], "params": g.get("params") or [],
             "nwps": g.get("nwps"), "type": g.get("type"), "state": g.get("state"), "from": "name"} for g in rows]


def pick(cands: list[dict], pts, geom, limit: float) -> tuple[float, dict] | None:
    """The candidate nearest most of the reference points (ties: the nearer one), within limit km of
    the nearest point; with the outline as reference, simply the nearest."""
    scored = []
    for c in cands:
        if c.get("lat") is None or c.get("lon") is None:
            continue
        if pts:
            ds = [km(c["lon"], c["lat"], x, y) for x, y in pts]
            d = min(ds)
        else:
            d, ds = distance_to(c, "water", None, geom), []
        if d is not None and d <= limit:
            scored.append((d, ds, c))
    if not scored:
        return None
    votes = [0] * len(scored)
    for j in range(len(pts or [])):
        votes[min(range(len(scored)), key=lambda i: scored[i][1][j])] += 1
    i = min(range(len(scored)), key=lambda i: (-votes[i], scored[i][0]))
    return scored[i][0], scored[i][2]


def choose(w: dict, outfalls: list, gauges: dict, table: dict, geom=None, live: set | None = None) -> dict | None:
    """The gauge for one water (module docstring), with its distance and what it is measured from.
    `live`: gauges reporting flow, temperature or turbidity now; they come before gauges that report
    only a water level (a tidal stage gauge says little about the plume)."""
    obl_cands, launch_pts, ran = ([], [], False) if w.get("extra") else candidates_from_launches(w, gauges)
    frm, pts = reference_points(w, outfalls, launch_pts)
    seen = {c["site"] for c in obl_cands}
    river = obl_cands + [c for c in candidates_from_table(w, table) if c["site"] not in seen]
    tiers = [(river, GAUGE_TABLE_KM)]
    if not ran:
        tiers.append((candidates_by_name(w, gauges), GAUGE_RIVER_KM if w.get("kind") in RIVER_KINDS else GAUGE_LAKE_KM))
    for cands, limit in tiers:
        cands = [c for c in cands if same_river(w.get("name"), c.get("name"))]
        live_c = [c for c in cands if live is None or c["site"] in live]
        best = pick(live_c, pts, geom, limit) or pick(cands, pts, geom, limit)
        if best:
            d, c = best
            return {**c, "distance_km": round(d, 1), "distance_from": frm}
    return None


# ---------------------------------------------------------------- readings (one call per state)

def parse_latest(features: list) -> dict[str, dict]:
    """latest-continuous features -> {monitoring_location_id: {param: {value, unit, time}}}, newest per param."""
    sites: dict[str, dict] = {}
    for f in features or []:
        p = (f or {}).get("properties") or {}
        code, sid = p.get("parameter_code"), p.get("monitoring_location_id")
        v, t = fnum(p.get("value")), parse_time(p.get("time"))
        if code not in PARAMS or not sid or v is None or t is None:
            continue
        cur = sites.setdefault(sid, {}).get(code)
        if cur is None or parse_time(cur["time"]) < t:
            sites[sid][code] = {"value": v, "unit": str(p.get("unit_of_measure") or "").lstrip("_"), "time": p.get("time")}
    return sites


def fetch_state(st: str) -> dict[str, dict]:
    feats, offset = [], 0
    while True:
        r = session().get(LATEST, params={
            "f": "json", "state_code": STATE_FIPS[st], "parameter_code": ",".join(PARAMS), "limit": 10000,
            "offset": offset, "skipGeometry": "true",
            "properties": "monitoring_location_id,parameter_code,time,value,unit_of_measure"}, timeout=120)
        r.raise_for_status()
        page = r.json().get("features", [])
        feats += page
        if len(page) < 10000:
            return parse_latest(feats)
        offset += 10000


def refresh_readings(states, force: bool = False, now: datetime | None = None, fetch=fetch_state) -> dict:
    """Refetch each state whose copy is older than REFRESH_MIN; keep the last good values on failure."""
    now = now or datetime.now(UTC)
    cur = read_json(READINGS, {}) or {}
    by_state, sites = dict(cur.get("states") or {}), dict(cur.get("sites") or {})
    fetched = []
    for st in states:
        info = by_state.get(st) or {}
        last = parse_time(info.get("fetched_at"))
        if not force and info.get("ok") and last and now - last < timedelta(minutes=REFRESH_MIN):
            continue
        try:
            got = fetch(st)
            for sid, params in got.items():
                sites[sid] = {**params, "_state": st}
            by_state[st] = {"fetched_at": now.isoformat(timespec="seconds"), "ok": True, "error": None,
                            "sites": len(got)}
            fetched.append(st)
        except Exception as e:
            by_state[st] = {**info, "ok": False, "error": f"{type(e).__name__}: {e}"[:200],
                            "failed_at": now.isoformat(timespec="seconds")}
        time.sleep(PAUSE_S if fetch is fetch_state else 0)
    out = {"source": LATEST, "params": list(PARAMS), "states": by_state, "sites": sites, "refetched": fetched}
    write_json(READINGS, out)
    return out


# ---------------------------------------------------------------- daily 90th percentile

def percentile(vals: list[float], q: float) -> float | None:
    v = sorted(vals)
    if not v:
        return None
    h = (len(v) - 1) * q
    lo = math.floor(h)
    return v[lo] + (v[min(lo + 1, len(v) - 1)] - v[lo]) * (h - lo)


def fetch_daily(site: str, y0: int, y1: int) -> list[float]:
    r = session().get(DAILY, params={
        "f": "json", "monitoring_location_id": f"USGS-{site}", "parameter_code": "00060", "statistic_id": "00003",
        "time": f"{y0}-01-01/{y1}-12-31", "limit": 10000, "skipGeometry": "true", "properties": "time,value"},
        timeout=120)
    r.raise_for_status()
    return [x for x in (fnum((f.get("properties") or {}).get("value")) for f in r.json().get("features", []))
            if x is not None]


def flow_stats(sites, now: datetime | None = None, fetch=fetch_daily) -> dict:
    """The 90th percentile of daily mean discharge per gauge, computed once and kept STATS_DAYS."""
    now = now or datetime.now(UTC)
    cur = read_json(FLOW_STATS, {}) or {}
    stats = dict(cur.get("sites") or {})
    y1 = now.year - 1
    y0 = y1 - STATS_YEARS + 1
    changed = False
    for site in sorted(set(sites)):
        s = stats.get(site) or {}
        t = parse_time(s.get("computed_at") or s.get("failed_at"))
        keep = timedelta(days=STATS_DAYS) if s.get("computed_at") else timedelta(hours=STATS_RETRY_H)
        if t and now - t < keep:
            continue
        try:
            vals = fetch(site, y0, y1)
            p90 = percentile(vals, 0.9) if len(vals) >= STATS_MIN_DAYS else None
            stats[site] = {"p90_cfs": round(p90, 1) if p90 is not None else None, "days": len(vals),
                           "years": f"{y0}-{y1}", "computed_at": now.isoformat(timespec="seconds"),
                           "note": None if p90 is not None else f"only {len(vals)} daily values"}
        except Exception as e:
            limited = isinstance(e, requests.HTTPError) and e.response is not None and e.response.status_code == 429
            stats[site] = {**{k: v for k, v in s.items() if k not in ("failed_at", "error")},
                           "error": f"{type(e).__name__}: {e}"[:200],
                           # over the rate limit: this one and the rest are tried again on the next run
                           **({} if limited else {"failed_at": now.isoformat(timespec="seconds")})}
            if limited:
                changed = True
                break
        changed = True
        if fetch is fetch_daily:
            time.sleep(PAUSE_S)
    out = {"source": DAILY + " (00060, statistic 00003)", "sites": stats}
    if changed or not FLOW_STATS.exists():
        write_json(FLOW_STATS, out)
    return out


# ---------------------------------------------------------------- NWS flood categories

def match_nwps(lat, lon, nwps: list[dict], max_m: float = NWPS_M) -> str | None:
    best = None
    for g in nwps:
        la, lo = g.get("latitude"), g.get("longitude")
        if la is None or lo is None or abs(la - lat) > 0.01 or abs(lo - lon) > 0.015:
            continue
        d = km(lon, lat, lo, la) * 1000
        if d <= max_m and (best is None or d < best[0]):
            best = (d, g["lid"])
    return best[1] if best else None


def parse_flood(body: dict, site: str) -> dict | None:
    """NWPS gauge detail -> flood stages (feet), only when the detail names this USGS gauge."""
    if not isinstance(body, dict) or str(body.get("usgsId") or "") != site:
        return None
    cats = ((body.get("flood") or {}).get("categories")) or {}
    stages = {}
    for k in ("action", "minor", "moderate", "major"):
        s = fnum((cats.get(k) or {}).get("stage"))
        if s is not None and s > 0:
            stages[k] = s
    return stages


def fetch_nwps(lid: str) -> dict:
    r = session().get(NWPS + lid, timeout=60)
    r.raise_for_status()
    return r.json()


def flood_stages(pairs: dict[str, str], now: datetime | None = None, fetch=fetch_nwps) -> dict:
    """{lid: {site, stages, fetched_at}} for the chosen gauges with an NWPS lid, kept FLOOD_DAYS."""
    now = now or datetime.now(UTC)
    cur = read_json(FLOOD, {}) or {}
    rows = dict(cur.get("gauges") or {})
    for lid, site in sorted(pairs.items()):
        r = rows.get(lid) or {}
        t = parse_time(r.get("fetched_at") or r.get("failed_at"))
        keep = timedelta(days=FLOOD_DAYS) if r.get("fetched_at") else timedelta(hours=STATS_RETRY_H)
        if t and now - t < keep and r.get("site") == site:
            continue
        try:
            stages = parse_flood(fetch(lid), site)
            rows[lid] = {"site": site, "stages": stages, "match": stages is not None,
                         "fetched_at": now.isoformat(timespec="seconds")}
        except Exception as e:
            rows[lid] = {**{k: v for k, v in r.items() if k != "failed_at"}, "site": site,
                         "failed_at": now.isoformat(timespec="seconds"), "error": f"{type(e).__name__}: {e}"[:200]}
        if fetch is fetch_nwps:
            time.sleep(PAUSE_S)
    out = {"source": NWPS + "<lid>", "gauges": rows}
    write_json(FLOOD, out)
    return out


# ---------------------------------------------------------------- the record

def reading(params: dict, code: str, now: datetime) -> dict | None:
    r = (params or {}).get(code)
    t = parse_time((r or {}).get("time"))
    if not r or t is None or t > now + timedelta(hours=1) or now - t > timedelta(hours=MAX_AGE_H):
        return None
    return r


def record(c: dict, readings: dict, stats: dict, flood: dict, th: dict, now: datetime) -> dict:
    site = c["site"]
    params = (readings.get("sites") or {}).get(f"USGS-{site}") or {}
    got = {name: reading(params, code, now) for code, name in PARAMS.items()}
    val = lambda k: got[k]["value"] if got[k] else None   # noqa: E731
    flow, temp, turb = val("flow"), val("temp"), val("turbidity")
    flow_ok = got["flow"] and str(got["flow"]["unit"]).lower().replace(" ", "") in ("ft^3/s", "ft3/s", "cfs")
    if not flow_ok:
        flow = None
    p90 = ((stats.get("sites") or {}).get(site) or {}).get("p90_cfs")
    times = {k: (v or {}).get("time") for k, v in got.items() if v}
    newest = max(times.values(), key=lambda s: parse_time(s), default=None)
    st_info = ((readings.get("states") or {}).get(params.get("_state")) or {}) if params else {}
    lid = c.get("nwps")
    fl = (flood.get("gauges") or {}).get(lid) if lid else None
    nwps = None
    if fl and fl.get("match") and fl.get("site") == site:
        nwps = {"lid": lid, **(fl.get("stages") or {}), "url": NWS_PAGE.format(lid=lid)}
    reported = sorted({PARAMS_LABEL[k] for k in times})
    return {
        "gauge_id": site, "gauge_name": pretty_name(c.get("name")) or f"USGS {site}", "gauge_name_usgs": c.get("name"),
        "gauge_from": c["from"], "gauge_lat": c.get("lat"), "gauge_lon": c.get("lon"),
        "distance_km": c["distance_km"], "distance_from": c["distance_from"],
        "flow_cfs": flow, "stage_ft": val("stage") if got["stage"] and got["stage"]["unit"] == "ft" else None,
        "temp_c": temp if got["temp"] and str(got["temp"]["unit"]).lower().startswith("deg") else None,
        "turbidity_ntu": turb, "turbidity_unit": got["turbidity"]["unit"] if got["turbidity"] else None,
        "conductance": val("conductance"), "conductance_unit": got["conductance"]["unit"] if got["conductance"] else None,
        "time": times.get("flow") or newest, "times": times, "reported": reported,
        "flow_p90_cfs": p90, "flow_p90_years": ((stats.get("sites") or {}).get(site) or {}).get("years") if p90 else None,
        "nwps": nwps,
        "flags": {"cold": temp is not None and temp < th["cold_water_c"],
                  "turbid": turb is not None and turb > th["turbid_ntu"],
                  "high_flow": bool(flow is not None and p90 and flow > p90)},
        "source_url": USGS_PAGE.format(site=site), "fetched_at": st_info.get("fetched_at"),
    }


PARAMS_LABEL = {"flow": "flow", "stage": "water level", "temp": "water temperature", "conductance": "specific conductance",
                "turbidity": "turbidity"}


def build(force: bool = False, now: datetime | None = None, fetch_latest=fetch_state, fetch_days=fetch_daily,
          fetch_flood=fetch_nwps) -> dict:
    now = now or datetime.now(UTC)
    waters = load_waters()
    outfalls = outfall_points()
    gauges = obl_gauges()
    table = table_gauges()
    prev = (read_json(CONDITIONS, {}) or {}).get("waters") or {}
    obl_ok = OBL_LAUNCH_DIR.exists() and bool(gauges)
    states = sorted({w.get("state") for w in waters.values() if w.get("state") in STATE_FIPS})
    readings = refresh_readings(states, force=force, now=now, fetch=fetch_latest)
    live = {sid.removeprefix("USGS-") for sid, params in (readings.get("sites") or {}).items()
            if any(reading(params, code, now) for code in ("00060", "00010", "63680"))}
    from build import status as status_mod
    chosen: dict[str, dict] = {}
    for slug, w in waters.items():
        if obl_ok:
            geom = None
            if not outfalls.get(slug) and (w.get("extra") or not w.get("launches")):
                geom = status_mod.water_geometry(slug, waters)
            c = choose(w, outfalls.get(slug, []), gauges, table, geom, live)
        else:
            # openboatlaunch's files are not on this machine: keep the gauges chosen last time
            p = prev.get(slug)
            c = ({"site": p["gauge_id"], "name": p.get("gauge_name_usgs") or p.get("gauge_name"), "lat": p.get("gauge_lat"),
                  "lon": p.get("gauge_lon"), "nwps": p.get("nwps_lid"), "from": p.get("gauge_from"),
                  "distance_km": p.get("distance_km"), "distance_from": p.get("distance_from")}
                 if p and p.get("gauge_id") else None)
        if c:
            chosen[slug] = c
    extra = sorted({c["state"] for c in chosen.values() if c.get("state") in STATE_FIPS and c["state"] not in states})
    if extra:                       # a gauge across a state line (openboatlaunch's lists include New York)
        readings = refresh_readings(extra, force=force, now=now, fetch=fetch_latest)
        states += extra
    nwps = nwps_list()
    for c in chosen.values():
        if not c.get("nwps") and c.get("lat") is not None and nwps:
            c["nwps"] = match_nwps(c["lat"], c["lon"], nwps)
    flowing = {c["site"] for c in chosen.values()
               if "00060" in ((readings.get("sites") or {}).get(f"USGS-{c['site']}") or {})}
    stats = flow_stats(flowing, now=now, fetch=fetch_days)
    flood = flood_stages({c["nwps"]: c["site"] for c in chosen.values() if c.get("nwps")}, now=now, fetch=fetch_flood)
    th = thresholds()
    recs = {slug: record(c, readings, stats, flood, th, now) for slug, c in sorted(chosen.items())}
    for slug, r in recs.items():
        r["nwps_lid"] = chosen[slug].get("nwps")
    counts = {
        "waters": len(waters), "with_gauge": len(recs),
        "by_rule": {k: sum(1 for r in recs.values() if r["gauge_from"] == k) for k in ("openboatlaunch", "hydrography", "name")},
        "with_reading": sum(1 for r in recs.values() if r["times"]),
        "with_flow": sum(1 for r in recs.values() if r["flow_cfs"] is not None),
        "with_temperature": sum(1 for r in recs.values() if r["temp_c"] is not None),
        "with_turbidity": sum(1 for r in recs.values() if r["turbidity_ntu"] is not None),
        "with_flood_stages": sum(1 for r in recs.values() if r["nwps"]),
        "with_p90": sum(1 for r in recs.values() if r["flow_p90_cfs"]),
        "flags": {k: sum(1 for r in recs.values() if r["flags"][k]) for k in ("cold", "turbid", "high_flow")},
        "gauges": len({r["gauge_id"] for r in recs.values()}),
    }
    out = {"built": now.isoformat(timespec="seconds"), "thresholds": th,
           "doc": "Conditions at the nearest USGS gauge, shown beside the status; they never change it.",
           "readings": {st: {k: v for k, v in (readings.get("states") or {}).get(st, {}).items() if k != "sites"}
                        for st in states},
           "counts": counts, "waters": recs}
    write_json(CONDITIONS, out)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--force", action="store_true", help="refetch every state's readings now")
    a = ap.parse_args()
    out = build(force=a.force)
    c = out["counts"]
    errs = {st: r.get("error") for st, r in out["readings"].items() if r.get("error")}
    print(f"conditions: {c['with_gauge']} of {c['waters']} waters have a gauge ({c['by_rule']}); readings now: "
          f"flow {c['with_flow']}, temperature {c['with_temperature']}, turbidity {c['with_turbidity']}; "
          f"flood stages {c['with_flood_stages']}; 90th percentile {c['with_p90']}; flags {c['flags']}; "
          f"errors {errs or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
