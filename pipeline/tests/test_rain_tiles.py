"""The radar grid read in tiles (ingest/mrms_grid.py tiles(), ingest/rainfall.py read_grid, since 2026-11-14): tiled and
untiled sampling agree at tile edges and interiors (on the real Calais export and on synthetic grids), a point outside
the radar grid is left out (the Ohio outfall registered at 83.99 E that stretched the one box of before to 20,796
pixels on 2026-11-08), a failed tile's points go to the per-point fallback alone, and the source's state and the exit
code: ok false on any fallback, the exit code non-zero only when readings are missing, the forecast's deferrals never.
Run from pipeline/: python -m pytest tests -q
"""
from __future__ import annotations

import gzip
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
    saved: list = []                                     # the raw files, as written
    monkeypatch.setattr(RF, "save_raw", lambda src, data, ext: saved.append((src, json.loads(gzip.decompress(data)))))
    monkeypatch.setattr(RF.time, "sleep", lambda s: None)
    world = {"outfalls": outs, "n_west": n_west, "tmp": tmp_path, "saved": saved}
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


class Faulty(FakeNOAA):
    """The service answering some tiles' exports wrongly: which(x centre, y centre) gives "shift" (the image a pixel
    west of the box asked), "empty" (no data everywhere), "short" (a truncated image: sampling fails), "flaky" (an
    error the first time only) or None."""

    def __init__(self, which, **kw):
        super().__init__(**kw)
        self.which, self.seen = which, set()

    def get(self, url, params=None, headers=None, timeout=None):
        if RF.request_kind(url) != "mrms_export":
            return super().get(url, params=params, headers=headers, timeout=timeout)
        xmin, ymin, xmax, ymax = (float(v) for v in params["bbox"].split(","))
        mode = self.which((xmin + xmax) / 2, (ymin + ymax) / 2)
        key = (params["bbox"], params["mosaicRule"])
        if mode == "flaky" and key not in self.seen:
            self.seen.add(key)
            self.calls.append("mrms_export")
            return Resp(status=502, body={"error": "bad gateway"})
        if mode in ("shift", "empty", "short"):
            self.calls.append("mrms_export")
            w, hh = (int(v) for v in params["size"].split(","))
            west = xmin - 0.01 if mode == "shift" else xmin
            tif = make_tiff(w, hh, west, ymax, (lambda la, lo: G.NODATA) if mode == "empty"
                            else (lambda la, lo: rain_at(la, lo)), tile=64, lzw=False)
            return Resp(content=tif[:-16300] if mode == "short" else tif, ctype="image/tiff")   # 84 bytes of a block
        return super().get(url, params=params, headers=headers, timeout=timeout)


def mrms_raw(world) -> dict:
    """The run's raw MRMS file (the last written)."""
    return [d for src, d in world["saved"] if src == "noaa-mrms-qpe"][-1]


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


def test_a_fallback_answer_over_the_bound_makes_the_whole_run_millimetres(nation):
    # the grid alone gives no evidence (the service's stated inches); a failed tile's identify answer is over the
    # bound: the unit is decided once from every value the run read (decide_units, the physical bound), so the grid's
    # values and the fallback's are divided alike, and the change is recorded
    fake = TileFails(west_of=-100.0, scale=25.4, identify_wet={(40.01, -100.01): 60.0})
    out = RF.run(now=NOW, session=fake)
    u = out["mrms"]["units"]
    assert u["units_read"] == "mm" and u["basis"] == "physical_bound" and "fallback" in u["with_fallback"]
    p = out["points"]["40.01,-100.01"]["mrms"]
    assert p["read"] == "point" and p["h24"] == round(60.0 / 25.4, 2) and p["units_read"] == "mm"
    q = out["points"]["40.00,-75.00"]["mrms"]
    assert q["read"] == "grid" and q["h24"] == rain_at(40.0, -75.0) and q["units_read"] == "mm"
    assert out["mrms"]["units_last_determined"]["basis"] == "physical_bound"
    assert any("decided with the per-point fallback's answers" in x for x in out["mrms"]["problems"])
    assert out["mrms"]["grid"]["check"]["factor"] == 25.4                # the check compared at the run's unit


