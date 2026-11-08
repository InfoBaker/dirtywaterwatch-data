"""Kentucky's Central-time counties, with their outlines, for the time-zone rule of Kentucky's records
(pipeline/ingest/echo_sewer_overflow_events.py, Kentucky; pipeline/zones.py). The shape of South Dakota's and
Nebraska's files (one mechanism): an event's own point against the outlines of the counties the other zone covers.
Kentucky's larger part keeps Eastern time (pipeline/zones.py STATE_ZONES); the listed counties keep Central time.

The rule's public records
  - The zone boundary: 49 CFR 71.5(c), "Boundary line between eastern and central zones", Kentucky: "From the
    junction of the east line of Perry County, Ind., with the Indiana-Kentucky boundary easterly along that boundary
    to the west line of Meade County, Ky.; thence southeasterly and southwesterly along the west lines of Meade and
    Hardin Counties to the southwest corner of Hardin County; thence along the south lines of Hardin and Larue Counties
    to the northwest corner of Taylor County; thence southeasterly along the west (southwest) lines of Taylor County
    and northeasterly along the east (southeast) line of Taylor County to the west line of Casey County; and thence
    southerly along the west and south lines of Casey and Pulaski Counties to the intersection with the western
    boundary of Wayne County; and then south along the western boundary of Wayne County to the Kentucky-Tennessee
    boundary." (https://www.law.cornell.edu/cfr/text/49/71.5, read 2026-11-07.)
  - Read with the county map, the line follows county lines only, so it leaves forty-one counties wholly in the
    Central zone (CENTRAL_COUNTIES below) and splits none. Checked against the U.S. Department of Transportation's
    time-zone layer (NTAD Time Zones,
    https://services.arcgis.com/xOi1kZaI0eWDREZv/arcgis/rest/services/NTAD_Time_Zones/FeatureServer/0, read
    2026-11-07): each of the forty-one lies in its Central polygon (Adair, Clinton, Grayson, Green and Russell to
    99.9%, the rest wholly), and no other Kentucky county more than 0.3% (Taylor 0.1%, Wayne 0.2%: the layer's
    generalised line along their borders).
  - The outlines: U.S. Census Bureau TIGERweb, State_County MapServer layer 1 (counties), state 21, generalised by
    the service to 0.001 degree (https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/State_County/MapServer/1).

Writes data/reference/ky-central-time-counties.json in South Dakota's shape with "zone" America/Chicago (the listed
counties) and "other_zone" America/New_York (the rest of the state), "zone_label" "Central" (the word the records'
time-zone note uses), the counties' names, GEOIDs and outlines, and no split counties. Coordinates rounded to 4
decimals.

Run from the repository root:
  pipeline/.venv/bin/python scripts/ky_central_time_counties.py [--file counties.geojson --zones central.geojson]
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from shapely.geometry import shape

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "reference" / "ky-central-time-counties.json"
URL = ("https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/State_County/MapServer/1/query"
       "?where=STATE%3D%2721%27&outFields=NAME,GEOID,BASENAME&returnGeometry=true&maxAllowableOffset=0.001"
       "&outSR=4326&f=geojson")
DOT_LAYER = "https://services.arcgis.com/xOi1kZaI0eWDREZv/arcgis/rest/services/NTAD_Time_Zones/FeatureServer/0"
DOT_URL = (DOT_LAYER + "/query?where=zone%3D%27Central%27&outFields=zone&returnGeometry=true"
           "&geometry=-89.6,36.4,-81.9,39.2&geometryType=esriGeometryEnvelope&inSR=4326"
           "&spatialRel=esriSpatialRelIntersects&outSR=4326&f=geojson")
CENTRAL_COUNTIES = ("Adair", "Allen", "Ballard", "Barren", "Breckinridge", "Butler", "Caldwell", "Calloway", "Carlisle",
                    "Christian", "Clinton", "Crittenden", "Cumberland", "Daviess", "Edmonson", "Fulton", "Graves",
                    "Grayson", "Green", "Hancock", "Hart", "Henderson", "Hickman", "Hopkins", "Livingston", "Logan",
                    "Lyon", "Marshall", "McCracken", "McLean", "Metcalfe", "Monroe", "Muhlenberg", "Ohio", "Russell",
                    "Simpson", "Todd", "Trigg", "Union", "Warren", "Webster")
CFR = "49 CFR 71.5(c)"
CFR_URL = "https://www.law.cornell.edu/cfr/text/49/71.5"
# a county is checked as the rule reads it when this share of its area lies in the DOT layer's Central polygon
DOT_AGREES = 0.99
DOT_STRAY = 0.01


def _round(coords):
    if isinstance(coords[0], (int, float)):
        return [round(coords[0], 4), round(coords[1], 4)]
    return [_round(c) for c in coords]


def check_against_dot(doc: dict, zones: dict) -> list[str]:
    """Counties where the rule's list and the DOT layer disagree (empty when they agree)."""
    polys = [shape(f["geometry"]).buffer(0) for f in zones["features"]]
    if not polys:
        raise SystemExit("no Central polygon in the DOT answer")
    central = polys[0]
    for g in polys[1:]:
        central = central.union(g)
    out = []
    for f in doc["features"]:
        n, g = f["properties"]["BASENAME"], shape(f["geometry"])
        share = g.intersection(central).area / g.area
        if n in CENTRAL_COUNTIES and share < DOT_AGREES:
            out.append(f"{n}: {share:.3f} of it in the DOT Central polygon")
        if n not in CENTRAL_COUNTIES and share > DOT_STRAY:
            out.append(f"{n}: {share:.3f} of it in the DOT Central polygon although the rule reads it Eastern")
    return out


