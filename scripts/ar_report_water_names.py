"""Write research/ar/receiving-waters-missing.json: the water names Arkansas's records give that
data/receiving-waters-national.json does not hold for AR, one row per name and county.

Usage (after the Arkansas feeds have written their events files):
    pipeline/.venv/bin/python -I scripts/ar_report_water_names.py

Inputs: data/build/events/ar-deq-overflow-incidents.json (the waters a report's location text names, when DEQ's impact
does not rule water out: ingest/ar_transforms.py water_names; several names are split at "; ") and
ar-deq-hab-advisories.json (the water each bloom advisory names). A name is compared without case or punctuation with
the national list's name, key, names seen and GNIS names for AR. Records naming no water are left out and counted by
reason. Each row keeps its county (the record's point against data/reference/ar-counties.json, else the county the record
gives: for an overflow report the county of its permit's plant, for an advisory DEQ's county), the report count, the
open count, up to five points and the towns, so the names pass builds each name where the reports are.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVENTS = ROOT / "data" / "build" / "events"
NATIONAL = ROOT / "data" / "receiving-waters-national.json"
OUT = ROOT / "research" / "ar" / "receiving-waters-missing.json"
FEEDS = ("ar-deq-overflow-incidents", "ar-deq-hab-advisories")
NOT_A_WATER = re.compile(r"\bstorm\s*(?:water|drain|sewer)\b|\boutfall\b|\bditch\b|\bgutter\b|\bstreet\b|\bground\b", re.I)


DESCRIPTION = re.compile(r"^(stream|creek|pond|lake)\s+(by|near|at|behind)\b", re.I)


def key(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def main() -> int:
    import sys
    sys.path.insert(0, str(ROOT / "pipeline"))
    from build import status as S
    nat = json.loads(NATIONAL.read_text())
    held = {key(n) for w in ((nat.get("states") or {}).get("AR") or {}).get("waters") or []
            for n in [w.get("name"), w.get("key"), *(w.get("names_seen") or []), *(w.get("gnis_names") or [])] if n}
    rows: dict[tuple, dict] = {}
    left_out = defaultdict(int)
    listed = 0
    for sid in FEEDS:
        d = json.loads((EVENTS / f"{sid}.json").read_text())
        for r in d.get("records", []):
            raw = r.get("raw") or {}
            if r.get("duplicate_of"):
                left_out["a copy of another record (DEQ lists some reports twice)"] += 1
                continue
            names = [n.strip() for n in (r.get("waterbody_text") or "").split(";") if n.strip()]
            if not names:
                left_out["no water named"] += 1
                continue
            lat, lon = r.get("lat"), r.get("lon")
            here = S.point_county("AR", lat, lon)
            county = (f"{here[1]} County" if here and not here[1].endswith("County") else here[1] if here else None) \
                or raw.get("county")
            for name in names:
                if DESCRIPTION.match(name):
                    left_out["a description of a place, not a water's name"] += 1
                elif NOT_A_WATER.search(name):
                    left_out["a drain, outfall or street, not a water"] += 1
                elif key(name) in held:
                    listed += 1
                else:
                    add(rows, sid, r, raw, name, county, lat, lon)
    finish_rows(rows)
    return write(rows, left_out, listed)


def add(rows, sid, r, raw, name, county, lat, lon):
    row = rows.setdefault((key(name), county), {"name": name, "reports": 0, "county": county, "points": [],
                                           "towns": [], "sources": {}, "open": 0})
    row["reports"] += 1
    row["sources"][sid] = row["sources"].get(sid, 0) + 1
    if r.get("status") in ("advisory_active", "ongoing"):
        row["open"] += 1
    if lat is not None and lon is not None:
        pt = [round(float(lat), 3), round(float(lon), 3)]
        if pt not in row["points"] and len(row["points"]) < 5:
            row["points"].append(pt)
    town = raw.get("_nearest_area")
    if town and town not in row["towns"]:
        row["towns"].append(town)


def finish_rows(rows):
    for row in rows.values():
        row["places_from"] = sorted(row["sources"])
        row["towns"] = row["towns"][:4]


def write(rows, left_out, listed):
    out = sorted(rows.values(), key=lambda r: (-r["reports"], r["name"], r["county"] or ""))
    doc = {"about": ("Water names in Arkansas's records that data/receiving-waters-national.json does not hold for AR: "
                     "the waters the location text of a report in DEQ's Reported Noncompliance Incident Data names, when "
                     "the filer's impact does not say it stayed on land (read 2026-11-14, reports since 2025-01-01), and "
                     "the water each of DEQ's harmful algal bloom advisories names (52 advisories since 2014); one row "
                     "per name and county (an overflow report's county is its permit plant's, an advisory's the county "
                     "DEQ gives), with the number of reports, how many are open now, up to five points ([lat, lon], "
                     "0.001 degree: the advisories' GNIS points; overflow reports have none), the advisories' nearest "
                     "towns and the sources. Records naming no water are left out (by_reason). Written by "
                     "scripts/ar_report_water_names.py."),
           "state": "AR", "waters": len(out), "reports": sum(r["reports"] for r in out),
           "reports_on_listed_waters": listed, "by_reason": dict(left_out), "rows": out}
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps({k: v for k, v in doc.items() if k not in ("rows", "about")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
