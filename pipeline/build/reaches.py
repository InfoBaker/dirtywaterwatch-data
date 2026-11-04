"""Modeled downstream reaches below river outfalls (research/hydrography/downstream-approach.md).

    python -m build.reaches                 # trace within the default budget, then refresh flows
    python -m build.reaches --flows         # only refresh the gauge readings
    python -m build.reaches --limit 50      # at most 50 traces this run
    python -m build.reaches --requests 0 --seconds 0 --no-flows   # by hand: trace until done or
                                            # NLDI's hourly allowance runs low
    python -m build.reaches --outfall MA0101613:013

Outfalls: every registry outfall (common.load_outfall_registry when it exists, else
status.load_registry_outfalls: data/outfalls-ne.json, data/outfalls-mid-atlantic.json, ...) in a live
state (the covered states the export and the state pages use: status.states()), open (outfall_status
without CLS), CSO outfalls first and treatment-plant outfalls (outfall_kind "plant") after them; plus
data/build/ma-cso-outfalls.json (MassDEP layer; water from the registry row of the same permit +
outfall, else the nearest water within 400 m) and data/build/me-cso-outfalls.json (Maine DEP layer,
closed outfalls left out). An outfall whose water record is a river, stream or canal, or which has no
water record yet, is traced; one matched to a bay, sound, lake or pond is not (not_river), nor one
whose coordinates the registry flags (coords_problem). NBC pins are covered by the ECHO rows of
RI0100315 / RI0100072. A cached trace of an outfall the registry now lists as closed (and no state
layer lists as open) is moved to data/build/reaches/retired/, so the rain caution never uses it.

Trace: NLDI downstream-main from the EPA reach-indexed NPDES point
  https://api.water.usgs.gov/nldi/linked-data/npdes/<permit><outfall>/navigation/DM/flowlines?distance=D&trimStart=true
(asked only when the registry row has an EPA reach id, or does not say, or an earlier trace found it
there: rows ECHO did not reach-index are almost never in NLDI's npdes source), falling back to NLDI
comid/position (or hydrolocation) from the outfall's coordinates, then
comid/<comid>/navigation/DM/flowlines with the first flowline trimmed at the snapped point here.
When NLDI's navigation allowance is spent (a 429, or under 100 left) the run walks the same NHDPlus V2.1
network on EPA's MapServer instead (nhdplus_walk: one layer 2 query per level path, the start from NLDI's
npdes feature or comid/position, or EPA's catchment layer 6 when NLDI's whole allowance is low; each
record says which: navigation "nldi" or "nhdplus_walk"; 25 cached NLDI traces matched comid for comid).
NHDPlus V2.1 attributes come from one EPA MapServer layer 2 query per trace. Flowlines are
ordered by hydroseq (upstream first) and cut at the first tidal flowline, the first flowline in a
lake/pond or reservoir (wbarea_ftype 390/436), estuary (493) or on the coastline (fcode 56600), or at
rules.json reach.cap_km
(40 km), whichever comes first. Cache: data/build/reaches/<permit>-<outfall>.json for 30 days; a
failed trace is retried after 1, 2, 4 ... days (at most 30); a cached trace whose outfall moved is
traced again first; one whose water or name changed is updated without a request.

Budget (the hourly refresh runs this with no arguments): NLDI answers 3600 requests an hour and,
within them, 1000 navigation requests an hour (X-RateLimit headers, 2026-11-03), one request a
second here. A run traces in this order: recent discharges with a point but no reach, outfalls never
traced (CSO, then plant), failed traces due again, outfalls traced more than 30 days ago (oldest
first); it stops at --requests NLDI navigation requests (default 100), --seconds (default 150), or
after 8 traces in a row fail on a service error, and leaves the rest for the next run; when NLDI's
allowance left this hour (shared with anything else on this machine) falls under 100 it goes on with
the NHDPlus walk. A rate-limited request is never cached as a failure. Only one run traces at a time
(data/build/reaches.lock); another run refreshes flows only.
Per outfall state and the last runs' request counts: data/build/reach-outfalls.json.

Flows: gauges per river (data/build/gauges-by-river.json, from the gauge table in
research/hydrography/report.md 2.7, with each gauge's NHDPlus COMID, mean annual flow and drainage
area) and the latest discharge (parameter 00060) per state from the USGS Water Data OGC API
latest-continuous collection (data/build/gauges-latest.json).

Travel time: Jobson (1996, USGS WRIR 96-4013) eq. 12 (peak) and eq. 13 (maximum probable
velocity), leading edge at 0.89 of the peak time, per NHDPlus flowline with its drainage area,
mean annual flow (qe_ma) and slope; the flow on each flowline is the gauge's relative discharge
Q/Qa times the flowline's qe_ma. With no gauge reading, Q = qe_ma (NHDPlus mean annual), said so.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from collections import Counter, OrderedDict
from datetime import UTC, datetime, timedelta

import requests

import common
from common import BUILD_DIR, DATA_DIR, HEADERS, now_iso, read_json, write_json

NLDI = "https://api.water.usgs.gov/nldi/linked-data"
EPA_ATTRS = "https://watersgeo.epa.gov/arcgis/rest/services/NHDPlus/NHDPlus/MapServer/2/query"
OGC_LATEST = "https://api.waterdata.usgs.gov/ogcapi/v1/collections/latest-continuous/items"
REACH_DIR = BUILD_DIR / "reaches"
RETIRED_DIR = REACH_DIR / "retired"           # not *.json in REACH_DIR: load_reaches and the export skip it
REACH_INDEX = BUILD_DIR / "reach-outfalls.json"
LOCK_FILE = BUILD_DIR / "reaches.lock"
GAUGES_BY_RIVER = BUILD_DIR / "gauges-by-river.json"
GAUGES_LATEST = BUILD_DIR / "gauges-latest.json"

CACHE_DAYS = 30
RETRY_FAIL_DAYS = 1                           # first retry of a failed trace; doubles per failure, to CACHE_DAYS
NLDI_PAUSE_S = 1.0
DEFAULT_NAV_BUDGET = 100                      # NLDI navigation requests a default (hourly refresh) run may spend
DEFAULT_SECONDS = 150                         # and seconds of tracing
NAV_RESERVE = 100                             # stop tracing below this many navigation requests left this hour
MOVED_DEG = 0.0005                            # an outfall moved this far (~50 m) since its trace: trace again
RUNS_KEPT = 48
SERVICE_ERRORS = 8                            # this many traces in a row failing on a service error stop the run
DETERMINISTIC_ERRORS = ("outfall not indexed", "no NHDPlus catchment", "no flowlines")
# Treatment-plant outfalls (data/outfalls-plants-us.json, 2026-11-03: about 4,000 in the live states) are not
# traced by default: CSO outfalls first, and a plant's reach must not be coloured by its permittee's CSO rain
# caution (build/rain_likely.py targets() takes every reach of a permit) until that rule skips them. Each
# reach record carries outfall_kind for that filter. --plants traces them (after every CSO outfall).
TRACE_PLANTS = False
RIVER_KINDS = {"river", "stream", "canal"}
LAKE_FTYPES = {390, 436}          # NHD LakePond, Reservoir
ESTUARY_FTYPES = {493}            # NHD Estuary
COASTLINE_FCODE = 56600           # NHD Coastline flowlines: the sea, not a river
CFS = 0.0283168466
G = 9.80665
STATE_FIPS = {"CT": "09", "MA": "25", "ME": "23", "NH": "33", "RI": "44", "VT": "50", "NY": "36"}
ATTR_FIELDS = ["comid", "gnis_name", "reachcode", "lengthkm", "totdasqkm", "slope", "qe_ma", "ve_ma",
               *[f"ve_{m:02d}" for m in range(1, 13)], "tidal", "wbareacomid", "wbarea_ftype", "fcode",
               "hydroseq", "dnhydroseq"]

# research/hydrography/report.md 2.7: mainstem gauges reporting discharge (00060) now
GAUGE_TABLE = {
    "Connecticut River": [("01129200", "below Indian Stream nr Pittsburg NH"), ("01129500", "North Stratford NH"),
                          ("01131500", "near Dalton NH"), ("01138500", "Wells River VT"), ("01144500", "West Lebanon NH"),
                          ("01154500", "North Walpole NH"), ("01161280", "near Northfield MA"),
                          ("01170500", "Montague City MA"), ("01172010", "I-391 Bridge, Holyoke MA"),
                          ("01184000", "Thompsonville CT")],
    "Deerfield River": [("01168500", "Charlemont MA"), ("01170000", "near West Deerfield MA")],
    "Westfield River": [("01179500", "Knightville MA"), ("01181000", "West Branch at Huntington MA"),
                        ("01183500", "near Westfield MA")],
    "Chicopee River": [("01177000", "Indian Orchard MA")],
    "Merrimack River": [("01081500", "Franklin Junction NH"), ("01092000", "near Goffs Falls NH"),
                        ("01100000", "below Concord River at Lowell MA")],
    "Blackstone River": [("01109730", "Millbury MA"), ("01111212", "Uxbridge MA"), ("01112500", "Woonsocket RI"),
                         ("01113895", "Pawtucket RI")],
    "Housatonic River": [("01197000", "Coltsville MA"), ("01197145", ""), ("01197500", "Great Barrington MA"),
                         ("01198125", ""), ("01199000", "Falls Village CT"), ("01200500", "Gaylordsville CT"),
                         ("01200600", ""), ("01205500", "Stevenson CT")],
    "Androscoggin River": [("01053500", "Errol NH"), ("01053600", ""), ("01054000", "Gorham NH"),
                           ("01054500", "Rumford ME"), ("01059000", "near Auburn ME")],
    "Kennebec River": [("01042500", "The Forks ME"), ("01046500", "Bingham ME"), ("01047150", ""),
                       ("01049265", "North Sidney ME")],
    "Penobscot River": [("01034500", "West Enfield ME")],
    "Winooski River": [("04286000", "Montpelier VT"), ("04290500", "near Essex Junction VT")],
    "Charles River": [("01103280", "Medway MA"), ("01103500", "Dover MA"), ("01104200", "Wellesley MA"),
                      ("01104500", "Waltham MA")],
    "Neponset River": [("01105000", "Norwood MA"), ("01105500", ""), ("01105554", ""), ("011055566", "Milton Village MA")],
    "Nashua River": [("01094400", "Fitchburg MA"), ("01094500", ""), ("01095503", ""), ("01096500", "East Pepperell MA")],
}

_session: requests.Session | None = None
_last_nldi = 0.0
# requests this run (nldi: every NLDI request; nav: its navigation requests; epa: MapServer queries) and
# what NLDI said is left this hour (X-RateLimit-Remaining: navigation answers carry the 1000 allowance)
STATS: Counter = Counter()
RATE: dict[str, int | None] = {"nav_remaining": None, "nldi_remaining": None}
_NAV_MEMO: OrderedDict = OrderedDict()        # navigation answers this run (outfalls sharing a start comid)
_ATTR_MEMO: dict[int, dict] = {}
NAV_MEMO_MAX = 64


class RateLimited(Exception):
    """NLDI answered 429: the run stops and the outfall stays due (never cached as a failure)."""


def session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update(HEADERS)
    return _session


def _note_rate(url: str, r) -> None:
    left = r.headers.get("X-RateLimit-Remaining")
    try:
        left = int(left) if left is not None else None
    except ValueError:
        left = None
    if left is not None:
        RATE["nav_remaining" if "/navigation/" in url else "nldi_remaining"] = left


def nldi_get(url: str, timeout: int = 60):
    """One NLDI request, at most one a second; None on 404; a 5xx or connection failure is retried
    after 2 and 4 seconds; a 429 (the hourly allowance is spent) raises RateLimited at once, so a run
    stops instead of waiting (the next run goes on); raises on other failures. Navigation answers are
    remembered for the run."""
    global _last_nldi
    nav = "/navigation/" in url
    if nav and url in _NAV_MEMO:
        _NAV_MEMO.move_to_end(url)
        STATS["nav_memo"] += 1
        return _NAV_MEMO[url]
    for attempt in range(3):
        wait = NLDI_PAUSE_S - (time.monotonic() - _last_nldi)
        if wait > 0:
            time.sleep(wait)
        _last_nldi = time.monotonic()
        STATS["nldi"] += 1
        if nav:
            STATS["nav"] += 1
        try:
            r = session().get(url, timeout=timeout)
        except (requests.ConnectionError, requests.Timeout):
            if attempt >= 2:
                raise
            STATS["retries"] += 1
            time.sleep(2 * 2 ** attempt)
            continue
        _note_rate(url, r)
        if r.status_code == 429:                  # over the hourly allowance
            STATS["rate_limited"] += 1
            RATE["nav_remaining" if nav else "nldi_remaining"] = 0
            raise RateLimited(f"NLDI 429 for {url}")
        if r.status_code >= 500 and attempt < 2:
            STATS["retries"] += 1
            time.sleep(2 * 2 ** attempt)
            continue
        if r.status_code == 404:
            out = None
        else:
            r.raise_for_status()
            out = r.json()
        if nav:
            _NAV_MEMO[url] = out
            while len(_NAV_MEMO) > NAV_MEMO_MAX:
                _NAV_MEMO.popitem(last=False)
        return out
    raise requests.RequestException(f"NLDI gave up on {url}")


def load_rules() -> dict:
    return read_json(DATA_DIR / "rules.json") or {}


def cap_km(rules: dict | None = None) -> float:
    return float(((rules or load_rules()).get("reach") or {}).get("cap_km") or 40)


# ---------------------------------------------------------------- geometry helpers

def seg_km(coords) -> float:
    total = 0.0
    for (x1, y1), (x2, y2) in zip(coords, coords[1:]):
        p1, p2 = math.radians(y1), math.radians(y2)
        dp, dl = p2 - p1, math.radians(x2 - x1)
        a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        total += 2 * 6371.0088 * math.asin(math.sqrt(a))
    return total


def cut_line(coords, km: float):
    """The first `km` of a polyline."""
    out, done = [coords[0]], 0.0
    for a, b in zip(coords, coords[1:]):
        d = seg_km([a, b])
        if done + d >= km and d > 0:
            f = (km - done) / d
            out.append([a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f])
            return out
        out.append(b)
        done += d
    return out


def trim_from_point(coords, lon, lat):
    """The polyline from the vertex-projected point nearest (lon, lat) to its end."""
    from shapely.geometry import LineString, Point
    from shapely.ops import substring
    line = LineString(coords)
    d = line.project(Point(lon, lat))
    part = substring(line, d, line.length)
    return [list(c) for c in part.coords] if part.length > 0 else coords[-2:]


# ---------------------------------------------------------------- the cut rules (pure)

def build_segments(flowlines: list[dict], attrs: dict, cap: float) -> tuple[list[dict], str]:
    """flowlines: [{"comid", "coords"}] in NLDI order; attrs: {comid: NHDPlus attributes}.
    Returns (segments upstream first with km_start/km_end, cut_reason)."""
    def order(f):
        h = (attrs.get(f["comid"]) or {}).get("hydroseq")
        return -(h if isinstance(h, (int, float)) else 0)
    lines = sorted(flowlines, key=order) if all(attrs.get(f["comid"]) for f in flowlines) else list(flowlines)
    segs, km = [], 0.0
    for i, f in enumerate(lines):
        a = attrs.get(f["comid"]) or {}
        if not a or a.get("tidal") is None:
            # unknown flowline: its tidal and lake flags cannot be checked, so the trace stops here
            return segs, "attributes unavailable"
        if a.get("tidal") == 1:
            return segs, "tidal_at_outfall" if i == 0 else "tidal"
        ft = a.get("wbarea_ftype")
        if (a.get("wbareacomid") or 0) > 0 and ft in LAKE_FTYPES:
            return segs, "lake_at_outfall" if i == 0 else "lake_or_reservoir"
        if ((a.get("wbareacomid") or 0) > 0 and ft in ESTUARY_FTYPES) or a.get("fcode") == COASTLINE_FCODE:
            return segs, "tidal_at_outfall" if i == 0 else "estuary"
        coords = f["coords"]
        length = seg_km(coords)
        if length <= 0:
            continue
        if km + length >= cap:
            coords = cut_line(coords, cap - km)
            length = cap - km
            segs.append(segment(f["comid"], a, coords, km, km + length))
            return segs, "cap_km"
        segs.append(segment(f["comid"], a, coords, km, km + length))
        km += length
    return segs, "end_of_trace"


def segment(comid, a, coords, k0, k1) -> dict:
    keep = {k: a.get(k) for k in ATTR_FIELDS if k != "comid"}
    return {"comid": comid, "km_start": round(k0, 3), "km_end": round(k1, 3), **keep,
            "coords": [[round(x, 6), round(y, 6)] for x, y in coords]}


# ---------------------------------------------------------------- Jobson 1996

def usable(*xs) -> bool:
    return all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and x > 0 for x in xs)


def jobson(da_km2: float, qa_cfs: float, q_cfs: float, slope: float) -> tuple[float | None, float | None]:
    """(peak velocity eq. 12, maximum probable velocity eq. 13) in m/s. Da drainage area, Qa mean
    annual flow, Q flow at the time, S slope (m/m); D'a = Da^1.25 g^0.5 / Qa, Q'a = Q / Qa.
    Inputs outside the regression (zero, negative, missing, not finite) give (None, None)."""
    if not usable(da_km2, qa_cfs, q_cfs):
        return None, None
    if not usable(slope):
        slope = 1e-5
    da = da_km2 * 1e6
    qa = qa_cfs * CFS
    q = q_cfs * CFS
    s = max(slope, 1e-5)
    dpa = da ** 1.25 * math.sqrt(G) / qa
    qpa = q / qa
    group = dpa ** 0.919 * qpa ** -0.469 * s ** 0.159 * q / da
    return 0.094 + 0.0143 * group, 0.25 + 0.02 * group


def path_slope(segments: list[dict]) -> float:
    """Length-weighted mean NHDPlus slope over the trace (= elevation drop / length), the
    reach-average slope Jobson's subreaches use; NHDPlus floors flat flowlines at 1e-5, so a
    per-flowline slope would understate velocity on pooled stretches."""
    num = den = 0.0
    for s in segments:
        sl, ln = s.get("slope"), s["km_end"] - s["km_start"]
        if isinstance(sl, (int, float)) and sl > 0 and ln > 0:
            num, den = num + sl * ln, den + ln
    return num / den if den else 1e-5


def travel(segments: list[dict], q_ratio: float) -> list[dict]:
    """Cumulative arrival hours (peak, fastest, leading edge) at each segment's start and end.
    Per flowline: its drainage area and mean annual flow (qe_ma), flow = q_ratio x qe_ma, and the
    trace's mean slope; a flowline without usable attributes takes the previous velocities."""
    out, t_p, t_f = [], 0.0, 0.0
    slope = path_slope(segments)
    if not usable(q_ratio):
        q_ratio = None
    for s in segments:
        da, qa = s.get("totdasqkm"), s.get("qe_ma")
        vp, vf = jobson(da, qa, qa * q_ratio, slope) if q_ratio and usable(da, qa) else (None, None)
        length_m = (s["km_end"] - s["km_start"]) * 1000
        start_p, start_f = t_p, t_f
        if t_p is not None and vp and vf:
            t_p += length_m / vp / 3600
            t_f += length_m / vf / 3600
        else:
            t_p = t_f = None        # no drainage area / mean flow here: no time from here on, never zero

        def r(x):
            return round(x, 2) if x is not None else None
        out.append({"hours_typical_start": r(start_p), "hours_typical": r(t_p),
                    "hours_fast_start": r(start_f), "hours_fast": r(t_f),
                    "hours_leading_edge": r(0.89 * t_p) if t_p is not None else None,
                    "velocity_peak_ms": round(vp, 3) if vp else None, "velocity_max_ms": round(vf, 3) if vf else None})
    return out


