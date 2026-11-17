"""Shoreline stretches on the Great Lakes (data/rules.json reach.shoreline; decision of 2026-11-04: the Great Lakes are
modelled like rivers, not filled whole).

A report from an outfall on a shoreline lake never colours the lake's outline. The outfall's point gets a stretch of
shoreline instead, walked along the lake's outline up to each_way_km in both directions (alongshore currents on the
Great Lakes are driven by the wind and reverse every few days; the distance and its evidence are in the rule's
rationale and source), carried as a reach record (build/reaches.py writes it to data/build/reaches/ beside the
river traces, model "shoreline") with the lake as its water, the same lake's records in the other states it touches,
and those states. The status build colours the stretch and lists the report on the lake (build/status.py); the export
draws the lake as an outline (display "outline", stretch_model "shoreline") and the stretch in reaches.geojson.

Which lakes: shoreline_entry(): a lake or reservoir whose wikidata or gnis_id the rule lists, or whose name it lists at
name_min_area_km2 or more, or (min_area_km2 set: the size rule, size_entry) any record of min_area_kinds (default lake
and reservoir; bay and sound by the rules file) that large, by its area_km2 or else its outline's measured area, except
a bay or sound in a state an ocean entry covers. Under the size rule a lake or reservoir whose report can start no
stretch keeps its whole-water colour (build/status.py SHORE_WHOLE). An entry with `kinds` also applies to
records of those kinds, and one with `states` only in those states: Puget Sound (kind "sound", WA; Washington's go-live
gates, 2026-11-06), whose stretch is walked on its own outline like a lake's and worded for a sound ("sound": True on
the entry returned, reach records and the export). San Francisco Bay (kind "bay", CA; California's go-live gates,
2026-11-06) is walked the same way and worded as a bay ("bay": True); its entry's open_m cuts its Census water at the
Golden Gate (build/reaches.py cut_at_mouths).

The shore: a lake record's outline is not all shore. The Census-cut Michigan records run along the state and
international lines in the lake, and the NHDPlus Great Lakes polygons have straight edges on whole degrees where
their pieces end: a record of several pieces is dissolved first (stretch()), so a seam between two pieces is never an
end; a piece's outer edge away from land still is. An edge is shore when its midpoint lies within shore_m of land (the Census Bureau's 2023 1:500,000
state outlines, cb_2023_us_state_500k, which end at the shore). The walk crosses a run of edges away from land shorter
than gap_km (a river mouth, a breakwall) and stops at the start of a longer one (a state or international line, a tile
edge), and at each_way_km. Without land outlines (land=None) every edge is shore: only for outlines that are all shore.

A lake record with no outline of its own (openboatlaunch's Great Lakes records keep theirs in openboatlaunch's files,
which the hourly run does not have) is walked on its state's waters in the lake: build/reaches.py census_lake_outline
(the TIGER/Line state polygon, which runs through the lake along the state and international lines, less the
cartographic land). Where a stretch ends on another shoreline lake record (the next state's, or Lake Michigan beyond
NHD's line in the Straits of Mackinac), build/reaches.py goes on along that record's shore (onward()).

The open ocean (reach.shoreline.oceans; Florida's go-live gates, 2026-11-04): a report on the Atlantic Ocean or the Gulf of
Mexico (Gulf of America) colours a stretch of the state's ocean shore at its point, never the ocean. An ocean record's
own outline is the ocean, not the state's shore, so the walk is on the state's coastal waters near the point
(build/reaches.py ocean_outline: the TIGER/Line state polygon, which reaches 3 nautical miles out on the Atlantic and 9 on
Florida's Gulf coast, less the cartographic land, opened by ocean_open_m so that an inlet or pass narrower than twice
that is closed and the walk follows the open coast, not the lagoon behind a barrier island), and only the part of
those waters that reaches the state's offshore line. A bay or sound that opens wider than that to the sea is part of
those waters, and the walk follows its shore: build/reaches.py ocean_waters_along adds the records it runs along to the
stretch's waters. The distance and its evidence are in the rule's ocean rationale.

Pure geometry: no network. Coordinates are lon/lat; the work is in a local equirectangular projection (metres).
"""
from __future__ import annotations

