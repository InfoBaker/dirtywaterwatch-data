"""The radar rainfall read as one MRMS grid an hour (ingest/mrms_grid.py, ingest/rainfall.py; docs/rain-likely.md):
the TIFF reader against synthetic grids and a real export, the box, the per-state thresholds of the mid-Atlantic
states, the per-point fallback, and the hourly request count against the per-point method it replaced.
Run from pipeline/: python -m pytest tests -q
"""
from __future__ import annotations

import json
import math
import random
import struct
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from build import rain_likely as RL  # noqa: E402
from build import rain_thresholds as RT  # noqa: E402
from common import DATA_DIR  # noqa: E402
from ingest import mrms_grid as G  # noqa: E402
from ingest import rainfall as RF  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
H = timedelta(hours=1)
NOW = datetime(2026, 8, 10, 14, 28, tzinfo=UTC)
VALID = datetime(2026, 8, 10, 14, 0, tzinfo=UTC)
RULES = json.loads((DATA_DIR / "rules.json").read_text())


# ---------------------------------------------------------------- a TIFF writer and an LZW encoder for the tests

def lzw_encode(data: bytes) -> bytes:
    """TIFF LZW as libtiff writes it: Clear first, codes MSB-first, the width growing one code early, a Clear
    when the table is full, EOI last."""
    bits: list[tuple[int, int]] = []
    table = {bytes([i]): i for i in range(256)}
    nxt, nbits = 258, 9
    bits.append((256, nbits))
    w = b""
    for c in data:
        wc = w + bytes([c])
        if wc in table:
            w = wc
            continue
        bits.append((table[w], nbits))
        table[wc] = nxt
        nxt += 1
        if nxt == 4094:
            bits.append((256, nbits))
            table = {bytes([i]): i for i in range(256)}
            nxt, nbits = 258, 9
        elif nxt > (1 << nbits) - 1:
            nbits += 1
        w = bytes([c])
    if w:
        bits.append((table[w], nbits))
        nxt += 1
        if nxt > (1 << nbits) - 1 and nbits < 12:
            nbits += 1
    bits.append((257, nbits))
    acc, n, out = 0, 0, bytearray()
    for code, nb in bits:
        acc = (acc << nb) | code
        n += nb
        while n >= 8:
            out.append((acc >> (n - 8)) & 0xFF)
            n -= 8
    if n:
        out.append((acc << (8 - n)) & 0xFF)
    return bytes(out)