# ---------------------------------------------------------------- outfalls

def norm_oid(s) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(s or "").upper())


def reach_key(permit: str, outfall) -> str:
    return f"{permit}-{norm_oid(outfall)}"


def live_states() -> set[str]:
    """The live states: the covered-state list the export and the state pages use (common.live_states
    when the registry loader provides one, else status.states(): the water records' and rules' states)."""
    fn = getattr(common, "live_states", None)
    if callable(fn):
        try:
            return {str(s).upper() for s in fn()}
        except Exception:
            pass
    from build.status import states
    return {str(s).upper() for s in states()}


def registry_outfalls() -> list[dict]:
    """Every official registry outfall row: common.load_outfall_registry(provisional=False) (all
    data/outfalls-*.json, de-duplicated, with outfall_kind), else status.load_registry_outfalls(). The
    provisional places derived from the reports are left out: a modeled reach starts at an official
    outfall (a report with a point and no reach is traced from its own point, event_points)."""
    fn = getattr(common, "load_outfall_registry", None)
    rows = None
    if callable(fn):
        try:
            rows = fn(provisional=False)
        except TypeError:
            rows = None
        if isinstance(rows, dict):
            rows = rows.get("outfalls")
    if rows is None:
        from build.status import load_registry_outfalls
        rows = load_registry_outfalls()
    return [o for o in rows or [] if isinstance(o, dict)]


