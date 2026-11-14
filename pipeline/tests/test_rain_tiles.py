"""The radar grid read in tiles (ingest/mrms_grid.py tiles(), ingest/rainfall.py read_grid, since 2026-11-14): tiled and
untiled sampling agree at tile edges and interiors (on the real Calais export and on synthetic grids), a point outside
the radar grid is left out (the Ohio outfall registered at 83.99 E that stretched the one box of before to 20,796
pixels on 2026-11-08), a failed tile's points go to the per-point fallback alone, and the source's state and the exit
code: ok false on any fallback, the exit code non-zero only when readings are missing, the forecast's deferrals never.
Run from pipeline/: python -m pytest tests -q
"""
from __future__ import annotations

import json
import sys
from datetime import timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ingest import mrms_grid as G  # noqa: E402
from ingest import rainfall as RF  # noqa: E402
from test_rain_grid import NOW, VALID, FakeNOAA, Resp, make_tiff, rain_at, steady, synthetic_outfalls  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
CALAIS = G.Grid((FIXTURES / "mrms-qpe-24h-20261103T13Z.tif").read_bytes())


def raw_pixel(g: G.Grid, lat: float, lon: float) -> float:
    """The pixel of g containing the point as stored (negatives and NaN included); the export's no data outside."""
    v = g.pixel(*g.cell(lat, lon))
    return G.NODATA if v is None else v


def crop(g: G.Grid, box: dict, tile: int | None = 16) -> G.Grid:
    """What exportImage would answer over box from the raster g: a TIFF on the box's own pixels."""
    return G.Grid(make_tiff(box["width"], box["height"], box["xmin"], box["ymax"],
                            lambda la, lo: raw_pixel(g, la, lo), tile=tile, lzw=True))


def keyed(pts):
    return {f"{a:.2f},{b:.2f}": (a, b) for a, b in pts}


# ---------------------------------------------------------------- the tiles

def test_tiles_put_every_point_in_one_box_under_the_services_limits():
    # a national spread: both coasts, the interior, and points either side of the 20-degree lines (-120, -100, -80
    # and 40 N), as dense as a metro there
    pts = keyed([(47.61, -122.33), (37.77, -122.42), (32.72, -117.16), (40.76, -111.89), (35.08, -106.65),
                 (29.76, -95.37), (41.88, -87.63), (42.33, -83.05), (33.75, -84.39), (25.77, -80.19),
                 (40.44, -79.99), (40.44, -80.01), (40.00, -80.00), (39.99, -80.00), (39.95, -75.17),
                 (44.10, -100.00), (44.10, -100.01), (38.00, -120.00), (38.00, -120.01), (45.17, -67.29)])
    t = G.tiles(pts)
    assert sorted(k for x in t for k in x["keys"]) == sorted(pts)            # every point once
    assert len(t) <= 8
    for x in t:
        b = x["box"]
        assert b["width"] <= G.TILE_CELLS + 1 + 2 * G.MARGIN_CELLS <= G.MAX_WIDTH
        assert b["height"] <= G.TILE_CELLS + 1 + 2 * G.MARGIN_CELLS <= G.MAX_HEIGHT
        for k in x["keys"]:                                                  # each point inside its own box
            lat, lon = pts[k]
            assert b["xmin"] < lon < b["xmax"] and b["ymin"] < lat < b["ymax"]
    where = {k: x["tile"] for x in t for k in x["keys"]}
    assert where["40.00,-80.00"] == "-80,40" and where["39.99,-80.00"] == "-80,20"   # either side of 40 N
    assert where["40.44,-80.01"] == "-100,40" and where["40.44,-79.99"] == "-80,40"  # either side of 80 W
    assert where["38.00,-120.01"] == "-140,20" and where["38.00,-120.00"] == "-120,20"
    # one box over every point would be over the service's width limit only with a bad point; the tiles never are
    with pytest.raises(ValueError, match="over the service's limit"):
        G.grid_box([*pts.values(), (41.57, 83.99)])


def test_the_radar_grid_extent_is_the_conus_footprint():
    assert G.in_extent(41.57, -83.99) and G.in_extent(20.0, -130.0) and G.in_extent(55.0, -60.0)
    for lat, lon in ((41.57, 83.99), (61.22, -149.90), (21.31, -157.86), (18.47, -66.11), (None, -80.0)):
        assert not G.in_extent(lat, lon)                 # the sign error; Anchorage, Honolulu, San Juan; no coordinate