def make_tiff(width: int, height: int, west: float, north: float, fn, tile: int | None = 16, lzw: bool = True,
              cell: float = 0.01) -> bytes:
    """A little-endian float32 GeoTIFF: pixel (row, col) = fn(lat, lon) at the pixel centre."""
    def pix(r, c):
        return fn(round(north - (r + 0.5) * cell, 6), round(west + (c + 0.5) * cell, 6))
    blocks = []
    if tile:
        across, down = -(-width // tile), -(-height // tile)
        for tr in range(down):
            for tc in range(across):
                vals = []
                for r in range(tr * tile, tr * tile + tile):
                    for c in range(tc * tile, tc * tile + tile):
                        vals.append(pix(r, c) if r < height and c < width else 0.0)
                blocks.append(struct.pack(f"<{len(vals)}f", *vals))
    else:
        rows = 7
        for r0 in range(0, height, rows):
            vals = [pix(r, c) for r in range(r0, min(height, r0 + rows)) for c in range(width)]
            blocks.append(struct.pack(f"<{len(vals)}f", *vals))
    blocks = [lzw_encode(b) if lzw else b for b in blocks]
    entries = {256: (4, [width]), 257: (4, [height]), 258: (3, [32]), 259: (3, [5 if lzw else 1]), 262: (3, [1]),
               277: (3, [1]), 284: (3, [1]), 317: (3, [1]), 339: (3, [3]),
               33550: (12, [cell, cell, 0.0]), 33922: (12, [0.0, 0.0, 0.0, west, north, 0.0])}
    if tile:
        entries.update({322: (3, [tile]), 323: (3, [tile]), 324: (4, [0] * len(blocks)),
                        325: (4, [len(b) for b in blocks])})
    else:
        entries.update({273: (4, [0] * len(blocks)), 278: (3, [7]), 279: (4, [len(b) for b in blocks])})
    fmt = {3: "H", 4: "I", 12: "d"}
    size = {3: 2, 4: 4, 12: 8}
    n = len(entries)
    ifd_at = 8
    extra_at = ifd_at + 2 + 12 * n + 4
    extra = bytearray()
    data_at = None

    def layout(offsets):
        nonlocal extra
        extra = bytearray()
        ifd = struct.pack("<H", n)
        for tag in sorted(entries):
            typ, vals = entries[tag]
            if tag in (324, 273):
                vals = offsets
            raw = struct.pack("<" + fmt[typ] * len(vals), *vals)
            if len(raw) <= 4:
                ifd += struct.pack("<HHI", tag, typ, len(vals)) + raw.ljust(4, b"\0")
            else:
                ifd += struct.pack("<HHII", tag, typ, len(vals), extra_at + len(extra))
                extra += raw
        return ifd + b"\0\0\0\0"
    layout([0] * len(blocks))
    data_at = extra_at + len(extra)
    offsets, pos = [], data_at
    for b in blocks:
        offsets.append(pos)
        pos += len(b)
    ifd = layout(offsets)
    return b"II*\0" + struct.pack("<I", ifd_at) + ifd + bytes(extra) + b"".join(blocks)


def rain_at(lat: float, lon: float, hours: int = 24) -> float:
    """A synthetic rainfall field (inches): distinct per hundredth, never negative, 1 h below 24 h below 72 h."""
    base = ((round(lat * 100) % 7) * 0.1 + (round(-lon * 100) % 5) * 0.01)
    return round({1: base / 4, 24: base, 48: base + 0.1, 72: base + 0.2}.get(hours, base), 2)


# ---------------------------------------------------------------- the reader

def test_lzw_decodes_what_libtiff_style_encoding_writes():
    rnd = random.Random(7)
    for data in (bytes(100_000), rnd.randbytes(40_000), struct.pack("<4000f", *[rnd.choice((0.0, 0.25, 1.5))
                                                                                for _ in range(4000)]), b"ab" * 3):
        assert G.lzw_decode(lzw_encode(data)) == data


@pytest.mark.parametrize("tile,lzw", [(16, True), (None, True), (16, False), (None, False)])
def test_grid_samples_a_synthetic_tiff_at_each_point(tile, lzw):
    pts = [(41.27, -72.94), (41.30, -72.80), (41.40, -72.75), (41.33, -72.88)]
    box = G.grid_box(pts)
    assert (box["width"], box["height"]) == (20 + 2 * G.MARGIN_CELLS, 14 + 2 * G.MARGIN_CELLS)
    assert box["xmin"] == -72.995 and box["ymax"] == 41.455          # pixel edges halfway between hundredths

    def fn(lat, lon):
        if (round(lat, 2), round(lon, 2)) == (41.30, -72.80):
            return -3.0                                              # MRMS no coverage
        if (round(lat, 2), round(lon, 2)) == (41.40, -72.75):
            return float("nan")
        return rain_at(lat, lon)
    g = G.Grid(make_tiff(box["width"], box["height"], box["xmin"], box["ymax"], fn, tile=tile, lzw=lzw))
    assert G.check_georef(g, box) == []
    got = G.sample(g, {f"{a:.2f},{b:.2f}": (a, b) for a, b in pts})
    assert got == {"41.27,-72.94": rain_at(41.27, -72.94), "41.30,-72.80": None, "41.40,-72.75": None,
                   "41.33,-72.88": rain_at(41.33, -72.88)}
    assert g.value(41.271, -72.938) == rain_at(41.27, -72.94)          # an unrounded point: the pixel it is in
    assert g.value(45.0, -72.9) is None and g.value(41.3, -60.0) is None  # outside the box
    shifted = dict(box, xmin=box["xmin"] + 0.01)
    assert G.check_georef(g, shifted) and G.check_georef(g, dict(box, width=box["width"] + 1))


def test_a_real_export_equals_identify_at_the_point():
    """exportImage of conus_QPE_24H valid 2026-11-03T13:00Z over Calais, Maine (LZW tiles as the service writes
    them), and identify at three points of it at the same time: 3.8, 5.9 and 4.6 in."""
    g = G.Grid((FIXTURES / "mrms-qpe-24h-20261103T13Z.tif").read_bytes())
    box = G.grid_box([(45.10, -67.40), (45.25, -67.20)])
    assert G.check_georef(g, box) == [] and g.compression == 5
    assert (g.value(45.19, -67.27), g.value(45.12, -67.38), g.value(45.153, -67.334)) == (3.8, 5.9, 4.6)


def test_catalog_answer_gives_object_ids_and_valid_times():
    d = {"features": [{"attributes": {"objectid": 5, "name": "conus_QPE_24H", "idp_validendtime": 1793710800000}},
                      {"attributes": {"objectid": 4, "name": "conus_QPE_01H", "idp_validendtime": 1793707200000}},
                      {"attributes": {"objectid": 6, "name": "conus_QPE_01H", "idp_validendtime": 1793710800000}}]}
    assert G.parse_catalog(d) == {"conus_QPE_24H": {"objectid": 5, "valid_time": "2026-11-03T13:00:00Z"},
                                  "conus_QPE_01H": {"objectid": 6, "valid_time": "2026-11-03T13:00:00Z"}}
    p = G.export_params(5, G.grid_box([(42.0, -72.0)]))
    assert json.loads(p["mosaicRule"]) == {"mosaicMethod": "esriMosaicLockRaster", "lockRasterIds": [5]}
    assert p["interpolation"] == "RSP_NearestNeighbor" and p["format"] == "tiff" and p["noData"] == "-9999"


# ---------------------------------------------------------------- thresholds per state

def test_mid_atlantic_thresholds_follow_each_states_published_trigger():
    fb = RULES["rain_likely"]["fallback"]
    got = {st: RL.threshold_for(f"{st}0000001", st, {}, RULES) for st in ("NY", "PA", "MD", "VA", "DC")}
    assert {st: t["threshold_in"] for st, t in got.items()} == {"NY": 0.1, "PA": 0.1, "MD": 0.1, "VA": 0.1, "DC": 0.1}
    assert got["MD"]["rule"] == "rain_likely.fallback.by_state.MD" and "Anne Arundel" in got["MD"]["source"]
    assert got["DC"]["rule"] == "rain_likely.fallback.by_state.DC" and "Anacostia Riverkeeper" in got["DC"]["source"]
    assert got["NY"]["rule"] == "rain_likely.fallback.by_state.NY" and "750-2.7" in got["NY"]["source"]
    for st in ("PA", "VA"):                                          # no amount documented: the default
        assert got[st]["rule"] == "rain_likely.fallback.default" and got[st]["source"] == fb["default"]["source"]
    for st, t in got.items():
        assert t["basis"] == "published" and t["text"] and t["source"]
        assert RT.fallback_for(st, RULES)["threshold_in"] == t["threshold_in"]
    for st in ("MD", "DC"):                                          # their advice runs 48 hours, as the tail does
        assert "48 hours" in fb["by_state"][st]["basis"] and RULES["rain_likely"]["tail_hours"] == 48


def test_the_registry_outfalls_join_and_new_jersey_permits_on_the_shared_site_stay_there(tmp_path, monkeypatch):
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "nj-cso-likely.json").write_text(json.dumps({"permittees": [{"npdes_permit": "NJ0108880"}]}))
    rows = [{"npdes_permit": "PA0026689", "state": "PA", "outfall": "001", "outfall_status": "CSO", "permittee": "P",
             "lat": 39.95, "lon": -75.14, "water_slug": "delaware-river-pa", "match": "geometry+name", "distance_m": 40},
            {"npdes_permit": "PA0026689", "state": "PA", "outfall": "002", "outfall_status": "CLS", "lat": 39.96,
             "lon": -75.14},
            {"npdes_permit": "MD0021601", "state": "MD", "outfall": "003", "outfall_status": "TCS", "lat": 39.65,
             "lon": -78.76, "water_slug": "wills-creek-md", "match": "name_only", "distance_m": None},
            {"npdes_permit": "NJ0108812", "state": "NJ", "outfall": "004", "outfall_status": "CSO", "lat": 39.94,
             "lon": -75.12},
            {"npdes_permit": "NJ0108880", "state": "NJ", "outfall": "025", "outfall_status": "CSO", "lat": 40.92,
             "lon": -74.14},
            {"npdes_permit": "DC0021199", "state": "DC", "outfall": "005", "outfall_status": "CSO", "lat": None,
             "lon": None}]
    (tmp_path / "outfalls-mid-atlantic.json").write_text(json.dumps({"outfalls": rows}))
    monkeypatch.setattr(RF, "DATA_DIR", tmp_path)
    monkeypatch.setattr(RF, "BUILD_DIR", tmp_path / "build")
    got = RF.cso_outfalls()
    # Camden City (not on the shared site) is read by the radar; Paterson (on the site) keeps the site
    assert [(o["permit"], o["outfall"], o["state"], o["source"]) for o in got] == [
        ("PA0026689", "001", "PA", "echo-mid-atlantic"), ("MD0021601", "003", "MD", "echo-mid-atlantic"),
        ("NJ0108812", "004", "NJ", "echo-mid-atlantic")]
    assert got[0]["water_slug"] == "delaware-river-pa" and got[0]["water_match"] == "geometry+name"