def is_closed(o: dict) -> bool:
    return "CLS" in [t.strip() for t in str(o.get("outfall_status") or "").upper().split("|")]


def outfall_kind(o: dict) -> str:
    """"cso" (EPA's CSO inventory or a state CSO layer: rows without a kind) or "plant"."""
    return "plant" if str(o.get("outfall_kind") or "").lower() == "plant" else "cso"


REPORTED_DAYS = 90          # status.HISTORY_DAYS: a closed outfall named by a report this recent is open in fact


def reported_outfalls(days: int = REPORTED_DAYS) -> set:
    """{(permit, outfall key)} named by an event record of the last `days` (npdes_permit + outfall_id), and
    {reach key} of the reaches the last status build placed records on (data/build/status.json)."""
    from build.status import EVENTS_DIR, oid_key
    since = datetime.now(UTC) - timedelta(days=days)
    out: set = set()
    for p in sorted(EVENTS_DIR.glob("*.json")):
        try:
            d = json.loads(p.read_text())
        except Exception:
            continue
        for e in (d.get("records") or d.get("events") or []) if isinstance(d, dict) else []:
            if not isinstance(e, dict) or not e.get("npdes_permit") or e.get("outfall_id") in (None, ""):
                continue
            ts = [t for t in (_t(e.get(k)) for k in ("started_at", "ended_at", "reported_at", "published_at")) if t]
            if ts and max(ts) < since:
                continue
            k = oid_key(e["outfall_id"])
            out.add((e["npdes_permit"], k if k else norm_oid(e["outfall_id"])))
    st = read_json(BUILD_DIR / "status.json") or {}
    for pl in (st.get("placements") or {}).values():
        for k in [pl.get("reach"), *(pl.get("reaches") or [])]:
            if k:
                out.add(k)
    return out


