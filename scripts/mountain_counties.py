"""Colorado's, Montana's or Wyoming's counties with their outlines, for the county-aware name placement of the state's
reports (pipeline/build/status.py, COUNTY_STATES and COUNTY_FIELD_STATES): a name is placed only on a water record whose
box reaches the county the report's point lies in, or the county its own record names (raw.county). The three states
have many waters of one name (Colorado's Bear Creeks, Montana's Willow Creeks, Wyoming's Sand Creeks).

The outlines: U.S. Census Bureau TIGERweb, State_County MapServer layer 1 (counties), generalised by the service to
0.001 degree, as scripts/wi_counties.py reads Wisconsin's (coordinates rounded to 4 decimals by al_counties._round).
Colorado (FIPS 08) has 64 counties, Montana (30) 56, Wyoming (56) 23.

Writes data/reference/<st>-counties.json. Run from the repository root:
  pipeline/.venv/bin/python scripts/mountain_counties.py CO|MT|WY [--file counties.geojson --fetched-at ISO]
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
STATES = {"CO": ("08", 64), "MT": ("30", 56), "WY": ("56", 23)}


def url(fips: str) -> str:
    return ("https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/State_County/MapServer/1/query"
            f"?where=STATE%3D%27{fips}%27&outFields=NAME,GEOID,BASENAME&returnGeometry=true&maxAllowableOffset=0.001"
            "&outSR=4326&f=geojson")


def build(st: str, doc: dict, fetched_at: str) -> dict:
    fips, n = STATES[st]
    feats = sorted(doc["features"], key=lambda f: f["properties"]["GEOID"])
    if len(feats) != n:
        raise SystemExit(f"{len(feats)} counties in the TIGERweb answer, not {st}'s {n}")
    return {"state": st,
            "rule": ("A report's county is the county whose outline holds its point, else the county its own record "
                     "names; a water record's counties are those its box, padded by the name-match distance, reaches."),
            "source": {"name": "U.S. Census Bureau TIGERweb, State_County layer 1", "url": url(fips),
                       "fetched_at": fetched_at},
            "counties": [{"county": f["properties"]["NAME"], "geoid": f["properties"]["GEOID"],
                          "geometry": {"type": f["geometry"]["type"], "coordinates": _round(f["geometry"]["coordinates"])}}
                         for f in feats]}


def main(argv) -> int:
    st = argv[0].upper()
    fips, n = STATES[st]
    if "--file" in argv:
        doc = json.loads(Path(argv[argv.index("--file") + 1]).read_text())
        fetched_at = argv[argv.index("--fetched-at") + 1] if "--fetched-at" in argv else "from file"
    else:
        r = requests.get(url(fips), headers=HEADERS, timeout=(20, 600))
        r.raise_for_status()
        doc = r.json()
        fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = ROOT / "data" / "reference" / f"{st.lower()}-counties.json"
    out.write_text(json.dumps(build(st, doc, fetched_at), separators=(",", ":")) + "\n")
    print(f"{n} counties -> {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