def test_a_gauge_reading_inches_against_a_fallback_answer_over_the_bound_divides_nothing(nation, monkeypatch):
    # the gauge check (on the grid's box) reads inches; a failed tile's identify answer is over the bound: the
    # evidence conflicts (decide_units): nothing is divided, both pieces recorded, the unit not kept as determined
    monkeypatch.setattr(RF, "GAUGES", {"KTST": (42.06, -74.97)})
    fake = TileFails(west_of=-100.0, identify_wet={(40.01, -100.01): 60.0}, gauges={"KTST": [(9, 3.8)]})
    out = RF.run(now=NOW, session=fake)
    u = out["mrms"]["units"]
    assert u["units_read"] == "in" and u["basis"] == "conflict" and u["factor"] == 1.0
    assert u["evidence"]["gauge_check"]["verdict"] == "in" and u["evidence"]["physical_bound"]["box_max"]["h24"] == 60.0
    assert out["mrms"]["units_last_determined"] is None
    assert out["points"]["40.01,-100.01"]["mrms"]["h24"] == 60.0
    assert out["points"]["42.06,-74.97"]["mrms"]["h24"] == rain_at(42.06, -74.97)


def test_every_tile_failing_falls_back_and_fails_the_stage(nation):
    fake = FakeNOAA(export_fails=True)
    out = RF.run(now=NOW, session=fake)
    m, r = out["mrms"], out["requests"]
    assert r["mrms_export"] == 5 * 2 * 2                # each tile's 24-hour export twice, the whole read twice
    assert m["read"] == "point" and m["fallback"]["used"] and m["fallback"]["left"] > 0
    assert r["mrms_identify"] == RF.FALLBACK_MAX_CALLS
    assert not m["readings_ok"] and RF.exit_code(out) == 1 and out["ok"] is False
    assert "points in the radar grid have this hour's reading" in out["error"] and "per-point fallback" in out["error"]
    assert "FALLBACK per point (grid read failed: GridReadError: every grid tile failed (5)" in RF.summary_line(out, 1.0)
    # the raw file keeps what the failed reads asked and got: the catalog and each tile's rejected attempts
    raw = mrms_raw(nation)
    assert raw["read"] == "point" and len(raw["answers"]) == RF.FALLBACK_MAX_CALLS and len(raw["grid_rejected"]) == 2
    rej = raw["grid_rejected"][0]
    assert rej["catalog"]["features"] and len(rej["tiles"]) == 5
    assert all(len(a) == 2 and a[0]["error"] for a in rej["products"]["24"]["rejected"].values())


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


def test_a_misplaced_tile_and_an_empty_tile_are_failed_with_their_answers_kept(nation):
    # the 100 W quadrants west of it answer a pixel off (misplaced: never sampled) and with no data at all
    def which(x, y):
        return ("shift" if y > 40 else "empty") if x < -100 else None
    out = RF.run(now=NOW, session=Faulty(which))
    m = out["mrms"]
    assert sorted(m["grid"]["tiles_failed"]) == ["-120,20", "-120,40"]
    assert "origin" in m["grid"]["tiles_failed"]["-120,40"] and "no 24-hour value at any" in m["grid"]["tiles_failed"]["-120,20"]
    assert m["fallback"]["used"] and m["fallback"]["read"] == 8 and m["fresh"] == m["readable"]
    for k, p in out["points"].items():                  # no misplaced value kept anywhere
        lat, lon = map(float, k.split(","))
        assert p["mrms"]["h24"] == rain_at(lat, lon) and p["mrms"]["read"] == ("point" if lon < -100 else "grid")
    rej = mrms_raw(nation)["products"]["24"]["rejected"]
    assert [len(rej["-120,40"]), len(rej["-120,20"])] == [2, 1]   # two misplaced answers; one answer of no data
    assert all(a["sha256"] and a["bytes"] for a in rej["-120,40"])
    assert rej["-120,20"][-1]["sha256"] and rej["-120,20"][-1]["width"] and "no 24-hour value" in rej["-120,20"][-1]["error"]
    assert "-120,40" not in mrms_raw(nation)["products"]["24"]["tiles"]
    assert out["requests"]["total"] <= 2 * nation["baseline"]