def candidate_outfalls(waters: dict | None = None, registry: list[dict] | None = None, live: set | None = None,
                       skipped: dict | None = None, reported: set | None = None,
                       plants: bool | None = None) -> list[dict]:
    """The outfalls to trace (module docstring). `skipped` (if given) receives {key: {permit, outfall,
    state, kind, status, why}} for registry outfalls in live states that are not traced: closed,
    coords_problem, not_river (its water record is a bay, sound, lake or pond), no_location. An outfall
    the registry lists as closed but a recent report names (`reported`, reported_outfalls()) is traced:
    it is open in fact (Vermont reports discharges from outfalls ECHO lists as closed). Treatment-plant
    outfalls (outfall_kind "plant") are traced only with plants=True (TRACE_PLANTS; --plants), else
    listed as plant_deferred."""
    from build.status import Resolver, load_waters, oid_key
    waters = waters if waters is not None else load_waters()
    registry = registry if registry is not None else registry_outfalls()
    live = {str(s).upper() for s in (live if live is not None else live_states())}
    reported = reported if reported is not None else reported_outfalls()
    plants = TRACE_PLANTS if plants is None else plants
    skip: dict[str, dict] = {}
    by_po: dict[tuple, dict] = {}
    for o in registry:
        if o.get("npdes_permit"):
            by_po.setdefault((o["npdes_permit"], norm_oid(o.get("outfall"))), o)
    out: dict[str, dict] = {}

    def add(permit, outfall, lat, lon, slug, src, name=None, row=None):
        if not permit or outfall in (None, ""):
            return
        k = reach_key(permit, outfall)
        who = {"permit": permit, "outfall": str(outfall), "state": permit[:2].upper(), "kind": "cso"}
        if slug and slug in waters and waters[slug].get("kind") not in RIVER_KINDS:
            skip.setdefault(k, {**who, "why": "not_river", "note": f"its water record ({slug}) is a {waters[slug].get('kind')}"})
            return
        slug = slug if slug in waters else None             # no water record yet: the trace still runs
        if lat is None and (not row.get("reach_id") if row is not None else slug is None):
            # nothing to start from: NLDI knows a registry outfall only by its EPA reach index, and a
            # water record alone is no starting point
            skip.setdefault(k, {**who, "why": "no_location", "note": "no coordinates and no EPA reach id"})
            return
        rec = out.setdefault(k, {"key": k, "permit": permit, "outfall": str(outfall), "water_slug": slug,
                                 "lat": lat, "lon": lon, "name": name, "sources": []})
        rec["sources"].append(src)
        if src != "echo" and lat is not None:      # state layers are surveyed points; prefer them
            rec["lat"], rec["lon"] = lat, lon
        if rec["water_slug"] is None and slug:
            rec["water_slug"] = slug
        if row is not None:
            rec.setdefault("state", str(row.get("state") or permit[:2]).upper())
            rec.setdefault("outfall_kind", outfall_kind(row))
            rec.setdefault("file", row.get("_file") or row.get("file"))
            if "reach_id" in row:
                rec.setdefault("reach_id", row.get("reach_id") or None)
        rec.setdefault("state", permit[:2].upper())
        rec.setdefault("outfall_kind", "cso")

    seen = set()
    for o in registry:
        permit, oid = o.get("npdes_permit"), o.get("outfall")
        if not permit or oid in (None, ""):
            continue
        k = reach_key(permit, oid)
        if k in seen:                       # the first row wins (the loader puts the more specific file first)
            continue
        seen.add(k)
        st = str(o.get("state") or permit[:2]).upper()
        if st not in live:
            continue
        base = {"permit": permit, "outfall": str(oid), "state": st, "kind": outfall_kind(o)}
        if base["kind"] == "plant" and not plants:
            skip[k] = {**base, "why": "plant_deferred", "note": "treatment-plant outfall: traced with --plants"}
            continue
        ok = oid_key(oid)
        open_in_fact = k in reported or (permit, ok if ok else norm_oid(oid)) in reported
        if is_closed(o) and not open_in_fact:
            skip[k] = {**base, "why": "closed", "note": f"outfall_status {o.get('outfall_status')}"}
            continue
        if o.get("coords_problem"):
            skip[k] = {**base, "why": "coords_problem", "note": str(o["coords_problem"])[:300]}
            continue
        add(permit, oid, o.get("lat"), o.get("lon"), o.get("water_slug"), "echo", o.get("outfall_name"), row=o)
        if k in out and is_closed(o):
            out[k]["reported_while_closed"] = True
        if k in skip:
            skip[k] = {**skip[k], **base}
    resolver = None
    if "MA" in live:
        ma = (read_json(BUILD_DIR / "ma-cso-outfalls.json", {}) or {}).get("outfalls") or {}
        for o in (ma.values() if isinstance(ma, dict) else ma):
            e = by_po.get((o.get("npdes"), norm_oid(o.get("outfall"))))
            slug = e.get("water_slug") if e else None
            if not slug and o.get("lat") is not None:
                resolver = resolver or Resolver(waters, [])
                near = resolver.by_point(o["lat"], o["lon"], "MA")
                slug = near[1] if near else None
            add(o.get("npdes"), o.get("outfall"), o.get("lat"), o.get("lon"), slug, "massdep-layer", o.get("address"))
    if "ME" in live:
        me = (read_json(BUILD_DIR / "me-cso-outfalls.json", {}) or {}).get("outfalls") or []
        for o in me:
            if str(o.get("status") or "").upper() == "CLOSED":
                continue
            add(o.get("permit"), o.get("outfall"), o.get("lat"), o.get("lon"), o.get("water_slug"), "me-dep-layer",
                o.get("name"))
    if skipped is not None:
        for k, v in skip.items():
            if k not in out:                # a state layer listing it open wins over the registry's CLS
                skipped[k] = v
    return sorted(out.values(), key=lambda r: r["key"])


def try_npdes(o: dict, prev: dict | None = None) -> bool:
    """Ask NLDI's npdes source only when the registry row has an EPA reach id, does not say, or an
    earlier trace found the outfall there (rows ECHO did not reach-index were 1 in 8 there, 2026-11-03)."""
    if (prev or {}).get("method") == "nldi_npdes":
        return True
    return "reach_id" not in o or bool(o.get("reach_id"))


# ---------------------------------------------------------------- fetching

def fetch_attrs(comids: list[int]) -> dict[int, dict]:
    """NHDPlus V2.1 attributes by comid (EPA MapServer layer 2, 100 a query; answers remembered for the
    run; a failed query is tried once more after 3 seconds)."""
    out = {c: _ATTR_MEMO[c] for c in comids if c in _ATTR_MEMO}
    ask = [c for c in comids if c not in _ATTR_MEMO]
    for i in range(0, len(ask), 100):
        chunk = ask[i:i + 100]
        for attempt in range(2):
            try:
                STATS["epa"] += 1
                r = session().get(EPA_ATTRS, params={"where": f"comid in ({','.join(map(str, chunk))})",
                                                     "outFields": ",".join(ATTR_FIELDS), "returnGeometry": "false",
                                                     "f": "json"}, timeout=90)
                r.raise_for_status()
                d = r.json()
                if not isinstance(d, dict) or "error" in d or "features" not in d:
                    raise ValueError(f"EPA NHDPlus query error: {str(d.get('error') if isinstance(d, dict) else d)[:200]}")
                break
            except (requests.RequestException, ValueError):
                if attempt:
                    raise
                STATS["retries"] += 1
                time.sleep(3)
        for f in d.get("features", []):
            a = f.get("attributes") or {}
            if a.get("comid") is not None:
                out[int(a["comid"])] = _ATTR_MEMO[int(a["comid"])] = a
    return out


def lines_of(fc) -> list[dict]:
    out = []
    for f in (fc or {}).get("features", []):
        g = f.get("geometry") or {}
        comid = (f.get("properties") or {}).get("nhdplus_comid") or f.get("id")
        if g.get("type") == "LineString" and comid is not None:
            out.append({"comid": int(comid), "coords": g["coordinates"]})
        elif g.get("type") == "MultiLineString" and comid is not None:
            out.append({"comid": int(comid), "coords": [c for part in g["coordinates"] for c in part]})
    return out


# ---------------------------------------------------------------- the NHDPlus walk (when NLDI's allowance is spent)

EPA_CATCHMENT = "https://watersgeo.epa.gov/arcgis/rest/services/NHDPlus/NHDPlus/MapServer/6/query"
WALK_FIELDS = [*ATTR_FIELDS, "levelpathid", "dnlevelpathid", "pathlength", "terminalflag"]
EPA_PAUSE_S = 0.25
# NLDI answers ("nldi") or the walk below ("nhdplus_walk", for the rest of the run once set); until
# nldi_low_until (monotonic seconds) NLDI's whole allowance is low too, so the start comes from EPA's catchment
# layer; NLDI is asked again after NLDI_COOLDOWN_S. Set by Budget.stop() and by a 429.
MODE = {"walk": False, "nldi_low_until": 0.0}
NLDI_COOLDOWN_S = 300
_last_epa = 0.0


