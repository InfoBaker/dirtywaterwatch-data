"""research/al/receiving-waters-missing.json: the receiving-water names Alabama's reports give that
data/receiving-waters-national.json does not hold for AL, for `python -m ingest.waters_from_nhd --names ... --state AL`.

Usage (after pipeline/ingest/al_adem_sso.py and al_adem_beaches.py have written their events files):
    pipeline/.venv/bin/python -I scripts/al_report_water_names.py

Reads ADEM's SSO reports (the names the ingester reads from each report's receiving-water words: waterbody_text, split
at "; ", counted once per report; reports that say no water was reached, or name only a storm drain or ditch, have none)
and the beach monitoring stations' waters (meta.station_list of the beach feed: the water ADEM names for each station,
counted as stations, not reports). Names are compared with the national list's names, keys and names seen, case, spaces
and punctuation aside; spellings that differ only so are counted together. A report that names an unnamed tributary
("UT to Dodson Branch") is listed under that name: the water builder reads the named water it flows to. Each row: name,
reports, permits, sources, up to five of the reports' own points ([lat, lon]); a station water also gives stations.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVENTS = ROOT / "data" / "build" / "events"
OUT = ROOT / "research" / "al" / "receiving-waters-missing.json"


def compact(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def main() -> int:
    nat = json.loads((ROOT / "data" / "receiving-waters-national.json").read_text())["states"]["AL"]["waters"]
    have = {compact(n) for w in nat for n in [w.get("name"), w.get("key"), *(w.get("names_seen") or [])] if n}
    reports, permits, points, typed, sources, stations = (Counter(), defaultdict(set), defaultdict(list),
                                                          defaultdict(Counter), defaultdict(set), Counter())
    sso = json.loads((EVENTS / "al-adem-sso-history.json").read_text())
    for r in sso.get("records", []):
        if r.get("duplicate_of"):
            continue
        for n in dict.fromkeys(x.strip() for x in (r.get("waterbody_text") or "").split(";") if x.strip()):
            k = compact(n)
            if k in have:
                continue
            typed[k][n] += 1
            reports[k] += 1
            sources[k].add("al-adem-sso-history")
            if r.get("npdes_permit"):
                permits[k].add(r["npdes_permit"])
            pt = [r["lat"], r["lon"]] if r.get("lat") is not None else None
            if pt and pt not in points[k] and len(points[k]) < 5:
                points[k].append(pt)
    station_pts = defaultdict(list)
    beach = json.loads((EVENTS / "al-adem-beach-monitoring.json").read_text())
    for s in (beach.get("meta") or {}).get("station_list") or []:
        n = (s.get("water") or "").strip()
        k = compact(n)
        if not n or k in have:
            continue
        typed[k][n] += 1
        stations[k] += 1
        sources[k].add("al-adem-beach-monitoring")
        if s.get("lat") is not None and len(station_pts[k]) < 5:
            station_pts[k].append([round(s["lat"], 6), round(s["lon"], 6)])
    keys = set(reports) | set(stations)
    rows = []
    for k in sorted(keys, key=lambda x: (-reports[x], -stations[x], typed[x].most_common(1)[0][0])):
        row = {"name": typed[k].most_common(1)[0][0], "reports": reports[k], "permits": sorted(permits[k]),
               "sources": sorted(sources[k])}
        if stations[k]:
            row["stations"] = stations[k]
        if len(typed[k]) > 1:
            row["spellings"] = sorted(typed[k])
        p = points[k] or station_pts[k]
        if p:
            row["points"] = p
        rows.append(row)
    out = {"about": ("Receiving-water names in Alabama's reports (ADEM's SSO report layer, every report since 2012 read "
                     f"on {(sso.get('fetched_at') or '')[:10]}, and the waters ADEM names for its coastal beach "
                     "monitoring stations) that data/receiving-waters-national.json does not hold for AL, by name as "
                     "the ingester reads it from the report's words (spellings that differ only in case, spaces or "
                     "punctuation counted together), with the number of reports giving each and up to five of their "
                     "points. Reports that say the sewage reached no water, or name only a storm drain or ditch, are "
                     "left out; so are reports marked as duplicates of another."),
           "state": "AL", "waters": len(rows), "reports": sum(reports.values()), "rows": rows}
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print(f"{len(rows)} names, {sum(reports.values())} reports -> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
