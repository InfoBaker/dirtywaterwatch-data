"""South Dakota's Mountain-time counties, with their outlines, for the eRule module's time-zone rule
(pipeline/ingest/echo_sewer_overflow_events.py, South Dakota).

The rule's public records
  - The zone boundary: 49 CFR 71.7(b), "Boundary line between central and mountain zones", South Dakota: "From the
    junction of the North Dakota-South Dakota boundary with the Missouri River southerly along the main channel of
    that river to the crossing of the original Chicago & North Western Railway near Pierre; thence southwesterly to
    the northern boundary of Jones County ...; thence west along the northern boundary of Jones County; thence south
    along the western boundaries of Jones, Mellette and Todd Counties to the South Dakota-Nebraska boundary."
    (https://www.law.cornell.edu/cfr/text/49/71.7, read 2026-11-07.)
  - Read with the county map, that line leaves fifteen counties wholly in the Mountain zone (MOUNTAIN_COUNTIES below)
    and splits one, Stanley County, whose corner around Fort Pierre (east of the line from the railway crossing near
    Pierre) keeps Central time. Checked against the U.S. Department of Transportation's time-zone layer (NTAD Time
    Zones, https://services.arcgis.com/xOi1kZaI0eWDREZv/arcgis/rest/services/NTAD_Time_Zones/FeatureServer/0,
    read 2026-11-07): each of the fifteen lies in its Mountain polygon (Corson and Dewey to within the river
    channel), Stanley County 84% of its area, and no other county more than 1%.
  - The outlines: U.S. Census Bureau TIGERweb, State_County MapServer layer 1 (counties), state 46, generalised by
    the service to 0.001 degree (https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/State_County/MapServer/1).

Writes data/reference/sd-mountain-time-counties.json: the fifteen counties' names, GEOIDs and outlines (coordinates
rounded to 4 decimals), and under split_counties Stanley County cut in two by the DOT layer's Central polygon: its
central_part (the Fort Pierre corner) and its mountain_part (the rest, 84% of the county); review 2026-11-07 P2-2.

Run from the repository root:
  pipeline/.venv/bin/python scripts/sd_mountain_time_counties.py [--file counties.geojson] [--tz-file zones.geojson]
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "reference" / "sd-mountain-time-counties.json"
URL = ("https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/State_County/MapServer/1/query"
       "?where=STATE%3D%2746%27&outFields=NAME,GEOID,BASENAME&returnGeometry=true&maxAllowableOffset=0.001"
       "&outSR=4326&f=geojson")
MOUNTAIN_COUNTIES = ("Bennett", "Butte", "Corson", "Custer", "Dewey", "Fall River", "Haakon", "Harding", "Jackson",
                     "Lawrence", "Meade", "Oglala Lakota", "Pennington", "Perkins", "Ziebach")
SPLIT_COUNTIES = ("Stanley",)
CFR = "49 CFR 71.7(b)"
CFR_URL = "https://www.law.cornell.edu/cfr/text/49/71.7"


def _round(coords):
    if isinstance(coords[0], (int, float)):
        return [round(coords[0], 4), round(coords[1], 4)]
    return [_round(c) for c in coords]


TZ_URL = ("https://services.arcgis.com/xOi1kZaI0eWDREZv/arcgis/rest/services/NTAD_Time_Zones/FeatureServer/0/query"
          "?where=1%3D1&outFields=zone&geometry=-104.1,42.4,-96.4,46&geometryType=esriGeometryEnvelope&inSR=4326"
          "&spatialRel=esriSpatialRelIntersects&outSR=4326&maxAllowableOffset=0.0005&f=geojson")


def _geom(g) -> dict:
    from shapely.geometry import mapping
    m = mapping(g)
    return {"type": m["type"], "coordinates": _round(json.loads(json.dumps(m["coordinates"])))}


def split(county: dict, zones: dict) -> dict:
    """The county's outline cut by the DOT layer's Central polygon."""
    from shapely.geometry import shape
    central = next(shape(f["geometry"]) for f in zones["features"] if f["properties"]["zone"] == "Central")
    g = shape(county["geometry"])
    c, m = g.intersection(central), g.difference(central)
    return {"central_part": _geom(c), "mountain_part": _geom(m),
            "mountain_share": round(m.area / g.area, 3)}


def build(doc: dict, fetched_at: str, zones: dict | None = None) -> dict:
    by = {f["properties"]["BASENAME"]: f for f in doc["features"]}
    missing = [n for n in MOUNTAIN_COUNTIES + SPLIT_COUNTIES if n not in by]
    if missing:
        raise SystemExit(f"counties missing from the TIGERweb answer: {missing}")

    def row(n):
        f = by[n]
        return {"county": f["properties"]["NAME"], "geoid": f["properties"]["GEOID"],
                "geometry": {"type": f["geometry"]["type"], "coordinates": _round(f["geometry"]["coordinates"])}}
    return {
        "state": "SD",
        "zone": "America/Denver",
        "other_zone": "America/Chicago",
        "rule": (f"The Central-Mountain boundary in South Dakota ({CFR}) runs down the Missouri River from North Dakota "
                 "to Pierre, then along the north line of Jones County and the west lines of Jones, Mellette and Todd "
                 "counties; the fifteen counties listed lie wholly west of it, in the Mountain zone. Stanley County is "
                 "split: its corner around Fort Pierre keeps Central time."),
        "law": {"cite": CFR, "url": CFR_URL, "read": "2026-11-07"},
        "checked_against": {"name": "U.S. DOT NTAD Time Zones",
                            "url": "https://services.arcgis.com/xOi1kZaI0eWDREZv/arcgis/rest/services/NTAD_Time_Zones/FeatureServer/0",
                            "read": "2026-11-07"},
        "source": {"name": "U.S. Census Bureau TIGERweb, State_County layer 1", "url": URL, "fetched_at": fetched_at},
        "counties": [row(n) for n in MOUNTAIN_COUNTIES],
        "split_counties": [dict(row(n), note="split by the boundary; the Fort Pierre corner keeps Central time, the rest "
                                             "is in the Mountain zone (parts cut by the U.S. DOT time-zone layer)",
                                **(split(by[n], zones) if zones else {})) for n in SPLIT_COUNTIES],
    }


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--file" in argv:
        doc = json.loads(Path(argv[argv.index("--file") + 1]).read_text())
    else:
        r = requests.get(URL, timeout=60)
        r.raise_for_status()
        doc = r.json()
    if "--tz-file" in argv:
        zones = json.loads(Path(argv[argv.index("--tz-file") + 1]).read_text())
    else:
        r = requests.get(TZ_URL, timeout=60)
        r.raise_for_status()
        zones = r.json()
    out = build(doc, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), zones)
    OUT.write_text(json.dumps(out, indent=1) + "\n")
    print(f"{OUT.relative_to(ROOT)}: {len(out['counties'])} Mountain-time counties, {len(out['split_counties'])} split")
    return 0


if __name__ == "__main__":
    sys.exit(main())
