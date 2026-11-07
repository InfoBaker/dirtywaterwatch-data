"""NOAA MRMS radar-only rainfall as one grid per accumulation per hour, sampled at every outfall point.

Used by ingest/rainfall.py (docs/rain-likely.md); not a feed. In place of one ImageServer `identify` per
outfall point per hour, the hour's catalog items are looked up once (`query`: object id and valid end time
of conus_QPE_01H and conus_QPE_24H, and of the 48 and 72-hour items when the history needs its earlier
windows filled) and each item is exported once over a box around every outfall point (`exportImage`,
locked to that object id, EPSG:4326, 0.01 degree pixels centred on the hundredths the points are rounded
to, nearest neighbour, float32 GeoTIFF with LZW compression, no data as -9999). A pixel then holds what
`identify` answers at the point (checked against identify at six points on 2026-11-03: equal to the
hundredth). Sampling is local: the TIFF is read here (tiles or strips, LZW or none) with the standard
library only.

The values are as the service answers them: it states inches but answered millimetres (found 2026-11-07); the unit
is decided in ingest/rainfall.py (decide_units) from the box maximum (Grid.max_read) and a gauge check, and
millimetres converted there, before anything uses them.

Pure except catalog() and export(), which take a requests session.
"""
from __future__ import annotations

import json
import math
import re
import struct
import sys
from array import array
from datetime import UTC, datetime

MRMS_URL = "https://mapservices.weather.noaa.gov/raster/rest/services/obs/mrms_qpe/ImageServer"
CELL = 0.01                    # degrees: the MRMS grid and the rounding of the outfall points
MARGIN_CELLS = 5               # pixels of margin around the outfall points
MAX_WIDTH, MAX_HEIGHT = 15000, 4100          # the service's maxImageWidth / maxImageHeight
NODATA = -9999.0
ITEM = "conus_QPE_{h:02d}H"


def item_name(hours: int) -> str:
    return ITEM.format(h=hours)


def iso(t: datetime | None) -> str | None:
    return t.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z") if t else None


# ---------------------------------------------------------------- the box

def grid_box(points) -> dict:
    """The export box for points [(lat, lon)]: pixel centres on the hundredths (indices are the coordinates
    times 100), MARGIN_CELLS around the outermost points. {xmin, ymin, xmax, ymax, width, height, i0, j1}:
    i0 the column index of the westernmost centre, j1 the row index (latitude x 100) of the northernmost."""
    pts = [(float(a), float(b)) for a, b in points]
    if not pts:
        raise ValueError("no points")
    i0 = math.floor(min(lon for _, lon in pts) * 100 + 0.5) - MARGIN_CELLS
    i1 = math.floor(max(lon for _, lon in pts) * 100 + 0.5) + MARGIN_CELLS
    j0 = math.floor(min(lat for lat, _ in pts) * 100 + 0.5) - MARGIN_CELLS
    j1 = math.floor(max(lat for lat, _ in pts) * 100 + 0.5) + MARGIN_CELLS
    w, h = i1 - i0 + 1, j1 - j0 + 1
    if w > MAX_WIDTH or h > MAX_HEIGHT:
        raise ValueError(f"box {w} x {h} pixels is over the service's limit")
    return {"xmin": round((i0 - 0.5) / 100, 3), "ymin": round((j0 - 0.5) / 100, 3),
            "xmax": round((i1 + 0.5) / 100, 3), "ymax": round((j1 + 0.5) / 100, 3), "width": w, "height": h,
            "i0": i0, "j1": j1}


# ---------------------------------------------------------------- the TIFF

TYPES = {1: ("B", 1), 2: ("s", 1), 3: ("H", 2), 4: ("I", 4), 11: ("f", 4), 12: ("d", 8), 16: ("Q", 8)}


def lzw_decode(data: bytes) -> bytes:
    """TIFF LZW (compression 5): MSB-first codes of 9 to 12 bits, Clear 256, EOI 257, the width growing
    one code early (as libtiff writes it)."""
    out = bytearray()
    table: list[bytes] = [bytes([i]) for i in range(256)] + [b"", b""]
    nbits, pos, end = 9, 0, len(data) * 8
    prev: bytes | None = None
    padded = bytes(data) + b"\0\0\0"
    while pos + nbits <= end:
        b = pos >> 3
        code = (int.from_bytes(padded[b:b + 3], "big") >> (24 - (pos & 7) - nbits)) & ((1 << nbits) - 1)
        pos += nbits
        if code == 256:
            del table[258:]
            nbits, prev = 9, None
            continue
        if code == 257:
            break
        if prev is None:
            if code >= len(table):
                raise ValueError("LZW: first code after a clear is not in the table")
            entry = table[code]
        elif code < len(table):
            entry = table[code]
            table.append(prev + entry[:1])
        elif code == len(table):
            entry = prev + prev[:1]
            table.append(entry)
        else:
            raise ValueError(f"LZW: code {code} beyond the table ({len(table)})")
        out += entry
        prev = entry
        if len(table) + 1 >= (1 << nbits) and nbits < 12:
            nbits += 1
    return bytes(out)


