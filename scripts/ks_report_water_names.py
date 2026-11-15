"""Write research/ks/receiving-waters-missing.json: the water names Kansas's records give that
data/receiving-waters-national.json does not hold for KS, one row per name and county.

Usage (after the three Kansas feeds have written their events files):
    pipeline/.venv/bin/python -I scripts/ks_report_water_names.py

Inputs: data/build/events/ks-leavenworth-sso-transparency.json (the creek Leavenworth's page names),
ks-kdhe-stream-advisories.json (the waters KDHE's stream advisories name) and ks-kdhe-hab-status.json (the lakes under a
bloom advisory, with their points). A name is compared without case or punctuation with the national list's name, key,
names seen and GNIS names for KS. Records naming no water are left out and counted. Each row keeps its county (the
record's point against data/reference/ks-counties.json, else the county the record gives), the report count, the open
count, up to five points and the operator, so the names pass builds the name where the reports are.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVENTS = ROOT / "data" / "build" / "events"
NATIONAL = ROOT / "data" / "receiving-waters-national.json"
OUT = ROOT / "research" / "ks" / "receiving-waters-missing.json"
FEEDS = ("ks-leavenworth-sso-transparency", "ks-kdhe-stream-advisories", "ks-kdhe-hab-status")
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
    held = {key(n) for w in ((nat.get("states") or {}).get("KS") or {}).get("waters") or []
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
            name = (r.get("waterbody_text") or "").strip()
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
            here = S.point_county("KS", lat, lon)
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
    for row in rows.values():
        row["places_from"] = sorted(row["sources"])
        row["towns"] = row["towns"][:4]
    out = sorted(rows.values(), key=lambda r: (-r["reports"], r["name"], r["county"] or ""))
    doc = {"about": ("Water names in Kansas's records that data/receiving-waters-national.json does not hold for KS: "
                     "the creek Leavenworth's overflow pages name, the waters KDHE's stream advisories name and the lakes "
                     "under KDHE's bloom advisories; one row per name and county (the county of the record's point, else "
                     "the county it gives), with the number of reports, how many are open now, up to five of their "
                     "points ([lat, lon], 0.001 degree) and the operator, so the names pass builds each name where the "
                     "reports are. Records naming no water are left out (by_reason). Written by "
                     "scripts/ks_report_water_names.py."),
           "state": "KS", "waters": len(out), "reports": sum(r["reports"] for r in out),
           "reports_on_listed_waters": listed, "by_reason": dict(left_out), "rows": out}
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps({k: v for k, v in doc.items() if k not in ("rows", "about")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