# ---------------------------------------------------------------- the run: grid, check, fallback, requests

class Resp:
    def __init__(self, status=200, body=None, content=None, ctype="application/json"):
        self.status_code, self._body = status, body
        self.content = content if content is not None else json.dumps(body).encode()
        self.headers = {"content-type": ctype}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._body


class FakeNOAA:
    """The MRMS ImageServer and api.weather.gov as the run sees them, from rain_at()."""
    IDS = {1: 101, 24: 124, 48: 148, 72: 172}

    def __init__(self, export_fails=False, identify_off=0.0):
        self.headers: dict = {}
        self.export_fails, self.identify_off = export_fails, identify_off
        self.calls: list[str] = []

    def get(self, url, params=None, headers=None, timeout=None):
        kind = RF.request_kind(url)
        self.calls.append(kind)
        vt = int(VALID.timestamp() * 1000)
        if kind == "mrms_query":
            return Resp(body={"features": [{"attributes": {"objectid": i, "name": G.item_name(h), "idp_validendtime": vt}}
                                           for h, i in self.IDS.items()]})
        if kind == "mrms_export":
            if self.export_fails:
                return Resp(status=500, body={"error": "x"})
            h = {i: h for h, i in self.IDS.items()}[json.loads(params["mosaicRule"])["lockRasterIds"][0]]
            xmin, ymin, xmax, ymax = (float(v) for v in params["bbox"].split(","))
            w, hh = (int(v) for v in params["size"].split(","))
            return Resp(content=make_tiff(w, hh, xmin, ymax, lambda la, lo: rain_at(la, lo, h), tile=64, lzw=False),
                        ctype="image/tiff")
        if kind == "mrms_identify":
            g = json.loads(params["geometry"])
            lat, lon = g["y"], g["x"]
            names = [G.item_name(h) for h in RF.HOURS]
            vals = [str(rain_at(lat, lon, h) + (self.identify_off if h == 24 else 0)) for h in RF.HOURS]
            return Resp(body={"properties": {"Values": vals}, "catalogItems": {"features": [
                {"attributes": {"name": n, "idp_validendtime": vt}} for n in names]}})
        if kind == "nws_points":
            lat, lon = (float(v) for v in url.rsplit("/", 1)[1].split(","))
            return Resp(body={"properties": {"gridId": "BOX", "gridX": round(-lon * 40), "gridY": round(lat * 40)}})
        if kind == "nws_gridpoints":
            return Resp(body={"properties": {"updateTime": "2026-08-10T12:00:00+00:00", "quantitativePrecipitation": {
                "uom": "wmoUnit:mm", "values": [{"validTime": "2026-08-10T12:00:00+00:00/PT6H", "value": 2.0}]}}})
        raise AssertionError(url)


