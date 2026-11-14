"""data/outfalls-mo.json: Missouri's combined sewer outfalls from the Department of Natural Resources' NPDES outfall layer,
correcting EPA's national CSO inventory (data/outfalls-us.json, left as it is).

Usage: pipeline/.venv/bin/python -I scripts/mo_outfall_layer.py [--file data/raw/mo-dnr-npdes-outfalls/cso.json]

Source: DNR's NPDES Waste Water Outfalls map service, layer 1
(https://gis.dnr.mo.gov/host/rest/services/waste/NPDES_WasteWaterOutfalls/MapServer/1), one point per permitted feature,
EPSG:26915 read as WGS84 (outSR 4326), 2,000 rows a page. The query asks for the rows with CSO = 'Y' (the feature is a
combined sewer overflow) or CSO_FLAG = 'Y' (the permit has one) and only the fields below; the owner, mailing and phone
fields of the layer are never requested. Read 2026-11-14: 7,533 features in the layer, 165 on CSO permits, 146 of them
CSO features on five permits: MSD's Lemay plant MO0025151 (120), St. Joseph MO0023043 (14), KC Water's Westside plant
MO0024929 (5), Moberly MO0117960 (4) and Macon MO0023221 (3). The other 19 are the same permits' plant and stormwater
outfalls, which stay EPA's plant rows (data/outfalls-plants-us.json).

Rules
  - One row per CSO feature (PERMIT_ID + P_FEAT_ID), the registry row shape (data/outfalls-oh.json): DNR's point, its
    receiving stream (REC_STREAM) as the receiving water, DNR's continuing authority (CA_NAME, a city or district) as
    the permittee, the facility name as permit_name, and the layer's own provenance (horizontal accuracy in metres and the
    method that fixed the point). STATUS is the permit's ("Effective", "Expired": an expired permit is administratively
    continued until reissued, so the outfall stays open); no row says when an outfall overflowed.
  - Where EPA's inventory has the same permit and outfall number, DNR's row supersedes it ("supersedes" names EPA's row).
    EPA lists MSD's Lemay permit with three closed outfalls and none open; DNR's 120 open Lemay CSO outfalls (River des
    Peres and its tributaries, Black Creek, Deer Creek and Mississippi tributaries) are new rows.
  - EPA's open CSO rows that DNR's layer does not flag stay EPA's rows and are listed in epa_not_on_state_layer: KC
    Water's Blue River plant MO0024911 (80), Cape Girardeau MO0050580 (1) and Show Me Ethanol MO0134198 (1).
  - Show Me Ethanol (MO0134198) is an ethanol plant, not a sewer system: its single outfall EPA flags as a CSO is kind
    "other" here (kept off the map, out of the outfall count and the rain caution) until the permit shows a combined
    sewer; EPA's row is named in supersedes.
  - MSD's Bissell Point plant (MO0025178, DNR's issued-permit listing, effective 2026-09-01) is in neither inventory:
    its outfalls are unknown here and the state text says so.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "mo-dnr-npdes-outfalls" / "cso.json"
EPA = ROOT / "data" / "outfalls-us.json"
OUT = ROOT / "data" / "outfalls-mo.json"
LAYER = "https://gis.dnr.mo.gov/host/rest/services/waste/NPDES_WasteWaterOutfalls/MapServer/1"
PAGE = "https://dnr.mo.gov/data-e-services/geographic-information-systems"
FIELDS = ("OBJECTID,PERMIT_ID,P_FEAT_ID,GIS_LOC_ID,FAC_NAME,FAC_COUNTY,STATUS,CSO,CSO_FLAG,PF_TYPE,REC_STREAM,WB_NAME,"
          "WBID,NHD_ID,HUC_8,HACCURACY,HCOLLTEXT,EPE,DATECOLL,PF_ACTIVE,PF_EXPIRE,P_TYPE,P_CAT,WASTE_TYPE,MAJOR,CA_NAME,"
          "CA_LEVEL,PRIMARY_PF,TOTAL_PF,FLOW_DSGN,SIC_DESC")
HEADERS = {"User-Agent": "DirtyWaterWatch/0.1 (+https://dirtywaterwatch.org; admin@infobakery.com)"}
NOT_SEWAGE = {"MO0134198": ("An ethanol plant's outfall that EPA's CSO inventory flags as a combined sewer overflow; the "
                            "permit is an industrial one and no combined sewer is shown, so the row is kept off the map "
                            "and out of the outfall count until the permit confirms one.")}
PERMITTEE = {"Metropolitan St. Louis Sewer District": "Metropolitan St. Louis Sewer District",
             "City of Kansas City": "City of Kansas City (KC Water)"}


def fetch() -> dict:
    r = requests.get(f"{LAYER}/query", headers=HEADERS, timeout=(20, 300), params={
        "where": "CSO='Y' OR CSO_FLAG='Y'", "outFields": FIELDS, "outSR": 4326, "f": "json",
        "resultRecordCount": 2000, "orderByFields": "OBJECTID"})
    r.raise_for_status()
    doc = r.json()
    if doc.get("exceededTransferLimit"):
        raise SystemExit("more than one page of CSO features: page the query")
    RAW.parent.mkdir(parents=True, exist_ok=True)
    RAW.write_text(json.dumps(doc))
    return doc


def build(doc: dict, epa_rows: list[dict], fetched_at: str) -> dict:
    epa = {(r["npdes_permit"], str(r.get("outfall") or "")): r for r in epa_rows if r.get("state") == "MO"}
    rows, paired = [], set()
    for f in sorted(doc["features"], key=lambda f: (f["attributes"]["PERMIT_ID"], f["attributes"]["P_FEAT_ID"])):
        a, g = f["attributes"], f.get("geometry") or {}
        if a.get("CSO") != "Y":
            continue
        p, o = a["PERMIT_ID"], str(a["P_FEAT_ID"]).strip()
        e = epa.get((p, o))
        row = {"npdes_permit": p, "permittee": PERMITTEE.get(a.get("CA_NAME"), a.get("CA_NAME")),
               "permit_name": a.get("FAC_NAME"), "state": "MO", "county": a.get("FAC_COUNTY"),
               "outfall": o, "outfall_name": None, "outfall_status": "open (DNR outfall layer)",
               "permit_status_dnr": a.get("STATUS"), "feature_type": a.get("PF_TYPE"),
               "receiving_water_echo": a.get("REC_STREAM"), "receiving_water_source": "state",
               "dnr_water_body": a.get("WB_NAME"), "dnr_wbid": a.get("WBID"), "huc_8": a.get("HUC_8"),
               "lat": round(g["y"], 6) if g.get("y") is not None else None,
               "lon": round(g["x"], 6) if g.get("x") is not None else None,
               "coords_from": "state outfall layer", "horizontal_accuracy_m": a.get("HACCURACY"),
               "coords_method": a.get("HCOLLTEXT"), "outfall_kind": "cso", "country": "US",
               "source": "mo-dnr-npdes-outfalls", "source_url": LAYER, "page_url": PAGE,
               "source_record_id": a.get("OBJECTID"), "gis_loc_id": a.get("GIS_LOC_ID"), "fetched_at": fetched_at}
        if e:
            paired.add((p, o))
            row["echo_url"] = e.get("echo_url")
            row["supersedes"] = {"file": "data/outfalls-us.json", "npdes_permit": p, "outfall": o,
                                 "outfall_status": e.get("outfall_status"),
                                 "note": "EPA's row for the same permit and outfall; DNR's point and receiving stream"}
        rows.append(row)
    unpaired_epa = []
    for (p, o), e in sorted(epa.items()):
        if (p, o) in paired or str(e.get("outfall_status") or "").upper().startswith("CLS"):
            continue
        if p in NOT_SEWAGE:
            rows.append({**e, "outfall_kind": "other", "kind_note": NOT_SEWAGE[p], "checked": fetched_at[:10],
                         "supersedes": {"file": "data/outfalls-us.json", "npdes_permit": p, "outfall": o,
                                        "note": "EPA's row, held back from the CSO count"}})
        unpaired_epa.append({"npdes_permit": p, "outfall": o, "permittee": e.get("permittee"),
                             "reason": (NOT_SEWAGE[p] if p in NOT_SEWAGE else
                                        "open in EPA's CSO inventory but not flagged CSO on DNR's outfall layer; it "
                                        "stays EPA's row")})
    by = Counter(r["npdes_permit"] for r in rows if r["outfall_kind"] == "cso")
    return {"source": f"Missouri DNR NPDES Waste Water Outfalls, layer 1 ({LAYER}), CSO = 'Y', fetched {fetched_at}; "
                      "EPA's rows for the same permit and outfall (data/outfalls-us.json) are kept and named in supersedes",
            "rule": "one row per CSO feature on DNR's layer; the feature id is the permit's outfall number; DNR's point",
            "generated": fetched_at[:10], "count": len(rows), "cso_by_permit": dict(sorted(by.items())),
            "paired_with_epa": len(paired), "epa_not_on_state_layer": unpaired_epa,
            "not_in_either_inventory": [{"npdes_permit": "MO0025178", "permittee": "Metropolitan St. Louis Sewer District",
                                         "permit_name": "Bissell Point Wastewater Treatment Plant",
                                         "reason": ("DNR's issued-permit listing names the permit (effective 2026-09-01); "
                                                    "neither DNR's outfall layer nor EPA's inventory lists its combined "
                                                    "sewer outfalls")}],
            "outfalls": rows}


def main(argv) -> int:
    if "--file" in argv:
        doc = json.loads(Path(argv[argv.index("--file") + 1]).read_text())
    elif RAW.exists():
        doc = json.loads(RAW.read_text())
    else:
        doc = fetch()
    if "--fetched-at" in argv:
        fetched_at = argv[argv.index("--fetched-at") + 1]
    else:                                           # the saved answer's own time (the file is written at the fetch)
        from datetime import datetime, timezone
        src = Path(argv[argv.index("--file") + 1]) if "--file" in argv else RAW
        fetched_at = datetime.fromtimestamp(src.stat().st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = build(doc, json.loads(EPA.read_text())["outfalls"], fetched_at)
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print(f"{OUT.name}: {out['count']} rows, {out['paired_with_epa']} paired with EPA, by permit {out['cso_by_permit']}, "
          f"EPA open rows not on DNR's layer {len(out['epa_not_on_state_layer'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
