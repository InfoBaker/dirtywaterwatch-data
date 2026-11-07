"""research/ak/receiving-waters-missing.json: the receiving-water names Alaska reports give that
data/receiving-waters-national.json does not hold for AK, for `python -m ingest.waters_from_nhd --names ... --state AK`.

Usage (after ingest.echo_sewer_overflow_events has written data/build/events): pipeline/.venv/bin/python -I
scripts/ak_report_water_names.py

Reads EPA's overflow tables (AK permits; the only Alaska feed) and the receiving waters of Alaska operator rows whose
permit is in neither of EPA's outfall tables (0 reports). A name is the record's waterbody_text split at semicolons
(the module joins several receiving waters so, and reads "X which flowed to Y" as X; Y), counted once per report, and
compared with the national list's names and keys case and punctuation aside. Reports that say no water was reached are
not records and do not count. Each row: name, reports, permits, sources, and up to five report points.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVENTS = ROOT / "data" / "build" / "events" / "echo-sewer-overflow.json"
OUT = ROOT / "research" / "ak" / "receiving-waters-missing.json"
NOT_IN_OUTFALL_TABLES = {"AK0053384"}   # the private candidate's permit (scripts/add_ak_operators.py EXTRA)


def compact(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def main() -> int:
    nat = json.loads((ROOT / "data" / "receiving-waters-national.json").read_text())["states"]["AK"]["waters"]
    have = {compact(n) for w in nat for n in [w.get("name"), w.get("key"), *(w.get("names_seen") or [])] if n}
    reports, permits, sources, points, read = Counter(), defaultdict(set), defaultdict(set), defaultdict(list), 0
    for r in json.loads(EVENTS.read_text()).get("records", []):
        if not str(r.get("npdes_permit") or "").startswith("AK"):
            continue
        read += 1
        for n in dict.fromkeys(x.strip() for x in (r.get("waterbody_text") or "").split(";") if x.strip()):
            if compact(n) in have:
                continue
            reports[n] += 1
            permits[n].add(r["npdes_permit"])
            sources[n].add(r["source_id"])
            if r.get("lat") is not None and len(points[n]) < 5:
                points[n].append([r["lat"], r["lon"]])
    for op in json.loads((ROOT / "data" / "dischargers.json").read_text()):
        if op.get("state") != "AK" or not set(op.get("npdes_permits") or []) & NOT_IN_OUTFALL_TABLES:
            continue
        for n in op.get("receiving_waters") or []:
            if compact(n) not in have:
                reports[n] += 0
                permits[n] |= set(op["npdes_permits"]) & NOT_IN_OUTFALL_TABLES
                sources[n].add("operator row " + op["id"])
    rows = [{"name": n, "reports": c, "permits": sorted(permits[n]), "sources": sorted(sources[n])}
            | ({"points": points[n]} if points.get(n) else {})
            for n, c in sorted(reports.items(), key=lambda x: (-x[1], x[0]))]
    doc = {"about": ("Receiving-water names in Alaska's reports (EPA's overflow tables for Alaska permits, the "
                     "2026-11-04 extract: the 6 reports kept, 5 of which name a water) that data/receiving-waters-national.json "
                     "does not hold for AK, by name as the report gives it once 'which flowed to' is split, with the "
                     "number of reports giving each and the reports' points; and the receiving water of the one "
                     "Alaska sewage permit in neither of EPA's outfall tables (0 reports). Reports that say the sewage "
                     "reached no water are left out. Cook Inlet and Tongass Narrows are on the national list."),
           "state": "AK", "records_read": read, "waters": len(rows), "reports": sum(reports.values()), "rows": rows}
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    print(f"{len(rows)} names, {sum(reports.values())} reports -> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