import math

import numpy as np

from common import same_gnis

KINDS = {"lake", "reservoir"}
# the open ocean (data/rules.json reach.shoreline.oceans, 2026-11-04: Florida's Atlantic Ocean and Gulf records): an
# ocean record is kept as a bay or sound by openboatlaunch ("Atlantic Ocean", kind bay), so these kinds qualify too,
# but only for a record the rule's ocean entries name (by wikidata or by one of the entry's names, exactly)
OCEAN_KINDS = {"bay", "sound", "sea", "ocean", "lake", "reservoir"}
# The size rule (owner, 2026-11-16, docs/analysis/2026-11-15-shoreline-threshold-review.md in the site repository):
# with min_area_km2 set, a record of one of min_area_kinds at least that large is a shoreline water too. min_area_kinds
# defaults to lake and reservoir (the reading before the kinds list existed); the rules file adds "bay" and "sound" to
# bring those under the rule, with no code change. Neither key is in data/rules.json while the rule is off
# (min_area_km2 null), so the file, and everything that hashes it, reads as before. The record's area is its own
# area_km2, else the area measured from its outline (outline_area_km2, put on the record by build/status.py
# outline_areas only while the rule is on), with where the figure came from.
SIZE_KINDS = ("lake", "reservoir")
DEFAULTS = {"each_way_km": 20.0, "shore_m": 500.0, "gap_km": 3.0, "snap_km": 5.0, "name_min_area_km2": 100.0,
            "min_area_km2": None, "min_area_kinds": list(SIZE_KINDS), "min_mean_width_km": None, "min_ring_km": None,
            "lakes": [], "oceans": [], "ocean_open_m": 1000.0, "ocean_tie_offshore_km": None}
OUTLINE_AREA = "outline_area_km2"      # the record key status.with_outline_areas fills for a record with no area_km2
# the outline's mean width (twice the area over the length of every shore ring, islands included), which
# status.with_outline_areas puts on a crossing lake or reservoir only while min_mean_width_km is set; and the mark it
# puts on a bay or sound with no outline here while the size rule takes those kinds
OUTLINE_WIDTH = "outline_mean_width_km"
NO_OUTLINE = "no_outline_here"
FILL_KINDS = {"lake", "reservoir", "pond"}
STATE_NEAR_M = 2_000          # a stretch point this close to a state's land touches that state
MODEL = "shoreline"
STOP_LIMIT = "shoreline_limit"     # the walk reached each_way_km
STOP_END = "shoreline_end"         # the shore ends here (a state or international line, the edge of the record)


class NoShore(Exception):
    """The point is farther than snap_km from any shore of the lake: no stretch."""


def rule(rules: dict | None) -> dict:
    """data/rules.json reach.shoreline with the defaults filled in ({} rules: the defaults, no lakes)."""
    r = ((rules or {}).get("reach") or {}).get("shoreline") or {}
    return {**DEFAULTS, **{k: v for k, v in r.items() if not str(k).startswith("_")}}


def _norm(s) -> str:
    return " ".join("".join(ch if ch.isalnum() else " " for ch in str(s or "").lower()).split())