def synthetic_outfalls():
    """319 New England points (79 permittees) and 908 mid-Atlantic points (184 permittees), as on 2026-11-03."""
    out = []
    ne = [(round(42.0 + 0.03 * i, 2), round(-75.0 + 0.03 * j, 2)) for i in range(11) for j in range(29)]
    mid = [(round(40.0 + 0.03 * i, 2), round(-75.0 + 0.03 * j, 2)) for i in range(28) for j in range(33)][:908]
    for n, (lat, lon) in enumerate(ne):
        out.append({"permit": f"MA{n % 79:07d}", "outfall": str(n), "state": "MA", "name": "x", "lat": lat, "lon": lon,
                    "water_slug": None, "water_match": None, "distance_m": None, "source": "echo"})
    for n, (lat, lon) in enumerate(mid):
        st = ("PA", "NY", "MD", "VA", "DC")[(n % 184) % 5]
        out.append({"permit": f"{st}{n % 184:07d}", "outfall": str(n), "state": st, "name": "y", "lat": lat, "lon": lon,
                    "water_slug": None, "water_match": None, "distance_m": None, "source": "echo-mid-atlantic"})
    return out, len(ne)


@pytest.fixture
def world(tmp_path, monkeypatch):
    outs, n_ne = synthetic_outfalls()
    monkeypatch.setattr(RF, "cso_outfalls", lambda: outs)
    monkeypatch.setattr(RF, "OUT", tmp_path / "rainfall.json")
    monkeypatch.setattr(RF, "HISTORY", tmp_path / "rainfall-history.json")
    monkeypatch.setattr(RF, "GRIDS", tmp_path / "nws-gridpoints.json")
    monkeypatch.setattr(RF, "save_raw", lambda *a, **k: None)
    monkeypatch.setattr(RF.time, "sleep", lambda s: None)
    return {"outfalls": outs, "n_ne": n_ne, "tmp": tmp_path}


