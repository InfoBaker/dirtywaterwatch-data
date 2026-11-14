"""West Wendover, Nevada's city limits, for Nevada's clock (pipeline/zones.py, nevada_zone).

49 CFR 71.9(b) (read in eCFR, 2026-11-14): the Mountain-Pacific line runs "from the northeast corner of the State of
Nevada southerly along the Utah-Nevada boundary to the junction with the northern border of the City of West Wendover,
Nevada. Then westward along the northern, western, and southern boundaries of the City of West Wendover back to the
Utah-Nevada boundary"; 71.9(d): "All municipalities located upon the zone boundary line described in this section are
in the mountain standard time zone." West Wendover keeps Mountain time; the rest of Nevada, Pacific. (Jackpot and
other border towns that keep Mountain time by local custom are Pacific in law, and the law is the rule here.)

The outline: U.S. Census Bureau TIGERweb, Places_CouSub_ConCity_SubMCD MapServer layer 4 (Incorporated Places, the
current vintage), state 32, "West Wendover city", generalised by the service to 0.0005 degree.

Writes data/reference/nv-west-wendover.json: the city's name, GEOID and outline (coordinates rounded to 4 decimals).

Run from the repository root:
  pipeline/.venv/bin/python scripts/nv_west_wendover.py [--file place.geojson]
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
OUT = ROOT / "data" / "reference" / "nv-west-wendover.json"
URL = ("https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Places_CouSub_ConCity_SubMCD/MapServer/4/query"
       "?where=STATE%3D%2732%27+AND+BASENAME%3D%27West+Wendover%27&outFields=NAME,GEOID,BASENAME&returnGeometry=true"
       "&maxAllowableOffset=0.0005&outSR=4326&f=geojson")
LAW = {"cite": "49 CFR 71.9(b) and (d)", "url": "https://www.ecfr.gov/current/title-49/subtitle-A/part-71/section-71.9"}


def build(doc: dict, fetched_at: str) -> dict:
    feats = doc.get("features") or []
    if len(feats) != 1:
        raise SystemExit(f"{len(feats)} places in the TIGERweb answer, not West Wendover alone")
    f = feats[0]
    return {"state": "NV", "zone": "America/Denver", "law": LAW,
            "rule": ("A Nevada record whose point lies inside West Wendover's city limits is read in Mountain time; "
                     "every other Nevada record, and one with no point, in Pacific time."),
            "source": {"name": "U.S. Census Bureau TIGERweb, Incorporated Places (layer 4)", "url": URL,
                       "fetched_at": fetched_at},
            "place": {"name": f["properties"]["NAME"], "geoid": f["properties"]["GEOID"],
                      "geometry": {"type": f["geometry"]["type"], "coordinates": _round(f["geometry"]["coordinates"])}}}


def main(argv) -> int:
    if "--file" in argv:
        doc = json.loads(Path(argv[argv.index("--file") + 1]).read_text())
        fetched_at = argv[argv.index("--fetched-at") + 1] if "--fetched-at" in argv else "from file"
    else:
        r = requests.get(URL, headers=HEADERS, timeout=(20, 300))
        r.raise_for_status()
        doc = r.json()
        fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    OUT.write_text(json.dumps(build(doc, fetched_at), separators=(",", ":")) + "\n")
    print(f"West Wendover -> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
