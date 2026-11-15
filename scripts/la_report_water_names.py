"""research/la/receiving-waters-missing.json: the water names Louisiana's records give that
data/receiving-waters-national.json does not hold for LA, for `python -m ingest.waters_from_nhd --names ... --state LA`.

Usage (after the Louisiana feeds): pipeline/.venv/bin/python -I scripts/la_report_water_names.py

Source: Baton Rouge's quarterly reports (la-baton-rouge-quarterly): each record's receiving water as the City-Parish
writes it, counted per record, with the parish (East Baton Rouge: the names are to be placed in that parish or the
water flowing out of it, never elsewhere in the state) and the permits. The reports give no points. 'None' is no name.
Rules and keys: scripts/wv_la_water_names_common.py.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wv_la_water_names_common import NOT_A_NAME, ROOT, key, known_keys  # noqa: E402

OUT = ROOT / "research" / "la" / "receiving-waters-missing.json"
EVENTS = ROOT / "data" / "build" / "events"


def main() -> int:
    known = known_keys("LA")
    rows = defaultdict(lambda: {"name": None, "reports": 0, "counties": set(), "permits": set(), "sources": set()})
    p = EVENTS / "la-baton-rouge-quarterly.json"
    for r in (json.loads(p.read_text()).get("records", []) if p.exists() else []):
        name = " ".join(str(r.get("waterbody_text") or "").split())
        if not name or NOT_A_NAME.match(name):
            continue
        x = rows[key(name)]
        x["name"] = x["name"] or name
        x["reports"] += 1
        x["counties"].add((r.get("raw") or {}).get("county") or "East Baton Rouge Parish")
        x["permits"].add(r.get("npdes_permit"))
        x["sources"].add("la-baton-rouge-quarterly")
    out = [{"name": r["name"], "reports": r["reports"], "counties": sorted(r["counties"]), "points": [],
            "permits": sorted(r["permits"]), "sources": sorted(r["sources"]),
            "reason": "not in data/receiving-waters-national.json for LA; the reports give no point: place in the parish"}
           for k, r in sorted(rows.items(), key=lambda kv: (-kv[1]["reports"], kv[0])) if k not in known]
    doc = {"about": ("Water names in Louisiana's records that data/receiving-waters-national.json does not hold for LA: "
                     "Baton Rouge's consent-decree quarterly reports (the receiving water of each discharge, Reports 93 "
                     "to 98 that pass the layout check, read 2026-11-14), with the number of records giving each and "
                     "the parish."),
           "state": "LA", "waters": len(out), "reports": sum(r["reports"] for r in out), "rows": out}
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    print(f"{OUT.relative_to(ROOT)}: {len(out)} names, {doc['reports']} records")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