def test_a_tile_read_on_its_second_attempt_is_no_fallback(nation):
    out = RF.run(now=NOW, session=Faulty(lambda x, y: "flaky" if x < -100 and y > 40 else None))
    m, r = out["mrms"], out["requests"]
    assert not m["grid"]["tiles_failed"] and not m["fallback"]["used"] and out["ok"] and RF.exit_code(out) == 0
    assert r["mrms_export"] == 2 * 5 + 2 and r["mrms_identify"] == 1  # each of its two exports failed once
    tile = mrms_raw(nation)["products"]["24"]["tiles"]["-120,40"]
    assert tile["sha256"] and tile["rejected"][0]["error"].startswith("ExportError: RuntimeError: HTTP 502")
    assert tile["rejected"][0]["sha256"] and tile["rejected"][0]["bytes"]       # the error answer's body, hashed


def test_a_failed_tile_over_the_cap_leaves_points_stale_and_says_so(nation, monkeypatch):
    monkeypatch.setattr(RF, "FALLBACK_MAX_CALLS", 5)
    out = RF.run(now=NOW, session=TileFails(west_of=-100.0))
    m = out["mrms"]
    assert m["fallback"]["points"] == 8 and m["fallback"]["read"] == 5 and m["fallback"]["left"] == 3
    assert m["fresh"] == m["readable"] - 3 and m["readings_ok"] and RF.exit_code(out) == 0 and out["ok"] is False
    assert "5 of 8 point(s) read by identify, 3 left at the cap of 5" in out["error"]
    assert "5 of 8 read, 3 left at the cap of 5" in RF.summary_line(out, 1.0)


def test_a_check_that_disagrees_after_several_tiles_discards_the_whole_grid_and_keeps_its_evidence(nation):
    out = RF.run(now=NOW, session=FakeNOAA(identify_off=0.5))
    m = out["mrms"]
    assert m["read"] == "point" and m["grid"]["used"] is False and m["grid"]["check"]["result"] == "differs"
    assert m["fallback"]["used"] and "check at" in m["fallback"]["reason"]
    assert all(p["mrms"]["read"] == "point" for p in out["points"].values() if p.get("mrms"))
    rej = mrms_raw(nation)["grid_rejected"]
    assert len(rej) == 1 and rej[0]["check"]["result"] == "differs" and rej[0]["check"]["answer"]
    assert len(rej[0]["products"]["24"]["tiles"]) == 5 and len(rej[0]["values"]) == m["readable"]
    assert out["requests"]["total"] <= 2 * nation["baseline"]


def test_a_forced_rerun_reads_a_failed_tiles_points_by_point(nation):
    RF.run(now=NOW, session=FakeNOAA())
    fake = TileFails(west_of=-100.0)
    out = RF.run(now=NOW + timedelta(minutes=10), session=fake, force=True)
    m = out["mrms"]
    assert m["fallback"]["used"] and m["fallback"]["points"] == m["fallback"]["read"] == 8
    assert out["requests"]["mrms_identify"] == 8 + 1
    assert all(p["mrms"]["read"] == ("point" if p["lon"] < -100 else "grid") for p in out["points"].values())


