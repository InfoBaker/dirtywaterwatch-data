"""Nebraska's Mountain-time counties, with their outlines, for the eRule module's time-zone rule
(pipeline/ingest/echo_sewer_overflow_events.py, Nebraska). The same shape as South Dakota's file, so the two states
share one mechanism: an event's own point against the outlines of the area the Mountain zone covers.

The rule's public records
  - The zone boundary: 49 CFR 71.7(c), "Boundary line between central and mountain zones", Nebraska: "From the
    junction of the west line of Tripp County, South Dakota with the South Dakota-Nebraska boundary west along that
    boundary to the west line of R. 30 W.; thence south along the range line between Rs. 30 and 31 W. ... [section
    and township lines through Cherry County] ... thence southerly along the range line to the north line of Thomas
    County; thence westerly along the north line of Thomas County to the west line of Thomas County; thence south
    along the west line of Thomas County to the north line of McPherson County; thence west along the north line of
    McPherson County to the west line of McPherson County; thence south along the west line of McPherson County to
    the north line of Keith County; thence east along the north line of Keith County to the west line of Lincoln
    County; thence south along the west line of Lincoln County to the north line of Hayes County; thence west along
    the north lines of Hayes County to the west line of Hayes County; thence south along the west line of Hayes and
    Hitchcock Counties to the Nebraska-Kansas boundary." (https://www.law.cornell.edu/cfr/text/49/71.7, read
    2026-11-07.)
  - Read with the county map, that line leaves eighteen counties wholly in the Mountain zone (MOUNTAIN_COUNTIES
    below) and splits one, Cherry County, whose western part (west of the range and section lines the rule follows)
    keeps Mountain time and whose eastern part, Valentine's, Central time. Checked against the U.S. Department of
    Transportation's time-zone layer (NTAD Time Zones,
    https://services.arcgis.com/xOi1kZaI0eWDREZv/arcgis/rest/services/NTAD_Time_Zones/FeatureServer/0, read
    2026-11-07): each of the eighteen lies in its Mountain polygon (Hooker County to 99.9%), Cherry County 65% of its
    area, and no other Nebraska county more than 0.1%.
  - The outlines: U.S. Census Bureau TIGERweb, State_County MapServer layer 1 (counties), state 31, generalised by
    the service to 0.001 degree (https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/State_County/MapServer/1).
    Cherry County's Mountain part is its outline cut by the DOT layer's Mountain polygon (the rule's section lines are
    not drawn in any county layer), simplified to 0.001 degree.

Writes data/reference/ne-mountain-time-counties.json in South Dakota's shape (one mechanism for both states): the
eighteen counties' names, GEOIDs and outlines, and Cherry County under split_counties with its outline, its
mountain_part (west of the line, cut by the DOT Mountain polygon), its central_part and the Mountain share of its area.
Coordinates rounded to 4 decimals.

Run from the repository root:
  pipeline/.venv/bin/python scripts/ne_mountain_time_counties.py [--file counties.geojson --zones mountain.geojson]
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from shapely.geometry import mapping, shape

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "reference" / "ne-mountain-time-counties.json"
URL = ("https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/State_County/MapServer/1/query"
       "?where=STATE%3D%2731%27&outFields=NAME,GEOID,BASENAME&returnGeometry=true&maxAllowableOffset=0.001"
       "&outSR=4326&f=geojson")
DOT_LAYER = "https://services.arcgis.com/xOi1kZaI0eWDREZv/arcgis/rest/services/NTAD_Time_Zones/FeatureServer/0"
DOT_URL = (DOT_LAYER + "/query?where=zone%3D%27Mountain%27&outFields=zone&returnGeometry=true"
           "&geometry=-104.1,39.9,-95.3,43.1&geometryType=esriGeometryEnvelope&inSR=4326"
           "&spatialRel=esriSpatialRelIntersects&outSR=4326&f=geojson")
MOUNTAIN_COUNTIES = ("Arthur", "Banner", "Box Butte", "Chase", "Cheyenne", "Dawes", "Deuel", "Dundy", "Garden", "Grant",
                     "Hooker", "Keith", "Kimball", "Morrill", "Perkins", "Scotts Bluff", "Sheridan", "Sioux")
SPLIT_COUNTIES = ("Cherry",)
CFR = "49 CFR 71.7(c)"
CFR_URL = "https://www.law.cornell.edu/cfr/text/49/71.7"


def _round(coords):
    if isinstance(coords[0], (int, float)):
        return [round(coords[0], 4), round(coords[1], 4)]
    return [_round(c) for c in coords]


def _geom(g) -> dict:
    m = mapping(g)
    return {"type": m["type"], "coordinates": _round(json.loads(json.dumps(m["coordinates"])))}


def build(doc: dict, zones: dict, fetched_at: str) -> dict:
    by = {f["properties"]["BASENAME"]: f for f in doc["features"]}
    missing = [n for n in MOUNTAIN_COUNTIES + SPLIT_COUNTIES if n not in by]
    if missing:
        raise SystemExit(f"counties missing from the TIGERweb answer: {missing}")
    mountain = [shape(f["geometry"]) for f in zones["features"]]
    if not mountain:
        raise SystemExit("no Mountain polygon in the DOT answer")
    mpoly = mountain[0].buffer(0)
    for g in mountain[1:]:
        mpoly = mpoly.union(g.buffer(0))

    def row(n):
        f = by[n]
        return {"county": f["properties"]["NAME"], "geoid": f["properties"]["GEOID"],
                "geometry": {"type": f["geometry"]["type"], "coordinates": _round(f["geometry"]["coordinates"])}}

    def split(n):
        g = shape(by[n]["geometry"])
        m, c = g.intersection(mpoly).simplify(0.001), g.difference(mpoly).simplify(0.001)
        return dict(row(n), note=("split by the boundary; its western part keeps Mountain time, the rest, Valentine's "
                                  "part, Central time (parts cut by the U.S. DOT time-zone layer)"),
                    central_part=_geom(c), mountain_part=_geom(m), mountain_share=round(m.area / g.area, 3),
                    central_label="Central part")
    return {
        "state": "NE",
        "zone": "America/Denver",
        "other_zone": "America/Chicago",
        "rule": (f"The Central-Mountain boundary in Nebraska ({CFR}) runs south from the South Dakota line along range "
                 "and section lines through Cherry County, then along the north and west lines of Thomas County, the "
                 "north and west lines of McPherson County, the north line of Keith County, the west line of Lincoln "
                 "County and the west lines of Hayes and Hitchcock counties to Kansas; the eighteen counties listed lie "
                 "wholly west of it, in the Mountain zone, with the western part of Cherry County. The rest of Cherry "
                 "County, Valentine's part, keeps Central time."),
        "law": {"cite": CFR, "url": CFR_URL, "read": "2026-11-07"},
        "checked_against": {"name": "U.S. DOT NTAD Time Zones", "url": DOT_LAYER, "read": "2026-11-07"},
        "source": {"name": "U.S. Census Bureau TIGERweb, State_County layer 1", "url": URL, "fetched_at": fetched_at},
        "counties": [row(n) for n in MOUNTAIN_COUNTIES],
        "split_counties": [split(n) for n in SPLIT_COUNTIES],
    }


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--file" in argv:
        doc = json.loads(Path(argv[argv.index("--file") + 1]).read_text())
        zones = json.loads(Path(argv[argv.index("--zones") + 1]).read_text())
    else:
        r = requests.get(URL, timeout=60)
        r.raise_for_status()
        doc = r.json()
        z = requests.get(DOT_URL, timeout=180)
        z.raise_for_status()
        zones = z.json()
    out = build(doc, zones, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1) + "\n")
    print(f"{OUT.relative_to(ROOT)}: {len(out['counties'])} Mountain-time areas, {len(out['split_counties'])} split")
    return 0


if __name__ == "__main__":
    sys.exit(main())