def test_tiled_and_untiled_sampling_agree_on_the_real_export_at_edges_and_interiors():
    """The Calais export (conus_QPE_24H, 2026-11-03T13Z) as the world: every hundredth in it sampled from one box
    (the raster itself) and from 0.1-degree tiles cropped from it as the service would answer them. Equal at every
    point, the ones on each side of a tile line included."""
    pts = keyed([(round(45.10 + a / 100, 2), round(-67.40 + b / 100, 2)) for a in range(16) for b in range(21)])
    whole = G.sample(CALAIS, pts)
    assert sum(v is not None for v in whole.values()) > 300 and len(set(whole.values())) > 20
    t = G.tiles(pts, cells=10)
    assert len(t) == 6                                   # 67.4, 67.3 and 67.2 W by 45.1 and 45.2 N
    edge = 0
    tiled = {}
    for x in t:
        g = crop(CALAIS, x["box"])
        assert G.check_georef(g, x["box"]) == []
        got = G.sample(g, {k: pts[k] for k in x["keys"]})
        tiled.update(got)
        for k in x["keys"]:
            j, i = G.cell_index(*pts[k])
            edge += (i % 10 in (0, 9)) or (j % 10 in (0, 9))
    assert tiled == whole
    assert edge > 100                                    # many points sit on a tile's first or last row or column
    assert (tiled["45.19,-67.27"], tiled["45.12,-67.38"]) == (3.8, 5.9)     # identify's values there


# ---------------------------------------------------------------- the run

def national_outfalls():
    """The synthetic New England and mid-Atlantic points (one tile, 80 to 60 W), plus a cluster on the corner of four
    tiles (40 N, 100 W): five tiles, the cluster's four a few pixels each."""
    outs, _ = synthetic_outfalls()
    west = [(round(39.97 + 0.02 * a, 2), round(-100.03 + 0.02 * b, 2)) for a in range(4) for b in range(4)]
    for n, (lat, lon) in enumerate(west):
        outs.append({"permit": f"NE{n % 7:07d}", "outfall": f"W{n}", "state": "NE", "name": "w", "lat": lat,
                     "lon": lon, "water_slug": None, "water_match": None, "distance_m": None, "source": "echo-registry"})
    return outs, len(west)


@pytest.fixture
def nation(tmp_path, monkeypatch):
    outs, n_west = national_outfalls()
    monkeypatch.setattr(RF, "cso_outfalls", lambda: outs)
    monkeypatch.setattr(RF, "OUT", tmp_path / "rainfall.json")
    monkeypatch.setattr(RF, "HISTORY", tmp_path / "rainfall-history.json")
    monkeypatch.setattr(RF, "GRIDS", tmp_path / "nws-gridpoints.json")
    monkeypatch.setattr(RF, "GAUGE_CACHE", tmp_path / "raw" / "nws-gauges" / "observations.json")
    monkeypatch.setattr(RF, "save_raw", lambda *a, **k: None)
    monkeypatch.setattr(RF.time, "sleep", lambda s: None)
    world = {"outfalls": outs, "n_west": n_west, "tmp": tmp_path}
    world["baseline"] = steady(world)
    return world


class TileFails(FakeNOAA):
    """The service failing every export whose box is centred west of a longitude (identify_wet: values only identify
    answers, as if the grid had not seen them)."""

    def __init__(self, west_of: float, identify_wet=None, **kw):
        super().__init__(**kw)
        self.west_of, self.identify_wet = west_of, identify_wet or {}
        self.boxes: list[str] = []

    def get(self, url, params=None, headers=None, timeout=None):
        if RF.request_kind(url) == "mrms_identify" and self.identify_wet:
            saved, self.wet = self.wet, {**self.wet, **self.identify_wet}
            try:
                return super().get(url, params=params, headers=headers, timeout=timeout)
            finally:
                self.wet = saved
        if RF.request_kind(url) == "mrms_export":
            self.boxes.append(params["bbox"])
            xmin, _, xmax, _ = (float(v) for v in params["bbox"].split(","))
            if (xmin + xmax) / 2 < self.west_of:
                return Resp(status=503, body={"error": "busy"})
        return super().get(url, params=params, headers=headers, timeout=timeout)


