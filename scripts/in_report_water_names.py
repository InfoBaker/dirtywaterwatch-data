"""research/in/receiving-waters-missing.json: the water names Indiana's records and outfall rows give that
data/receiving-waters-national.json does not hold for IN, for `python -m ingest.waters_from_nhd --names ... --state IN`.

Usage (after the Indiana feeds have written data/build/events and scripts/build_in_outfalls.py data/outfalls-in.json):
    pipeline/.venv/bin/python -I scripts/in_report_water_names.py

Sources:
  - IDEM's CSO outfall layer (data/outfalls-in.json): each open combined sewer outfall's receiving stream as IDEM names
    it, counted once per outfall, with the outfall's point and county.
  - EPA's monthly DMRs (in-echo-dmr-cso): the records' receiving water (the registry outfall's), counted per record.
  - EPA's overflow tables (echo-sewer-overflow): the Indiana records' waterbody_text, counted per report.
  - IDEM's cyanobacteria layer (in-idem-cyanobacteria): each bloom record's lake, with the beach's point (rounded).
A name is compared with the national list's names, keys, the names EPA's rows gave (names_seen) and the GNIS names
its records were built from, case and punctuation aside, so a name another spelling already covers is not listed.
A qualified name ("Little Buck Creek", "West Fork White River") is its own water and is compared as written. Each
row: name, reports (outfalls and records naming it), counties, points (up to five), permits, sources.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVENTS = ROOT / "data" / "build" / "events"
OUT = ROOT / "research" / "in" / "receiving-waters-missing.json"
NOT_A_NAME = re.compile(r"^\s*(?:unnamed\b.*|unknown|none|n/?a|storm sewer)\s*$", re.I)
ABBR = [(r"\bfk\b", "fork"), (r"\bw\b", "west"), (r"\be\b", "east"), (r"\bn\b", "north"), (r"\bs\b", "south"),
        (r"\bcr\b", "creek"), (r"\br\b", "river"), (r"\bft\b", "fort"), (r"\bst\b", "saint"), (r"\bof the\b", " ")]


def key(name: str) -> str:
    s = re.sub(r"[^a-z0-9 ]+", " ", (name or "").lower())
    for pat, rep in ABBR:          # 'W FK WHITE RIVER' and 'West Fork of the White River' are one name
        s = re.sub(pat, rep, s)
    return " ".join(s.split())


def known_keys() -> set[str]:
    doc = json.loads((ROOT / "data" / "receiving-waters-national.json").read_text())
    st = doc["states"].get("IN") or {}
    out = set()
    for w in st.get("waters") or []:
        for n in [w.get("name"), w.get("key"), *(w.get("names_seen") or []), *(w.get("gnis_names") or [])]:
            if n:
                out.add(key(n))
    return out


def collect() -> dict[str, dict]:
    rows: dict[str, dict] = defaultdict(lambda: {"name": None, "reports": 0, "counties": set(), "points": [],
                                                 "permits": set(), "sources": set()})

    def add(name, src, permit=None, point=None, county=None, n=1):
        name = " ".join(str(name or "").split())
        if not name or NOT_A_NAME.match(name):
            return
        r = rows[key(name)]
        r["name"] = r["name"] or name
        r["reports"] += n
        r["sources"].add(src)
        if permit:
            r["permits"].add(permit)
        if county:
            r["counties"].add(county)
        if point and point[0] is not None and len(r["points"]) < 5:
            p = [round(float(point[0]), 3), round(float(point[1]), 3)]
            if p not in r["points"]:
                r["points"].append(p)

    for o in json.loads((ROOT / "data" / "outfalls-in.json").read_text())["outfalls"]:
        if o.get("outfall_kind") == "cso" and not str(o.get("outfall_status") or "").startswith("CLS"):
            add(o.get("receiving_water_echo"), "in-idem-cso-outfall-layer", o["npdes_permit"], (o.get("lat"), o.get("lon")),
                o.get("county"))
    for sid in ("in-echo-dmr-cso", "echo-sewer-overflow", "in-idem-cyanobacteria"):
        p = EVENTS / f"{sid}.json"
        if not p.exists():
            continue
        for r in json.loads(p.read_text()).get("records", []):
            permit = r.get("npdes_permit") or ""
            if sid == "echo-sewer-overflow" and not permit.startswith("IN"):
                continue
            county = (r.get("raw") or {}).get("county")
            for name in str(r.get("waterbody_text") or "").split(";"):
                add(name, sid, permit or None, (r.get("lat"), r.get("lon")), county)
    return rows


def main() -> int:
    known = known_keys()
    rows = collect()
    out = []
    for k, r in sorted(rows.items(), key=lambda kv: (-kv[1]["reports"], kv[0])):
        if k in known:
            continue
        out.append({"name": r["name"], "reports": r["reports"], "counties": sorted(r["counties"]),
                    "points": r["points"], "permits": sorted(r["permits"])[:10], "sources": sorted(r["sources"]),
                    "reason": "not in data/receiving-waters-national.json for IN"})
    doc = {"about": ("Water names in Indiana's records and outfall rows that data/receiving-waters-national.json does "
                     "not hold for IN: IDEM's CSO outfall layer (each open outfall's receiving stream, read 2026-11-14), "
                     "EPA's monthly DMR records and overflow tables (2026-11-12 extract), and IDEM's cyanobacteria "
                     "layer's lakes, with the number of outfalls and records giving each, their counties and points."),
           "state": "IN", "waters": len(out), "reports": sum(r["reports"] for r in out), "rows": out}
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    print(f"{OUT.relative_to(ROOT)}: {len(out)} names, {doc['reports']} outfalls and records")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