class NoData(TileFails):
    """Identify answering no data (MRMS -3) west of 100 W."""

    def get(self, url, params=None, headers=None, timeout=None):
        r = super().get(url, params=params, headers=headers, timeout=timeout)
        if RF.request_kind(url) == "mrms_identify" and json.loads(params["geometry"])["x"] < -100:
            body = r.json()
            body["properties"]["Values"] = ["-3"] * len(body["properties"]["Values"])
            return Resp(body=body)
        return r


def read_an_hour_before(path: Path) -> dict:
    """The rainfall.json at path as if its readings were the previous hour's (fetched and valid an hour earlier)."""
    d = json.loads(path.read_text())
    for p in d["points"].values():
        if p.get("mrms"):
            p["mrms"].update(fetched_at=RF.iso(NOW - timedelta(hours=1)), valid_time=RF.iso(VALID - timedelta(hours=1)))
    path.write_text(json.dumps(d))
    return d


def test_a_fallback_answer_of_no_data_is_not_a_fresh_reading(nation):
    # the points were read the hour before (MRMS -3 at them now is an outage, not a place outside radar coverage)
    RF.run(now=NOW, session=FakeNOAA())
    first = read_an_hour_before(nation["tmp"] / "rainfall.json")
    out = RF.run(now=NOW, session=NoData(west_of=-100.0))
    m = out["mrms"]
    west = [k for k, p in out["points"].items() if p["lon"] < -100]
    for k in west:              # nothing new stored; the reading of before set aside (never fresh, never shown)
        assert "mrms" not in out["points"][k] and out["points"][k]["last_mrms"] == first["points"][k]["mrms"]
        assert out["points"][k]["no_coverage"]["read_before"] is True
    assert {m["failed"][k] for k in west} == {"no 24-hour value in the answer"}
    assert m["fresh"] == m["readable"] - 8 and m["fallback"]["read"] == 0 and m["fallback"]["failed"] == 8
    assert m["outside_coverage"] == [] and out["ok"] is False


def test_a_set_read_by_point_with_no_data_fails_the_stage(tmp_path, monkeypatch):
    outs = [{"permit": "NE0000001", "outfall": str(n), "state": "NE", "name": "n", "lat": round(40.01 + n / 100, 2),
             "lon": -100.01, "water_slug": None, "water_match": None, "distance_m": None, "source": "echo-registry"}
            for n in range(10)]
    monkeypatch.setattr(RF, "cso_outfalls", lambda: outs)
    for name, f in (("OUT", "rainfall.json"), ("HISTORY", "rainfall-history.json"), ("GRIDS", "nws-gridpoints.json")):
        monkeypatch.setattr(RF, name, tmp_path / f)
    monkeypatch.setattr(RF, "GAUGE_CACHE", tmp_path / "gauges.json")
    monkeypatch.setattr(RF, "save_raw", lambda *a, **k: None)
    monkeypatch.setattr(RF.time, "sleep", lambda s: None)
    RF.run(now=NOW, session=FakeNOAA(), qpf=False)
    read_an_hour_before(tmp_path / "rainfall.json")                   # read the hour before
    out = RF.run(now=NOW, session=NoData(west_of=0.0), qpf=False)     # every export fails, identify answers no data
    m = out["mrms"]
    assert m["fresh"] == 0 and not m["readings_ok"] and RF.exit_code(out) == 1 and out["ok"] is False
    assert m["outside_coverage"] == [] and len(m["failed"]) == 10


def test_a_reading_of_an_old_product_is_not_fresh(nation):
    # three hours after the product the service still serves (VALID): read, but stale; the stage fails loudly
    out = RF.run(now=NOW + timedelta(hours=3), session=FakeNOAA())
    m = out["mrms"]
    assert m["read"] == "grid" and m["fetched"] == m["readable"] and m["valid_time"] == RF.iso(VALID)
    assert m["fresh"] == 0 and not m["readings_ok"] and RF.exit_code(out) == 1 and out["ok"] is False
    # an hour late is allowed (a product posted late)
    late = RF.run(now=NOW + timedelta(hours=1), session=FakeNOAA(), force=True)
    assert late["mrms"]["fresh"] == late["mrms"]["readable"] and late["ok"] and RF.exit_code(late) == 0