def nldi_low() -> bool:
    return time.monotonic() < MODE["nldi_low_until"]


def set_nldi_low() -> None:
    MODE["walk"] = True
    MODE["nldi_low_until"] = time.monotonic() + NLDI_COOLDOWN_S


def epa_query(url: str, params: dict) -> list[dict]:
    """One EPA NHDPlus MapServer query (features), at most four a second, tried once more after 3 s."""
    global _last_epa
    for attempt in range(2):
        wait = EPA_PAUSE_S - (time.monotonic() - _last_epa)
        if wait > 0:
            time.sleep(wait)
        _last_epa = time.monotonic()
        try:
            STATS["epa"] += 1
            r = session().get(url, params={**params, "f": "json"}, timeout=90)
            r.raise_for_status()
            d = r.json()
            if not isinstance(d, dict) or "error" in d or "features" not in d:
                raise ValueError(f"EPA NHDPlus query error: {str(d.get('error') if isinstance(d, dict) else d)[:200]}")
            return d["features"]
        except (requests.RequestException, ValueError):
            if attempt:
                raise
            STATS["retries"] += 1
            time.sleep(3)
    return []


def flowlines_where(where: str) -> list[dict]:
    """NHDPlus V2.1 flowlines (layer 2) with geometry (lon/lat) and the walk's attributes, upstream first."""
    return epa_query(EPA_ATTRS, {"where": where, "outFields": ",".join(WALK_FIELDS), "returnGeometry": "true",
                                 "outSR": 4326, "orderByFields": "hydroseq DESC"})


def nhdplus_walk(comid: int, dist: float) -> list[dict]:
    """The downstream-main path from `comid` (itself first) for about `dist` km, from EPA's NHDPlus V2.1
    MapServer: one query per level path (levelpathid, hydroseq at or below the current one, pathlength
    within reach), then the flowline its last one drains to (dnhydroseq) starts the next level path. This
    is the network NLDI's DM navigation follows (the same flowlines, 2026-11-03: 25 cached NLDI traces
    matched comid for comid). Attributes are remembered for fetch_attrs."""
    first = flowlines_where(f"comid = {int(comid)}")
    if not first:
        return []
    a0 = first[0]["attributes"]
    floor = float(a0.get("pathlength") or 0) + float(a0.get("lengthkm") or 0) - dist
    lines, seen = [], set()
    lp, hs = a0.get("levelpathid"), a0.get("hydroseq")
    for _ in range(25):
        if not lp or hs is None:
            break
        feats = flowlines_where(f"levelpathid = {int(lp)} AND hydroseq <= {hs} AND pathlength + lengthkm >= {floor:.3f}")
        for f in feats:
            a = f.get("attributes") or {}
            c = a.get("comid")
            if c is None or int(c) in seen:
                continue
            seen.add(int(c))
            _ATTR_MEMO[int(c)] = a
            coords = [pt[:2] for path in (f.get("geometry") or {}).get("paths") or [] for pt in path]
            if coords:
                lines.append({"comid": int(c), "coords": coords})
        if not feats:
            break
        last = feats[-1].get("attributes") or {}
        if last.get("terminalflag") == 1 or not last.get("dnhydroseq") or float(last.get("pathlength") or 0) <= floor:
            break
        nxt = flowlines_where(f"hydroseq = {last['dnhydroseq']}")
        if not nxt:
            break
        lp, hs = nxt[0]["attributes"].get("levelpathid"), nxt[0]["attributes"].get("hydroseq")
    return lines


def catchment_comid(lon: float, lat: float) -> int | None:
    """The comid of the NHDPlus V2.1 catchment holding the point (EPA layer 6; what NLDI comid/position answers)."""
    feats = epa_query(EPA_CATCHMENT, {"geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint", "inSR": 4326,
                                      "spatialRel": "esriSpatialRelIntersects", "outFields": "featureid",
                                      "returnGeometry": "false"})
    for f in feats:
        c = (f.get("attributes") or {}).get("featureid")
        if c:
            return int(c)
    return None


# ---------------------------------------------------------------- the trace

def _start_nldi(o: dict, rec: dict, npdes_id: str | None, prev: dict | None, dist: int) -> list[dict]:
    """NLDI navigation: npdes DM (trimmed by NLDI), else comid/position (or hydrolocation) and comid DM."""
    fc = nldi_get(f"{NLDI}/npdes/{npdes_id}/navigation/DM/flowlines?distance={dist}&trimStart=true") \
        if npdes_id and try_npdes(o, prev) else None
    lines = lines_of(fc)
    if lines:
        rec["method"], rec["npdes_id"] = "nldi_npdes", npdes_id
        return lines
    if o.get("lat") is None:
        return []
    # comid/position answers in about half a second; hydrolocation (raindrop trace) often
    # times out upstream, so it is only the fallback. The first flowline is trimmed here at
    # the point on it nearest the outfall.
    comid, snap = None, None
    try:
        p = nldi_get(f"{NLDI}/comid/position?coords=POINT({o['lon']}%20{o['lat']})")
        for f in (p or {}).get("features", []):
            if (f.get("properties") or {}).get("comid"):
                comid = int(f["properties"]["comid"])
        rec["method"] = "nldi_position"
    except requests.RequestException:
        h = nldi_get(f"{NLDI}/hydrolocation?coords=POINT({o['lon']}%20{o['lat']})")
        for f in (h or {}).get("features", []):
            q = f.get("properties") or {}
            if q.get("comid"):
                comid, snap = int(q["comid"]), (f.get("geometry") or {}).get("coordinates")
        rec["method"] = "nldi_hydrolocation"
    if not comid:
        return []
    lines = lines_of(nldi_get(f"{NLDI}/comid/{comid}/navigation/DM/flowlines?distance={dist}"))
    rec["start_comid"] = comid
    for ln in lines:
        if ln["comid"] == comid:
            x, y = (snap or [o["lon"], o["lat"]])[:2]
            ln["coords"] = trim_from_point(ln["coords"], x, y)
    return lines


def _start_walk(o: dict, rec: dict, npdes_id: str | None, prev: dict | None, dist: int) -> list[dict]:
    """The NHDPlus walk: the start from NLDI's npdes feature (its indexed point; not a navigation request) or
    comid/position, or, when NLDI's whole allowance is low, EPA's catchment layer; the first flowline
    trimmed at the indexed point or the outfall."""
    comid, snap = None, None
    if npdes_id and try_npdes(o, prev) and not nldi_low():
        f = ((nldi_get(f"{NLDI}/npdes/{npdes_id}") or {}).get("features") or [None])[0]
        if f and (f.get("properties") or {}).get("comid"):
            comid, snap = int(f["properties"]["comid"]), (f.get("geometry") or {}).get("coordinates")
            rec["method"], rec["npdes_id"] = "nldi_npdes", npdes_id
    if comid is None and o.get("lat") is not None:
        if not nldi_low():
            p = nldi_get(f"{NLDI}/comid/position?coords=POINT({o['lon']}%20{o['lat']})")
            for f in (p or {}).get("features", []):
                if (f.get("properties") or {}).get("comid"):
                    comid = int(f["properties"]["comid"])
            rec["method"] = "nldi_position"
        else:
            comid = catchment_comid(o["lon"], o["lat"])
            rec["method"] = "nhdplus_catchment"
    if not comid:
        return []
    rec["start_comid"] = comid
    lines = nhdplus_walk(comid, dist)
    x, y = (snap or [o.get("lon"), o.get("lat")])[:2]
    if x is not None:
        for ln in lines:
            if ln["comid"] == comid:
                ln["coords"] = trim_from_point(ln["coords"], x, y)
    return lines