class Grid:
    """A single-band float32 GeoTIFF in EPSG:4326 (as exportImage writes it), read lazily by tile or strip.
    value(lat, lon) is the pixel containing the point; None outside the grid, for NaN and for negative
    values (MRMS writes -3 for no coverage; the export writes NODATA)."""

    def __init__(self, data: bytes):
        self.data = data
        if data[:4] not in (b"II*\0", b"MM\0*"):
            raise ValueError("not a TIFF")
        self.e = "<" if data[:2] == b"II" else ">"
        tags = self._ifd(struct.unpack(self.e + "I", data[4:8])[0])
        self.width, self.height = int(tags[256][0]), int(tags[257][0])
        bps = tags.get(258, (32,))[0]
        fmt = tags.get(339, (1,))[0]
        self.compression = tags.get(259, (1,))[0]
        predictor = tags.get(317, (1,))[0]
        if (bps, fmt) != (32, 3) or tags.get(277, (1,))[0] != 1:
            raise ValueError(f"not one float32 band (bits {bps}, format {fmt})")
        if self.compression not in (1, 5) or predictor != 1:
            raise ValueError(f"unsupported compression {self.compression} / predictor {predictor}")
        scale, tie = tags.get(33550), tags.get(33922)
        if not scale or not tie or len(tie) < 6:
            raise ValueError("no georeference (ModelPixelScale / ModelTiepoint)")
        self.dx, self.dy = float(scale[0]), float(scale[1])
        self.x0 = float(tie[3]) - float(tie[0]) * self.dx       # the west edge of column 0
        self.y0 = float(tie[4]) + float(tie[1]) * self.dy       # the north edge of row 0
        if 322 in tags:
            self.tw, self.th = int(tags[322][0]), int(tags[323][0])
            self.offsets, self.counts = tags[324], tags[325]
            self.across = -(-self.width // self.tw)
        else:
            self.tw, self.th = self.width, int(tags.get(278, (self.height,))[0])
            self.offsets, self.counts = tags[273], tags[279]
            self.across = 1
        self._blocks: dict[int, bytes] = {}

    def _ifd(self, off: int) -> dict[int, tuple]:
        d, e = self.data, self.e
        n = struct.unpack(e + "H", d[off:off + 2])[0]
        tags = {}
        for i in range(n):
            p = off + 2 + 12 * i
            tag, typ, cnt = struct.unpack(e + "HHI", d[p:p + 8])
            if typ not in TYPES:
                continue
            ch, size = TYPES[typ]
            raw = d[p + 8:p + 12] if size * cnt <= 4 else d[struct.unpack(e + "I", d[p + 8:p + 12])[0]:][:size * cnt]
            tags[tag] = (raw[:cnt],) if typ == 2 else struct.unpack(e + ch * cnt, raw[:size * cnt])
        return tags

    def _block(self, k: int) -> bytes:
        if k not in self._blocks:
            raw = self.data[self.offsets[k]:self.offsets[k] + self.counts[k]]
            self._blocks[k] = lzw_decode(raw) if self.compression == 5 else bytes(raw)
        return self._blocks[k]

    def pixel(self, row: int, col: int) -> float | None:
        if not (0 <= row < self.height and 0 <= col < self.width):
            return None
        k = (row // self.th) * self.across + col // self.tw
        off = ((row % self.th) * self.tw + col % self.tw) * 4
        b = self._block(k)
        if off + 4 > len(b):
            raise ValueError(f"block {k} is short ({len(b)} bytes)")
        return struct.unpack(self.e + "f", b[off:off + 4])[0]

    def cell(self, lat: float, lon: float) -> tuple[int, int]:
        return math.floor((self.y0 - float(lat)) / self.dy), math.floor((float(lon) - self.x0) / self.dx)

    def value(self, lat: float, lon: float) -> float | None:
        v = self.pixel(*self.cell(lat, lon))
        if v is None or v != v or v < 0:
            return None
        return round(v, 2)

    def max_read(self) -> float | None:
        """The largest value (NaN and negatives left out) in the blocks read so far: after sample(), every block
        that holds an outfall point, the box maximum the reader decides the grid's unit from (ingest/rainfall.py
        decide_units). The blocks not read are not decoded for it (a box can be millions of pixels)."""
        best = None
        for b in self._blocks.values():
            a = array("f")
            a.frombytes(b[:len(b) // 4 * 4])
            if (self.e == "<") != (sys.byteorder == "little"):
                a.byteswap()
            m = max((v for v in a if v == v and v >= 0), default=None)
            if m is not None and (best is None or m > best):
                best = m
        return round(best, 2) if best is not None else None

    def meta(self) -> dict:
        return {"width": self.width, "height": self.height, "west": round(self.x0, 6), "north": round(self.y0, 6),
                "pixel_deg": [round(self.dx, 9), round(self.dy, 9)], "compression": self.compression,
                "blocks_read": len(self._blocks), "blocks": len(self.offsets)}


def check_georef(g: Grid, box: dict) -> list[str]:
    """The answer covers the box asked for, at 0.01 degree: problems, if any (a shift would pair points
    with the wrong pixels)."""
    probs = []
    if (g.width, g.height) != (box["width"], box["height"]):
        probs.append(f"size {g.width} x {g.height}, asked {box['width']} x {box['height']}")
    if abs(g.dx - CELL) > 1e-6 or abs(g.dy - CELL) > 1e-6:
        probs.append(f"pixel {g.dx} x {g.dy} degrees, asked {CELL}")
    if abs(g.x0 - box["xmin"]) > CELL / 4 or abs(g.y0 - box["ymax"]) > CELL / 4:
        probs.append(f"origin {g.x0},{g.y0}, asked {box['xmin']},{box['ymax']}")
    return probs


# ---------------------------------------------------------------- the service

def parse_catalog(d: dict) -> dict[str, dict]:
    """{item name: {objectid, valid_time}} from a catalog query answer; the latest valid time wins."""
    out: dict[str, dict] = {}
    for f in (d or {}).get("features") or []:
        a = f.get("attributes") or {}
        name, oid, vt = a.get("name"), a.get("objectid"), a.get("idp_validendtime")
        if not name or oid is None or vt is None:
            continue
        if name not in out or vt > out[name]["_vt"]:
            out[name] = {"objectid": int(oid), "valid_time": iso(datetime.fromtimestamp(vt / 1000, UTC)), "_vt": vt}
    return {k: {kk: vv for kk, vv in v.items() if kk != "_vt"} for k, v in out.items()}


def catalog(session, names: list[str], timeout: int = 30) -> tuple[dict, dict]:
    """One `query` for the named catalog items: (parsed, the answer)."""
    for n in names:
        if not re.fullmatch(r"conus_QPE_\d\dH", n):
            raise ValueError(f"unexpected item name {n!r}")
    where = "name IN (" + ",".join(f"'{n}'" for n in names) + ")"
    r = session.get(f"{MRMS_URL}/query", params={"where": where, "outFields": "objectid,name,idp_validendtime",
                                                 "returnGeometry": "false", "f": "json"}, timeout=timeout)
    r.raise_for_status()
    d = r.json()
    if "error" in d:
        raise ValueError(f"service error {d['error']}")
    return parse_catalog(d), d


def export_params(objectid: int, box: dict) -> dict:
    return {"bbox": f"{box['xmin']},{box['ymin']},{box['xmax']},{box['ymax']}", "bboxSR": "4326", "imageSR": "4326",
            "size": f"{box['width']},{box['height']}", "format": "tiff", "compression": "LZ77", "pixelType": "F32",
            "noData": str(int(NODATA)), "interpolation": "RSP_NearestNeighbor",
            "mosaicRule": json.dumps({"mosaicMethod": "esriMosaicLockRaster", "lockRasterIds": [int(objectid)]}),
            "f": "image"}


def export(session, objectid: int, box: dict, timeout: int = 120) -> bytes:
    """One `exportImage` of a catalog item over the box: the TIFF bytes."""
    r = session.get(f"{MRMS_URL}/exportImage", params=export_params(objectid, box), timeout=timeout)
    r.raise_for_status()
    ctype = r.headers.get("content-type", "")
    if "json" in ctype or "html" in ctype or r.content[:1] in (b"{", b"<"):
        raise ValueError(f"no image in the answer ({ctype}): {r.content[:200]!r}")
    return r.content


def sample(grid: Grid, points: dict[str, tuple[float, float]]) -> dict[str, float | None]:
    """{point key: value} for every point."""
    return {k: grid.value(lat, lon) for k, (lat, lon) in points.items()}