def test_a_national_set_is_read_in_tiles_with_the_values_one_box_gave(nation, monkeypatch):
    fake = FakeNOAA()
    out = RF.run(now=NOW, session=fake)
    m, r = out["mrms"], out["requests"]
    tiles = m["grid"]["tiles"]
    assert len(tiles) == 5 and m["grid"]["tiles_read"] == 5 and not m["grid"]["tiles_failed"]
    assert [x["tile"] for x in tiles] == ["-120,40", "-120,20", "-100,40", "-100,20", "-80,40"]
    assert [x["points"] for x in tiles] == [4, 4, 4, 4, 319 + 908]
    assert r["mrms_export"] == 2 * 5 and r["mrms_query"] == 1 and r["mrms_identify"] == 1
    assert r["total"] <= 2 * nation["baseline"]
    assert m["read"] == "grid" and m["fresh"] == m["readable"] == m["points"] == m["fetched"]
    assert out["ok"] and m["readings_ok"] and not m["fallback"]["used"] and RF.exit_code(out) == 0
    tiled = {k: p["mrms"] for k, p in out["points"].items()}
    for k, v in tiled.items():
        lat, lon = map(float, k.split(","))
        assert v["read"] == "grid" and v["h24"] == rain_at(lat, lon) and v["h1"] == rain_at(lat, lon, 1)
    line = RF.summary_line(out, 1.0)
    assert "read by grid (5 of 5 tiles, 10 exports)" in line and "FALLBACK" not in line
    assert f"requests {r['total']} (MRMS {r['noaa_mrms']}: 1 query, 10 export, 1 identify;" in line
    # the same hour read as one box over every point (tiles as large as the country): the same values
    monkeypatch.setattr(G, "TILE_CELLS", 10 ** 6)
    one = RF.run(now=NOW, session=FakeNOAA(), force=True)
    assert len(one["mrms"]["grid"]["tiles"]) == 1 and one["requests"]["mrms_export"] == 2
    assert {k: (p["mrms"]["h1"], p["mrms"]["h24"]) for k, p in one["points"].items()} == \
        {k: (v["h1"], v["h24"]) for k, v in tiled.items()}


def test_a_point_outside_the_radar_grid_is_left_out_and_never_stretches_a_box(nation):
    nation["outfalls"].append({"permit": "OH0020974", "outfall": "014", "state": "OH", "name": "d", "lat": 41.574444,
                               "lon": 83.994722, "water_slug": None, "water_match": None, "distance_m": None,
                               "source": "echo-registry"})
    fake = TileFails(west_of=-1000.0)                   # fails nothing; keeps the boxes asked for
    out = RF.run(now=NOW, session=fake)
    m = out["mrms"]
    assert m["outside_grid"] == ["41.57,83.99"] and out["points"]["41.57,83.99"]["outside_grid"] is True
    assert "mrms" not in out["points"]["41.57,83.99"]
    assert m["readable"] == m["points"] - 1 == m["fresh"] and out["ok"] and RF.exit_code(out) == 0
    # its permittee has no point in the grid and no history: no 48 and 72-hour grids for it, hour after hour
    assert out["requests"]["mrms_export"] == 10 and out["requests"]["mrms_identify"] == 1
    assert len(fake.boxes) == 10 and all(float(b.split(",")[2]) < -60 for b in fake.boxes)   # none east of the grid
    assert any("outside the radar grid" in p and "OH0020974:014" in p for p in m["problems"])
    assert "1 outside the radar grid" in RF.summary_line(out, 1.0)


def test_a_failed_tile_sends_only_its_points_to_the_fallback(nation):
    fake = TileFails(west_of=-100.0)                    # the two tiles west of 100 W fail; the other three are read
    out = RF.run(now=NOW, session=fake)
    m, r = out["mrms"], out["requests"]
    gi, fb = m["grid"], m["fallback"]
    west = {k for k, p in out["points"].items() if p["lon"] < -100}
    assert len(west) == 8 and sorted(gi["tiles_failed"]) == ["-120,20", "-120,40"] and gi["tiles_read"] == 3
    # each failed tile: its 24-hour export tried twice, its 1-hour export never asked
    assert r["mrms_export"] == 3 * 2 + 2 * 2
    assert m["read"] == "grid" and fb["used"] and fb["points"] == fb["read"] == 8 and fb["left"] == 0
    assert r["mrms_identify"] == 8 + 1                  # the fallback's points and the grid's check
    for k, p in out["points"].items():
        lat, lon = map(float, k.split(","))
        assert p["mrms"]["read"] == ("point" if k in west else "grid")
        assert p["mrms"]["h24"] == rain_at(lat, lon) and p["mrms"]["valid_time"] == RF.iso(VALID)
        assert p["mrms"]["units_read"] == m["units"]["units_read"]
    # every reading fresh: the exit code is 0, but the source says the fallback ran
    assert m["fresh"] == m["readable"] and m["readings_ok"] and RF.exit_code(out) == 0
    assert out["ok"] is False and "per-point fallback (2 of 5 grid tile(s) failed" in out["error"]
    assert out["last_ok_at"] is None
    line = RF.summary_line(out, 1.0)
    assert "read by grid (3 of 5 tiles," in line and "FALLBACK per point" in line and "8 of 8 read" in line
    # the same hour again reads nothing and keeps saying so
    again = RF.run(now=NOW + timedelta(minutes=10), session=FakeNOAA())
    assert again["requests"]["noaa_mrms"] == 0 and again["ok"] is False and again["mrms"]["fallback"]["used"]
    assert again["mrms"]["fallback"]["carried_from"] and RF.exit_code(again) == 0


