"""Tennessee's Eastern-time counties, with their outlines, for the Tennessee time-zone rule (pipeline/zones.py,
tennessee_zone).

The rule's public records
  - The zone boundary: 49 CFR 71.5(d), "Boundary line between eastern and central zones", which in Tennessee follows
    county lines from the Kentucky line to the Georgia line, leaving East Tennessee in the Eastern zone
    (https://www.law.cornell.edu/cfr/text/49/71.5, read 2026-11-07).
  - Read with the county map, the line leaves thirty counties wholly in the Eastern zone (EASTERN_COUNTIES below) and
    splits none. Checked against the U.S. Department of Transportation's time-zone layer (NTAD Time Zones,
    https://services.arcgis.com/xOi1kZaI0eWDREZv/arcgis/rest/services/NTAD_Time_Zones/FeatureServer/0, read
    2026-11-07): each of the thirty lies wholly in its Eastern polygon, and no other Tennessee county more than 1%.
  - The outlines: U.S. Census Bureau TIGERweb, State_County MapServer layer 1 (counties), state 47, generalised by the
    service to 0.001 degree.

Writes data/reference/tn-eastern-time-counties.json: the thirty counties' names, GEOIDs and outlines (coordinates
rounded to 4 decimals). The other sixty-five counties keep Central time. Also writes data/reference/tn-counties.json,
all ninety-five counties in the shape of tx-counties.json, for the status build's county-aware name placement
(build/status.py COUNTY_STATES).

Run from the repository root:
  pipeline/.venv/bin/python scripts/tn_eastern_time_counties.py [--file counties.geojson]
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "reference" / "tn-eastern-time-counties.json"
ALL_OUT = ROOT / "data" / "reference" / "tn-counties.json"
URL = ("https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/State_County/MapServer/1/query"
       "?where=STATE%3D%2747%27&outFields=NAME,GEOID,BASENAME&returnGeometry=true&maxAllowableOffset=0.001"
       "&outSR=4326&f=geojson")
EASTERN_COUNTIES = ("Anderson", "Blount", "Bradley", "Campbell", "Carter", "Claiborne", "Cocke", "Grainger", "Greene",
                    "Hamblen", "Hamilton", "Hancock", "Hawkins", "Jefferson", "Johnson", "Knox", "Loudon", "McMinn",
                    "Meigs", "Monroe", "Morgan", "Polk", "Rhea", "Roane", "Scott", "Sevier", "Sullivan", "Unicoi",
                    "Union", "Washington")
CFR = "49 CFR 71.5(d)"
CFR_URL = "https://www.law.cornell.edu/cfr/text/49/71.5"


def _round(coords):
    if isinstance(coords[0], (int, float)):
        return [round(coords[0], 4), round(coords[1], 4)]
    return [_round(c) for c in coords]


def build(doc: dict, fetched_at: str) -> dict:
    by = {f["properties"]["BASENAME"]: f for f in doc["features"]}
    missing = [n for n in EASTERN_COUNTIES if n not in by]
    if missing:
        raise SystemExit(f"counties missing from the TIGERweb answer: {missing}")

    def row(n):
        f = by[n]
        return {"county": f["properties"]["NAME"], "geoid": f["properties"]["GEOID"],
                "geometry": {"type": f["geometry"]["type"], "coordinates": _round(f["geometry"]["coordinates"])}}
    return {
        "state": "TN",
        "zone": "America/New_York",
        "other_zone": "America/Chicago",
        "rule": (f"The Eastern-Central boundary in Tennessee ({CFR}) follows county lines from Kentucky to Georgia; the "
                 "thirty counties listed (East Tennessee) lie wholly east of it, in the Eastern zone. The other "
                 "sixty-five keep Central time; no county is split."),
        "law": {"cite": CFR, "url": CFR_URL, "read": "2026-11-07"},
        "checked_against": {"name": "U.S. DOT NTAD Time Zones",
                            "url": "https://services.arcgis.com/xOi1kZaI0eWDREZv/arcgis/rest/services/NTAD_Time_Zones/FeatureServer/0",
                            "read": "2026-11-07"},
        "source": {"name": "U.S. Census Bureau TIGERweb, State_County layer 1", "url": URL, "fetched_at": fetched_at},
        "counties": [row(n) for n in EASTERN_COUNTIES],
    }


def all_counties(doc: dict, fetched_at: str) -> dict:
    rows = sorted(({"county": f["properties"]["NAME"], "geoid": f["properties"]["GEOID"],
                    "geometry": {"type": f["geometry"]["type"], "coordinates": _round(f["geometry"]["coordinates"])}}
                   for f in doc["features"]), key=lambda r: r["county"])
    if len(rows) != 95:
        raise SystemExit(f"{len(rows)} counties in the TIGERweb answer, not 95")
    return {"state": "TN",
            "rule": ("A report's county is the county its point lies in, or its own county field (TDEC's Events Report "
                     "gives no point); a water record's counties are those its box, padded by the name-match distance, "
                     "reaches."),
            "source": {"name": "U.S. Census Bureau TIGERweb, State_County layer 1", "url": URL, "fetched_at": fetched_at},
            "counties": rows}


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--file" in argv:
        doc = json.loads(Path(argv[argv.index("--file") + 1]).read_text())
    else:
        r = requests.get(URL, timeout=120)
        r.raise_for_status()
        doc = r.json()
    fetched = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = build(doc, fetched)
    OUT.write_text(json.dumps(out, separators=(",", ":")) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(out['counties'])} counties")
    every = all_counties(doc, fetched)
    ALL_OUT.write_text(json.dumps(every, separators=(",", ":")) + "\n")
    print(f"wrote {ALL_OUT.relative_to(ROOT)}: {len(every['counties'])} counties")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