# ---------------------------------------------------------------- Astra's second pass (2026-11-15)

def identify_answer(values: dict, times: dict) -> dict:
    names = {h: G.item_name(h) for h in RF.HOURS}
    return {"properties": {"Values": [str(values.get(h, 0.0)) for h in RF.HOURS]},
            "catalogItems": {"features": [{"attributes": {"name": names[h], "idp_validendtime": int(times[h].timestamp() * 1000)}}
                                          for h in RF.HOURS]}}


def test_an_identify_answer_of_mixed_hours_is_dated_by_its_24_hour_total():
    old, new = VALID - timedelta(hours=2), VALID
    m = RF.parse_identify(identify_answer({1: 0.1, 3: 0.2, 6: 0.3, 12: 0.4, 24: 0.5, 48: 0.6, 72: 0.7},
                                          {h: (new if h == 1 else old) for h in RF.HOURS}))
    assert m["valid_time"] == RF.iso(old) and m["h24"] == 0.5 and m["h1"] is None
    assert "the 24-hour total's" in m["problems"][0] and "1-hour" in m["problems"][0]
    assert not RF.is_fresh({**m, "fetched_at": RF.iso(NOW)}, NOW)       # two hours old: stale, though the 1 h is new


class MixedHours(TileFails):
    """Identify west of 100 W answering a 24-hour total three hours old beside a current 1-hour total."""

    def get(self, url, params=None, headers=None, timeout=None):
        if RF.request_kind(url) == "mrms_identify" and json.loads(params["geometry"])["x"] < -100:
            return Resp(body=identify_answer({h: 0.3 for h in RF.HOURS},
                                             {h: VALID - timedelta(hours=0 if h == 1 else 3) for h in RF.HOURS}))
        return super().get(url, params=params, headers=headers, timeout=timeout)


def test_a_fallback_answer_with_an_old_24_hour_total_is_not_fresh(nation):
    out = RF.run(now=NOW, session=MixedHours(west_of=-100.0))
    m = out["mrms"]
    west = [k for k, p in out["points"].items() if p["lon"] < -100]
    assert all(out["points"][k]["mrms"]["valid_time"] == RF.iso(VALID - timedelta(hours=3)) for k in west)
    assert m["fresh"] == m["readable"] - 8 and out["ok"] is False


def test_an_older_product_never_replaces_a_newer_reading(nation):
    first = RF.run(now=NOW, session=FakeNOAA())
    before = {k: p["mrms"] for k, p in first["points"].items()}

    class Behind(FakeNOAA):              # the catalog three hours behind, everything else the same
        def get(self, url, params=None, headers=None, timeout=None):
            r = super().get(url, params=params, headers=headers, timeout=timeout)
            if RF.request_kind(url) == "mrms_query":
                for f in r.json()["features"]:
                    f["attributes"]["idp_validendtime"] -= 3 * 3600 * 1000
                return Resp(body=r.json())
            return r
    out = RF.run(now=NOW + timedelta(minutes=10), session=Behind(scale=1.0), force=True)
    assert {k: p["mrms"] for k, p in out["points"].items()} == before
    assert any("answered with an older product than the reading stored; the newer kept" in x
               for x in out["mrms"]["problems"])
    assert mrms_raw(nation)["values"]                              # the older answers are in the raw file


