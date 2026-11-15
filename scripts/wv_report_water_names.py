"""research/wv/receiving-waters-missing.json: the water names West Virginia's outlet rows and records give that
data/receiving-waters-national.json does not hold for WV, for `python -m ingest.waters_from_nhd --names ... --state WV`.

Usage (after scripts/build_wv_outfalls.py and the West Virginia feeds): pipeline/.venv/bin/python -I
scripts/wv_report_water_names.py

Sources: DEP's NPDES Outlets layer (data/outfalls-wv.json): each open combined sewer outlet's receiving stream, the
first part of DEP's chain ("Buffalo Creek/Monongahela River" is Buffalo Creek; "UNT/..." an unnamed tributary, left
out), once per outlet, with the outlet's point and county; EPA's monthly DMR records (wv-echo-dmr-cso) and DEP's bloom
map (wv-dep-hab-advisories), per record. Rules and keys: scripts/wv_la_water_names_common.py.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wv_la_water_names_common import ROOT, first_named, key, known_keys  # noqa: E402

OUT = ROOT / "research" / "wv" / "receiving-waters-missing.json"
EVENTS = ROOT / "data" / "build" / "events"
# DEP spellings that are plainly another name on the national list (not merged here: the batch decides)
LIKELY_SPELLING = {"jim rum": "Jim Run (on the national list for WV; DEP's layer writes 'Jim Rum')"}


def collect() -> dict:
    rows = defaultdict(lambda: {"name": None, "reports": 0, "counties": set(), "points": [], "permits": set(),
                                "sources": set(), "as_given": set()})

    def add(text, src, permit=None, point=None, county=None):
        name = first_named(text)
        if not name:
            return
        r = rows[key(name)]
        r["name"] = r["name"] or name
        r["reports"] += 1
        r["sources"].add(src)
        r["as_given"].add(" ".join(str(text).split()))
        if permit:
            r["permits"].add(permit)
        if county:
            r["counties"].add(county)
        if point and point[0] is not None and len(r["points"]) < 5:
            p = [round(float(point[0]), 3), round(float(point[1]), 3)]
            if p not in r["points"]:
                r["points"].append(p)

    for o in json.loads((ROOT / "data" / "outfalls-wv.json").read_text())["outfalls"]:
        if not o.get("dep_outlet_end"):
            add(o.get("receiving_water_echo"), "wv-dep-npdes-outlets", o["npdes_permit"], (o.get("lat"), o.get("lon")),
                o.get("county"))
    for sid in ("wv-echo-dmr-cso", "wv-dep-hab-advisories"):
        p = EVENTS / f"{sid}.json"
        if p.exists():
            for r in json.loads(p.read_text()).get("records", []):
                add(r.get("waterbody_text"), sid, r.get("npdes_permit"), (r.get("lat"), r.get("lon")))
    return rows


def main() -> int:
    known = known_keys("WV")
    out = []
    for k, r in sorted(collect().items(), key=lambda kv: (-kv[1]["reports"], kv[0])):
        if k in known:
            continue
        out.append({"name": r["name"], "reports": r["reports"], "counties": sorted(r["counties"]),
                    "points": r["points"], "permits": sorted(r["permits"])[:10], "sources": sorted(r["sources"]),
                    "as_given": sorted(r["as_given"])[:5], "reason": "not in data/receiving-waters-national.json for WV"
                    + (f"; likely {LIKELY_SPELLING[k]}" if k in LIKELY_SPELLING else "")})
    doc = {"about": ("Water names in West Virginia's outlet rows and records that data/receiving-waters-national.json "
                     "does not hold for WV: DEP's NPDES Outlets layer (each open combined sewer outlet's receiving "
                     "stream, read 2026-11-14), EPA's monthly DMR records and DEP's bloom map, with the number of outlets "
                     "and records giving each, their counties and points."),
           "state": "WV", "waters": len(out), "reports": sum(r["reports"] for r in out), "rows": out}
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    print(f"{OUT.relative_to(ROOT)}: {len(out)} names, {doc['reports']} outlets and records")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
