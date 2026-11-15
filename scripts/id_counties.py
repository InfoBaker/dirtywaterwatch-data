"""Idaho's 44 counties with their outlines, for the county-aware name placement of Idaho's reports
(pipeline/build/status.py, COUNTY_STATES and COUNTY_FIELD_STATES) and for Idaho's time-zone rule (pipeline/zones.py,
idaho_zone).

The time-zone rule's public record
  - 49 CFR 71.9(a), "Boundary line between mountain and Pacific zones" (eCFR, read 2026-11-14): "From the junction of
    the Idaho-Montana boundary with the boundary between the United States and Canada southerly along the
    Idaho-Montana boundary to the boundary line between Idaho County, Idaho, and Lemhi County, Idaho; thence
    southwesterly along the boundary line between those two counties to the main channel of the Salmon River; thence
    westerly along the main channel of the Salmon River to the Idaho-Oregon boundary; ..." and 71.9(d): "All
    municipalities located upon the zone boundary line described in this section are in the mountain standard time
    zone." Idaho north of the Salmon River is in the Pacific zone: nine counties wholly (PACIFIC_COUNTIES) and Idaho
    County north of the river; the rest of the state is Mountain.
  - Idaho County is cut in two by the U.S. Department of Transportation's time-zone layer (NTAD Time Zones,
    https://services.arcgis.com/xOi1kZaI0eWDREZv/arcgis/rest/services/NTAD_Time_Zones/FeatureServer/0): its
    pacific_part (north of the Salmon River: Grangeville, Cottonwood, Kooskia) and the rest. Each of the nine lies in
    the layer's Pacific polygon (PACIFIC_AGREES), no other county more than PACIFIC_STRAY, as checked when written.
  - The outlines: U.S. Census Bureau TIGERweb, State_County MapServer layer 1 (counties), state 16, generalised by
    the service to 0.001 degree.

Writes data/reference/id-counties.json: each county's name, GEOID and outline (coordinates rounded to 4 decimals),
and under time_zone the rule, the nine Pacific counties and Idaho County's pacific_part.

Run from the repository root:
  pipeline/.venv/bin/python scripts/id_counties.py [--file counties.geojson --tz-file zones.geojson]
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from al_counties import HEADERS, _round  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "reference" / "id-counties.json"
URL = ("https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/State_County/MapServer/1/query"
       "?where=STATE%3D%2716%27&outFields=NAME,GEOID,BASENAME&returnGeometry=true&maxAllowableOffset=0.001"
       "&outSR=4326&f=geojson")
DOT_LAYER = "https://services.arcgis.com/xOi1kZaI0eWDREZv/arcgis/rest/services/NTAD_Time_Zones/FeatureServer/0"
TZ_URL = (DOT_LAYER + "/query?where=zone%3D%27Pacific%27&outFields=zone&geometry=-117.3,41.9,-111.0,49.1"
          "&geometryType=esriGeometryEnvelope&inSR=4326&spatialRel=esriSpatialRelIntersects&outSR=4326"
          "&maxAllowableOffset=0.0005&f=geojson")
COUNT = 44
PACIFIC_COUNTIES = ("Benewah", "Bonner", "Boundary", "Clearwater", "Kootenai", "Latah", "Lewis", "Nez Perce", "Shoshone")
SPLIT_COUNTY = "Idaho"
CFR = "49 CFR 71.9(a) and (d)"
CFR_URL = "https://www.ecfr.gov/current/title-49/subtitle-A/part-71/section-71.9"
PACIFIC_AGREES = 0.98
PACIFIC_STRAY = 0.02


def _geom(g) -> dict:
    from shapely.geometry import mapping
    m = mapping(g)
    return {"type": m["type"], "coordinates": _round(json.loads(json.dumps(m["coordinates"])))}


def time_zone(feats: list, zones: dict) -> dict:
    from shapely.geometry import shape
    from shapely.ops import unary_union
    pac = unary_union([shape(f["geometry"]).buffer(0) for f in zones["features"]])
    by = {f["properties"]["BASENAME"]: f for f in feats}
    missing = [n for n in PACIFIC_COUNTIES + (SPLIT_COUNTY,) if n not in by]
    if missing:
        raise SystemExit(f"counties missing from the TIGERweb answer: {missing}")
    problems = []
    for n, f in by.items():
        g = shape(f["geometry"]).buffer(0)
        share = g.intersection(pac).area / g.area
        if n in PACIFIC_COUNTIES and share < PACIFIC_AGREES:
            problems.append(f"{n}: {share:.3f} in the DOT Pacific polygon")
        if n not in PACIFIC_COUNTIES and n != SPLIT_COUNTY and share > PACIFIC_STRAY:
            problems.append(f"{n}: {share:.3f} in the DOT Pacific polygon although the rule reads it Mountain")
    if problems:
        raise SystemExit("the rule and the DOT layer disagree: " + "; ".join(problems))
    g = shape(by[SPLIT_COUNTY]["geometry"]).buffer(0)
    part = g.intersection(pac)
    return {"zone": "America/Los_Angeles", "other_zone": "America/Denver",
            "rule": (f"Idaho north of the main channel of the Salmon River is in the Pacific zone ({CFR}): the nine "
                     "counties listed wholly, and Idaho County north of the river (its pacific_part); a municipality "
                     "on the line keeps Mountain time; the rest of the state is Mountain."),
            "law": {"cite": CFR, "url": CFR_URL, "read": "2026-11-14"},
            "checked_against": {"name": "U.S. DOT NTAD Time Zones", "url": DOT_LAYER, "read": "2026-11-14"},
            "pacific_counties": [by[n]["properties"]["NAME"] for n in PACIFIC_COUNTIES],
            "split_county": by[SPLIT_COUNTY]["properties"]["NAME"],
            "pacific_part": _geom(part), "pacific_share": round(part.area / g.area, 3)}


def build(doc: dict, fetched_at: str, zones: dict) -> dict:
    feats = sorted(doc["features"], key=lambda f: f["properties"]["GEOID"])
    if len(feats) != COUNT:
        raise SystemExit(f"{len(feats)} counties in the TIGERweb answer, not Idaho's {COUNT}")
    return {"state": "ID",
            "rule": ("A report's county is the county whose outline holds its point, else the county its own record "
                     "names; a water record's counties are those its box, padded by the name-match distance, reaches."),
            "source": {"name": "U.S. Census Bureau TIGERweb, State_County layer 1", "url": URL, "fetched_at": fetched_at},
            "time_zone": time_zone(feats, zones),
            "counties": [{"county": f["properties"]["NAME"], "geoid": f["properties"]["GEOID"],
                          "geometry": {"type": f["geometry"]["type"], "coordinates": _round(f["geometry"]["coordinates"])}}
                         for f in feats]}


def main(argv) -> int:
    if "--file" in argv:
        doc = json.loads(Path(argv[argv.index("--file") + 1]).read_text())
        fetched_at = argv[argv.index("--fetched-at") + 1] if "--fetched-at" in argv else "from file"
    else:
        r = requests.get(URL, headers=HEADERS, timeout=(20, 600))
        r.raise_for_status()
        doc = r.json()
        fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if "--tz-file" in argv:
        zones = json.loads(Path(argv[argv.index("--tz-file") + 1]).read_text())
    else:
        r = requests.get(TZ_URL, headers=HEADERS, timeout=(20, 600))
        r.raise_for_status()
        zones = r.json()
    out = build(doc, fetched_at, zones)
    OUT.write_text(json.dumps(out, separators=(",", ":")) + "\n")
    print(f"{COUNT} counties -> {OUT.relative_to(ROOT)}; Idaho County's Pacific share "
          f"{out['time_zone']['pacific_share']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