def steady(world):
    """An hour like any other: every point's NWS cell known, a third of the cells due, the history complete."""
    pts = RF.group_points(world["outfalls"])
    grids = {k: {"grid": f"BOX/{round(-p['lon'] * 40)},{round(p['lat'] * 40)}"} for k, p in pts.items()}
    cells = sorted({g["grid"] for g in grids.values()})
    data = {c: {"update_time": "x", "values": [], "fetched_at": RF.iso(NOW - ((i % 3) + 1) * H - timedelta(minutes=1))}
            for i, c in enumerate(cells)}
    (world["tmp"] / "nws-gridpoints.json").write_text(json.dumps(grids))
    (world["tmp"] / "rainfall.json").write_text(json.dumps({"grids": data}))
    start = RF.hour_floor(NOW) - timedelta(hours=RF.HISTORY_DAYS * 24 - 1)
    perms = {o["permit"] for o in world["outfalls"]}
    (world["tmp"] / "rainfall-history.json").write_text(json.dumps(
        {"start": RF.iso(start), "permits": {p: [0.0] * (RF.HISTORY_DAYS * 24) for p in perms}}))
    ne_cells = {grids[k]["grid"] for k, p in pts.items() if any(s == "MA" for s in p["states"])}
    # before the grid: one identify per New England point, and a third of its forecast cells, each hour
    return sum(1 for p in pts.values() if "MA" in p["states"]) + math.ceil(len(ne_cells) / 3)


def test_one_grid_an_hour_samples_every_point_within_twice_the_old_request_count(world):
    baseline = steady(world)
    fake = FakeNOAA()
    out = RF.run(now=NOW, session=fake)
    r = out["requests"]
    assert r["mrms_query"] == 1 and r["mrms_export"] == 2 and r["mrms_identify"] == 1 and r["noaa_mrms"] == 4
    assert r["nws_points"] == 0 and r["total"] == len(fake.calls) <= 2 * baseline
    m = out["mrms"]
    assert m["read"] == "grid" and m["fetched"] == m["points"] == m["fresh"] == 319 + 908 and out["ok"]
    assert m["grid"]["check"]["result"] == "agrees" and m["grid"]["valid_time"] == RF.iso(VALID)
    for k, p in out["points"].items():
        assert p["mrms"]["h24"] == rain_at(p["lat"], p["lon"]) and p["mrms"]["h1"] == rain_at(p["lat"], p["lon"], 1)
        assert p["mrms"]["read"] == "grid" and p["mrms"]["valid_time"] == RF.iso(VALID)
    row = out["permits"]["PA0000000"]
    assert row["read"] == "grid" and "conus_QPE_24H" in row["product"] and row["state"] == "PA"
    assert row["h24"] == max(rain_at(*map(float, k.split(","))) for k in row["points"])
    # the same hour again: nothing to read
    again = RF.run(now=NOW + timedelta(minutes=10), session=FakeNOAA())
    assert again["requests"]["noaa_mrms"] == 0 and again["mrms"]["read"] is None and again["ok"]


