"""research/nm/receiving-waters-missing.json: the water names New Mexico's records give that
data/receiving-waters-national.json does not hold for NM, for `python -m ingest.waters_from_nhd --names ... --state NM`.

Usage (after pipeline/ingest/echo_sewer_overflow_events.py and `python -m ingest.generic nm-nmed-hab-mapper` have
written data/build/events, and the bloom layer's last response is saved under data/raw/nm-nmed-hab-mapper/):
    pipeline/.venv/bin/python -I scripts/nm_report_water_names.py

Two feeds:
  - EPA's overflow tables (echo-sewer-overflow): the records placed in New Mexico (NM permits, and the Navajo Nation's
    whose point lies in New Mexico); a name is the record's waterbody_text split at semicolons, counted once per report.
    Reports that say no water was reached are not records and do not count.
  - NMED's bloom map (nm-nmed-hab-mapper): every station's assessment unit in the layer's last saved response, not only
    the stations under an advisory today (a station is monitored all season and becomes a record when an advisory is
    issued), with the advisory records counted as reports. An assessment unit of a river is named with its segment
    ('Rio Grande (Embudo Creek to Rio Pueblo de Taos)'): the water is the name before the bracket, the segment kept.
A name is compared with the national list's names and keys, case and punctuation aside. Each row: name, reports,
stations (bloom map), permits, sources, segments, up to five points (the report's or the station's own).
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVENTS = ROOT / "data" / "build" / "events"
HAB_RAW = ROOT / "data" / "raw" / "nm-nmed-hab-mapper"
OUT = ROOT / "research" / "nm" / "receiving-waters-missing.json"


def compact(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def base_name(n: str) -> tuple[str, str | None]:
    m = re.match(r"^\s*(.+?)\s*\((.+)\)\s*$", n or "")
    return (m.group(1).strip(), m.group(2).strip()) if m else (" ".join((n or "").split()), None)


def main() -> int:
    nat = json.loads((ROOT / "data" / "receiving-waters-national.json").read_text())["states"]["NM"]["waters"]
    have = {compact(n) for w in nat for n in [w.get("name"), w.get("key"), *(w.get("names_seen") or [])] if n}
    reports, stations, permits, sources = Counter(), Counter(), defaultdict(set), defaultdict(set)
    segments: dict[str, set] = defaultdict(set)
    points: dict[str, list] = defaultdict(list)
    spelling: dict[str, str] = {}

    def add(n0: str, src: str, pt, permit=None, report=False, station=False):
        n, seg = base_name(n0)
        if not n or compact(n) in have:
            return
        n = spelling.setdefault(compact(n), n.title() if n.isupper() or n.islower() else n)
        reports[n] += report
        stations[n] += station
        sources[n].add(src)
        if permit:
            permits[n].add(permit)
        if seg:
            segments[n].add(seg)
        if pt and pt not in points[n] and len(points[n]) < 5:
            points[n].append(pt)

    p = EVENTS / "echo-sewer-overflow.json"
    for r in json.loads(p.read_text()).get("records", []) if p.exists() else []:
        if ((r.get("raw") or {}).get("state") or str(r.get("npdes_permit") or "")[:2]) != "NM":
            continue
        for n0 in dict.fromkeys(x.strip() for x in (r.get("waterbody_text") or "").split(";") if x.strip()):
            add(n0, r["source_id"], [r["lat"], r["lon"]] if r.get("lat") is not None else None, r["npdes_permit"], True)
    p = EVENTS / "nm-nmed-hab-mapper.json"
    for r in json.loads(p.read_text()).get("records", []) if p.exists() else []:
        if not (r.get("raw") or {}).get("_missing_from_source_since") and r.get("waterbody_text"):
            add(r["waterbody_text"], r["source_id"], None, report=True)
    saved = sorted(f for f in HAB_RAW.glob("*.json") if not f.name.endswith(".meta.json")) if HAB_RAW.exists() else []
    if saved:
        doc = json.loads(saved[-1].read_text())   # the generic reader's saved response: {layer, pages: [query pages]}
        for f in [f for pg in doc.get("pages", [doc]) for f in pg.get("features", [])]:
            a = f.get("attributes") or {}
            if a.get("ASSESSMENT_UNIT_NAME"):
                pt = ([a["MLOC_LATITUDE"], a["MLOC_LONGITUDE"]] if a.get("MLOC_LATITUDE") is not None else None)
                add(a["ASSESSMENT_UNIT_NAME"], "nm-nmed-hab-mapper", pt, station=True)
    rows = [{"name": n, "reports": reports[n]} | ({"stations": stations[n]} if stations[n] else {})
            | {"permits": sorted(permits[n]), "sources": sorted(sources[n])}
            | ({"segments": sorted(segments[n])} if segments.get(n) else {}) | ({"points": points[n]} if points.get(n) else {})
            for n in sorted(set(reports) | set(stations), key=lambda x: (-reports[x], -stations[x], x))]
    doc = {"about": ("Water names in NM's records that data/receiving-waters-national.json does not hold for NM: EPA's "
                     "overflow tables (the 2026-11-04 extract read on 2026-11-07; New Mexico permits and the Navajo "
                     "Nation's reports located in New Mexico; every receiving water they name is already on the national "
                     "list) and NMED's bloom map (every station's assessment unit in the layer read on 2026-11-07, a "
                     "river's segment apart), with the number of records giving each and the stations on it. Reports that "
                     "say the discharge reached no water are left out."),
           "state": "NM", "waters": len(rows), "reports": sum(reports.values()), "rows": rows}
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    print(f"{len(rows)} names, {sum(reports.values())} reports -> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