def shoreline_entry(w: dict | None, r: dict) -> dict | None:
    """The rule's lake entry this water record is ({name, ...}), a synthetic {"name": <its name>} when only
    min_area_km2 makes it one, or None: not a shoreline lake."""
    if not w:
        return None
    if w.get("kind") in OCEAN_KINDS:
        for e in r.get("oceans") or []:
            names = {_norm(x) for x in [e.get("name"), *(e.get("names") or [])] if x}
            if e.get("states") and str(w.get("state") or "").upper() not in {str(x).upper() for x in e["states"]}:
                continue            # the entry lists the states it is applied in (the others keep today's handling)
            if (e.get("wikidata") and w.get("wikidata") == e["wikidata"]) or _norm(w.get("name")) in names:
                return {**e, "ocean": True}
    kind = w.get("kind")
    area = w.get("area_km2")
    area = float(area) if isinstance(area, (int, float)) else None
    for e in r.get("lakes") or []:
        # an entry may name other kinds it applies to (Puget Sound, kind "sound"; San Francisco Bay, kind "bay";
        # 2026-11-06) and the states it is
        # applied in; a lake or reservoir qualifies as before
        extra = {str(k) for k in e.get("kinds") or []}
        if kind not in KINDS | extra:
            continue
        if e.get("states") and str(w.get("state") or "").upper() not in {str(x).upper() for x in e["states"]}:
            continue
        hit = e if kind in KINDS else {**e, "bay": True} if kind == "bay" else {**e, "sound": True}
        if e.get("wikidata") and w.get("wikidata") == e["wikidata"]:
            return hit
        if same_gnis(e.get("gnis_id"), w.get("gnis_id")):
            return hit
        floor = r.get("name_min_area_km2")
        if _norm(w.get("name")) == _norm(e.get("name")) and area is not None and (floor is None or area >= floor):
            return hit
    return size_entry(w, r)


def size_on(r: dict) -> bool:
    """Whether the size rule is in force: min_area_km2 set and at least one kind it may apply to (an empty or
    all-rejected min_area_kinds is the rule off, never an error)."""
    return r.get("min_area_km2") is not None and bool(size_kinds(r))


def drawable(rec: dict | None) -> bool:
    """Whether a cached stretch record can be drawn: a segment with two distinct points or more. A record that cannot
    is no stretch, and the report keeps the whole-water colour (Astra review 2026-11-16, finding 5)."""
    return any(len({(round(float(x), 6), round(float(y), 6)) for x, y in (sg.get("coords") or [])}) >= 2
               for sg in (rec or {}).get("segments") or [])


def size_kinds(r: dict) -> set[str]:
    """The record kinds the size rule applies to (min_area_kinds; default lake and reservoir). Only lake, reservoir,
    pond, bay and sound can be named: a river is never a shoreline water."""
    k = r.get("min_area_kinds")
    return ({str(x) for x in k} & SIZE_RULE_KINDS) if isinstance(k, (list, tuple)) else set(SIZE_KINDS)


SIZE_RULE_KINDS = {"lake", "reservoir", "pond", "bay", "sound"}


def _area_words(km2: float) -> str:
    mi2 = km2 / 2.589988
    return f"{mi2:,.0f} square miles ({km2:,.0f} square kilometres)"


def _miles(km: float) -> str:
    return f"{km * 0.621371:,.0f}"


def _kind_list(kinds: set[str]) -> str:
    order = [k for k in ("lake", "reservoir", "pond", "bay", "sound") if k in kinds]
    words = [f"{k}s" for k in order]
    return words[0] if len(words) == 1 else f"{', '.join(words[:-1])} and {words[-1]}"


