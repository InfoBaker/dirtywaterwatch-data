"""Wisconsin's receiving-water names that data/receiving-waters-national.json lacks for WI -> research/wi/receiving-waters-missing.json

Usage (after pipeline/ingest/wi_mmsd_storm_updates.py has written its events file):
    pipeline/.venv/bin/python -I scripts/wi_report_water_names.py [--dry-run]

Reads the waters the Milwaukee Metropolitan Sewerage District's Storm Update records name (waterbody_text, "; "
between names); a name the national list holds for WI (by its key, lower case) is resolved, any other is a row with the
number of reports naming it, the county (Milwaukee: every MMSD record is in Milwaukee County), the towns and the
sources, and no points (the posts give none and a street is never geocoded). Records naming no water are counted in
by_reason. Rows sorted by reports, then name.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NATIONAL = ROOT / "data" / "receiving-waters-national.json"
OUT = ROOT / "research" / "wi" / "receiving-waters-missing.json"
SOURCES = ("wi-mmsd-storm-updates",)


def k(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def main(argv) -> int:
    nat = json.loads(NATIONAL.read_text())["states"].get("WI") or {}
    have = {k(n) for w in nat.get("waters") or []
            for n in [w.get("name"), w.get("key"), *(w.get("names_seen") or []), *(w.get("gnis_names") or [])] if n}
    rows: dict[tuple[str, str], dict] = {}
    reasons, resolved = Counter(), Counter()
    for sid in SOURCES:
        f = ROOT / "data" / "build" / "events" / f"{sid}.json"
        for r in (json.loads(f.read_text()).get("records") if f.exists() else []):
            names = [n.strip() for n in (r.get("waterbody_text") or "").split(";") if n.strip()]
            if not names:
                reasons["no water named"] += 1
                continue
            county = ((r.get("raw") or {}).get("county") or "") + " County"
            for n in names:
                if k(n) in have:
                    resolved[n] += 1
                    continue
                row = rows.setdefault((n, county), {"name": n, "reports": 0, "county": county, "points": [],
                                                    "towns": [], "sources": defaultdict(int), "open": 0,
                                                    "places_from": []})
                row["reports"] += 1
                row["sources"][sid] += 1
                if "Milwaukee" not in row["towns"]:
                    row["towns"].append("Milwaukee")
    out_rows = sorted(rows.values(), key=lambda x: (-x["reports"], x["name"]))
    for x in out_rows:
        x["sources"] = dict(x["sources"])
    doc = {"about": ("Water names in Wisconsin's records that data/receiving-waters-national.json does not hold for WI: "
                     "the waters the Milwaukee Metropolitan Sewerage District's Storm Update posts name, one row per "
                     "name and county, with the number of reports, the town and sources; no points (the posts give "
                     "none). Records naming no water are counted in by_reason. EPA's outfall registry gives every CSO "
                     "and plant outfall its receiving water separately. Written by scripts/wi_report_water_names.py."),
           "state": "WI", "waters": len(out_rows), "reports": sum(x["reports"] for x in out_rows),
           "by_reason": dict(reasons), "resolved_names": len(resolved), "resolved_reports": sum(resolved.values()),
           "rows": out_rows}
    print(json.dumps({k: v for k, v in doc.items() if k not in ("rows", "about")}), [x["name"] for x in out_rows])
    if "--dry-run" not in argv:
        OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