def build(doc: dict, fetched_at: str) -> dict:
    by = {f["properties"]["BASENAME"]: f for f in doc["features"]}
    missing = [n for n in CENTRAL_COUNTIES if n not in by]
    if missing:
        raise SystemExit(f"counties missing from the TIGERweb answer: {missing}")

    def row(n):
        f = by[n]
        return {"county": f["properties"]["NAME"], "geoid": f["properties"]["GEOID"],
                "geometry": {"type": f["geometry"]["type"], "coordinates": _round(f["geometry"]["coordinates"])}}

    return {
        "state": "KY",
        "zone": "America/Chicago",
        "other_zone": "America/New_York",
        "zone_label": "Central",
        "rule": (f"The Eastern-Central boundary in Kentucky ({CFR}) runs from the Indiana line along the west lines of "
                 "Meade and Hardin counties, the south lines of Hardin and Larue counties, around Taylor County, along "
                 "the west and south lines of Casey and Pulaski counties and the west line of Wayne County to "
                 "Tennessee; the forty-one counties listed lie wholly west of it, in the Central zone. The rest of the "
                 "state keeps Eastern time."),
        "law": {"cite": CFR, "url": CFR_URL, "read": "2026-11-07"},
        "checked_against": {"name": "U.S. DOT NTAD Time Zones", "url": DOT_LAYER, "read": "2026-11-07"},
        "source": {"name": "U.S. Census Bureau TIGERweb, State_County layer 1", "url": URL, "fetched_at": fetched_at},
        "counties": [row(n) for n in CENTRAL_COUNTIES],
        "split_counties": [],
    }


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--file" in argv:
        doc = json.loads(Path(argv[argv.index("--file") + 1]).read_text())
        zones = json.loads(Path(argv[argv.index("--zones") + 1]).read_text())
    else:
        r = requests.get(URL, timeout=120)
        r.raise_for_status()
        doc = r.json()
        z = requests.get(DOT_URL, timeout=300)
        z.raise_for_status()
        zones = z.json()
    bad = check_against_dot(doc, zones)
    if bad:
        raise SystemExit("the rule's county list and the DOT layer disagree: " + "; ".join(bad))
    out = build(doc, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1) + "\n")
    print(f"{OUT.relative_to(ROOT)}: {len(out['counties'])} Central-time counties, {len(out['split_counties'])} split")
    return 0


if __name__ == "__main__":
    sys.exit(main())
