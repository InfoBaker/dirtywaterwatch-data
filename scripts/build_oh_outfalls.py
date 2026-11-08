"""Ohio outfall rows that improve on EPA's (data/outfalls-oh.json): NEORSD's CSO alerts map layers.

Usage: pipeline/.venv/bin/python -I scripts/build_oh_outfalls.py [LAYER4.json LAYER5.json]
  The saved answers of NEORSD's layers 4 (metered outfalls) and 5 (the others), asked for the safe fields of
  pipeline/ingest/oh_neorsd_cso.py (default: data/raw/oh-neorsd/q4.json and q5.json); the service is
  https://utility.arcgis.com/usrsvcs/servers/d1477ea79422426b90560e015ce2bad9/rest/services/Public/
  CSONotificationApp_PROD/MapServer.

Why: EPA's national CSO inventory (data/outfalls-us.json) lists 133 outfalls for NEORSD's permit OH0043991, every one
at the plant's point (coords_from "facility") and none with a receiving water. NEORSD's layers give each of its 112
open outfalls its own point and receiving water; the CSO number is EPA's outfall number (all 112 pair). Each becomes a
registry row here citing the layer; a regional file outranks the national one (common.outfall_file_rank), so these
rows replace EPA's for the same permit and outfall, and EPA's row stays in data/outfalls-us.json untouched, named in
`supersedes`. EPA's 21 other NEORSD outfalls (not on NEORSD's map) keep EPA's rows.
  - outfall_name: the CSO number and NEORSD's location text, a house number in it cut (oh_neorsd_cso.scrub_location).
  - receiving_water_echo: NEORSD's receiving water ("Big Creek"); the water record is tied by the cloud batch
    (python -m ingest.outfall_waters --state OH), not here.
  - monitored: true for layer 4 (NEORSD meters it), false for layer 5 (NEORSD's model gives its overflows).
  - outfall_status "active (operator map)": the outfall is on NEORSD's map; not a statement that it overflows.
Akron's layer is not used here: its site names ("CSO BASIN 12", "Rack 03") do not map to the permit's outfall
numbers in any public table, so Akron keeps EPA's rows.
"""
from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
from ingest.oh_neorsd_cso import LAYERS, PAGE_URL, PERMIT, SERVICE, cso_number, rows_of, water_name  # noqa: E402

OUT = ROOT / "data" / "outfalls-oh.json"
RAW = ROOT / "data" / "raw" / "oh-neorsd"


def build(docs: dict[int, dict], fetched_at: str) -> dict:
    epa = {r["outfall"]: r for r in json.loads((ROOT / "data" / "outfalls-us.json").read_text())["outfalls"]
           if r["npdes_permit"] == PERMIT}
    rows, unpaired = [], []
    for lid, doc in docs.items():
        for a in rows_of(doc, LAYERS[lid]):
            num = cso_number(a)
            if not num or a.get("_lat") is None:
                continue
            e = epa.get(num)
            row = {"npdes_permit": PERMIT, "permittee": "Northeast Ohio Regional Sewer District",
                   "discharger_id": "oh-northeast-ohio-regional-sd-oh0043991", "state": "OH", "city": "CLEVELAND", "outfall": num,
                   "outfall_name": " ".join(x for x in (a.get("CSONUMBER"), a.get("LOCATION")) if x),
                   "outfall_status": "active (operator map)", "feature_type": "EXO",
                   "receiving_water_echo": water_name(a.get("RECIEVINGWATER")),
                   "monitored": LAYERS[lid] == "metered", "treatment_plant_area": a.get("WWTP"),
                   "control_measure": a.get("CONTROLMEASURE"), "public_access_area": a.get("PUBLICACCESSAREA"),
                   "ohio_epa_station": a.get("PERMITNUMBER"),
                   "lat": round(a["_lat"], 6), "lon": round(a["_lon"], 6), "coords_from": "operator map layer",
                   "outfall_kind": "cso", "country": "US", "source": "oh-neorsd-cso-notification-map",
                   "source_url": f"{SERVICE}/{lid}", "page_url": PAGE_URL, "source_record_id": a.get("OBJECTID"),
                   "fetched_at": fetched_at}
            if e:
                row.update(echo_url=e.get("echo_url"), permit_status=e.get("permit_status"), in_icis=e.get("in_icis"),
                           supersedes={"file": "data/outfalls-us.json", "npdes_permit": PERMIT, "outfall": e["outfall"],
                                       "coords_from": e.get("coords_from"),
                                       "note": "EPA's row gives the plant's point and no receiving water"})
            else:
                unpaired.append(num)
            rows.append(row)
    rows.sort(key=lambda r: r["outfall"])
    return {"source": (f"NEORSD CSO alerts map layers 4 and 5 ({SERVICE}), fetched {fetched_at}; EPA's rows for the "
                       "same permit and outfall (data/outfalls-us.json) are kept and named in supersedes"),
            "rule": "one row per outfall on NEORSD's map; the CSO number is the permit's outfall number; NEORSD's point",
            "generated": datetime.now(UTC).date().isoformat(), "count": len(rows), "paired_with_epa": len(rows) - len(unpaired),
            "unpaired": unpaired,
            "epa_not_on_operator_map": [
                {"npdes_permit": PERMIT, "outfall": n,
                 "reason": ("open in EPA's CSO inventory but not on NEORSD's CSO alerts map; EPA gives only the plant's "
                            "point and no receiving water, so it stays EPA's row, tied to no water until NEORSD or "
                            "EPA gives its place")}
                for n in sorted(k for k, e in epa.items() if k not in {r["outfall"] for r in rows}
                                and not str(e.get("outfall_status") or "").upper().startswith("CLS"))],
            "outfalls": rows}


def main(argv) -> int:
    files = argv[1:3] if len(argv) >= 3 else [str(RAW / "q4.json"), str(RAW / "q5.json")]
    docs = {lid: json.loads(Path(f).read_text()) for lid, f in zip(LAYERS, files)}
    fetched = datetime.fromtimestamp(Path(files[0]).stat().st_mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = build(docs, fetched)
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print(f"{out['count']} NEORSD outfalls ({out['paired_with_epa']} paired with EPA's rows) -> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