def trace(o: dict, cap: float, prev: dict | None = None) -> dict:
    """One outfall's downstream trace (module docstring). NLDI navigation while its allowance lasts, then
    (MODE["walk"]) the NHDPlus walk, started from EPA's catchments once NLDI's whole allowance is spent
    (nldi_low()). A failure is a no_trace record with its error."""
    rec = {**o, "fetched_at": now_iso(), "cap_km": cap, "method": None, "npdes_id": None, "start_comid": None,
           "segments": [], "cut_reason": None, "length_km": 0.0, "error": None}
    dist = int(math.ceil(cap + 5))
    oid = norm_oid(o.get("outfall"))
    npdes_id = f"{o['permit']}{oid.zfill(3) if oid.isdigit() else oid}" if o.get("permit") and oid else None
    try:
        lines = None
        if not MODE["walk"]:
            try:
                lines = _start_nldi(o, rec, npdes_id, prev, dist)
                rec["navigation"] = "nldi"
            except RateLimited:
                MODE["walk"] = True             # navigation allowance spent: walk NHDPlus for the rest of the run
                if RATE.get("nldi_remaining") == 0:
                    set_nldi_low()              # and NLDI's whole allowance: start from EPA's catchments
                rec.update({"method": None, "npdes_id": None, "start_comid": None})
        if lines is None:
            try:
                lines = _start_walk(o, rec, npdes_id, prev, dist)
            except RateLimited:
                set_nldi_low()
                rec.update({"method": None, "npdes_id": None, "start_comid": None})
                lines = _start_walk(o, rec, npdes_id, prev, dist)
            rec["navigation"] = "nhdplus_walk"
        if not lines:
            rec["cut_reason"] = "no_trace"
            rec["error"] = ("outfall not indexed in NLDI and no coordinates to snap" if o.get("lat") is None else
                            "no NHDPlus catchment at the outfall's point (open water or the coast)"
                            if rec["start_comid"] is None else "no flowlines")
            return rec
        attrs = fetch_attrs(sorted({ln["comid"] for ln in lines}))
        if rec["start_comid"] is None:
            rec["start_comid"] = lines[0]["comid"]
        segs, why = build_segments(lines, attrs, cap)
        rec["segments"], rec["cut_reason"] = segs, why
        rec["length_km"] = round(segs[-1]["km_end"], 3) if segs else 0.0
        rec["river"] = (segs[0].get("gnis_name") if segs else (attrs.get(lines[0]["comid"]) or {}).get("gnis_name"))
    except RateLimited:
        raise
    except Exception as e:  # keep going; the failure is cached and retried after a day (then 2, 4 ...)
        rec["cut_reason"] = "no_trace"
        rec["error"] = f"{type(e).__name__}: {e}"[:300]
    return rec


def event_points() -> list[dict]:
    """Recent river discharges with a point but no outfall reach (status.json needs_reach: sewer
    breaks, pump stations): traced from the event's own coordinates."""
    import hashlib
    st = read_json(BUILD_DIR / "status.json") or {}
    out = []
    for n in st.get("needs_reach") or []:
        key = "pt-" + hashlib.sha1(n["event_id"].encode()).hexdigest()[:12]
        out.append({"key": key, "permit": n.get("permit"), "outfall": None, "water_slug": n.get("water_slug"),
                    "lat": n["lat"], "lon": n["lon"], "name": None, "sources": ["event-point"],
                    "event_ids": [n["event_id"]]})
    return out


def _t(s) -> datetime | None:
    try:
        t = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def retry_days(d: dict) -> float:
    """Days a cached record stays fresh: CACHE_DAYS for a trace; for a failure 1, 2, 4 ... days by its
    consecutive failures, at most CACHE_DAYS."""
    if d.get("cut_reason") != "no_trace":
        return CACHE_DAYS
    return min(CACHE_DAYS, RETRY_FAIL_DAYS * 2 ** max(0, int(d.get("failures") or 1) - 1))


def fresh(path, now) -> bool:
    d = read_json(path)
    return bool(d) and fresh_rec(d, now)


def moved(c: dict, d: dict) -> bool:
    """The outfall's point moved since its cached trace (or gained one)."""
    if c.get("lat") is None:
        return False
    if d.get("lat") is None:
        return d.get("cut_reason") == "no_trace" or not d.get("segments")
    return abs(c["lat"] - d["lat"]) > MOVED_DEG or abs(c["lon"] - d["lon"]) > MOVED_DEG


META_FIELDS = ("water_slug", "name", "sources", "state", "outfall_kind", "file", "reach_id", "reported_while_closed")


def plan(cands: list[dict], cached: dict[str, dict], now: datetime) -> tuple[list[dict], list[tuple[dict, dict]]]:
    """(the outfalls to trace in order, [(candidate, cached record)] whose fields changed but need no trace).
    Order: event points, never traced or moved (CSO, then plant), failures due again (oldest first),
    traces older than CACHE_DAYS (oldest first)."""
    todo, touch = [], []
    for c in cands:
        d = cached.get(c["key"])
        kind = 1 if c.get("outfall_kind") == "plant" else 0
        if c.get("sources") == ["event-point"]:
            if not d or not fresh_rec(d, now):
                todo.append(((0, 0, ""), c))
            continue
        if not d or moved(c, d):
            todo.append(((1, kind, ""), c))
            continue
        if not fresh_rec(d, now):
            tier = 2 if d.get("cut_reason") == "no_trace" else 3
            todo.append(((tier, kind, d.get("fetched_at") or ""), c))
            continue
        if any(c.get(f) != d.get(f) for f in META_FIELDS if f in c):
            touch.append((c, d))
    todo.sort(key=lambda x: (x[0], x[1]["key"]))
    return [c for _, c in todo], touch


def fresh_rec(d: dict, now: datetime) -> bool:
    t = _t(d.get("fetched_at"))
    return t is not None and now - t < timedelta(days=retry_days(d))


def outcome(d: dict | None) -> str:
    """A cached record's public-facing state: traced, tidal_at_outfall, lake_at_outfall or no_trace."""
    if not d:
        return "pending"
    if d.get("segments"):
        return "traced"
    if d.get("cut_reason") in ("tidal_at_outfall", "lake_at_outfall"):
        return d["cut_reason"]
    return "no_trace"


class Budget:
    """When a run stops tracing: NLDI navigation requests (0: no limit), seconds (0: no limit), --limit
    traces. With NLDI's allowance left this hour under `reserve` the run switches to the NHDPlus walk."""

    def __init__(self, nav: int = DEFAULT_NAV_BUDGET, seconds: float = DEFAULT_SECONDS, reserve: int = NAV_RESERVE,
                 limit: int = 0):
        self.nav, self.seconds, self.reserve, self.limit = nav, seconds, reserve, limit
        self.t0 = time.monotonic()
        self.nav0 = STATS["nav"]
        self.traced = 0

    def stop(self) -> str | None:
        if self.limit and self.traced >= self.limit:
            return f"--limit {self.limit} traces"
        if self.nav and STATS["nav"] - self.nav0 + 2 > self.nav:     # a trace asks at most two navigation questions
            return f"request budget ({self.nav} NLDI navigation requests)"
        if self.seconds and time.monotonic() - self.t0 >= self.seconds:
            return f"time budget ({self.seconds:g} s)"
        # NLDI's allowance is shared with everything on this machine: under the reserve, the run goes on with
        # the NHDPlus walk (and EPA's catchments for the start) instead of spending the rest
        left = RATE.get("nav_remaining")
        if left is not None and left < self.reserve:
            MODE["walk"] = True
        left = RATE.get("nldi_remaining")
        if left is not None and left < self.reserve and not nldi_low():
            set_nldi_low()
            RATE["nldi_remaining"] = None       # asked again after the cool-down
        return None