def size_texts(r: dict) -> dict:
    """The public words of the size rule while it is on, for out/rules.json (export/build.py shoreline_rules): "doc"
    and "rationale" sentences that follow the rule's own doc and rationale. {} while it is off. The 20 km distance is
    the Great Lakes' and the ocean's (the rule's source and ocean_source); a large lake gets it as the same cautious
    distance, not as a measurement there."""
    if not size_on(r):
        return {}
    kinds = size_kinds(r)
    area = _area_words(float(r["min_area_km2"]))
    each = float(r.get("each_way_km") or 20)
    filled = sorted(kinds & {"lake", "reservoir", "pond"})
    tidal = sorted(kinds & {"bay", "sound"})
    doc = f"Other {_kind_list(kinds)} of {area} or more are drawn the same way."
    if filled:
        doc += (f" A report on such a {' or '.join(filled)} that cannot be placed on the shore colours the whole water, "
                f"as on a smaller one.")
    rationale = (f"We draw other {_kind_list(kinds)} of {area} or more the same way. The {_miles(each)}-mile "
                 f"({each:g}-kilometre) distance comes from studies on the Great Lakes and on ocean shores; on these "
                 f"smaller waters we apply it as a cautious distance, not a measurement. Where a water's whole "
                 f"shoreline is shorter than {_miles(2 * each)} miles ({2 * each:g} kilometres), the stretch covers all "
                 f"of it.")
    if filled:
        rationale += (f" A report on such a {' or '.join(filled)} that we cannot place on the shore colours the "
                      f"whole water, as on a smaller {filled[0]}.")
    floor = r.get("min_mean_width_km")
    if filled and floor is not None:
        fl = float(floor)
        rationale += (f" {_kind_list(set(filled)).capitalize()} narrower than {fl * 0.621371:.1f} mile ({fl:g} "
                      f"kilometres) on average, such as reservoirs that fill a river valley, are still coloured as a "
                      f"whole: a stretch along one bank would leave the nearby opposite bank grey.")
    if tidal:
        rationale += (f" On a {' or '.join(tidal)}, such a report is listed on the water's page, and its outlets "
                      f"are marked on the map. Where we draw the ocean shore, a {' or '.join(tidal)} open to the sea is "
                      f"followed by that stretch instead.")
    return {"doc": doc, "rationale": rationale}


def ocean_states(r: dict) -> set[str]:
    """The states an ocean entry is applied in (reach.shoreline.oceans[].states)."""
    return {str(s).upper() for e in r.get("oceans") or [] for s in e.get("states") or []}


def is_sea_record(w: dict, r: dict) -> bool:
    """A bay or sound record that is an ocean or a sea (openboatlaunch holds them as bays or sounds: "North Atlantic
    Ocean", "Bering Sea"): named as an ocean entry names one, in any state, or named "... Ocean" or "... Sea". The
    size rule leaves them to the ocean rule."""
    n = _norm(w.get("name"))
    names = {_norm(x) for e in r.get("oceans") or [] for x in [e.get("name"), *(e.get("names") or [])] if x}
    return n in names or n.endswith(" ocean") or n.endswith(" sea") or n in ("ocean", "sea")


def record_area(w: dict) -> tuple[float | None, str | None]:
    """(area in km2, where it came from: "record" or "outline"): the record's own area_km2, else the area measured
    from its outline (OUTLINE_AREA, filled by build/status.py outline_areas while the size rule is on), else none."""
    a = w.get("area_km2")
    if isinstance(a, (int, float)) and not isinstance(a, bool):
        return float(a), "record"
    a = w.get(OUTLINE_AREA)
    if isinstance(a, (int, float)) and not isinstance(a, bool):
        return float(a), "outline"
    return None, None


def size_entry(w: dict, r: dict) -> dict | None:
    """The synthetic entry of a record the size rule makes a shoreline water, or None. A bay or sound in a state where
    an ocean entry is applied (Florida and California today) is left out: there the ocean walk already follows the
    shore of every bay or sound that opens more than about 2 km to the sea (build/reaches.py ocean_outline and
    ocean_waters_along), and a second model on the same shore would draw it twice."""
    if not size_on(r):
        return None
    kind = w.get("kind")
    if kind not in size_kinds(r):
        return None
    if kind in ("bay", "sound") and str(w.get("state") or "").upper() in ocean_states(r):
        return None
    if kind in ("bay", "sound") and (w.get(NO_OUTLINE) or is_sea_record(w, r)):
        return None             # no outline here: markers, as before; an ocean or sea record is the ocean rule's
    area, basis = record_area(w)
    if area is None or area < float(r["min_area_km2"]):
        return None
    floor = r.get("min_mean_width_km")
    width = w.get(OUTLINE_WIDTH)
    if (kind in FILL_KINDS and floor is not None and isinstance(width, (int, float)) and not isinstance(width, bool)
            and width < float(floor)):
        return None             # long and narrow (a reservoir in a drowned river valley): filled whole, as before
    hit = {"name": w.get("name"), "size_rule": True, "area_km2": round(area, 3), "area_basis": basis}
    if kind == "bay":
        hit["bay"] = True
    elif kind == "sound":
        hit["sound"] = True
    return hit


