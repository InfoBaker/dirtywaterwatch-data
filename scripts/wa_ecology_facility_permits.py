"""Ecology's facility names on the Washington sewage spill list -> NPDES permits
(data/reference/wa-ecology-facility-permits.json), read by pipeline/ingest/wa_ecology_spills.py.

Usage: pipeline/.venv/bin/python -I scripts/wa_ecology_facility_permits.py [LAYER_JSON]

The spill list's "Permittee" field (permitee) is a coded-value domain of Ecology's facility names (524 on 2026-11-04;
the stored code is the name cut to 30 characters). The list carries no permit number, so each name is matched to a
permit here, once, and the ingester joins the operator through it:
  1. HAND below: names read against Ecology's PARIS permit search and EPA ICIS-NPDES by hand (2026-11-04);
  2. the name (or its 30-character code) equals, letters and digits only, the facility or permittee name of exactly
     one Washington permit in EPA's lists (data/outfalls-plants-us.json, data/outfalls-us.json);
  3. otherwise the name is listed with permit null: the ingester then names Ecology's facility and no operator.
A name that matches several permits of different owners is left null (never guessed).
LAYER_JSON: the layer's ?f=json answer (default data/raw/wa-ecology-sewage-spills/layer.json).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "reference" / "wa-ecology-facility-permits.json"
LAYER = ROOT / "data" / "raw" / "wa-ecology-sewage-spills" / "layer.json"
CHECKED = "2026-11-04"
# Ecology code -> (permit or None, why). Read by hand: EPA ICIS-NPDES names the same plant differently.
HAND = {
    "Lakehaven - Lakota WWTP": ("WA0022624", "EPA: LAKOTA WWTP, Lakehaven Water and Sewer District"),
    "Lakehaven - Redondo WWTP": ("WA0023451", "EPA: REDONDO WWTP, Lakehaven Water and Sewer District"),
    "LOTT - Budd Inlet WRF": ("WA0037061", "EPA: LOTT BUDD INLET WATER RECLAMATION FACILITY"),
    "Vancouver - Westside STP": ("WA0024350", "EPA: VANCOUVER WEST STP, City of Vancouver"),
    "Tacoma - Central STP": ("WA0037087", "EPA: TACOMA CENTRAL NO 1, City of Tacoma"),
    "Post Point Resource Recovery Pl": ("WA0023744", "EPA: BELLINGHAM STP (Post Point), City of Bellingham"),
    "Spokane County Regional WRF": ("WA0093317", "EPA: SPOKANE COUNTY REGIONAL WATER RECLAMATION FACILITY"),
    "Spokane Riverside Park WRF": ("WA0024473", "EPA: SPOKANE RIVERSIDE PARK WATER RECLAMATION FACILITY"),
    "SWSSD - Miller Creek WWTP": ("WA0022764", "EPA: MILLER CREEK WWTP, Southwest Suburban Sewer District"),
    "Big Lake WWTP": ("WA0030597", "EPA: SKAGIT COUNTY SEWER DIST 2 BIG LAKE WWTP"),
    "Concrete WWTP": ("WA0020851", "EPA: CONCRETE STP, Town of Concrete"),
    "Midway WWTP": ("WA0020958", "EPA: MIDWAY SEWER DISTRICT WWTP"),
    "Pierce County - Chambers Creek": ("WA0039624", "EPA: CHAMBERS CREEK STP, Pierce County Public Works"),
    "Alderbrook Resort & Spa STP": ("WA0037753", "EPA: ALDERBROOK RESORT & SPA"),
    "King County - Vashon STP": ("WA0022527", "EPA: KING COUNTY VASHON WWTP"),
    "LOTT - Martin Way WRF": (None, "LOTT's Martin Way reclaimed-water plant: no NPDES permit in EPA's lists"),
    "DCWA  - Salmon Creek STP": (None, "Discovery Clean Water Alliance's Salmon Creek plant: not in EPA's lists "
                                        "(EPA's SALMON CREEK WWTP, WA0022772, is Southwest Suburban's, in Burien)"),
}


def norm(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def epa_names() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for f in ("outfalls-plants-us.json", "outfalls-us.json"):
        doc = json.loads((ROOT / "data" / f).read_text())
        for r in doc["outfalls"] if isinstance(doc, dict) else doc:
            p = str(r.get("npdes_permit") or "")
            if not p.startswith("WA"):
                continue
            for n in (r.get("permittee"), r.get("permit_name")):
                if n:
                    out.setdefault(norm(n), set()).add(p)
    return out


def build(domain: list[dict], names: dict[str, set[str]]) -> dict:
    rows, counts = {}, {"hand": 0, "name": 0, "none": 0}
    for c in domain:
        code, name = c["code"], c.get("name") or c["code"]
        if code in HAND:
            permit, why = HAND[code]
            basis = "hand"
        else:
            hits = names.get(norm(name)) or names.get(norm(code)) or set()
            permit = next(iter(hits)) if len(hits) == 1 else None
            basis = "name" if permit else "none"
            why = ("Ecology's name equals EPA's facility or permittee name" if permit else
                   ("several permits share the name" if len(hits) > 1 else "no permit in EPA's lists has this name"))
        counts[basis if permit else "none"] += 1
        rows[code] = {"name": name, "npdes_permit": permit, "basis": basis, "why": why}
    return {"about": ("Ecology's facility names on the Washington sewage spill list (the layer's permittee domain) "
                      "matched to NPDES permits; scripts/wa_ecology_facility_permits.py"),
            "checked": CHECKED, "counts": counts, "facilities": dict(sorted(rows.items()))}


def main(argv: list[str]) -> int:
    layer = json.loads(Path(argv[0] if argv else LAYER).read_text())
    domain = next(f["domain"]["codedValues"] for f in layer["fields"] if f["name"] == "permitee")
    doc = build(domain, epa_names())
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps(doc["counts"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
