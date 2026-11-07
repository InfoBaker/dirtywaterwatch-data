"""research/ne/receiving-waters-missing.json: the receiving-water names Nebraska reports give that
data/receiving-waters-national.json does not hold for NE, for `python -m ingest.waters_from_nhd --names ... --state NE`.

Usage (after the Nebraska feeds have written data/build/events): pipeline/.venv/bin/python -I scripts/ne_report_water_names.py

Reads EPA's overflow tables (NE permits) and DWEE's Beach Watch records. A name is the record's waterbody_text split at
semicolons (EPA's module joins several receiving waters so), counted once per report, compared with the national list's
names and keys case and punctuation aside. It is read as typed and normalised only the way the Illinois build did:
a segment code in brackets ("Big Nemaha River (Segment NE2-10000)") and a place after "at" ("Missouri River at South
Table Creek") are cut, and "A/B" is read as the two waters it names; a name the national list then holds is not
missing. A text that names no water ('Unknown', 'Intermittent Stream', 'Unnamed Drainageway') is kept with that reason,
so the build does not look it up as a name. Reports that say no water was reached are not records and do not count.
Each row: name, reports, permits, sources, up to five points of the reports and the operators' towns.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVENTS = ROOT / "data" / "build" / "events"
FEEDS = ["echo-sewer-overflow", "ne-dwee-beachwatch"]
OUT = ROOT / "research" / "ne" / "receiving-waters-missing.json"
NO_NAME = re.compile(r"^(unknown|intermittent stream|unnamed( drainageway| tributary| stream)?|drainage ditch\b.*)$", re.I)


def compact(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def names_in(text: str) -> list[str]:
    """The waters a receiving-water text names, as the national list would hold them."""
    out = []
    for part in re.split(r"\s*;\s*|\s*/\s*", text or ""):
        p = re.sub(r"\s*\((?:segment|seg\.?)\s+[^)]*\)\s*", " ", part, flags=re.I)
        p = re.sub(r"\s+at\s+.*$", "", p, flags=re.I).strip()
        if p:
            out.append(p)
    return list(dict.fromkeys(out))


def main() -> int:
    nat = json.loads((ROOT / "data" / "receiving-waters-national.json").read_text())["states"]["NE"]["waters"]
    have = {compact(n) for w in nat for n in [w.get("name"), w.get("key"), *(w.get("names_seen") or [])] if n}
    towns_by_permit = {p: d.get("towns") or [] for d in json.loads((ROOT / "data" / "dischargers.json").read_text())
                       if d.get("state") == "NE" for p in d.get("npdes_permits") or []}
    reports, permits, sources = Counter(), defaultdict(set), defaultdict(set)
    points, typed = defaultdict(list), defaultdict(set)
    for f in FEEDS:
        p = EVENTS / f"{f}.json"
        if not p.exists():
            raise SystemExit(f"{p.relative_to(ROOT)} missing: run the Nebraska feeds first")
        for r in json.loads(p.read_text()).get("records", []):
            if f == "echo-sewer-overflow" and not str(r.get("npdes_permit") or "").startswith("NE"):
                continue
            seen = set()
            for raw in [x.strip() for x in (r.get("waterbody_text") or "").split(";") if x.strip()]:
                for n in ([raw] if NO_NAME.match(raw) else names_in(raw)):
                    if compact(n) in have or n in seen:
                        continue
                    seen.add(n)
                    reports[n] += 1
                    typed[n].add(raw)
                    if r.get("npdes_permit"):
                        permits[n].add(r["npdes_permit"])
                    sources[n].add(r["source_id"])
                    if r.get("lat") is not None and len(points[n]) < 5 and [r["lat"], r["lon"]] not in points[n]:
                        points[n].append([r["lat"], r["lon"]])
    rows = []
    for n, c in sorted(reports.items(), key=lambda x: (-x[1], x[0])):
        row = {"name": n, "reports": c, "permits": sorted(permits[n]), "sources": sorted(sources[n])}
        if typed[n] != {n}:
            row["as_typed"] = sorted(typed[n])
        if points.get(n):
            row["points"] = points[n]
        towns = sorted({t for p in permits[n] for t in towns_by_permit.get(p, [])})
        if towns:
            row["towns"] = towns
        if NO_NAME.match(n):
            row["reason"] = "an unnamed or unknown stream: the report names no water"
        rows.append(row)
    named = [r for r in rows if "reason" not in r]
    doc = {"about": ("Receiving-water names in Nebraska's reports (EPA's overflow tables for Nebraska permits, the "
                     "2026-11-04 extract, and DWEE's Beach Watch health alerts and E. coli labels, read on 2026-11-07) "
                     "that data/receiving-waters-national.json does not hold for NE, by name as the report gives it "
                     "(a segment code and a place after 'at' cut), with the number of reports giving each. Reports "
                     "that say the discharge reached no water are left out."),
           "state": "NE", "waters": len(rows), "reports": sum(reports.values()),
           "by_reason": dict(Counter(r.get("reason", "not in data/receiving-waters-national.json for NE")
                                     for r in rows)),
           "named_waters": len(named), "rows": rows}
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    print(f"{len(rows)} names ({len(named)} named), {sum(reports.values())} reports -> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