def test_a_first_reading_adds_the_48_and_72_hour_grids_and_caps_the_forecast_lookups(world):
    baseline = steady(world)
    for f in ("nws-gridpoints.json", "rainfall.json", "rainfall-history.json"):
        (world["tmp"] / f).unlink()
    fake = FakeNOAA()
    out = RF.run(now=NOW, session=fake)
    r = out["requests"]
    assert r["mrms_export"] == 4 and r["nws_points"] == RF.LOOKUP_MAX and r["total"] <= 2 * baseline
    assert out["qpf"]["lookups_deferred"] == 319 + 908 - RF.LOOKUP_MAX
    hist = json.loads((world["tmp"] / "rainfall-history.json").read_text())
    arr = hist["permits"]["MD0000002"]
    assert arr[-1] is not None and arr[-25] is not None and arr[-49] is not None    # the implied windows filled


def test_a_failed_grid_falls_back_to_points_one_per_permittee_first(world):
    baseline = steady(world)
    fake = FakeNOAA(export_fails=True)
    out = RF.run(now=NOW, session=fake)
    r = out["requests"]
    assert r["mrms_identify"] == RF.FALLBACK_MAX_CALLS and r["total"] <= 2 * baseline
    assert out["mrms"]["read"] == "point" and not out["ok"]          # most points keep the last reading
    read = [k for k, p in out["points"].items() if (p.get("mrms") or {}).get("read") == "point"]
    assert len(read) == RF.FALLBACK_MAX_CALLS
    every = {o["permit"] for o in world["outfalls"]}
    assert {p for k in read for p in out["points"][k]["permits"]} == every   # every permittee has a reading
    assert any("per-point fallback" in p for p in out["mrms"]["problems"])


def test_a_grid_that_disagrees_with_identify_is_not_used(world):
    steady(world)
    out = RF.run(now=NOW, session=FakeNOAA(identify_off=0.5))
    assert out["mrms"]["read"] == "point" and out["mrms"]["grid"]["used"] is False
    assert "check at" in out["mrms"]["grid"]["errors"][-1]


def test_fallback_order_takes_each_permittees_wettest_point_first():
    pts = {"a": {"permits": ["P1"], "mrms": {"h24": 0.1}}, "b": {"permits": ["P1"], "mrms": {"h24": 0.9}},
           "c": {"permits": ["P2"], "mrms": None}, "d": {"permits": ["P1", "P2"], "mrms": {"h24": 0.5}}}
    assert RF.fallback_order(pts, list(pts), 10) == ["b", "d", "a", "c"]
    assert RF.fallback_order(pts, list(pts), 2) == ["b", "d"]


# ---------------------------------------------------------------- the caution and its coverage

