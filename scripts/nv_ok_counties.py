"""Nevada's 17 counties (Carson City among them) and Oklahoma's 77, with their outlines, for the county-aware name
placement of the two states' records (pipeline/build/status.py, COUNTY_STATES and COUNTY_FIELD_STATES; the names pass).

Nevada: the state parks' bloom advisories name a water and the park, never a point; the crosswalk gives each known
water's county (raw.county). Oklahoma: the National Park Service's Chickasaw table names sampling places in Murray
County. A name then resolves only to a water record reaching that county, so a same-named water elsewhere is not taken.
The outlines: U.S. Census Bureau TIGERweb, State_County MapServer layer 1 (counties), states 32 and 40, generalised by
the service to 0.001 degree, as scripts/ks_counties.py reads Kansas's.

Writes data/reference/nv-counties.json and ok-counties.json: each county's name, GEOID and outline (coordinates rounded
to 4 decimals, as every county file under data/reference; a county outline is a public boundary, not a report point).

Run from the repository root:
  pipeline/.venv/bin/python scripts/nv_ok_counties.py [nv|ok ...]
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
STATES = {"nv": ("NV", "32", 17), "ok": ("OK", "40", 77)}
URL = ("https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/State_County/MapServer/1/query"
       "?where=STATE%3D%27{}%27&outFields=NAME,GEOID,BASENAME&returnGeometry=true&maxAllowableOffset=0.001"
       "&outSR=4326&f=geojson")


def build(st: str, doc: dict, fetched_at: str) -> dict:
    code, fips, n = STATES[st]
    feats = sorted(doc["features"], key=lambda f: f["properties"]["GEOID"])
    if len(feats) != n or any(not f["properties"]["GEOID"].startswith(fips) for f in feats):
        raise SystemExit(f"{len(feats)} counties in the TIGERweb answer, not {code}'s {n}")
    return {"state": code,
            "rule": ("A report's county is the county whose outline holds its point, else the county its own record "
                     "names; a water record's counties are those its box, padded by the name-match distance, reaches."),
            "source": {"name": "U.S. Census Bureau TIGERweb, State_County layer 1", "url": URL.format(fips),
                       "fetched_at": fetched_at},
            "counties": [{"county": f["properties"]["NAME"], "geoid": f["properties"]["GEOID"],
                          "geometry": {"type": f["geometry"]["type"], "coordinates": _round(f["geometry"]["coordinates"])}}
                         for f in feats]}


def main(argv) -> int:
    for st in [a for a in argv if a in STATES] or list(STATES):
        r = requests.get(URL.format(STATES[st][1]), headers=HEADERS, timeout=(20, 600))
        r.raise_for_status()
        fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        out = ROOT / "data" / "reference" / f"{st}-counties.json"
        out.write_text(json.dumps(build(st, r.json(), fetched_at), separators=(",", ":")) + "\n")
        print(f"{STATES[st][2]} counties -> {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
