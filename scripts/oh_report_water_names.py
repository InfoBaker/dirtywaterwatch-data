"""research/oh/receiving-waters-missing.json: the receiving-water names Ohio's reports give that
data/receiving-waters-national.json does not hold for OH, for `python -m ingest.waters_from_nhd --names ... --state OH`.

Usage (after the Ohio ingesters have written their events files):
    pipeline/.venv/bin/python -I scripts/oh_report_water_names.py [--events-dir DIR]

Reads the waterbody_text of every Ohio feed's records (FEEDS: NEORSD's and Akron's outfall waters, Columbus's and Bowling
Green's overflow sites, Ohio EPA's spills that name a waterway, BeachGuard's beach waters), counted once per record.
Names are compared with the national list's names, keys and names seen, case, spaces and punctuation aside. Each row:
name, reports, permits, sources, the counties the reports give (Ohio EPA's spills) and up to five of the reports' own
points ([lat, lon]).
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVENTS = ROOT / "data" / "build" / "events"
OUT = ROOT / "research" / "oh" / "receiving-waters-missing.json"
FEEDS = ["oh-neorsd-cso-notification-map", "oh-akron-cso-notifications", "oh-columbus-sewer-overflow",
         "oh-bowling-green-cso-events", "oh-epa-spills-opendata", "oh-odh-beachguard"]


def compact(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def main(argv) -> int:
    events = Path(argv[argv.index("--events-dir") + 1]) if "--events-dir" in argv else EVENTS
    nat = json.loads((ROOT / "data" / "receiving-waters-national.json").read_text())["states"]["OH"]["waters"]
    have = {compact(n) for w in nat for n in [w.get("name"), w.get("key"), *(w.get("names_seen") or [])] if n}
    reports, permits, points, typed, sources, counties = (Counter(), defaultdict(set), defaultdict(list),
                                                          defaultdict(Counter), defaultdict(set), defaultdict(set))
    read, total = {}, 0
    for sid in FEEDS:
        p = events / f"{sid}.json"
        if not p.exists():
            read[sid] = "not built"
            continue
        doc = json.loads(p.read_text())
        read[sid] = f"{len(doc.get('records') or [])} records, fetched {(doc.get('fetched_at') or '')[:10]}"
        for r in doc.get("records") or []:
            n = (r.get("waterbody_text") or "").strip()
            if not n:
                continue
            total += 1
            k = compact(n)
            if k in have:
                continue
            typed[k][n] += 1
            reports[k] += 1
            sources[k].add(sid)
            if r.get("npdes_permit"):
                permits[k].add(r["npdes_permit"])
            if (r.get("raw") or {}).get("county"):
                counties[k].add(r["raw"]["county"])
            pt = [round(r["lat"], 6), round(r["lon"], 6)] if r.get("lat") is not None else None
            if pt and pt not in points[k] and len(points[k]) < 5:
                points[k].append(pt)
    rows = []
    for k in sorted(reports, key=lambda x: (-reports[x], typed[x].most_common(1)[0][0])):
        row = {"name": typed[k].most_common(1)[0][0], "reports": reports[k], "permits": sorted(permits[k]),
               "sources": sorted(sources[k])}
        if counties[k]:
            row["counties"] = sorted(counties[k])
        if len(typed[k]) > 1:
            row["spellings"] = sorted(typed[k])
        if points[k]:
            row["points"] = points[k]
        rows.append(row)
    out = {"about": ("Receiving-water names in Ohio's reports (NEORSD's CSO alerts layers, Akron's overflow status "
                     "layer, Columbus's overflow events, Bowling Green's CSO events, the Ohio EPA spills that name a "
                     "waterway, and BeachGuard's beach waters) that data/receiving-waters-national.json does not hold "
                     "for OH, by name as the record gives it (spellings that differ only in case, spaces or punctuation "
                     "counted together), with the number of records giving each, the counties the spills give and up "
                     "to five of the records' points. Records that name no water are left out."),
           "state": "OH", "feeds_read": read, "records_naming_a_water": total, "waters": len(rows),
           "reports": sum(reports.values()), "rows": rows}
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print(f"{len(rows)} names, {sum(reports.values())} of {total} records -> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