def test_a_mid_atlantic_caution_cites_the_grid_product_and_the_threshold_source():
    now = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
    n = 90 * 24
    start = now - (n - 1) * H
    waters = {"wills-creek-md": {"slug": "wills-creek-md", "kind": "river", "state": "MD"},
              "test-run-pa": {"slug": "test-run-pa", "kind": "river", "state": "PA"}}

    def permit(st, slug, h24):
        return {"name": f"{st} sewer", "state": st, "valid_time": RF.iso(now), "h24": h24, "h24_point": "39.65,-78.76",
                "read": "grid", "product": RF.PRODUCT, "qpf_24h_in": 0.0,
                "outfalls": [{"outfall": "003", "water_slug": slug, "water_match": "name_only", "point": "39.65,-78.76"}]}
    rain = {"rainfall": {"fetched_at": RF.iso(now), "ok": True, "mrms": {"valid_time": RF.iso(now), "read": "grid"},
                         "permits": {"MD0021601": permit("MD", "wills-creek-md", 0.6),
                                     "PA0026689": permit("PA", "test-run-pa", 0.4)}},
            "history": {"start": RF.iso(start), "permits": {"MD0021601": [None] * (n - 3) + [0.0, 0.6, 0.6],
                                                            "PA0026689": [None] * (n - 3) + [0.0, 0.08, 0.4]}},
            "thresholds": {}, "dischargers": {}}
    by_water, _, block = RL.compute(rain, RULES, [], now, now - 24 * H, waters, [], {}, lambda r, w: [])
    md = by_water["wills-creek-md"][0]["rain"]
    assert md["threshold_in"] == 0.1 and md["threshold_rule"] == "rain_likely.fallback.by_state.MD"   # the site default, stricter than the local half-inch advice
    assert "Anne Arundel" in md["threshold_source"] and md["rainfall_read"] == "grid"
    assert "conus_QPE_24H" in md["rainfall_product"] and md["valid_time"] == RF.iso(now)
    assert by_water["wills-creek-md"][0]["placement"] == "unmodeled"
    pa = by_water["test-run-pa"][0]["rain"]
    assert pa["threshold_in"] == 0.1 and pa["threshold_rule"] == "rain_likely.fallback.default" and pa["threshold_source"]
    assert block["permits"]["MD0021601"]["status"] == "likely" and block["rainfall"]["read"] == "grid"
    # MD at 0.05 in: below the 0.1 in trigger
    rain["history"]["permits"]["MD0021601"][-1] = 0.05
    rain["history"]["permits"]["MD0021601"][-2] = 0.05
    by_water, _, block = RL.compute(rain, RULES, [], now, now - 24 * H, waters, [], {}, lambda r, w: [])
    assert "wills-creek-md" not in by_water and block["permits"]["MD0021601"]["status"] == "below"


def test_coverage_names_the_grid_for_radar_states_and_leaves_new_jersey_as_it_was():
    block = {"enabled": True, "rainfall": {"read": "grid"}, "permits": {
        "MD0021601": {"state": "MD", "threshold_basis": "published", "threshold_in": 0.5, "rainfall_read": "grid",
                      "waters": ["wills-creek-md"]},
        "PA0026689": {"state": "PA", "threshold_basis": "published", "threshold_in": 0.1, "rainfall_read": "grid",
                      "waters": ["a-pa", "b-pa"]},
        "MA0101613": {"state": "MA", "threshold_basis": "history", "threshold_in": 0.23, "rainfall_read": "grid",
                      "waters": ["c-ma"]},
        "MA0100552": {"state": "MA", "threshold_basis": "published", "threshold_in": 0.1, "rainfall_read": "grid",
                      "waters": ["d-ma"]},
        "NJ0108812": {"state": "NJ", "threshold_basis": "site_flag", "threshold_in": None, "waters": ["e-nj"]}}}
    cov = RL.caution_coverage(block, {"MD": {"MD0021601"}, "PA": {"PA0026689", "PA0000001"}, "NJ": {"NJ0108812", "NJ2"},
                                      "VA": {"VA0063177"}})
    md, pa, ma, nj, va = (cov[s] for s in ("MD", "PA", "MA", "NJ", "VA"))
    assert md["covered"] and md["methods"] == ["radar"] and md["rainfall_read"] == ["grid"] and md["threshold_in"] == 0.5
    assert md["method"] == "NOAA MRMS radar rainfall: one radar grid an hour, sampled at each outfall"
    assert "against the published amount of 0.5 in" in md["sentence"]
    assert pa["covered"] and "1 of the 2" in pa["sentence"] and pa["sources"] == [RL.SOURCE_ID]
    assert "threshold_in" not in ma and "own threshold (or a published one)" in ma["sentence"]
    assert set(nj) == {"covered", "methods", "permits", "waters", "sources", "cso_permits", "sentence"}
    assert nj["methods"] == ["site_flag"] and "njcsonotifications.com" in nj["sentence"]
    assert not va["covered"] and va["sentence"].startswith('No "discharge likely" caution here')
