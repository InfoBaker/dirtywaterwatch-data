"""One cited public point per lake of North Dakota DEQ's harmful algal bloom listing, so each advisory draws its own
marker (wave 4 rule 1; Astra review 2026-11-14 P1-1): data/reference/nd-hab-lake-points.json.

Source: the U.S. Geological Survey's National Hydrography Dataset, Waterbody - Large Scale
(https://hydro.nationalmap.gov/arcgis/rest/services/nhd/MapServer/12), asked once for the lakes' GNIS names within
North Dakota's box, and the USGS Geographic Names Information System (The National Map's geonames service, layer 7),
asked once on 2026-11-14 for the six names with no outline. A lake gets a point only from the one GNIS identity of its
name (or the GNIS name in GNIS_NAME below, the same water under its official name) in a county DEQ lists for it
(data/reference/nd-counties.json): the representative point of its NHD outline (the largest part when one GNIS id has
several), else the GNIS point of the one gazetteer lake of that exact name in that county. Two GNIS identities of the
name in the listed counties are separate lakes and none is chosen (review 2026-11-14 P2-2). Points kept to 0.001
degree, the GNIS id cited. A qualified name is another water ("South Golden Lake" is not "Golden Lake"); a lake with no
identified water gets no point, stays in the listing's records and is named in the state text.

Run from the repository root:
  pipeline/.venv/bin/python scripts/nd_hab_lake_points.py --file a.json [--file b.json ...] [--gnis-file g.json]
  (saved NHD answers; the GNIS gazetteer's lakes of the listed names in North Dakota)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
OUT = ROOT / "data" / "reference" / "nd-hab-lake-points.json"
URL = "https://hydro.nationalmap.gov/arcgis/rest/services/nhd/MapServer/12"
# DEQ's name -> the GNIS name of the same water (checked by county below)
GNIS_NAME = {"Bowman - Haley Dam": "Bowman-Haley Lake", "Patterson Lake": "Edward Arthur Patterson Lake",
             "North Lake Washington": "North Washington Lake", "Antelope Lake": "Antelope Lakes",
             "Blacktail Dam": "Blacktail Lake"}


TIE_KM = 25.0
GAZ_URL = "https://carto.nationalmap.gov/arcgis/rest/services/geonames/MapServer/7"


def _km(a, b) -> float:
    import math
    (la1, lo1), (la2, lo2) = a, b
    x = math.radians(lo2 - lo1) * math.cos(math.radians((la1 + la2) / 2))
    return 6371.0 * math.hypot(x, math.radians(la2 - la1))


def build(features: list[dict], listing: list[dict], fetched_at: str, gazetteer: list[dict] | None = None) -> dict:
    """One point per listed lake, from the one GNIS identity of its name in a county DEQ lists (review 2026-11-14
    P2-2): the NHD outlines carrying one GNIS id are parts of one lake (the point inside its largest part); two or
    more GNIS ids of the name in the listed counties are separate same-named lakes, and DEQ's name does not say which
    it means, so the lake gets no point (refused whatever the distance; a tie more than 25 km apart is named as such).
    A lake with no NHD outline of its name gets the GNIS gazetteer's own point when exactly one GNIS lake of that
    exact name lies in a listed county (the gazetteer's county and the point's county agree). A qualified name is
    another water: names are compared exactly."""
    from shapely.geometry import shape
    import zones
    rows, missing = [], []
    for x in listing:
        want = GNIS_NAME.get(x["lake"], x["lake"])
        by_id: dict[str, list] = {}
        for f in features:
            if (f["attributes"].get("GNIS_NAME") or "") != want or not f.get("geometry"):
                continue
            g = shape({"type": "Polygon", "coordinates": f["geometry"]["rings"]}).buffer(0)
            p = g.representative_point()
            county = zones.nd_point_county(p.y, p.x)
            if county and county.removesuffix(" County") in x["counties"]:
                by_id.setdefault(str(f["attributes"].get("GNIS_ID") or ""), []).append((g.area, p, county,
                                                                                       f["attributes"]))
        if len(by_id) > 1 or "" in by_id:
            pts = [max(v, key=lambda c: c[0])[1] for v in by_id.values()]
            far = max(_km((a.y, a.x), (b.y, b.x)) for a in pts for b in pts)
            missing.append({"lake": x["lake"], "counties": x["counties"],
                            "why": (f"{len(by_id)} separate NHD lakes named {want!r} (GNIS ids "
                                    f"{', '.join(sorted(k or 'none' for k in by_id))}) in "
                                    f"{', '.join(x['counties'])} County, {far:.0f} km apart"
                                    f"{' (a name-only tie beyond 25 km)' if far > TIE_KM else ''}: DEQ's name does "
                                    f"not say which, so no point is chosen")})
            continue
        if by_id:
            area, p, county, a = max(next(iter(by_id.values())), key=lambda c: c[0])
            rows.append({"lake": x["lake"], "counties": x["counties"], "gnis_name": a["GNIS_NAME"],
                         "gnis_id": a["GNIS_ID"], "lat": round(p.y, 3), "lon": round(p.x, 3), "county": county,
                         "coord_source": "nhd_waterbody",
                         "basis": "a point inside the NHD waterbody of that GNIS name in the county DEQ lists"})
            continue
        gaz = []
        for f in gazetteer or []:
            a = f.get("attributes") or {}
            gm = f.get("geometry") or {}
            if (a.get("gaz_name") or "") != want or a.get("state_alpha") != "ND" or gm.get("x") is None:
                continue
            if (a.get("gaz_featureclass") or "") not in ("Lake", "Reservoir"):
                continue
            county = zones.nd_point_county(gm["y"], gm["x"])
            if (a.get("county_name") in x["counties"] and county
                    and county.removesuffix(" County") == a.get("county_name")):
                gaz.append((a, gm, county))
        if len(gaz) == 1:
            a, gm, county = gaz[0]
            rows.append({"lake": x["lake"], "counties": x["counties"], "gnis_name": a["gaz_name"],
                         "gnis_id": f"{int(a['gaz_id']):08d}", "lat": round(gm["y"], 3), "lon": round(gm["x"], 3),
                         "county": county, "coord_source": "gnis_point", "source_url": GAZ_URL,
                         "basis": ("the GNIS point of the one lake of that exact name in the county DEQ lists (the "
                                   "National Hydrography Dataset draws no outline for it)")})
            continue
        missing.append({"lake": x["lake"], "counties": x["counties"],
                        "why": (f"{len(gaz)} GNIS lakes named {want!r} in {', '.join(x['counties'])} County: DEQ's "
                                f"name does not say which, so no point is chosen" if gaz else
                                f"no NHD waterbody and no GNIS lake named {want!r} in "
                                f"{', '.join(x['counties'])} County")})
    return {"state": "ND", "source": {"name": "USGS National Hydrography Dataset, Waterbody - Large Scale", "url": URL,
                                      "fetched_at": fetched_at},
            "gazetteer": {"name": "USGS Geographic Names Information System (The National Map, geonames, Other "
                                  "Hydrographic Features)", "url": GAZ_URL, "fetched_at": fetched_at},
            "rule": ("one point per listed lake from the one GNIS identity of its exact name in a county DEQ lists: "
                     "inside its NHD outline, else the GNIS point; two identities of the name are not chosen between; "
                     "0.001 degree"),
            "lakes": rows, "without_point": missing}


def main(argv) -> int:
    from ingest import nd_deq_hab_listings as H
    feats, gaz = [], []
    for i, a in enumerate(argv):
        if a == "--file":
            feats += json.loads(Path(argv[i + 1]).read_text())["features"]
        if a == "--gnis-file":
            gaz += json.loads(Path(argv[i + 1]).read_text())["features"]
    listing = H.parse((ROOT / "pipeline" / "tests" / "fixtures" / "nd" / "HABsListings.pdf").read_bytes())
    doc = build(feats, listing, argv[argv.index("--fetched-at") + 1] if "--fetched-at" in argv else "2026-11-14", gaz)
    OUT.write_text(json.dumps(doc, indent=1) + "\n")
    print(f"{len(doc['lakes'])} lakes with a point, {len(doc['without_point'])} without -> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
