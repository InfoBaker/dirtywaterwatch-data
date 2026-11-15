"""Arkansas's 75 counties with their outlines, for the county-aware name placement of Arkansas's reports
(pipeline/build/status.py, COUNTY_STATES and COUNTY_FIELD_STATES; pipeline/ingest/waters_from_nhd.py, the names pass).

DEQ's incident search gives no point and no county, so a report's county is the county of its permit's
treatment plant (EPA ICIS-NPDES point; raw.county_basis says so), used only to judge which of several same-named
waters a report's water name means; a water record's counties are those its box (padded by the name-match
distance) reaches. Arkansas has many same-named creeks (Mill Creek, Spring Creek, Town Branch) in distant counties. The outlines: U.S. Census Bureau TIGERweb,
State_County MapServer layer 1 (counties), state 05, generalised by the service to 0.001 degree, as
scripts/al_counties.py reads Alabama's.

Writes data/reference/ar-counties.json: each county's name, GEOID and outline (coordinates rounded to 4 decimals).

Run from the repository root:
  pipeline/.venv/bin/python scripts/ar_counties.py [--file counties.geojson]
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
OUT = ROOT / "data" / "reference" / "ar-counties.json"
URL = ("https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/State_County/MapServer/1/query"
       "?where=STATE%3D%2705%27&outFields=NAME,GEOID,BASENAME&returnGeometry=true&maxAllowableOffset=0.001"
       "&outSR=4326&f=geojson")


def build(doc: dict, fetched_at: str) -> dict:
    feats = sorted(doc["features"], key=lambda f: f["properties"]["GEOID"])
    if len(feats) != 75:
        raise SystemExit(f"{len(feats)} counties in the TIGERweb answer, not Arkansas's 75")
    return {"state": "AR",
            "rule": ("A report's county is the county whose outline holds its point, else the county its own record "
                     "names; a water record's counties are those its box, padded by the name-match distance, reaches."),
            "source": {"name": "U.S. Census Bureau TIGERweb, State_County layer 1", "url": URL, "fetched_at": fetched_at},
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
    OUT.write_text(json.dumps(build(doc, fetched_at), separators=(",", ":")) + "\n")
    print(f"75 counties -> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
