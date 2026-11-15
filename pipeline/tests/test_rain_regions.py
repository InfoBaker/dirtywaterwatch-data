"""The radar read beyond the lower 48 (since 2026-11-15): Alaska, Hawaii and the Caribbean (Puerto Rico, the Virgin
Islands) each read from their own MRMS grid (mrms_grid.REGIONS), on the real exports of 2026-11-15T13Z
(tests/fixtures/mrms-{alaska,carib,alaska-prudhoe}-qpe-24h-20261115T13Z.tif, research/mrms/regions-2026-11-15.md):
each region's own items, tiles, unit, check and fallback; a place no radar sees (MRMS -3, Prudhoe Bay) listed and never
failing the stage; a stale regional product and a failed regional export loud in ok, error, the summary line and (for
missing readings) the exit code; a permittee's old reading never shown as this hour's.
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
from test_rain_grid import NOW, VALID, FakeNOAA, Resp, make_tiff, rain_at, steady  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
RASTERS = {"alaska": [G.Grid((FIXTURES / "mrms-alaska-qpe-24h-20261115T13Z.tif").read_bytes()),
                      G.Grid((FIXTURES / "mrms-alaska-prudhoe-qpe-24h-20261115T13Z.tif").read_bytes())],
           "carib": [G.Grid((FIXTURES / "mrms-carib-qpe-24h-20261115T13Z.tif").read_bytes())]}
IDS = {"conus": 100, "alaska": 200, "hawaii": 300, "carib": 400}
# the outfall points: Juneau's three (AK0023213 002, 003, 004) and the wettest pixel of the Alaska export (4.9 mm);
# San Juan's eight (PR0021555) and the wettest of the Caribbean export (7.9 mm); Prudhoe Bay (MRMS -3)
JUNEAU = [(58.30, -134.42), (58.30, -134.41), (58.28, -134.39)]
AK_WET = (57.85, -135.51)
SAN_JUAN = [(18.43, -66.06), (18.43, -66.08), (18.44, -66.07), (18.44, -66.08), (18.45, -66.08), (18.45, -66.09),
            (18.46, -66.12), (18.47, -66.12)]
PR_WET = (18.08, -66.73)
PRUDHOE = (70.26, -148.62)


def outfall(permit, n, state, lat, lon):
    return {"permit": permit, "outfall": f"{n:03d}", "state": state, "name": "x", "lat": lat, "lon": lon,
            "water_slug": None, "water_match": None, "distance_m": None, "source": "echo-registry"}


def lower48():
    return [outfall(f"RI{n % 3:07d}", n, "RI", round(41.80 + n / 100, 2), -71.40) for n in range(20)]


def alaska(prudhoe=False):
    pts = [*JUNEAU, AK_WET] + ([PRUDHOE] if prudhoe else [])
    return [outfall("AK0023213" if p != PRUDHOE else "AKG320002", n + 2, "AK", *p) for n, p in enumerate(pts)]


def puerto_rico():
    return [outfall("PR0021555", n + 2, "PR", *p) for n, p in enumerate([*SAN_JUAN, PR_WET])]


def mm_24h(region: str, lat: float, lon: float) -> float:
    """The 24-hour value the real export holds at the point (millimetres, MRMS -3 where no radar sees)."""
    for g in RASTERS.get(region, []):
        v = g.raw(lat, lon)
        if v is not None:
            return round(v, 1)
    return G.NODATA


class RegionNOAA(FakeNOAA):
    """The service with its four grids: the lower 48 from rain_at() (FakeNOAA), Alaska and the Caribbean from the real
    exports (other hours: the 24-hour value scaled, never shrinking with the window); the catalog answering every
    region's items (stale: {region: hours late}); statistics per region; identify answering every grid whose
    footprint holds the point, as the service does where two overlap. fail: the regions whose exports fail."""

    def __init__(self, stale=None, fail=(), stats=None, wet=None, **kw):
        super().__init__(**kw)
        self.stale, self.fail = stale or {}, set(fail)
        self.stats = {"alaska": 93.3, "carib": 53.9, "hawaii": 20.4, **(stats or {})}
        self.region_wet = wet or {}                 # {(lat, lon): {hours: value}} for a regional identify
        self.exports: list[tuple[str, str]] = []

    def vt(self, region):
        return VALID - timedelta(hours=self.stale.get(region, 0))

    def region_raw(self, region, lat, lon, h):
        if region == "conus":
            return self.raw(lat, lon, h)
        w = self.region_wet.get((round(lat, 2), round(lon, 2)), {})
        if h in w:
            return w[h]
        v = mm_24h(region, lat, lon)
        if v < 0:
            return v
        return round(v * h / 24, 1) if h < 24 else round(v + (h - 24) / 24, 1)

    def get(self, url, params=None, headers=None, timeout=None):
        kind = RF.request_kind(url)
        if kind == "mrms_query":
            self.calls.append(kind)
            names = set(params["where"].split("(")[1].rstrip(")").replace("'", "").split(","))
            feats = [{"attributes": {"objectid": IDS[r] + h, "name": G.item_name(h, r),
                                     "idp_validendtime": int(self.vt(r).timestamp() * 1000)}}
                     for r in G.REGIONS for h in RF.HOURS if G.item_name(h, r) in names]
            return Resp(body={"features": feats})
        if kind == "mrms_export":
            self.calls.append(kind)
            oid = json.loads(params["mosaicRule"])["lockRasterIds"][0]
            region, h = next((r, oid - i) for r, i in IDS.items() if 0 < oid - i < 100)
            self.exports.append((region, params["bbox"]))
            if region in self.fail:
                return Resp(status=503, body={"error": "busy"})
            xmin, ymin, xmax, ymax = (float(v) for v in params["bbox"].split(","))
            w, hh = (int(v) for v in params["size"].split(","))
            return Resp(content=make_tiff(w, hh, xmin, ymax, lambda la, lo: self.region_raw(region, la, lo, h),
                                          tile=64, lzw=False), ctype="image/tiff")
        if kind == "mrms_statistics":
            self.calls.append(kind)
            oid = json.loads(params["mosaicRule"])["lockRasterIds"][0]
            region = next(r for r, i in IDS.items() if 0 < oid - i < 100)
            return Resp(body={"statistics": [{"min": -3, "max": self.stats[region], "mean": -1.4, "count": 5960000}]})
        if kind == "mrms_identify":
            self.calls.append(kind)
            g = json.loads(params["geometry"])
            lat, lon = g["y"], g["x"]
            items, vals = [], []
            for r, ext in G.REGIONS.items():
                if G.in_extent(lat, lon, ext):
                    for h in RF.HOURS:
                        items.append({"attributes": {"name": G.item_name(h, r),
                                                     "idp_validendtime": int(self.vt(r).timestamp() * 1000)}})
                        vals.append(str(self.region_raw(r, lat, lon, h)))
            return Resp(body={"properties": {"Values": vals}, "catalogItems": {"features": items}})
        return super().get(url, params=params, headers=headers, timeout=timeout)


@pytest.fixture
def world(tmp_path, monkeypatch):
    outs = lower48() + alaska() + puerto_rico()
    monkeypatch.setattr(RF, "cso_outfalls", lambda: outs)
    monkeypatch.setattr(RF, "OUT", tmp_path / "rainfall.json")
    monkeypatch.setattr(RF, "HISTORY", tmp_path / "rainfall-history.json")
    monkeypatch.setattr(RF, "GRIDS", tmp_path / "nws-gridpoints.json")
    monkeypatch.setattr(RF, "GAUGE_CACHE", tmp_path / "raw" / "nws-gauges" / "observations.json")
    saved: list = []
    monkeypatch.setattr(RF, "save_raw", lambda src, data, ext: saved.append((src, json.loads(gzip.decompress(data)))))
    monkeypatch.setattr(RF.time, "sleep", lambda s: None)
    w = {"outfalls": outs, "tmp": tmp_path, "saved": saved}
    steady(w)
    return w


def key(p):
    return f"{p[0]:.2f},{p[1]:.2f}"


# ---------------------------------------------------------------- the regions

def test_states_go_to_their_own_grid_and_only_guam_samoa_and_the_marianas_have_none():
    assert {s: G.region_of(s) for s in ("AK", "HI", "PR", "VI", "FL", "WA", "ME")} == \
        {"AK": "alaska", "HI": "hawaii", "PR": "carib", "VI": "carib", "FL": "conus", "WA": "conus", "ME": "conus"}
    assert RF.OUTSIDE_RADAR_GRID == {"GU", "AS", "MP"}
    assert RF.radar_states({"AK", "HI", "PR", "VI", "GU", "AS", "MP", "MA"}) == {"AK", "HI", "PR", "VI", "MA"}
    for r in G.REGIONS:
        assert G.item_name(24, r) == f"{r}_QPE_24H"
    with pytest.raises(ValueError):
        G.item_name(24, "guam")
    for p in [*JUNEAU, AK_WET, PRUDHOE]:
        assert G.in_extent(*p, G.ALASKA_EXTENT) and not G.in_extent(*p, G.CONUS_EXTENT)
    for p in [*SAN_JUAN, PR_WET]:
        assert G.in_extent(*p, G.CARIB_EXTENT) and not G.in_extent(*p, G.CONUS_EXTENT)
    assert G.in_extent(21.31, -157.86, G.HAWAII_EXTENT)


def test_the_real_regional_exports_hold_millimetres_and_no_coverage():
    a, prud = RASTERS["alaska"]
    (c,) = RASTERS["carib"]
    assert a.value(*AK_WET) == 4.9 and c.value(*PR_WET) == 7.9                  # identify's values there
    assert {a.value(*p) for p in JUNEAU} == {0.0} and {c.value(*p) for p in SAN_JUAN} == {0.0}
    assert prud.value(*PRUDHOE) is None and prud.raw(*PRUDHOE) == G.NO_COVERAGE
    assert G.no_coverage(prud, {"p": PRUDHOE}) == {"p"} and G.no_coverage(a, {"j": JUNEAU[0]}) == set()
    for g in (a, prud, c):
        assert abs(g.dx - G.CELL) < 1e-9 and abs(g.dy - G.CELL) < 1e-9


def test_identify_where_two_grids_overlap_is_read_from_the_points_own_region():
    vt = int(VALID.timestamp() * 1000)
    items = [{"attributes": {"name": G.item_name(h, r), "idp_validendtime": vt}} for h in RF.HOURS
             for r in ("carib", "conus")]                                       # interleaved, as at Key West
    vals = [str(9.0 if i % 2 == 0 else 1.0) for i in range(len(items))]        # carib 9, conus 1
    d = {"properties": {"Values": vals}, "catalogItems": {"features": items}}
    assert RF.parse_identify(d, "conus")["h24"] == 1.0 and RF.parse_identify(d, "carib")["h24"] == 9.0
    nocov = {"properties": {"Values": ["-3"] * 7}, "catalogItems": {"features": [
        {"attributes": {"name": G.item_name(h, "alaska"), "idp_validendtime": vt}} for h in RF.HOURS]}}
    m = RF.parse_identify(nocov, "alaska")
    assert m["h24"] is None and m["no_coverage"] is True
    assert "no_coverage" not in RF.parse_identify({**nocov, "properties": {"Values": ["nan"] * 7}}, "alaska")


def test_alaska_and_puerto_rico_are_read_from_their_own_grids(world):
    fake = RegionNOAA()
    out = RF.run(now=NOW, session=fake)
    m, r, regs = out["mrms"], out["requests"], out["mrms"]["regions"]
    assert list(regs) == ["conus", "alaska", "carib"]
    # one catalog query for every region; per region its tile's two exports (1 and 24 hours), locked to its own items
    assert r["mrms_query"] == 1 and r["mrms_export"] == 2 + 2 + 2 and r["mrms_statistics"] == 2
    assert r["mrms_identify"] == 3                                              # each region's check
    assert sorted(x for x, _ in fake.exports) == ["alaska"] * 2 + ["carib"] * 2 + ["conus"] * 2
    for region, bbox in fake.exports:
        xmin, ymin, xmax, ymax = (float(v) for v in bbox.split(","))
        assert G.in_extent((ymin + ymax) / 2, (xmin + xmax) / 2, G.REGIONS[region])
    assert regs["alaska"]["requests"] == {"mrms_export": 2, "mrms_identify": 1, "mrms_statistics": 1, "nws_stations": 1}
    for name, pts, wet, mm in (("alaska", [*JUNEAU, AK_WET], AK_WET, 4.9), ("carib", [*SAN_JUAN, PR_WET], PR_WET, 7.9)):
        o = regs[name]
        assert o["read"] == "grid" and o["fresh"] == o["counted"] == len(pts) and o["readings_ok"]
        assert o["grid"]["check"]["result"] == "agrees" and o["grid"]["tiles_read"] == 1
        assert o["valid_time"] == o["product_valid_time"] == RF.iso(VALID) and not o["stale_product"]
        # the unit: the region's own statistics over the 24-hour bound (93.3 and 53.9): millimetres, converted
        u = o["units"]
        assert u["units_read"] == "mm" and u["basis"] == "physical_bound" and u["statistics"]["max"] > 50
        assert o["units_last_determined"]["units_read"] == "mm"
        reading = out["points"][key(wet)]["mrms"]
        assert reading["h24"] == round(mm / 25.4, 2) and reading["units_read"] == "mm" and reading["read"] == "grid"
        assert reading["product"].endswith(f"({name}_QPE_24H)")
        for p in pts:
            assert out["points"][key(p)]["region"] == name and RF.is_fresh(out["points"][key(p)]["mrms"], NOW)
    assert out["permits"]["AK0023213"]["h24"] == round(4.9 / 25.4, 2) and out["permits"]["PR0021555"]["state"] == "PR"
    assert "alaska_QPE_24H" in out["permits"]["AK0023213"]["product"]
    assert m["fresh"] == m["readable"] == 20 + 4 + 9 and m["readings_ok"] and out["ok"] and RF.exit_code(out) == 0
    line = RF.summary_line(out, 1.0)
    assert "alaska by grid (1 of 1 tiles, 2 exports, 1 statistics), 4 fresh of 4, valid 2026-08-10T14:00:00Z" in line
    assert "carib by grid (1 of 1 tiles, 2 exports, 1 statistics), 9 fresh of 9" in line
    assert "MRMS 12: 1 query, 6 export, 3 identify, 2 statistics;" in line and "FALLBACK" not in line
    raw = [d for src, d in world["saved"] if src == "noaa-mrms-qpe"][-1]
    assert set(raw["regions"]) == {"alaska", "carib"} and raw["regions"]["alaska"]["products"]["24"]["tiles"]


def test_prudhoe_bay_without_radar_coverage_is_listed_never_read_and_never_fails_the_stage(world, monkeypatch):
    outs = lower48() + alaska(prudhoe=True)
    monkeypatch.setattr(RF, "cso_outfalls", lambda: outs)
    out = RF.run(now=NOW, session=RegionNOAA())
    m, a = out["mrms"], out["mrms"]["regions"]["alaska"]
    k = key(PRUDHOE)
    # its tile (-160,60) holds MRMS -3 at its one point: not a failed tile, no fallback, no identify for it
    assert a["grid"]["tiles_read"] == 2 and not a["grid"]["tiles_failed"] and not a["fallback"]["used"]
    assert m["outside_coverage"] == [k] and a["outside_coverage"] == [k] and a["counted"] == 4 == a["fresh"]
    assert "mrms" not in out["points"][k] and out["points"][k]["no_coverage"]["read_before"] is False
    assert out["permits"]["AKG320002"]["h24"] is None and out["permits"]["AKG320002"]["valid_time"] is None
    assert k not in m["failed"] and out["ok"] and m["readings_ok"] and RF.exit_code(out) == 0
    assert "(1 without radar coverage)" in RF.summary_line(out, 1.0)
    assert any("without radar coverage" in p and "AKG320002:006" in p for p in m["problems"])
    # an hour later: still listed, still not failing
    nxt = RF.run(now=NOW + timedelta(hours=1), session=RegionNOAA(), force=True)
    assert nxt["mrms"]["outside_coverage"] == [k] and nxt["points"][k]["no_coverage"]["since"] == RF.iso(NOW)
    assert nxt["ok"] and RF.exit_code(nxt) == 0
    # a region whose only point no radar sees reads nothing and does not fail
    monkeypatch.setattr(RF, "cso_outfalls", lambda: lower48() + [outfall("AKG320002", 6, "AK", *PRUDHOE)])
    only = RF.run(now=NOW, session=RegionNOAA(), force=True)
    assert only["mrms"]["regions"]["alaska"]["counted"] == 0 and only["mrms"]["regions"]["alaska"]["readings_ok"]
    assert only["ok"] and RF.exit_code(only) == 0


def test_a_point_read_before_that_loses_radar_coverage_is_an_outage_and_counted(world, monkeypatch):
    outs = lower48() + alaska()
    monkeypatch.setattr(RF, "cso_outfalls", lambda: outs)
    RF.run(now=NOW, session=RegionNOAA())
    d = json.loads((world["tmp"] / "rainfall.json").read_text())         # read the hour before
    for p in d["points"].values():
        if p.get("mrms"):
            p["mrms"].update(fetched_at=RF.iso(NOW - timedelta(hours=1)), valid_time=RF.iso(VALID - timedelta(hours=1)))
    (world["tmp"] / "rainfall.json").write_text(json.dumps(d))
    dark = {key(p): {h: -3.0 for h in RF.HOURS} for p in [*JUNEAU, AK_WET]}
    fake = RegionNOAA(wet={tuple(map(float, k.split(","))): v for k, v in dark.items()})
    out = RF.run(now=NOW, session=fake)
    a = out["mrms"]["regions"]["alaska"]
    assert a["outside_coverage"] == [] and a["fresh"] == 0 and a["counted"] == 4 and not a["readings_ok"]
    assert all(out["points"][k]["no_coverage"]["read_before"] for k in dark)
    assert RF.exit_code(out) == 1 and out["ok"] is False and out["error"].startswith("alaska: 0 of 4 points")


def test_a_stale_regional_product_fails_the_stage_loudly_and_shows_no_reading(world):
    out = RF.run(now=NOW, session=RegionNOAA(stale={"carib": 5}))
    m, c = out["mrms"], out["mrms"]["regions"]["carib"]
    assert c["product_valid_time"] == RF.iso(VALID - timedelta(hours=5)) and c["stale_product"]
    assert c["fresh"] == 0 and not c["readings_ok"] and m["regions"]["conus"]["readings_ok"]
    assert m["regions"]["alaska"]["readings_ok"] and not m["readings_ok"] and RF.exit_code(out) == 1
    assert out["ok"] is False and "carib: 0 of 9 points in the carib radar grid" in out["error"]
    assert "its product is valid to 2026-08-10T09:00:00Z" in out["error"]
    assert "STALE product valid 2026-08-10T09:00:00Z" in RF.summary_line(out, 1.0)
    # its readings, five hours old, are never shown as the permittee's this hour
    row = out["permits"]["PR0021555"]
    assert row["h24"] is None and row["valid_time"] is None and row["points_reporting"] == 0
    assert row["last_reading"]["valid_time"] == RF.iso(VALID - timedelta(hours=5))
    assert out["permits"]["AK0023213"]["h24"] is not None


def test_a_failed_regional_export_falls_back_in_that_region_only_and_keeps_its_unit(world):
    fake = RegionNOAA(fail={"alaska"})
    out = RF.run(now=NOW, session=fake)
    m, r, a = out["mrms"], out["requests"], out["mrms"]["regions"]["alaska"]
    assert a["read"] == "point" and a["fallback"]["used"] and a["fallback"]["read"] == 4 and a["fallback"]["cap"] == 25
    assert "grid read failed" in a["fallback"]["reason"] and not m["fallback"]["used"]        # the lower 48's is not
    assert a["requests"]["mrms_export"] == 4                    # its one tile's 24-hour export, twice, read twice
    assert a["requests"]["mrms_identify"] == 4 and a["requests"]["mrms_statistics"] == 1
    # the unit from the region's statistics (the catalog's 24-hour item), not the service's stated inches
    assert a["units"]["units_read"] == "mm" and a["units"]["basis"] == "physical_bound"
    assert out["points"][key(AK_WET)]["mrms"]["h24"] == round(4.9 / 25.4, 2)
    assert out["points"][key(AK_WET)]["mrms"]["read"] == "point"
    assert m["regions"]["carib"]["read"] == "grid" and not m["regions"]["carib"]["fallback"]["used"]
    assert m["readings_ok"] and RF.exit_code(out) == 0 and out["ok"] is False
    assert "alaska: per-point fallback (grid read failed" in out["error"]
    line = RF.summary_line(out, 1.0)
    assert "alaska by point, 4 fresh of 4" in line and "FALLBACK per point (grid read failed" in line
    assert r["mrms_identify"] == 4 + 2                          # the fallback's points, the two grids' checks


def test_a_regional_gauge_reading_inches_against_the_regions_bound_divides_nothing(world):
    pajn = (58.35, -134.58)
    fake = RegionNOAA(wet={pajn: {1: 0.15, 3: 0.15, 6: 0.15}}, gauges={"PAJN": [(9, 3.8)]})
    out = RF.run(now=NOW, session=fake)
    u = out["mrms"]["regions"]["alaska"]["units"]
    assert u["units_read"] == "in" and u["basis"] == "conflict" and u["factor"] == 1.0
    assert u["evidence"]["gauge_check"]["verdict"] == "in" and u["evidence"]["gauge_check"]["gauges"] == ["PAJN"]
    assert u["evidence"]["physical_bound"]["box_max"]["h24"] == 93.3
    assert out["mrms"]["regions"]["alaska"]["units_last_determined"] is None
    assert out["points"][key(AK_WET)]["mrms"]["h24"] == 4.9                   # the larger value: the safety side
    assert out["mrms"]["regions"]["carib"]["units"]["units_read"] == "mm"      # another region's unit unaffected


def test_a_point_outside_its_regions_grid_is_left_out_and_listed(world, monkeypatch):
    outs = lower48() + puerto_rico() + [outfall("PR0021555", 99, "PR", 18.44, 66.07)]    # its longitude's sign flipped
    monkeypatch.setattr(RF, "cso_outfalls", lambda: outs)
    fake = RegionNOAA()
    out = RF.run(now=NOW, session=fake)
    m = out["mrms"]
    assert m["outside_grid"] == ["18.44,66.07"] and m["regions"]["carib"]["outside_grid"] == ["18.44,66.07"]
    assert all(float(b.split(",")[2]) < -60 for _, b in fake.exports) and out["ok"] and RF.exit_code(out) == 0


def test_a_lower_48_only_run_asks_nothing_of_the_other_grids(world, monkeypatch):
    monkeypatch.setattr(RF, "cso_outfalls", lambda: lower48())
    fake = RegionNOAA()
    out = RF.run(now=NOW, session=fake)
    assert list(out["mrms"]["regions"]) == ["conus"] and {x for x, _ in fake.exports} == {"conus"}
    assert out["requests"].get("mrms_statistics") == 0 and "statistics" not in RF.summary_line(out, 1.0)
    for p in out["points"].values():
        assert p["mrms"]["h24"] == rain_at(p["lat"], p["lon"])
