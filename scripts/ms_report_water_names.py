"""research/ms/receiving-waters-missing.json: the receiving-water names Mississippi reports give that
data/receiving-waters-national.json does not hold for MS, for `python -m ingest.waters_from_nhd --names ... --state MS`.

Usage (after pipeline/ingest/echo_sewer_overflow_events.py has written its events file):
    pipeline/.venv/bin/python -I scripts/ms_report_water_names.py

Reads EPA's overflow tables (MS permits; the module has already read the City of Jackson's shorthand names as the NHD
creeks they name), the only Mississippi feed with receiving waters. A name is the record's waterbody_text split at
semicolons (EPA's module joins several receiving waters so), counted once per report, compared with the national list's
names and keys case, spaces and punctuation aside. Reports that say no water was reached are not records and do not
count. Each row: name, reports, permits, sources, and up to five of the reports' own points ([lat, lon]).
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVENTS = ROOT / "data" / "build" / "events" / "echo-sewer-overflow.json"
OUT = ROOT / "research" / "ms" / "receiving-waters-missing.json"


def compact(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def main() -> int:
    nat = json.loads((ROOT / "data" / "receiving-waters-national.json").read_text())["states"]["MS"]["waters"]
    have = {compact(n) for w in nat for n in [w.get("name"), w.get("key"), *(w.get("names_seen") or [])] if n}
    reports, permits, points, typed = Counter(), defaultdict(set), defaultdict(list), defaultdict(Counter)
    doc = json.loads(EVENTS.read_text())
    for r in doc.get("records", []):
        if not str(r.get("npdes_permit") or "").startswith("MS"):
            continue
        for n in dict.fromkeys(x.strip() for x in (r.get("waterbody_text") or "").split(";") if x.strip()):
            if compact(n) in have:
                continue
            k = compact(n)
            typed[k][n] += 1
            reports[k] += 1
            permits[k].add(r["npdes_permit"])
            pt = [r["lat"], r["lon"]] if r.get("lat") is not None else None
            if pt and pt not in points[k] and len(points[k]) < 5:
                points[k].append(pt)
    rows = [{"name": typed[k].most_common(1)[0][0], "reports": c, "permits": sorted(permits[k]),
             "sources": ["echo-sewer-overflow"], **({"spellings": sorted(typed[k])} if len(typed[k]) > 1 else {}),
             **({"points": points[k]} if points[k] else {})}
            for k, c in sorted(reports.items(), key=lambda x: (-x[1], typed[x[0]].most_common(1)[0][0]))]
    out = {"about": ("Receiving-water names in MS's reports (EPA's overflow tables for Mississippi permits, the "
                     f"extract of {doc.get('meta', {}).get('extract_date')}) that data/receiving-waters-national.json "
                     "does not hold for MS, by name as typed (spellings that differ only in case, spaces or punctuation "
                     "counted together), with the number of reports giving each and up to five of their points. The "
                     "City of Jackson's shorthand names are given as the NHD creeks the ingester reads them as. Reports "
                     "that say the discharge reached no water are left out."),
           "state": "MS", "waters": len(rows), "reports": sum(reports.values()), "rows": rows}
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print(f"{len(rows)} names, {sum(reports.values())} reports -> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
