"""data/outfalls-pr.json: the 12 combined sewer outfalls of PRASA's Puerto Nuevo system from PRASA's own layer.

Usage: pipeline/.venv/bin/python -I scripts/add_pr_cso_outfalls.py [--file saved-layer.json]

Source: PRASA's ArcGIS feature service CSO_Data (registry pr-prasa-cso-data), the layer behind its "Sistema de
Alcantarillado Combinado" map (acueductos.pr.gov/en-us/combinado/mapa-de-ubicacion-csos): 12 points with the outfall
number (cso_num), name, receiving water (receptor) and the receiving water's designated uses (usocuerpor), read once
with outSR=4326 (fetched 2026-11-14; saved to data/raw/pr-prasa-cso-data/layer.json, git-ignored). The street address
field (direccion) and the controls text are not copied.

Rule: one row per PRASA outfall under the Puerto Nuevo permit PR0021555, paired with EPA's national inventory row of the
same permit and outfall number (data/outfalls-us.json, which is left as it is: a state file ranks above it in
common.load_outfall_registry). PRASA's layer gives every point and the receiving water in its own words; EPA's inventory
gives no point for outfall 003 and a longitude for outfall 010 equal to its latitude (-66.44075, about 37 km west of
San Juan), so the layer's points are used for all 12 (each row keeps EPA's in epa_row). Names and receiving waters are
kept as PRASA writes them (Spanish), never translated.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "outfalls-pr.json"
EPA = ROOT / "data" / "outfalls-us.json"
SAVED = ROOT / "data" / "raw" / "pr-prasa-cso-data" / "layer.json"
LAYER = "https://gis.acueductospr.com/arcgis_local/rest/services/Hosted/CSO_Data/FeatureServer/0"
PERMIT = "PR0021555"
READ = "2026-11-14"
UA = {"User-Agent": "DirtyWaterWatch/0.1 (+https://dirtywaterwatch.org)"}


def clean(v) -> str | None:
    v = " ".join(str(v or "").split())
    return v or None


def layer(path: Path | None) -> dict:
    if path:
        return json.loads(path.read_text())
    r = requests.get(f"{LAYER}/query", params={"where": "1=1", "outFields": "*", "outSR": "4326", "f": "json"},
                     headers=UA, timeout=120)
    r.raise_for_status()
    return r.json()


def main(argv: list[str]) -> int:
    path = Path(argv[argv.index("--file") + 1]) if "--file" in argv else (SAVED if SAVED.exists() else None)
    feats = layer(path).get("features") or []
    epa = {str(r.get("outfall")).zfill(3): r for r in json.loads(EPA.read_text())["outfalls"]
           if r.get("npdes_permit") == PERMIT}
    rows = []
    for f in feats:
        a, g = f["attributes"], f.get("geometry") or {}
        num = clean(a.get("cso_num")).zfill(3)
        e = epa.get(num) or {}
        rows.append({
            "npdes_permit": PERMIT, "permittee": "PRASA PUERTO NUEVO WWTP", "state": "PR", "city": "SAN JUAN",
            "outfall": num, "outfall_name": clean(a.get("cso_name")), "outfall_status": "CSO",
            "receiving_water_echo": clean(a.get("receptor")), "receiving_water_source": "operator",
            "designated_uses": clean(a.get("usocuerpor")),
            "lat": round(float(g["y"]), 6), "lon": round(float(g["x"]), 6), "coords_from": "pr-prasa-cso-data",
            "outfall_kind": "cso", "country": "US", "source_id": "pr-prasa-cso-data",
            "source_url": f"{LAYER}/query?where=objectid%3D{a.get('objectid')}&outFields=*&f=json",
            "source_record_id": a.get("objectid"), "checked": READ,
            "epa_row": ({"file": "data/outfalls-us.json", "npdes_permit": PERMIT, "outfall": e.get("outfall"),
                         "outfall_name": e.get("outfall_name"), "receiving_water_echo": e.get("receiving_water_echo"),
                         "lat": e.get("lat"), "lon": e.get("lon"), "paired_by": "the same permit and outfall number"}
                        if e else None),
            "supersedes": f"data/outfalls-us.json {PERMIT} {num}" if e else None,
            "water_slug": None, "match": "none",
        })
    rows.sort(key=lambda r: r["outfall"])
    doc = {"source": f"PRASA's CSO_Data layer (pr-prasa-cso-data), read {READ}; EPA's national CSO inventory "
                     "(data/outfalls-us.json) for the permit and outfall numbers",
           "source_url": LAYER,
           "rule": "one row per PRASA outfall point, paired with EPA's row of the same permit and outfall number; the "
                   "layer's point and receiving water are used, EPA's kept in epa_row",
           "generated": READ, "count": len(rows), "paired_with_epa": sum(1 for r in rows if r["epa_row"]),
           "outfalls": rows}
    if len(rows) != 12 or doc["paired_with_epa"] != 12:
        raise SystemExit(f"expected 12 outfalls paired with EPA's 12, got {len(rows)} / {doc['paired_with_epa']}")
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    print(f"{OUT.name}: {len(rows)} rows, {doc['paired_with_epa']} paired with EPA's inventory")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
