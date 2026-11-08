"""Write research/ut/receiving-waters-missing.json: the water names Utah's records give that
data/receiving-waters-national.json does not hold for UT, one row per name and county.

Usage (after the three Utah feeds have written their events files):
    pipeline/.venv/bin/python -I scripts/ut_report_water_names.py

Inputs: data/build/events/ut-deq-environmental-incidents.json (the water a sewage report's title names),
ut-dwq-recreational-advisories.json (the water each advisory site lies on) and echo-sewer-overflow.json (EPA's receiving
water on Utah's reports). A name is compared without case or punctuation with the national list's name, key, names seen
and GNIS names for UT. Records naming no water, and EPA's "Storm water outfall" (a drain, not a water), are left out and
counted by reason. Each row keeps its county (the record's point against data/reference/ut-counties.json, else the
county the record gives), the report count, the open count, up to five points and the towns, so the names pass builds
the name at the reports' places (go-live audit 2026-11-08 P2-3, P2-5).
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVENTS = ROOT / "data" / "build" / "events"
NATIONAL = ROOT / "data" / "receiving-waters-national.json"
OUT = ROOT / "research" / "ut" / "receiving-waters-missing.json"
FEEDS = ("ut-deq-environmental-incidents", "ut-dwq-recreational-advisories", "echo-sewer-overflow")
NOT_A_WATER = re.compile(r"\bstorm\s*(?:water|drain|sewer)\b|\boutfall\b|\bditch\b|\bgutter\b|\bstreet\b|\bground\b", re.I)


def key(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def main() -> int:
    import sys
    sys.path.insert(0, str(ROOT / "pipeline"))
    from build import status as S
    nat = json.loads(NATIONAL.read_text())
    held = {key(n) for w in ((nat.get("states") or {}).get("UT") or {}).get("waters") or []
            for n in [w.get("name"), w.get("key"), *(w.get("names_seen") or []), *(w.get("gnis_names") or [])] if n}
    rows: dict[tuple, dict] = {}
    left_out = defaultdict(int)
    listed = 0
    for sid in FEEDS:
        d = json.loads((EVENTS / f"{sid}.json").read_text())
        for r in d.get("records", []):
            raw = r.get("raw") or {}
            if sid == "echo-sewer-overflow" and not str(r.get("npdes_permit") or "").startswith("UT"):
                continue
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
            here = S.point_county("UT", lat, lon)
            county = (here[1] if here else None) or raw.get("county")
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
            town = raw.get("nearest_city")
            if town and town not in row["towns"]:
                row["towns"].append(town)
    for row in rows.values():
        row["places_from"] = sorted(row["sources"])
        row["towns"] = row["towns"][:4]
    out = sorted(rows.values(), key=lambda r: (-r["reports"], r["name"], r["county"] or ""))
    doc = {"about": ("Water names in Utah's records that data/receiving-waters-national.json does not hold for UT: the "
                     "water a sewage report's title names (DEQ's Environmental Incidents layer), the water each advisory "
                     "site of DWQ's Recreational Waters Map lies on, and EPA's receiving water on Utah's eRule reports; "
                     "one row per name and county (the county of the record's point, else the county it gives), with "
                     "the number of reports, how many are open now, up to five of their points ([lat, lon], 0.001 "
                     "degree), their towns and sources, so the names pass builds each name where the reports are "
                     "(Utah has a Gordon Creek in Morgan County and another in Carbon County). Records naming no water "
                     "and texts that name a drain or outfall are left out (by_reason). Written by "
                     "scripts/ut_report_water_names.py."),
           "state": "UT", "waters": len(out), "reports": sum(r["reports"] for r in out),
           "reports_on_listed_waters": listed, "by_reason": dict(left_out), "rows": out}
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps({k: v for k, v in doc.items() if k not in ("rows", "about")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