def is_size_rule(w: dict | None, r: dict) -> bool:
    """Whether the record is a shoreline water by the size rule alone (not listed by id or name, not an ocean)."""
    return bool((shoreline_entry(w, r) or {}).get("size_rule"))


def is_shoreline(w: dict | None, r: dict) -> bool:
    return shoreline_entry(w, r) is not None


def is_ocean(w: dict | None, r: dict) -> bool:
    """Whether the record is one of the rule's open-ocean waters (reach.shoreline.oceans)."""
    return bool((shoreline_entry(w, r) or {}).get("ocean"))


def shoreline_slugs(waters: dict, r: dict) -> set[str]:
    return {s for s, w in (waters or {}).items() if is_shoreline(w, r)}


def lake_waters(slug: str, states: list[str], waters: dict, r: dict) -> list[str]:
    """The outfall's lake record first, then the same lake's records (same rule entry) in the other states the
    stretch touches, by slug."""
    e = shoreline_entry(waters.get(slug), r)
    if e is None:
        return [slug]
    name = _norm(e.get("name"))
    want = {str(s).upper() for s in states}
    rest = sorted(s for s, w in waters.items() if s != slug and str(w.get("state") or "").upper() in want
                  and shoreline_entry(w, r) is not None and _norm(shoreline_entry(w, r).get("name")) == name
                  # a water under the size rule has no entry of its own: a record of the same name is the same water
                  # only where their boxes meet (Lake Champlain's Vermont and New York records; not two Clear Lakes)
                  and (not e.get("size_rule") or _boxes_meet(waters[slug].get("bbox"), w.get("bbox"))))
    return [slug, *rest]


def _boxes_meet(a, b) -> bool:
    try:
        return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])
    except (TypeError, IndexError):
        return False


# ---------------------------------------------------------------- geometry

def _k(lat0: float) -> np.ndarray:
    return np.array([111_320.0 * math.cos(math.radians(lat0)), 110_574.0])


def _rings(geom) -> list[np.ndarray]:
    """Every exterior and interior ring of a (multi)polygon, as closed lon/lat arrays."""
    out = []
    for p in getattr(geom, "geoms", [geom]):
        if p.geom_type != "Polygon" or p.is_empty:
            continue
        for ring in [p.exterior, *p.interiors]:
            c = np.asarray(ring.coords, dtype=float)[:, :2]
            if len(c) >= 4:
                out.append(c)
    return out