def test_the_check_compares_at_the_runs_final_unit(nation):
    # millimetres the grid alone cannot tell (no value over the bound in it), a failed tile's answer over the bound,
    # and identify 0.02 mm off the grid at the check's point: within the tolerance in inches at the final unit, so the
    # grid is kept (at the grid's own stated inches 0.02 is over the 0.011 tolerance and would have discarded it)
    fake = TileFails(west_of=-100.0, scale=25.4, identify_off=0.02, identify_wet={(40.01, -100.01): 60.0})
    out = RF.run(now=NOW, session=fake)
    m = out["mrms"]
    assert m["units"]["units_read"] == "mm" and m["grid"]["used"] and m["grid"]["check"]["result"] == "agrees"
    assert m["grid"]["check"]["factor"] == 25.4 and m["read"] == "grid"


def test_a_truncated_answer_keeps_its_hash_and_a_thin_grid_keeps_its_values(nation):
    out = RF.run(now=NOW, session=Faulty(lambda x, y: "short" if x < -100 and y > 40 else None))
    assert "-120,40" in out["mrms"]["grid"]["tiles_failed"]
    rej = mrms_raw(nation)["products"]["24"]["rejected"]["-120,40"]
    assert rej[-1]["sha256"] and rej[-1]["bytes"] and rej[-1]["width"] and "short" in rej[-1]["error"]

    class Thin(FakeNOAA):                # no data at every other row: the grid has no value at most points
        def raw(self, lat, lon, h):
            return -3.0 if round(lat * 100) % 2 else super().raw(lat, lon, h)
    pts = RF.group_points(nation["outfalls"])
    with pytest.raises(RF.GridReadError) as e:      # points read before: no coverage at them now is an outage
        RF.read_grid(RF.CountingSession(Thin()), pts, [1, 24], seen=set(pts))
    ev = e.value.evidence
    assert ev["catalog"] and ev["products"]["24"]["tiles"] and ev["hours"] == [24, 1]
    assert sum(1 for v in ev["values"].values() if v[0] is None) > 0.2 * len(ev["values"])


def test_a_partial_fallback_then_a_discarded_grid_asks_each_point_once_within_one_cap(nation, monkeypatch):
    # two tiles fail (8 points read by identify), then the check disagrees and the whole grid is discarded: the rest
    # are read by identify within what is left of one cap, nobody twice; the unit is decided from the identify answers
    # alone (one over the bound: millimetres) and each converted once; the raw file keeps the answers and the grid
    monkeypatch.setattr(RF, "FALLBACK_MAX_CALLS", 20)
    fake = TileFails(west_of=-100.0, scale=25.4, identify_off=0.5, identify_wet={(40.01, -100.01): 60.0})
    out = RF.run(now=NOW, session=fake)
    m, fb, r = out["mrms"], out["mrms"]["fallback"], out["requests"]
    assert m["read"] == "point" and m["grid"]["used"] is False and m["grid"]["check"]["result"] == "differs"
    assert fb["called"] == 20 and fb["points"] == m["readable"] and fb["read"] + fb["failed"] + fb["left"] == fb["points"]
    assert fb["left"] == m["readable"] - 20 and r["mrms_identify"] == 20 + 1          # the 20 and the check, no repeat
    raw = mrms_raw(nation)
    assert len(raw["answers"]) == 20 and all(f"{p['lat']:.2f},{p['lon']:.2f}" in raw["answers"]
                                              for p in out["points"].values() if p["lon"] < -100)
    assert raw["grid_rejected"][0]["check"]["result"] == "differs" and raw["grid_rejected"][0]["products"]["24"]["tiles"]
    u = m["units"]
    assert u["units_read"] == "mm" and u["basis"] == "physical_bound" and "with_fallback" not in u
    assert out["points"]["40.01,-100.01"]["mrms"]["h24"] == round((60.0 + 0.5) / 25.4, 2)
    for k in raw["answers"]:
        lat, lon = map(float, k.split(","))
        if (lat, lon) != (40.01, -100.01):
            assert out["points"][k]["mrms"]["h24"] == round(round(rain_at(lat, lon) * 25.4 + 0.5, 2) / 25.4, 2)
    assert not m["readings_ok"] and RF.exit_code(out) == 1 and out["ok"] is False
