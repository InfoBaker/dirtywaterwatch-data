"""Texas's 254 counties with their outlines, for the county-aware name placement of Texas's reports
(pipeline/build/status.py, COUNTY_STATES; pipeline/ingest/waters_from_nhd.py, the names pass).

TCEQ's Sanitary Sewer Overflows table gives every report its county but no point, so a report's county is its own
county field (raw.county); a water record's counties are those its box (padded by the name-match distance) reaches.
The outlines: U.S. Census Bureau TIGERweb, State_County MapServer layer 1 (counties), state 48, generalised by the
service to 0.001 degree (the same layer as scripts/al_counties.py).

Writes data/reference/tx-counties.json: each county's name, GEOID and outline (coordinates rounded to 4 decimals).

Run from the repository root:
  pipeline/.venv/bin/python scripts/tx_counties.py [--file counties.geojson]
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from al_counties import HEADERS, _round  # noqa: E402

OUT = ROOT / "data" / "reference" / "tx-counties.json"
URL = ("https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/State_County/MapServer/1/query"
       "?where=STATE%3D%2748%27&outFields=NAME,GEOID,BASENAME&returnGeometry=true&maxAllowableOffset=0.001"
       "&outSR=4326&f=geojson")


def build(doc: dict, fetched_at: str) -> dict:
    feats = sorted(doc["features"], key=lambda f: f["properties"]["GEOID"])
    if len(feats) != 254:
        raise SystemExit(f"{len(feats)} counties in the TIGERweb answer, not Texas's 254")
    return {"state": "TX",
            "rule": ("A report's county is its own county field (TCEQ's table gives no point); a water record's counties "
                     "are those its box, padded by the name-match distance, reaches."),
            "source": {"name": "U.S. Census Bureau TIGERweb, State_County layer 1", "url": URL, "fetched_at": fetched_at},
            "counties": [{"county": f["properties"]["NAME"], "geoid": f["properties"]["GEOID"],
                          "geometry": {"type": f["geometry"]["type"], "coordinates": _round(f["geometry"]["coordinates"])}}
                         for f in feats]}


def main(argv) -> int:
    if "--file" in argv:
        doc = json.loads(Path(argv[argv.index("--file") + 1]).read_text())
        fetched_at = "from file"
    else:
        r = requests.get(URL, headers=HEADERS, timeout=(20, 900))
        r.raise_for_status()
        doc = r.json()
        fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = build(doc, fetched_at)
    OUT.write_text(json.dumps(out, separators=(",", ":")) + "\n")
    print(f"{len(out['counties'])} counties -> {OUT.relative_to(ROOT)} ({OUT.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
