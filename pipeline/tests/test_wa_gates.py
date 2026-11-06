"""Washington's go-live gates (2026-11-06): the NHD records tidied against openboatlaunch's extract, the King County and
Seattle outfalls tied by the operators' own lists (Ecology's permits WA0029181, WA0031682 and WA0029581, and Seattle
Public Utilities' CSO basin layer), the Census TIGER/Line records those lists need, and Puget Sound under the shoreline
model. Data tests on the files as committed; no network.
Run from pipeline/: python -m pytest tests/test_wa_gates.py -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"


def _json(name):
    return json.loads((DATA / name).read_text())


def _nhd_wa():
    return [r for r in _json("waters-nhd.json")["waters"] if r.get("state") == "WA"]


def _obl_wa():
    return {r["slug"]: r for r in _json("waters-wa.json")["waters"]}


def test_no_washington_nhd_record_hides_behind_an_openboatlaunch_slug():
    """The tidy (waters_from_nhd --state WA --tidy) ran after openboatlaunch's extract: an NHD record that shared a
    slug with an openboatlaunch record was either the same water (dropped) or another one (renamed). Before it, 35
    shared a slug and the status build kept openboatlaunch's: Renton's Black River was read as the Black River
    near Olympia, 78 km away, and two King County South plant outfalls were tied to it."""
    obl = _obl_wa()
    shared = sorted(r["slug"] for r in _nhd_wa() if r["slug"] in obl)
    assert shared == []
    renton = [r for r in _nhd_wa() if r["slug"] == "black-river-renton-wa"]
    assert len(renton) == 1 and renton[0]["name"] == "Black River" and "Renton" in renton[0]["towns"]


# the operators' own points (King County's status file, which Ecology's permit tables repeat) of the outfalls the
# hand records are for
POINTS = {
    ("WA0029181", "030"): (47.581476, -122.342997),     # Lander St: 'Duwamish River - East Waterway'
    ("WA0029181", "032"): (47.577223, -122.34278),      # Hanford #2: 'Duwamish River - East Waterway'
    ("WA0031682", "107"): (47.5736688, -122.3430585),   # 'East Waterway - Duwamish River'
    ("WA0031682", "059"): (47.6702494, -122.4061857),   # 'Salmon Bay'
    ("WA0031682", "060"): (47.6678326, -122.4077581),   # 'Salmon Bay'
    ("WA0029181", "014"): (47.64711, -122.304861),      # Montlake: 'Lake Washington Ship Canal'
}
HAND = {"east-waterway-wa": ("East Waterway", "110855770942", [("WA0029181", "030"), ("WA0029181", "032"),
                                                                ("WA0031682", "107")]),
        "salmon-bay-waterway-wa": ("Salmon Bay Waterway", "110855771286", [("WA0031682", "059"), ("WA0031682", "060")]),
        "montlake-cut-wa": ("Montlake Cut", "110855771359", [("WA0029181", "014")])}


def _dist_m(geom, lat, lon):
    import math

    import shapely
    from shapely.geometry import Point
    k = (111_320.0 * math.cos(math.radians(lat)), 110_574.0)
    return shapely.transform(geom, lambda xy: xy * k).distance(shapely.transform(Point(lon, lat), lambda xy: xy * k))


def test_the_washington_hand_records_are_the_census_polygons_at_the_operators_points():
    from shapely.geometry import shape
    recs = {r["slug"]: r for r in _nhd_wa()}
    for slug, (name, oid, outfalls) in HAND.items():
        r = recs[slug]
        assert r["name"] == name and r["hand"] is True and r["source"] == "census" and r["tiger_ids"] == [oid]
        assert r["kind"] == "canal" and r["towns"] == ["Seattle"]
        assert "Ecology's" in r["note"] and "WA00" in r["note"]          # the permit that names the water
        for key in outfalls:
            assert _dist_m(shape(r["geometry"]), *POINTS[key]) <= 20, (slug, key)
    assert recs["salmon-bay-waterway-wa"]["aliases"] == ["Salmon Bay"]
    assert recs["montlake-cut-wa"]["gnis_id"] == "1534602"


def test_the_washington_hand_specs_name_their_tiger_ids():
    from ingest import waters_from_nhd as N
    wa = {h["name"]: h for h in N.HAND if h["state"] == "WA"}
    assert {n: h["oids"] for n, h in wa.items()} == {v[0]: [v[1]] for v in HAND.values()}
    assert all(h["service"] == "tiger" and h.get("near") for h in wa.values())
