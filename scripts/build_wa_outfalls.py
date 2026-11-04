"""Washington outfall rows that improve on EPA's (data/outfalls-wa.json): the King County / Seattle CSO status file.

Usage: pipeline/.venv/bin/python -I scripts/build_wa_outfalls.py [CSV]
  CSV: a saved copy of https://your.kingcounty.gov/dnrp/library/wastewater/cso/img/CSO_metadata.CSV
       (default: the newest file under data/raw/wa-kc-cso-status/).

Why: EPA's national CSO inventory (data/outfalls-us.json) lists all 86 of Seattle's CSO outfalls (WA0031682) and 44
of King County's 48 (WA0029181) as closed, while King County's status file reports a live status for 89 Seattle
and 36 King County outfalls every 10 minutes. Each outfall of the file becomes a registry row here, citing the
file; the file's discharge serial number (DSN) is the permit's outfall number. A registry file of a region outranks
the national file (common.outfall_file_rank), so these rows replace EPA's for the same permit and outfall; EPA's row
stays in data/outfalls-us.json untouched and each row here names it in `supersedes`.
  - Point: the file's (coords_from "operator status file"). Five Seattle rows carry a placeholder (-120.0, 47.26):
    EPA's point for the outfall is used when EPA has one (coords_from "EPA ICIS-NPDES permitted feature"), else the
    outfall is listed in `not_placed` with no row.
  - outfall_name: King County's label ("Ballard"); Seattle's file gives none, so "Seattle CSO outfall <DSN>" (EPA's
    names for Seattle are street addresses and are not copied).
  - EPA's receiving-water text is not copied: for these two permits it is a permit-level label, wrong for many
    outfalls (King County's Henderson outfall on Lake Washington reads "Duwamish Waterway", its 8th Ave outfall on
    the Duwamish "Lake Washington-Sammamish River"; review 2026-11-04). It stays in supersedes.receiving_water_echo
    for reference. The operator's point decides the water: python -m ingest.outfall_waters --state WA ties each row
    by its point and the permit's listed receiving waters, or gives the reason.
  - outfall_status "active (status file)": the operator reports the outfall's status; it is not a statement that
    the outfall overflows.
"""
from __future__ import annotations

import csv
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
from ingest.wa_transforms import dsn, kc_operator  # noqa: E402

OUT = ROOT / "data" / "outfalls-wa.json"
RAW = ROOT / "data" / "raw" / "wa-kc-cso-status"
URL = "https://your.kingcounty.gov/dnrp/library/wastewater/cso/img/CSO_metadata.CSV"
PAGE = "https://kingcounty.gov/en/dept/dnrp/waste-services/wastewater-treatment/sewer-system-services/cso-status"
PLACEHOLDER = (-120.0, 47.26)
COPY = ("echo_url", "permit_status", "in_icis")


def epa_rows() -> dict[tuple[str, str], dict]:
    doc = json.loads((ROOT / "data" / "outfalls-us.json").read_text())
    rows = doc["outfalls"] if isinstance(doc, dict) else doc
    return {(r["npdes_permit"], str(r.get("outfall") or "").zfill(3)): r for r in rows
            if r.get("npdes_permit") in ("WA0029181", "WA0031682")}


def build(text: str, fetched_at: str) -> dict:
    epa = epa_rows()
    rows, not_placed = [], []
    for r in csv.DictReader(io.StringIO(text.lstrip("﻿"))):
        name = (r.get("Name") or "").strip()
        op = kc_operator(name)
        out = dsn(r.get("DSN"))
        if op is None or out is None:
            continue                                    # the legend rows (Dummy1-4)
        did, permit, operator = op
        e = epa.get((permit, out)) or {}
        try:
            lon, lat = float(r["X_COORD"]), float(r["Y_COORD"])
        except (TypeError, ValueError):
            lon = lat = None
        coords_from = "operator status file"
        if lon is None or (round(lon, 2), round(lat, 2)) == PLACEHOLDER:
            if e.get("lat") is not None:
                lat, lon, coords_from = e["lat"], e["lon"], "EPA ICIS-NPDES permitted feature (the status file gives a placeholder)"
            else:
                not_placed.append({"npdes_permit": permit, "outfall": out, "why": "the status file gives a placeholder "
                                   "point and EPA lists no point for this outfall"})
                continue
        label = name.split(":", 1)[1].strip() if ":" in name else f"Seattle CSO outfall {out}"
        row = {"npdes_permit": permit, "permittee": operator, "discharger_id": did, "state": "WA", "city": "SEATTLE",
               "outfall": out, "outfall_name": label, "outfall_status": "active (status file)", "feature_type": "EXO",
               "lat": round(lat, 7), "lon": round(lon, 7), "coords_from": coords_from, "outfall_kind": "cso",
               "country": "US", "source": "wa-kc-cso-status-csv", "source_url": URL, "page_url": PAGE,
               "status_tag": r.get("CSO_TagName"), "fetched_at": fetched_at,
               "supersedes": ({"file": "data/outfalls-us.json", "npdes_permit": permit, "outfall": e.get("outfall"),
                               "outfall_status": e.get("outfall_status"),
                               "receiving_water_echo": e.get("receiving_water_echo"),
                               "receiving_water_note": "EPA's text for this outfall, a permit-level label not used for "
                                                       "the tie (the operator's point is)"} if e else None)}
        row.update({k: e.get(k) for k in COPY if e.get(k) is not None})
        rows.append(row)
    rows.sort(key=lambda x: (x["npdes_permit"], x["outfall"]))
    return {"source": f"King County CSO status file ({URL}), fetched {fetched_at}; EPA's rows for the same permit and "
                      "outfall (data/outfalls-us.json) are kept and named in supersedes",
            "rule": "one row per outfall of the status file; DSN = the permit's outfall number; the file's point unless "
                    "it is the placeholder (-120.0, 47.26), then EPA's point",
            "count": len(rows), "outfalls": rows, "not_placed": not_placed}


def main(argv: list[str]) -> int:
    path = Path(argv[0]) if argv else max(RAW.glob("*.csv"), key=lambda p: p.stat().st_mtime)
    fetched = argv[1] if len(argv) > 1 else "2026-11-04T10:30:14Z"
    doc = build(path.read_text(encoding="utf-8"), fetched)
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps({"rows": doc["count"], "not_placed": len(doc["not_placed"]),
                      "superseding": sum(1 for r in doc["outfalls"] if r["supersedes"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