def retire_closed(skipped: dict[str, dict], cands: list[dict]) -> list[str]:
    """Move cached traces of outfalls the registry lists as closed (and no state layer lists as open)
    to RETIRED_DIR: the rain caution and the map never use a closed outfall. Returns the keys."""
    live = {c["key"] for c in cands}
    out = []
    for k, v in sorted(skipped.items()):
        if v.get("why") != "closed" or k in live:
            continue
        p = REACH_DIR / f"{k}.json"
        if p.exists():
            RETIRED_DIR.mkdir(parents=True, exist_ok=True)
            d = read_json(p) or {}
            d["retired"] = {"at": now_iso(), "why": f"the outfall registry lists this outfall as closed ({v.get('note')})"}
            write_json(RETIRED_DIR / p.name, d)
            p.unlink()
            out.append(k)
    return out


def write_index(cands: list[dict], skipped: dict[str, dict], cached: dict[str, dict], live: set, run: dict | None) -> dict:
    """data/build/reach-outfalls.json: every live-state registry outfall's trace state (traced,
    tidal_at_outfall, lake_at_outfall, no_trace, pending; or why it is not traced: closed,
    coords_problem, not_river, no_location), counts by state, and the last runs' request counts."""
    prev = read_json(REACH_INDEX) or {}
    rows = {}
    for c in cands:
        if c.get("sources") == ["event-point"]:
            continue
        d = cached.get(c["key"])
        row = {"permit": c["permit"], "outfall": c["outfall"], "state": c.get("state") or c["permit"][:2],
               "kind": c.get("outfall_kind") or "cso", "status": outcome(d)}
        if d:
            row.update({"cut_reason": d.get("cut_reason"), "length_km": d.get("length_km"), "method": d.get("method"),
                        "fetched_at": d.get("fetched_at")})
            if d.get("error"):
                row["error"] = d["error"]
        rows[c["key"]] = row
    for k, v in skipped.items():
        rows.setdefault(k, {"permit": v.get("permit"), "outfall": v.get("outfall"), "state": v.get("state"),
                            "kind": v.get("kind") or "cso", "status": v["why"], "note": v.get("note")})
    by_state: dict[str, Counter] = {}
    for r in rows.values():
        by_state.setdefault(r.get("state") or "?", Counter())[r["status"]] += 1
    runs = list(prev.get("runs") or [])
    if run:
        runs = (runs + [run])[-RUNS_KEPT:]
    out = {"built": now_iso(), "live_states": sorted(live),
           "statuses": {"traced": "a modeled downstream reach", "tidal_at_outfall": "NHDPlus marks the outfall's "
                        "flowline tidal, estuary or coastline: no reach", "lake_at_outfall": "the outfall's flowline is "
                        "in a lake or reservoir: no reach", "no_trace": "NLDI gave no flowlines (retried later)",
                        "pending": "not traced yet (a later run)", "closed": "closed outfall: not traced",
                        "coords_problem": "the registry flags the outfall's coordinates: not traced",
                        "not_river": "its water record is a bay, sound, lake or pond: not traced",
                        "no_location": "no coordinates and no EPA reach id: not traced",
                        "plant_deferred": "treatment-plant outfall: not traced yet (--plants)"},
           "counts": {"total": dict(Counter(r["status"] for r in rows.values())),
                      "by_state": {s: dict(c) for s, c in sorted(by_state.items())}},
           "outfalls": dict(sorted(rows.items())), "runs": runs}
    write_json(REACH_INDEX, out)
    return out


