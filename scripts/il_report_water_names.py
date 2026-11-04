"""research/il/receiving-waters-missing.json: the receiving-water names Illinois reports give that
data/receiving-waters-national.json does not hold for IL, for `python -m ingest.waters_from_nhd --names ... --state IL`.

Usage (after the Illinois feeds have written data/build/events): pipeline/.venv/bin/python -I scripts/il_report_water_names.py

Reads EPA's overflow tables (IL permits), MWRD's map and reversals and IDPH's BeachGuard records, and the waters of
MWRD's outfall rows (data/outfalls-il.json) still without a record (0 reports, up to five of their points); a name is the
record's waterbody_text split at semicolons (EPA's module joins several receiving waters so), counted once per report,
compared with the national list's names and keys case and punctuation aside. Reports that say no water was reached are
not records and do not count. Each row: name, reports, permits, sources; places are added by --add-places.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVENTS = ROOT / "data" / "build" / "events"
FEEDS = ["echo-sewer-overflow", "il-mwrd-possible-cso-events-layer", "il-mwrd-lake-michigan-reversals", "il-idph-beachguard"]
OUT = ROOT / "research" / "il" / "receiving-waters-missing.json"


def compact(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def main() -> int:
    nat = json.loads((ROOT / "data" / "receiving-waters-national.json").read_text())["states"]["IL"]["waters"]
    have = {compact(n) for w in nat for n in [w.get("name"), w.get("key"), *(w.get("names_seen") or [])] if n}
    reports, permits, sources = Counter(), defaultdict(set), defaultdict(set)
    for f in FEEDS:
        p = EVENTS / f"{f}.json"
        if not p.exists():
            continue
        for r in json.loads(p.read_text()).get("records", []):
            if f == "echo-sewer-overflow" and not str(r.get("npdes_permit") or "").startswith("IL"):
                continue
            for n in dict.fromkeys(x.strip() for x in (r.get("waterbody_text") or "").split(";") if x.strip()):
                if compact(n) in have:
                    continue
                reports[n] += 1
                if r.get("npdes_permit"):
                    permits[n].add(r["npdes_permit"])
                sources[n].add(r["source_id"])
    points = defaultdict(list)
    for o in json.loads((ROOT / "data" / "outfalls-il.json").read_text())["outfalls"]:
        n = o.get("receiving_water_echo")
        if not n or compact(n) in have or o.get("water_slug"):
            continue
        reports[n] += 0
        permits[n].add(o["npdes_permit"])
        sources[n].add("il-mwrd-cso-points")
        if o.get("lat") is not None and len(points[n]) < 5:
            points[n].append([o["lat"], o["lon"]])
    rows = [{"name": n, "reports": c, "permits": sorted(permits[n]), "sources": sorted(sources[n])}
            | ({"points": points[n]} if points.get(n) else {})
            for n, c in sorted(reports.items(), key=lambda x: (-x[1], x[0]))]
    doc = {"about": ("Receiving-water names in IL's reports (EPA's overflow tables for Illinois permits, MWRD's map and "
                     "Lake Michigan reversals table, IDPH's BeachGuard list, as read on 2026-11-04) that "
                     "data/receiving-waters-national.json does not hold for IL, by name as typed, with the number of "
                     "reports giving each. Reports that say the discharge reached no water are left out."),
           "state": "IL", "waters": len(rows), "reports": sum(reports.values()), "rows": rows}
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    print(f"{len(rows)} names, {sum(reports.values())} reports -> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
