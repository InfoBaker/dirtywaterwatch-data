"""One cited public point per lake of North Dakota DEQ's harmful algal bloom listing, so each advisory draws its own
marker (wave 4 rule 1; Astra review 2026-11-14 P1-1): data/reference/nd-hab-lake-points.json.

Source: the U.S. Geological Survey's National Hydrography Dataset, Waterbody - Large Scale
(https://hydro.nationalmap.gov/arcgis/rest/services/nhd/MapServer/12), asked once for the lakes' GNIS names within
North Dakota's box. A lake gets a point only when an NHD waterbody of its name (or the GNIS name in GNIS_NAME below, the
same water under its official name) lies in a county DEQ lists for it (data/reference/nd-counties.json); the point is
the waterbody's representative point (inside its outline), kept to 0.001 degree, with the GNIS id cited. A qualified
name is another water ("South Golden Lake" is not "Golden Lake"); a lake with no such waterbody gets none, and is listed.

Run from the repository root:
  pipeline/.venv/bin/python scripts/nd_hab_lake_points.py --file a.json [--file b.json ...]   (saved NHD answers)
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


def build(features: list[dict], listing: list[dict], fetched_at: str) -> dict:
    from shapely.geometry import shape
    import zones
    rows, missing = [], []
    for x in listing:
        want = GNIS_NAME.get(x["lake"], x["lake"])
        cands = []
        for f in features:
            if (f["attributes"].get("GNIS_NAME") or "") != want or not f.get("geometry"):
                continue
            g = shape({"type": "Polygon", "coordinates": f["geometry"]["rings"]}).buffer(0)
            p = g.representative_point()
            county = zones.nd_point_county(p.y, p.x)
            if county and county.removesuffix(" County") in x["counties"]:
                cands.append((g.area, p, county, f["attributes"]))
        if not cands:
            missing.append({"lake": x["lake"], "counties": x["counties"],
                            "why": f"no NHD waterbody named {want!r} in {', '.join(x['counties'])} County"})
            continue
        area, p, county, a = max(cands, key=lambda c: c[0])
        rows.append({"lake": x["lake"], "counties": x["counties"], "gnis_name": a["GNIS_NAME"], "gnis_id": a["GNIS_ID"],
                     "lat": round(p.y, 3), "lon": round(p.x, 3), "county": county,
                     "basis": "a point inside the NHD waterbody of that GNIS name in the county DEQ lists"})
    return {"state": "ND", "source": {"name": "USGS National Hydrography Dataset, Waterbody - Large Scale", "url": URL,
                                      "fetched_at": fetched_at},
            "rule": "one point inside the named lake's NHD outline, in a county DEQ lists for it, 0.001 degree",
            "lakes": rows, "without_point": missing}


def main(argv) -> int:
    from ingest import nd_deq_hab_listings as H
    feats = []
    for i, a in enumerate(argv):
        if a == "--file":
            feats += json.loads(Path(argv[i + 1]).read_text())["features"]
    listing = H.parse((ROOT / "pipeline" / "tests" / "fixtures" / "nd" / "HABsListings.pdf").read_bytes())
    doc = build(feats, listing, argv[argv.index("--fetched-at") + 1] if "--fetched-at" in argv else "2026-11-14")
    OUT.write_text(json.dumps(doc, indent=1) + "\n")
    print(f"{len(doc['lakes'])} lakes with a point, {len(doc['without_point'])} without -> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