def _seg_dist(p: np.ndarray, a: np.ndarray, b: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(distance from p to each segment a[i]-b[i], the fraction along it of the nearest point)."""
    d = b - a
    L2 = (d ** 2).sum(axis=1)
    t = np.where(L2 > 0, ((p - a) * d).sum(axis=1) / np.where(L2 > 0, L2, 1), 0.0).clip(0, 1)
    q = a + d * t[:, None]
    return np.hypot(*(q - p).T), t


class _Shore:
    """Shore flags of a ring's edges (metres), computed on demand against the land near the point."""

    def __init__(self, ring_m: np.ndarray, land_m, shore_m: float):
        self.c, self.land, self.shore_m, self.memo = ring_m, land_m, shore_m, {}

    def __call__(self, i: int) -> bool:
        if self.land is None:
            return True
        if i not in self.memo:
            from shapely.geometry import Point
            m = (self.c[i] + self.c[i + 1]) / 2
            self.memo[i] = self.land.distance(Point(m[0], m[1])) <= self.shore_m
        return self.memo[i]


def _walk(c: np.ndarray, i: int, p: np.ndarray, step: int, limit_m: float, gap_m: float, shore) -> tuple[list, float, str]:
    """Walk ring c (closed, metres) from point p on edge i, forward (step 1) or backward (-1), at most limit_m.
    Returns (points from p, metres walked, stop reason)."""
    n = len(c) - 1
    path, done = [p], 0.0
    pending, pend_m = [], 0.0
    cur = p
    j = i
    visited = 0
    while visited <= n:
        nxt = c[j + 1] if step > 0 else c[j]
        edge = float(np.hypot(*(nxt - cur)))
        on_shore = shore(j)
        left = limit_m - done - pend_m
        if edge >= left:
            if not on_shore:            # the limit falls inside a run away from land: end before that run
                return path, done, STOP_END if pend_m + edge > gap_m else STOP_LIMIT
            if pending:
                path.extend(pending)
                done += pend_m
                pending, pend_m = [], 0.0
            f = left / edge if edge > 0 else 0.0
            end = cur + (nxt - cur) * f
            path.append(end)
            return path, done + left, STOP_LIMIT
        if on_shore:
            if pending:
                path.extend(pending)
                done += pend_m
                pending, pend_m = [], 0.0
            path.append(nxt)
            done += edge
        else:
            pending.append(nxt)
            pend_m += edge
            if pend_m > gap_m:
                return path, done, STOP_END
        cur = nxt
        j = (j + step) % n
        visited += 1
    return path, done, STOP_END


def stretch(lon: float, lat: float, lake_geom, land=None, each_way_km: float = 20.0, shore_m: float = 500.0,
            gap_km: float = 3.0, snap_km: float = 5.0, land_states: dict | None = None,
            min_ring_km: float | None = None) -> dict:
    """The shoreline stretch at (lon, lat) on lake_geom (a shapely (multi)polygon, lon/lat). land: the land near
    the lake (a shapely geometry, lon/lat) or None (every edge is shore). land_states: {state: land geometry}
    for the states the stretch touches (else none are named). Returns {"sides": [{"coords", "km", "stop"} x2],
    "snap_m", "length_km", "states"}, and "islets" ([{"coords", "km"}], only with min_ring_km). NoShore when no shore
    edge lies within snap_km of the point.

    min_ring_km (reach.shoreline.min_ring_km; None: the walk as before, on the nearest ring whatever its size): a ring
    shorter than this (an islet beside the outfall) is not walked alone. The stretch starts on the nearest ring at
    least that long within snap_km, and every shorter ring nearer the point than that start is marked whole as well
    ("islets"). When no ring that long lies within snap_km, the nearest ring is walked as before."""
    import shapely
    from shapely.geometry import box
    from shapely.ops import unary_union
    if len(getattr(lake_geom, "geoms", [])) > 1:      # NHD pieces sharing a seam: one outline (the seam is no shore end)
        lake_geom = unary_union([g.buffer(0) for g in lake_geom.geoms])
    k = _k(lat)
    p = np.array([lon, lat]) * k
    reach_m = (each_way_km + gap_km) * 1000 + snap_km * 1000
    near_box = box(p[0] - reach_m, p[1] - reach_m, p[0] + reach_m, p[1] + reach_m)
    land_m = None
    if land is not None:
        land_m = shapely.transform(land, lambda xy: xy * k)
        land_m = land_m.intersection(near_box.buffer(shore_m * 2))
    best = None
    found = []              # (distance, ring in metres, edge, point on it, shore flags, ring length) of each ring
    for c in _rings(lake_geom):
        cm = c * k
        a, b = cm[:-1], cm[1:]
        d, t = _seg_dist(p, a, b)
        close = np.nonzero(d <= snap_km * 1000)[0]
        if not len(close):
            continue
        shore = _Shore(cm, land_m, shore_m)
        for i in close[np.argsort(d[close])]:
            if shore(int(i)):
                hit = (float(d[i]), cm, int(i), a[i] + (b[i] - a[i]) * t[i], shore)
                if best is None or d[i] < best[0]:
                    best = hit
                if min_ring_km is not None:
                    found.append((*hit, float(np.hypot(*np.diff(cm, axis=0).T).sum())))
                break
    if best is None:
        raise NoShore(f"no shore of the water within {snap_km:g} km of the point")
    islets = []
    if min_ring_km is not None:
        big = [f for f in found if f[5] >= float(min_ring_km) * 1000]
        if big:
            start = min(big, key=lambda f: f[0])
            best = start[:5]
            islets = [{"coords": [[round(float(x), 6), round(float(y), 6)] for x, y in f[1] / k], "km": round(f[5] / 1000, 3)}
                      for f in sorted(found, key=lambda f: f[0]) if f[5] < float(min_ring_km) * 1000 and f[0] < start[0]]
    snap_m, cm, i, q, shore = best
    ring_m = float(np.hypot(*np.diff(cm, axis=0).T).sum())
    limit = min(each_way_km * 1000, ring_m / 2)
    sides = []
    for step in (1, -1):
        pts, m, why = _walk(cm, i, q, step, limit, gap_km * 1000, shore)
        if why == STOP_LIMIT and m < each_way_km * 1000 - 1 and limit < each_way_km * 1000:
            why = STOP_END                  # a small island: the ring is shorter than both walks
        ll = [[round(float(x), 6), round(float(y), 6)] for x, y in (np.asarray(pts) / k)]
        dedup = [ll[0]] + [pt for prev, pt in zip(ll, ll[1:]) if pt != prev]
        sides.append({"coords": dedup if len(dedup) > 1 else [], "km": round(m / 1000, 3), "stop": why})
    states = []
    if land_states:
        from shapely.geometry import MultiPoint
        # a side with no length (the walk starts where the shore ends) has no coordinates
        pts = MultiPoint([pt for s in sides if s["coords"] for pt in (np.asarray(s["coords"]) * k).tolist()]
                         or [p.tolist()])
        for st, g in sorted(land_states.items()):
            gm = shapely.transform(g, lambda xy: xy * k)
            if gm.distance(pts) <= STATE_NEAR_M:
                states.append(st)
    return {"sides": sides, "snap_m": round(snap_m), "length_km": round(sum(s["km"] for s in sides), 3),
            "states": states, **({"islets": islets} if islets else {})}


ONWARD_M = 300          # a stretch that ends this close to another shoreline lake record's outline goes on along it


def onward(lon: float, lat: float, lake_geom, land, km: float, walked: list, shore_m: float = 500.0,
           gap_km: float = 3.0, land_states: dict | None = None) -> dict | None:
    """The shore of another lake record that a stretch ends on (an end at a state line where the next state's
    record of the same lake begins, or at the straight line NHD draws between Lake Michigan and Lake Huron in the
    Straits of Mackinac): the side of a stretch from the end point on lake_geom that runs away from the shore
    already walked (walked: lon/lat lines), at most km. {"coords", "km", "stop", "states"} or None (no such shore
    within ONWARD_M of the point, or nothing new)."""
    from shapely.geometry import LineString
    try:
        r = stretch(lon, lat, lake_geom, land, km, shore_m, gap_km, ONWARD_M / 1000, land_states=land_states)
    except NoShore:
        return None
    k = _k(lat)
    done = [LineString(np.asarray(c, dtype=float) * k) for c in walked if len(c) >= 2]
    best, best_new = None, 0.0
    for side in r["sides"]:
        if len(side["coords"]) < 2:
            continue
        line = LineString(np.asarray(side["coords"], dtype=float) * k)
        new = line.length
        for d in done:          # the part of the side that is not the shore already walked
            new -= line.intersection(d.buffer(shore_m / 2)).length
        if new > best_new:
            best, best_new = side, new
    if best is None or best_new < 100 or best_new < 0.5 * best["km"] * 1000:
        return None
    return {**best, "states": r["states"]}