def test_a_failed_tiles_points_take_the_grids_unit(nation):
    # the service in millimetres, a grid point over the 24-hour bound: the run's unit is millimetres, and the failed
    # tile's points, read by identify from the same service in the same hour, are divided like the grid's
    fake = TileFails(west_of=-100.0, scale=25.4, wet={(40.0, -75.0): 60.0})
    out = RF.run(now=NOW, session=fake)
    m = out["mrms"]
    assert m["units"]["units_read"] == "mm" and m["units"]["basis"] == "physical_bound"
    q = out["points"]["40.00,-75.00"]["mrms"]
    assert q["read"] == "grid" and q["h24"] == round(60.0 / 25.4, 2) and q["units_read"] == "mm"
    p = out["points"]["40.01,-100.01"]["mrms"]
    assert p["read"] == "point" and p["h24"] == rain_at(40.01, -100.01) and p["units_read"] == "mm"


def test_a_fallback_answer_over_the_bound_against_the_grids_inches_divides_nothing(nation):
    # the grid gives no evidence (the service's stated inches), a failed tile's identify answer is over the bound:
    # a conflict, recorded; nothing is divided (the larger reading, the safety side)
    fake = TileFails(west_of=-100.0, identify_wet={(40.01, -100.01): 60.0})
    out = RF.run(now=NOW, session=fake)
    m = out["mrms"]
    assert m["units"]["units_read"] == "in"
    p = out["points"]["40.01,-100.01"]["mrms"]
    assert p["read"] == "point" and p["h24"] == 60.0 and p["units_read"] == "in"
    assert any("per-point fallback: the largest 24-hour value read, 60.0" in x and "nothing divided" in x
               for x in m["problems"])


def test_every_tile_failing_falls_back_and_fails_the_stage(nation):
    fake = FakeNOAA(export_fails=True)
    out = RF.run(now=NOW, session=fake)
    m, r = out["mrms"], out["requests"]
    assert r["mrms_export"] == 5 * 2 * 2                # each tile's 24-hour export twice, the whole read twice
    assert m["read"] == "point" and m["fallback"]["used"] and m["fallback"]["left"] > 0
    assert r["mrms_identify"] == RF.FALLBACK_MAX_CALLS
    assert not m["readings_ok"] and RF.exit_code(out) == 1 and out["ok"] is False
    assert "points in the radar grid have this hour's reading" in out["error"] and "per-point fallback" in out["error"]
    assert "FALLBACK per point (grid read failed: ValueError: every grid tile failed (5)" in RF.summary_line(out, 1.0)


def test_a_small_set_read_wholly_by_the_fallback_is_not_ok_but_exits_zero(tmp_path, monkeypatch):
    outs = [{"permit": f"RI{n % 3:07d}", "outfall": str(n), "state": "RI", "name": "r", "lat": round(41.80 + n / 100, 2),
             "lon": -71.40, "water_slug": None, "water_match": None, "distance_m": None, "source": "echo"}
            for n in range(20)]
    monkeypatch.setattr(RF, "cso_outfalls", lambda: outs)
    for name, f in (("OUT", "rainfall.json"), ("HISTORY", "rainfall-history.json"), ("GRIDS", "nws-gridpoints.json")):
        monkeypatch.setattr(RF, name, tmp_path / f)
    monkeypatch.setattr(RF, "GAUGE_CACHE", tmp_path / "gauges.json")
    monkeypatch.setattr(RF, "save_raw", lambda *a, **k: None)
    monkeypatch.setattr(RF.time, "sleep", lambda s: None)
    out = RF.run(now=NOW, session=FakeNOAA(export_fails=True), qpf=False)
    m = out["mrms"]
    assert m["read"] == "point" and m["fresh"] == m["readable"] == 20 and m["readings_ok"]
    assert out["ok"] is False and m["fallback"]["used"] and RF.exit_code(out) == 0
    # --points is the per-point path by choice: no fallback, ok
    chosen = RF.run(now=NOW, session=FakeNOAA(), qpf=False, force=True, point_only=True)
    assert chosen["mrms"]["read"] == "point" and not chosen["mrms"]["fallback"]["used"] and chosen["ok"]


def test_forecast_cells_deferred_by_design_never_fail_the_stage(nation, monkeypatch):
    monkeypatch.setattr(RF, "QPF_FETCH_MAX", 3)
    out = RF.run(now=NOW, session=FakeNOAA())
    assert out["qpf"]["deferred"] > 0 and out["qpf"]["fetched"] == 3
    assert out["ok"] and RF.exit_code(out) == 0
