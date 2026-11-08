"""The status build's run-time fixes (docs/refresh-time-brief-2026-11-07.md), each with the same result as before:
reach_waters tests a reach's river records by box once per reach (it took 600 of status's 780 s an hour), the
placement stamp leaves out waters_from_nhd's hourly bookkeeping (no hourly run reused a placement), and a water's event
list breaks ties by event id (the order followed Python's hash seed). Run from pipeline/: python -m pytest tests -q
"""
from __future__ import annotations

import random

from build import status as S


def reach_waters_before(reach: dict, waters: dict) -> list[str]:
    """build.status.reach_waters as it was before the box prefilter (7023088), the reference."""
    from shapely.geometry import Point
    rivers = [(slug, w) for slug, w in waters.items() if w.get("kind") in S.RIVER_KINDS and w.get("bbox")]
    found = []
    for sg in reach.get("segments") or []:
        c = sg["coords"][len(sg["coords"]) // 2]
        pad = 0.01
        gnis = S.norm_name(sg.get("gnis_name") or "")
        for slug, w in rivers:
            b = w["bbox"]
            if slug in found:
                continue
            own = sg.get("comid") is not None and S._comid_in(sg["comid"], w)
            if gnis and not own and S.norm_name(w.get("name") or "") != gnis:
                continue
            if not (b[0] - pad <= c[0] <= b[2] + pad and b[1] - pad <= c[1] <= b[3] + pad):
                continue
            g = S.water_geometry(slug, waters)
            if g is not None and g.distance(Point(c[0], c[1])) * 111_320 <= S.REACH_WATER_M:
                found.append(slug)
    return found


def line(x0, y0, x1, y1):
    return {"type": "LineString", "coordinates": [[x0, y0], [x1, y1]]}


def test_reach_waters_gives_what_it_gave_before_on_random_rivers_and_reaches():
    rng = random.Random(7)
    names = ["Blue River", "Red Creek", "Green Brook", "Calumet River", "Little Calumet River"]
    for trial in range(40):
        waters = {}
        for i in range(60):
            x0, y0 = rng.uniform(-79.3, -79), rng.uniform(40, 40.3)
            x1, y1 = x0 + rng.uniform(-0.2, 0.2), y0 + rng.uniform(-0.2, 0.2)
            waters[f"w{i}"] = {"name": rng.choice(names), "kind": rng.choice(["river", "stream", "canal", "lake"]),
                               "state": "PA", "comids": rng.sample(range(1, 40), 3),
                               "bbox": [min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)],
                               "geometry": line(x0, y0, x1, y1)}
        segs = []
        # the reach runs along one of the rivers (within a few hundred metres of it), so matches are common
        g = waters[f"w{rng.randrange(60)}"]["geometry"]["coordinates"]
        steps = rng.randint(0, 12)
        pts = [(g[0][0] + (g[1][0] - g[0][0]) * k / 12 + rng.uniform(-0.004, 0.004),
                g[0][1] + (g[1][1] - g[0][1]) * k / 12 + rng.uniform(-0.004, 0.004)) for k in range(steps + 1)]
        x, y = pts[0]
        for j in range(steps):
            nx, ny = pts[j + 1]
            segs.append({"coords": [[x, y], [(x + nx) / 2, (y + ny) / 2], [nx, ny]], "comid": rng.choice([None, *range(1, 40)]),
                         "gnis_name": rng.choice([None, "", *names])})
            x, y = nx, ny
        reach = {"key": f"t{trial}", "segments": segs}
        S._REACH_WATERS.clear()
        S._GEOM_CACHE.clear()
        assert S.reach_waters(reach, waters) == reach_waters_before(reach, waters), trial
    S._REACH_WATERS.clear()
    S._GEOM_CACHE.clear()


def test_the_placement_stamp_ignores_the_nhd_builders_hourly_bookkeeping_only():
    w = {"x-creek-pa": {"name": "X Creek", "kind": "stream", "state": "PA", "bbox": [0, 0, 1, 1],
                        "geometry": line(0, 0, 1, 1), "fetched_at": "2026-11-07T22:00:00Z", "targets": 3}}
    base = S.placement_stamp(w, [], {}, {}, {"version": 1}, {"PA"})
    later = {"x-creek-pa": {**w["x-creek-pa"], "fetched_at": "2026-11-07T23:00:00Z", "targets": 4}}
    assert S.placement_stamp(later, [], {}, {}, {"version": 1}, {"PA"}) == base
    renamed = {"x-creek-pa": {**w["x-creek-pa"], "aliases": ["Ex Creek"]}}
    assert S.placement_stamp(renamed, [], {}, {}, {"version": 1}, {"PA"}) != base
    assert w["x-creek-pa"]["fetched_at"] == "2026-11-07T22:00:00Z"       # the records themselves are not touched