class TraceLock:
    """An exclusive, non-blocking lock on data/build/reaches.lock (released when the process ends)."""

    def __init__(self):
        self.fh = None

    def acquire(self) -> bool:
        import fcntl
        LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
        self.fh = open(LOCK_FILE, "a+")
        try:
            fcntl.flock(self.fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.fh.close()
            self.fh = None
            return False
        return True

    def release(self) -> None:
        if self.fh:
            import fcntl
            fcntl.flock(self.fh, fcntl.LOCK_UN)
            self.fh.close()
            self.fh = None


def load_reaches() -> dict[str, dict]:
    out = {}
    if not REACH_DIR.exists():
        return out
    for p in sorted(REACH_DIR.glob("*.json")):
        try:
            d = json.loads(p.read_text())
        except Exception:
            continue
        out[d.get("key") or p.stem] = d
    return out


# ---------------------------------------------------------------- gauges

def build_gauges(force: bool = False) -> dict:
    cur = read_json(GAUGES_BY_RIVER) or {}
    if cur.get("built") and not force:
        t = datetime.fromisoformat(cur["built"].replace("Z", "+00:00"))
        if datetime.now(UTC) - t < timedelta(days=CACHE_DAYS):
            return cur
    rivers, comids = {}, {}
    for river, sites in GAUGE_TABLE.items():
        for site, name in sites:
            try:
                d = nldi_get(f"{NLDI}/nwissite/USGS-{site}")
            except RateLimited:
                return cur              # NLDI's allowance is spent: keep the current table, rebuild next run
            except requests.RequestException:
                d = None
            f = ((d or {}).get("features") or [None])[0]
            if not f:
                continue
            p = f.get("properties") or {}
            x, y = (f.get("geometry") or {}).get("coordinates", [None, None])[:2]
            row = {"site": site, "id": f"USGS-{site}", "name": p.get("name") or name, "lat": y, "lon": x,
                   "comid": p.get("comid")}
            rivers.setdefault(river, []).append(row)
            if p.get("comid"):
                comids[int(p["comid"])] = row
    try:
        attrs = fetch_attrs(sorted(comids))
    except (requests.RequestException, ValueError):
        attrs = {}
    for c, row in comids.items():
        a = attrs.get(c) or {}
        row["qe_ma_cfs"], row["totdasqkm"], row["tidal"] = a.get("qe_ma"), a.get("totdasqkm"), a.get("tidal")
    out = {"built": now_iso(), "source": "research/hydrography/report.md 2.7 (gauge table); NLDI nwissite; "
                                         "EPA NHDPlus V2.1 MapServer layer 2 (qe_ma, totdasqkm at the gauge COMID)",
           "rivers": rivers}
    write_json(GAUGES_BY_RIVER, out)
    return out


def refresh_flows() -> dict:
    """Latest discharge (00060) for every NE gauge, one OGC API call per state."""
    prev = read_json(GAUGES_LATEST) or {}
    sites = dict(prev.get("sites") or {})
    errors = {}
    for st, fips in STATE_FIPS.items():
        try:
            r = session().get(OGC_LATEST, params={
                "f": "json", "state_code": fips, "parameter_code": "00060", "limit": 10000, "skipGeometry": "true",
                "properties": "monitoring_location_id,parameter_code,time,value,unit_of_measure"}, timeout=120)
            r.raise_for_status()
            for f in r.json().get("features", []):
                p = f.get("properties") or {}
                if p.get("parameter_code") != "00060":
                    continue
                try:
                    v = float(p.get("value"))
                except (TypeError, ValueError):
                    continue
                sites[p["monitoring_location_id"]] = {"value": v, "unit": p.get("unit_of_measure"), "time": p.get("time")}
        except Exception as e:
            errors[st] = f"{type(e).__name__}: {e}"[:200]
    out = {"fetched_at": now_iso(), "source": OGC_LATEST + " (parameter 00060)", "errors": errors, "sites": sites}
    write_json(GAUGES_LATEST, out)
    return out


def flow_for(reach: dict, gauges: dict, latest: dict, now: datetime | None = None) -> dict:
    """The relative discharge for a reach: nearest gauge on the same river with a reading in the
    last 6 hours, else NHDPlus mean annual (q_ratio 1)."""
    now = now or datetime.now(UTC)
    river = reach.get("river")
    best, rejected = None, []
    for g in ((gauges or {}).get("rivers") or {}).get(river or "", []):
        reading = ((latest or {}).get("sites") or {}).get(g["id"])
        if not reading or not usable(g.get("qe_ma_cfs")) or g.get("lat") is None:
            continue
        v, unit = reading.get("value"), str(reading.get("unit") or "ft^3/s").lower().replace(" ", "")
        if not usable(v) or unit not in ("ft^3/s", "ft3/s", "cfs"):
            rejected.append(f"USGS {g['site']} reading {v!r} {reading.get('unit') or ''} not usable")
            continue
        try:
            t = datetime.fromisoformat(str(reading["time"]).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue
        if t.tzinfo is None or t > now + timedelta(hours=1) or now - t > timedelta(hours=6):
            continue
        d = seg_km([[reach["lon"], reach["lat"]], [g["lon"], g["lat"]]]) if reach.get("lat") is not None else 0
        if best is None or d < best[0]:
            best = (d, g, reading)
    if best:
        d, g, reading = best
        return {"q_ratio": reading["value"] / g["qe_ma_cfs"], "gauge": g["id"], "gauge_name": g["name"],
                "flow_cfs": reading["value"], "flow_time": reading["time"], "gauge_km": round(d, 1),
                "flow_basis": f"USGS {g['site']} discharge {reading['value']:g} cfs at {reading['time']}"}
    note = "no current usable gauge reading on this river: NHDPlus mean annual flow (qe_ma) used"
    if rejected:
        note += " (" + "; ".join(rejected[:3]) + ")"
    return {"q_ratio": 1.0, "gauge": None, "gauge_name": None, "flow_cfs": None, "flow_time": None, "gauge_km": None,
            "flow_basis": note}


# ---------------------------------------------------------------- main

def run_traces(cands: list[dict], cap: float, budget: Budget, force: bool = False,
               log=print) -> tuple[dict, dict[str, dict]]:
    """Trace the due outfalls of `cands` in plan() order within `budget` (force: every candidate, cache
    ignored). Returns (the run record, the cached records after the run)."""
    now = datetime.now(UTC)
    cached = load_reaches()
    todo, touch = (list(cands), []) if force else plan(cands, cached, now)
    for c, d in touch:                       # water, name, sources or kind changed: no request needed
        d.update({f: c[f] for f in META_FIELDS if f in c})
        write_json(REACH_DIR / f"{c['key']}.json", d)
    before = Counter(STATS)
    MODE.update(walk=False, nldi_low_until=0.0)
    t0 = time.monotonic()
    log(f"reaches: {len(cands)} outfalls to keep traced, {len(todo)} due (cap {cap:g} km; "
        f"budget {budget.nav or 'no limit'} navigation requests, {budget.seconds or 'no limit'} s)")
    done, outcomes, navs, stopped, errs = 0, Counter(), Counter(), None, 0
    for i, c in enumerate(todo, 1):
        stopped = budget.stop()
        if not stopped and errs >= SERVICE_ERRORS:
            stopped = f"{errs} traces in a row failed on a service error (left for a later run)"
        if stopped:
            break
        path = REACH_DIR / f"{c['key']}.json"
        prev = cached.get(c["key"]) or read_json(path) or {}
        try:
            rec = trace(c, cap, prev)
        except RateLimited as e:
            stopped = f"NLDI rate limit ({e})"[:200]
            break
        budget.traced += 1
        if rec["cut_reason"] == "no_trace":
            rec["failures"] = int(prev.get("failures") or 0) + 1 if prev.get("cut_reason") == "no_trace" else 1
        if rec["cut_reason"] == "no_trace" and outcome(prev) in ("traced", "tidal_at_outfall", "lake_at_outfall"):
            # a transient failure never replaces a good cached trace (or a tidal / lake answer); retried tomorrow
            prev["last_attempt"] = {"at": rec["fetched_at"], "error": rec["error"]}
            prev["fetched_at"] = (datetime.now(UTC) - timedelta(days=CACHE_DAYS - RETRY_FAIL_DAYS)).isoformat()
            prev.update({f: c[f] for f in (*META_FIELDS, "lat", "lon") if f in c})    # retried by age, not as moved
            rec = prev
        write_json(path, rec)
        cached[c["key"]] = rec
        done += 1
        outcomes[outcome(rec)] += 1
        navs[rec.get("navigation") or "none"] += 1
        err = str(rec.get("error") or "") if rec.get("cut_reason") == "no_trace" else ""
        errs = errs + 1 if err and not err.startswith(DETERMINISTIC_ERRORS) else 0
        log(f"  [{i}/{len(todo)}] {c['key']} {rec['method']} {rec['cut_reason']} {rec['length_km']} km"
            f"{' ' + rec['error'] if rec.get('error') else ''}")
    used = Counter(STATS) - before
    run = {"at": now_iso(), "seconds": round(time.monotonic() - t0, 1), "due": len(todo), "traced": done,
           "left": len(todo) - done, "outcomes": dict(outcomes), "navigation": dict(navs),
           "metadata_updates": len(touch),
           "requests": {"nldi": used["nldi"], "nldi_navigation": used["nav"], "navigation_reused": used["nav_memo"],
                        "epa": used["epa"], "retries": used["retries"], "rate_limited": used["rate_limited"]},
           "nav_remaining": RATE.get("nav_remaining"), "nldi_remaining": RATE.get("nldi_remaining"),
           "stopped": stopped or ("done" if done == len(todo) else None)}
    log(f"reaches: traced {done} of {len(todo)} due in {run['seconds']:g} s ({dict(navs)}); NLDI {used['nldi']} "
        f"requests ({used['nav']} navigation, {used['nav_memo']} reused), EPA {used['epa']}; "
        f"{'stopped: ' + stopped if stopped else 'all due traced'}")
    return run, cached


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--flows", action="store_true", help="only refresh gauge readings")
    ap.add_argument("--no-flows", action="store_true", help="trace only (no gauge refresh)")
    ap.add_argument("--limit", type=int, default=0, help="at most this many traces")
    ap.add_argument("--requests", type=int, default=DEFAULT_NAV_BUDGET,
                    help=f"at most this many NLDI navigation requests (default {DEFAULT_NAV_BUDGET}; 0 no limit)")
    ap.add_argument("--seconds", type=float, default=DEFAULT_SECONDS,
                    help=f"stop tracing after this many seconds (default {DEFAULT_SECONDS}; 0 no limit)")
    ap.add_argument("--reserve", type=int, default=NAV_RESERVE,
                    help=f"stop when NLDI's navigation allowance left this hour is under this (default {NAV_RESERVE})")
    ap.add_argument("--plants", action="store_true", help="also trace treatment-plant outfalls (after the CSO ones)")
    ap.add_argument("--outfall", help="PERMIT:OUTFALL, trace just this one (ignores the cache)")
    a = ap.parse_args()
    if not a.flows:
        lock = TraceLock()
        if not lock.acquire():
            print("reaches: another run is tracing (data/build/reaches.lock); no traces this run", flush=True)
        else:
            try:
                cap = cap_km()
                REACH_DIR.mkdir(parents=True, exist_ok=True)
                live = live_states()
                skipped: dict[str, dict] = {}
                cands = candidate_outfalls(live=live, skipped=skipped, plants=a.plants or None)
                log = lambda m: print(m, flush=True)       # noqa: E731
                if a.outfall:
                    permit, oid = a.outfall.split(":", 1)
                    one = [c for c in cands if c["key"] == reach_key(permit, oid)] or [
                        {"key": reach_key(permit, oid), "permit": permit, "outfall": oid, "water_slug": None,
                         "lat": None, "lon": None, "name": None, "sources": ["cli"]}]
                    run, _ = run_traces(one, cap, Budget(0, 0, a.reserve), force=True, log=log)
                else:
                    retired = retire_closed(skipped, cands)
                    if retired:
                        print(f"reaches: {len(retired)} cached traces of closed outfalls moved to {RETIRED_DIR.name}/: "
                              f"{', '.join(retired[:10])}{' ...' if len(retired) > 10 else ''}", flush=True)
                    run, cached = run_traces(cands + event_points(), cap,
                                             Budget(a.requests, a.seconds, a.reserve, a.limit), log=log)
                    run["retired"] = len(retired)
                    idx = write_index(cands, skipped, cached, live, run)
                    print(f"reaches: outfalls in live states {idx['counts']['total']}", flush=True)
                build_gauges()
            finally:
                lock.release()
    if not a.no_flows:
        f = refresh_flows()
        print(f"flows: {len(f['sites'])} gauges with discharge; errors {f['errors'] or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
