"""research/az/receiving-waters-missing.json: the receiving-water names Arizona reports give that
data/receiving-waters-national.json does not hold for AZ, for `python -m ingest.waters_from_nhd --names ... --state AZ`.

Usage (after pipeline/ingest/echo_sewer_overflow_events.py has written data/build/events):
    pipeline/.venv/bin/python -I scripts/az_report_water_names.py

Reads EPA's overflow tables (AZ permits): a name is the record's waterbody_text split at semicolons (the module joins
several receiving waters so; an ADEQ waterbody identifier is already ADEQ's name there), counted once per report,
compared with the national list's names and keys case and punctuation aside. Reports that say no water was reached
are not records and do not count, and neither do the reports kept for a wash or canal their text names without a
receiving water ('flowed to an unnamed wash'): they carry no name. Each row: name, reports, permits, sources, the ADEQ
waterbody identifiers filed for it (with ADEQ's segment description) and up to five of the reports' points (the
report's own) and, apart, the points the reports gave that the module took for the plant's (plant_points: not the
water's place). The Navajo Nation's reports the module placed in Arizona count too.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVENTS = ROOT / "data" / "build" / "events"
FEEDS = ["echo-sewer-overflow"]
OUT = ROOT / "research" / "az" / "receiving-waters-missing.json"


def compact(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def main() -> int:
    nat = json.loads((ROOT / "data" / "receiving-waters-national.json").read_text())["states"]["AZ"]["waters"]
    have = {compact(n) for w in nat for n in [w.get("name"), w.get("key"), *(w.get("names_seen") or [])] if n}
    reports, permits, sources = Counter(), defaultdict(set), defaultdict(set)
    wbids: dict[str, dict] = defaultdict(dict)
    points: dict[str, list] = defaultdict(list)
    plant_pts: dict[str, list] = defaultdict(list)
    spelling: dict[str, str] = {}            # one name per spelling that differs in case or punctuation only
    spellings: dict[str, list] = defaultdict(list)
    for f in FEEDS:
        p = EVENTS / f"{f}.json"
        if not p.exists():
            continue
        for r in json.loads(p.read_text()).get("records", []):
            if str(r.get("npdes_permit") or "")[:2] not in ("AZ", "NN"):   # the Navajo Nation's placed in AZ
                continue
            raw = r.get("raw") or {}
            for n0 in dict.fromkeys(x.strip() for x in (r.get("waterbody_text") or "").split(";") if x.strip()):
                if compact(n0) in have:
                    continue
                n = spelling.setdefault(compact(n0), n0.title() if n0.isupper() or n0.islower() else n0)
                if n != n0 and n0 not in spellings[n]:
                    spellings[n].append(n0)
                reports[n] += 1
                permits[n].add(r["npdes_permit"])
                sources[n].add(r["source_id"])
                for code, seg in (raw.get("receiving_water_wbids") or {}).items():
                    if seg.get("name") == n:
                        wbids[n][code] = {k: seg[k] for k in ("origin", "terminus", "flow_regime") if seg.get(k)}
                if r.get("lat") is not None:
                    pt, into = [r["lat"], r["lon"]], points
                else:
                    pt, into = raw.get("reported_point"), plant_pts
                if pt and pt not in into[n] and len(into[n]) < 5:
                    into[n].append(pt)
    rows = [{"name": n, "reports": c, "permits": sorted(permits[n]), "sources": sorted(sources[n])}
            | ({"adeq_wbids": wbids[n]} if wbids.get(n) else {}) | ({"points": points[n]} if points.get(n) else {})
            | ({"plant_points": plant_pts[n]} if plant_pts.get(n) else {})
            | ({"spellings": spellings[n]} if spellings.get(n) else {})
            for n, c in sorted(reports.items(), key=lambda x: (-x[1], x[0]))]
    doc = {"about": ("Receiving-water names in AZ's reports (EPA's overflow tables for Arizona permits, the 2026-11-04 "
                     "extract read on 2026-11-07, with the Navajo Nation's reports located in Arizona) that "
                     "data/receiving-waters-national.json does not hold for AZ, by "
                     "name as the record gives it (an ADEQ waterbody identifier named as ADEQ's layer names it), with "
                     "the number of reports giving each. Reports that say the discharge reached no water are left out."),
           "state": "AZ", "waters": len(rows), "reports": sum(reports.values()), "rows": rows}
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    print(f"{len(rows)} names, {sum(reports.values())} reports -> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
