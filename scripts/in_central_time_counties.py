"""Indiana's Central-time counties, with their outlines, for the time-zone rule of Indiana's records
(pipeline/zones.py indiana_zone; pipeline/ingest/echo_sewer_overflow_events.py, Indiana). The shape of Kentucky's file
(one mechanism): an event's own point against the outlines of the counties the other zone covers. Indiana's larger part
keeps Eastern time (pipeline/zones.py STATE_ZONES); the twelve listed counties keep Central time.

The rule's public records
  - The zone boundary: 49 CFR 71.5(b), "Boundary line between eastern and central zones", Indiana-Illinois: "From the
    junction of the western boundary of the State of Michigan with the northern boundary of the State of Indiana
    easterly along the northern boundary of the State of Indiana to the east line of LaPorte County; thence southerly
    along the east line of LaPorte County to the north line of Starke County; thence east along the north line of
    Starke County to the west line of Marshall County; thence south along the west line of Marshall County; thence west
    along the north line of Pulaski County to the east line of Jasper County; thence south along the east line of
    Jasper County to the south line of Jasper County; thence west along the south lines of Jasper and Newton Counties
    to the western boundary of the State of Indiana; thence south along the western boundary of the State of Indiana
    to the north line of Gibson County; thence easterly and northerly along the north line of Gibson County to the
    west line of Pike County; thence south along the west line of Pike County to the north line of Warrick County;
    thence east along the north line of Warrick and Spencer Counties to the west line of Perry County; thence easterly
    and southerly along the north and east line of Perry County to the Indiana-Kentucky boundary."
    (eCFR, https://www.ecfr.gov/current/title-49/subtitle-A/part-71/section-71.5, read 2026-11-14.)
  - Read with the county map, the line follows county lines only: it leaves six northwestern counties (Lake, Porter,
    LaPorte, Starke, Jasper, Newton) and six southwestern counties (Gibson, Posey, Vanderburgh, Warrick, Spencer,
    Perry) wholly in the Central zone (CENTRAL_COUNTIES below) and splits none. Checked against the U.S. Department of
    Transportation's time-zone layer (NTAD Time Zones,
    https://services.arcgis.com/xOi1kZaI0eWDREZv/arcgis/rest/services/NTAD_Time_Zones/FeatureServer/0) at each run.
  - The outlines: U.S. Census Bureau TIGERweb, State_County MapServer layer 1 (counties), state 18, generalised by
    the service to 0.001 degree (https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/State_County/MapServer/1).

Writes data/reference/in-central-time-counties.json in Kentucky's shape with "zone" America/Chicago (the listed
counties) and "other_zone" America/New_York (the rest of the state), "zone_label" "Central", the counties' names,
GEOIDs and outlines, and no split counties. Coordinates rounded to 4 decimals.

Run from the repository root:
  pipeline/.venv/bin/python scripts/in_central_time_counties.py [--file counties.geojson --zones central.geojson]
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from shapely.geometry import shape

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "reference" / "in-central-time-counties.json"
URL = ("https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/State_County/MapServer/1/query"
       "?where=STATE%3D%2718%27&outFields=NAME,GEOID,BASENAME&returnGeometry=true&maxAllowableOffset=0.001"
       "&outSR=4326&f=geojson")
DOT_LAYER = "https://services.arcgis.com/xOi1kZaI0eWDREZv/arcgis/rest/services/NTAD_Time_Zones/FeatureServer/0"
DOT_URL = (DOT_LAYER + "/query?where=zone%3D%27Central%27&outFields=zone&returnGeometry=true"
           "&geometry=-88.2,37.7,-84.7,41.8&geometryType=esriGeometryEnvelope&inSR=4326"
           "&spatialRel=esriSpatialRelIntersects&outSR=4326&f=geojson")
CENTRAL_COUNTIES = ("Gibson", "Jasper", "Lake", "LaPorte", "Newton", "Perry", "Porter", "Posey", "Spencer", "Starke",
                    "Vanderburgh", "Warrick")
CFR = "49 CFR 71.5(b)"
CFR_URL = "https://www.ecfr.gov/current/title-49/subtitle-A/part-71/section-71.5"
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
        "state": "IN",
        "zone": "America/Chicago",
        "other_zone": "America/New_York",
        "zone_label": "Central",
        "rule": (f"The Eastern-Central boundary in Indiana ({CFR}) runs along county lines: around LaPorte, Starke, "
                 "Jasper and Newton counties in the northwest and along the north lines of Gibson, Warrick and Spencer "
                 "counties and around Perry County in the southwest; the twelve counties listed lie wholly west of it, "
                 "in the Central zone. The rest of the state keeps Eastern time."),
        "law": {"cite": CFR, "url": CFR_URL, "read": "2026-11-14"},
        "checked_against": {"name": "U.S. DOT NTAD Time Zones", "url": DOT_LAYER, "read": fetched_at[:10]},
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
