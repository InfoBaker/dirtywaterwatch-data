"""Rhode Island water lookup shared by the ri_* ingesters (not a feed; nothing is fetched here).

Water records are openboatlaunch's (data/waters-ri.json: slug, name, kind, towns, bbox). Their
geometry comes from ../openboatlaunch/out/water/<slug>.json when that tree is present and is cached
in data/build/ri-waters-geom.json so a machine without the sibling project still has it; failing
both, the bbox stands in for the shape (coarse, and said so by `geom_kind`).

Two lookups, both honest about what they are:
- `by_name(text, town)`: openboatlaunch waters whose name equals the text (normalised). A town,
  when given and the name is shared by several RI waters, picks the one listing that town.
- `near(lat, lon, max_m)`: waters whose geometry lies within max_m of the point, nearest first,
  as (slug, metres). Distances use a local equirectangular projection (good to ~0.1 % in RI).
"""
from __future__ import annotations

import json
import math
import re
from functools import lru_cache
from pathlib import Path

from common import BUILD_DIR, DATA_DIR, ROOT, read_json, write_json

OBL_WATER_DIR = ROOT.parent / "openboatlaunch" / "out" / "water"
GEOM_CACHE = BUILD_DIR / "ri-waters-geom.json"
LAT0 = 41.7
MY = 110_574.0
MX = 111_320.0 * math.cos(math.radians(LAT0))


def norm(s: str | None) -> str:
    s = (s or "").lower().replace("&", " and ").replace("’", "'")
    s = re.sub(r"'s\b", "s", s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def norm_town(s: str | None) -> str:
    s = norm(s)
    return {"wawick": "warwick", "burrilleville": "burrillville"}.get(s, s)


@lru_cache(maxsize=1)
def waters() -> list[dict]:
    return (read_json(DATA_DIR / "waters-ri.json", {}) or {}).get("waters", [])


@lru_cache(maxsize=1)
def _geoms() -> dict:
    """slug -> (shapely geometry in local metres, 'geometry' | 'bbox')."""
    import numpy as np
    import shapely
    from shapely.geometry import box, shape

    cache = read_json(GEOM_CACHE, {}) or {}
    raw = {}
    if OBL_WATER_DIR.is_dir():
        for w in waters():
            p = OBL_WATER_DIR / f"{w['slug']}.json"
            if p.exists():
                g = json.loads(p.read_text()).get("geometry")
                if g:
                    raw[w["slug"]] = g
        if raw and raw != cache.get("geometries"):
            write_json(GEOM_CACHE, {"source": str(OBL_WATER_DIR), "geometries": raw})
    else:
        raw = cache.get("geometries", {})

    origin, scale = np.array([-71.5, LAT0]), np.array([MX, MY])

    out = {}
    for w in waters():
        g, kind = None, None
        if w["slug"] in raw:
            try:
                g, kind = shape(raw[w["slug"]]), "geometry"
            except Exception:
                g = None
        if g is None and w.get("bbox"):
            g, kind = box(*w["bbox"]), "bbox"
        if g is not None:
            out[w["slug"]] = (shapely.transform(g, lambda c: (c - origin) * scale), kind)
    return out


def by_name(text: str | None, town: str | None = None) -> list[str]:
    n = norm(text)
    if not n:
        return []
    hits = [w for w in waters() if norm(w["name"]) == n]
    if len(hits) > 1 and town:
        t = norm_town(town)
        local = [w for w in hits if t in {norm_town(x) for x in w.get("towns") or []}]
        if local:
            hits = local
    return [w["slug"] for w in hits]


def near(lat: float | None, lon: float | None, max_m: float = 300) -> list[tuple[str, int]]:
    if lat is None or lon is None:
        return []
    from shapely.geometry import Point
    p = Point((lon - (-71.5)) * MX, (lat - LAT0) * MY)
    out = []
    for slug, (g, _kind) in _geoms().items():
        d = g.distance(p)
        if d <= max_m:
            out.append((slug, int(round(d))))
    return sorted(out, key=lambda t: t[1])


def geom_kind(slug: str) -> str | None:
    v = _geoms().get(slug)
    return v[1] if v else None


def name_of(slug: str) -> str | None:
    for w in waters():
        if w["slug"] == slug:
            return w["name"]
    return None


def water_words(slug: str) -> set[str]:
    stop = {"river", "lake", "pond", "brook", "bay", "harbor", "cove", "reservoir", "the", "of", "and",
            "beach", "upper", "lower", "north", "south", "east", "west", "sound", "passage", "town", "park"}
    return {w for w in norm(name_of(slug)).split() if w not in stop and len(w) > 2}


if __name__ == "__main__":  # quick check: python -m ingest.ri_waters 41.86 -71.402
    import sys
    lat, lon = float(sys.argv[1]), float(sys.argv[2])
    print(near(lat, lon, 1000))
