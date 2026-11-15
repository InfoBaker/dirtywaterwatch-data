"""Write research/mo/receiving-waters-missing.json: the water names Missouri's records give that
data/receiving-waters-national.json does not hold for MO, one row per name and county.

Usage (after the three Missouri feeds have written their events files):
    pipeline/.venv/bin/python -I scripts/mo_report_water_names.py

Inputs: data/build/events/mo-kc-water-overflow-notices.json, mo-msd-stl-project-clear.json (the water each operator's
post names) and mo-dnr-concern-reports.json (the water a concern names). A name is compared without case or punctuation
with the national list's name, key, names seen and GNIS names for MO; the receiving waters of DNR's outfall layer
(data/outfalls-mo.json, MSD Lemay's River des Peres, Black Creek and Deer Creek tributaries among them) are added as rows
too when the list lacks them. Records naming no water are left out and counted. No record has a point: each row keeps
its county (the county a concern gives, else the counties of the operator's area: KC Water's four, MSD's two), the
report count and the towns, so the names pass builds the name where the reports are (Missouri has many Brush, Mill,
Line and Indian Creeks).
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVENTS = ROOT / "data" / "build" / "events"
NATIONAL = ROOT / "data" / "receiving-waters-national.json"
OUT = ROOT / "research" / "mo" / "receiving-waters-missing.json"
FEEDS = ("mo-kc-water-overflow-notices", "mo-msd-stl-project-clear", "mo-dnr-concern-reports")
STATE_OUTFALLS = ROOT / "data" / "outfalls-mo.json"
NOT_A_WATER = re.compile(r"\bpresumed use\b|\b100k extent\b|\bstorm\s*(?:water|drain|sewer)\b|\boutfall\b|\bditch\b|\bgutter\b|\bstreet\b|\bground\b", re.I)


def key(s: str) -> str:
    """'Tributary to River des Peres' and 'River des Peres' are the same name here (the national list keys them so)."""
    s = re.sub(r"^\s*(?:trib(?:utary|\.)?\s+to|tributary of)\s+", "", (s or "").lower())
    s = re.sub(r"\s+tributary$", "", s)
    return re.sub(r"\br\.?$", "river", re.sub(r"[^a-z0-9 ]", "", s)).replace(" ", "")


def main() -> int:
    import sys
    sys.path.insert(0, str(ROOT / "pipeline"))
    from build import status as S
    nat = json.loads(NATIONAL.read_text())
    held = {key(n) for w in ((nat.get("states") or {}).get("MO") or {}).get("waters") or []
            for n in [w.get("name"), w.get("key"), *(w.get("names_seen") or []), *(w.get("gnis_names") or [])] if n}
    rows: dict[tuple, dict] = {}
    left_out = defaultdict(int)
    listed = 0
    for sid in FEEDS:
        d = json.loads((EVENTS / f"{sid}.json").read_text())
        for r in d.get("records", []):
            raw = r.get("raw") or {}
            if r.get("duplicate_of"):
                left_out["the same report as another source's"] += 1
                continue
            text = (r.get("waterbody_text") or "").strip()
            named = raw.get("waters_named") if isinstance(raw.get("waters_named"), list) else None
            # every water a report names counts (re-review P1-3: "Rock Creek; Missouri River" is two names)
            for name in ([n.strip() for n in named if n and n.strip()] if text and named else [text]):
                if not name:
                    left_out["no water named"] += 1
                    continue
                if NOT_A_WATER.search(name):
                    left_out["a drain, outfall or street, not a water"] += 1
                    continue
                if key(name) in held:
                    listed += 1
                    continue
                lat, lon = r.get("lat"), r.get("lon")
                here = S.point_county("MO", lat, lon)
                county = (here[1] if here else None) or raw.get("county") or " or ".join(raw.get("counties") or []) or None
                row = rows.setdefault((name, county), {"name": name, "reports": 0, "county": county, "points": [],
                                                       "towns": [], "sources": {}, "open": 0})
                row["reports"] += 1
                row["sources"][sid] = row["sources"].get(sid, 0) + 1
                if r.get("status") in ("advisory_active", "ongoing"):
                    row["open"] += 1
                if lat is not None and lon is not None:
                    pt = [round(float(lat), 3), round(float(lon), 3)]
                    if pt not in row["points"] and len(row["points"]) < 5:
                        row["points"].append(pt)
                town = r.get("discharger_name")
                if town and town not in row["towns"]:
                    row["towns"].append(town)
    for o in json.loads(STATE_OUTFALLS.read_text())["outfalls"]:     # DNR's outfall layer: its receiving streams
        name = (o.get("receiving_water_echo") or "").strip()
        if o.get("outfall_kind") != "cso" or not name or key(name) in held or NOT_A_WATER.search(name):
            continue
        row = rows.setdefault((name, o.get("county") and f"{o['county']} County"),
                              {"name": name, "reports": 0, "county": o.get("county") and f"{o['county']} County",
                               "points": [], "towns": [], "sources": {}, "open": 0})
        row["sources"]["mo-dnr-npdes-outfalls"] = row["sources"].get("mo-dnr-npdes-outfalls", 0) + 1
        row["outfalls"] = row.get("outfalls", 0) + 1
        pt = [round(o["lat"], 3), round(o["lon"], 3)]
        if pt not in row["points"] and len(row["points"]) < 5:
            row["points"].append(pt)
    for row in rows.values():
        row["places_from"] = sorted(row["sources"])
        row["towns"] = row["towns"][:4]
    out = sorted(rows.values(), key=lambda r: (-r["reports"], r["name"], r["county"] or ""))
    doc = {"about": ("Water names in Missouri's records that data/receiving-waters-national.json does not hold for MO: "
                     "the water KC Water's and MSD's overflow posts and DNR's concern reports name, and the receiving "
                     "stream of each combined sewer outfall on DNR's outfall layer; one row per name and county (the "
                     "county a concern gives, else the counties of the operator's area), with the number of reports, "
                     "the outfall count and points of the outfalls, and the operator, so the names pass builds each "
                     "name where the reports are. Records naming no water are left out (by_reason). Written by "
                     "scripts/mo_report_water_names.py."),
           "state": "MO", "waters": len(out), "reports": sum(r["reports"] for r in out),
           "reports_on_listed_waters": listed, "by_reason": dict(left_out), "rows": out}
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps({k: v for k, v in doc.items() if k not in ("rows", "about")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
