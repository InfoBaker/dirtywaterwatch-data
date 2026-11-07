"""ADEQ's Arizona Waterbody Identifiers (WBIDs) -> names, for the EPA overflow tables' Arizona receiving waters.

Usage: pipeline/.venv/bin/python -I scripts/az_adeq_wbids.py [--dry-run]

Arizona permittees often fill the receiving-water field of their eRule overflow reports with an ADEQ waterbody
identifier ('AZ15060202-421') rather than a name. ADEQ publishes its WBID layers on ArcGIS Online (owner adeq_gis,
read 2026-11-07; access information: ADEQ Water Quality Division, USGS, EPA; licence: provided "as is"):
  - STREAMS WBID AGOL (item 4c285a21f5a84df58b2166544309cd59), 4,165 stream segments: NAME, WBID, ORIGIN, TERMINUS,
    FLOWREGIME (perennial, intermittent, ephemeral ...), CANAL
  - LAKES WBID AGOL (item eecba603b39f49789bf60388fbeba5b7), 315 lakes: NAME, WBID, TYPE
This script keeps the identifier, the name and the segment's description of each (no geometry), in
data/reference/az-adeq-wbids.json, which pipeline/ingest/echo_sewer_overflow_events.py reads (AZ_WBID). EPA's
ATTAINS lists only the assessed units (9 of the 13 codes in the 2026-11-04 extract), so ADEQ's layer is the source.
Rerun when a new code appears unresolved (the module keeps the code as typed and says so in raw).
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "reference" / "az-adeq-wbids.json"
BASE = "https://services.arcgis.com/SzoH1oFM2apCSkx3/arcgis/rest/services"
LAYERS = {
    "stream": (f"{BASE}/STREAMS_WBID_AGOL/FeatureServer/0", "NAME,WBID,ORIGIN,TERMINUS,FLOWREGIME,CANAL",
               "https://www.arcgis.com/home/item.html?id=4c285a21f5a84df58b2166544309cd59"),
    "lake": (f"{BASE}/LAKES_WBID_AGOL/FeatureServer/0", "NAME,WBID,TYPE",
             "https://www.arcgis.com/home/item.html?id=eecba603b39f49789bf60388fbeba5b7"),
}
UA = {"User-Agent": "DirtyWaterWatch/1.0 (+https://dirtywaterwatch.org)"}


def clean(v):
    """Whitespace collapsed; a degree sign the layer stores as '?' between digits ('36?51'30.33"') put back."""
    if v in (None, ""):
        return None
    return re.sub(r"(?<=\d)\?(?=\d)", "\u00b0", " ".join(str(v).split()))


def fetch(url: str, fields: str) -> list[dict]:
    out, offset = [], 0
    while True:
        r = requests.get(f"{url}/query", params={"where": "1=1", "outFields": fields, "returnGeometry": "false",
                                                 "orderByFields": "OBJECTID", "resultOffset": offset,
                                                 "resultRecordCount": 2000, "f": "json"}, headers=UA, timeout=120)
        r.raise_for_status()
        d = r.json()
        if d.get("error"):
            raise RuntimeError(d["error"])
        feats = [f["attributes"] for f in d.get("features", [])]
        out += feats
        if not d.get("exceededTransferLimit") or not feats:
            return out
        offset += len(feats)


def build() -> dict:
    wbids: dict[str, dict] = {}
    counts = {}
    for kind, (url, fields, item) in LAYERS.items():
        rows = fetch(url, fields)
        counts[kind] = len(rows)
        for a in rows:
            w = clean(a.get("WBID"))
            if not w:
                continue
            rec = {"name": clean(a.get("NAME")), "kind": kind}
            if kind == "stream":
                rec.update({"origin": clean(a.get("ORIGIN")), "terminus": clean(a.get("TERMINUS")),
                            "flow_regime": clean(a.get("FLOWREGIME")), "canal": clean(a.get("CANAL"))})
            else:
                rec["type"] = clean(a.get("TYPE"))
            wbids.setdefault(w, {k: v for k, v in rec.items() if v is not None})
    return {"about": "ADEQ waterbody identifiers (WBIDs) and their names, from ADEQ's WBID layers on ArcGIS Online; "
                     "scripts/az_adeq_wbids.py",
            "source": {k: {"layer": v[0], "item": v[2]} for k, v in LAYERS.items()},
            "attribution": "Arizona Department of Environmental Quality (ADEQ), Water Quality Division",
            "checked": date.today().isoformat(), "counts": counts,
            "wbids": dict(sorted(wbids.items()))}


def main(argv: list[str]) -> int:
    doc = build()
    print(json.dumps(doc["counts"]), len(doc["wbids"]), "identifiers")
    if "--dry-run" not in argv:
        OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
