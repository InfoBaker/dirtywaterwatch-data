"""data/outfalls-la.json: Louisiana's corrections to EPA's combined sewer inventory rows.

Usage: pipeline/.venv/bin/python -I scripts/la_outfall_corrections.py

EPA's national CSO inventory (data/outfalls-us.json) lists two Louisiana rows, both at petrochemical plants: Shell
Chemical LP's Geismar plant (LA0005754, outfall 101, status 'CSO|DSW|NCW|NDP', to the Mississippi River) and LACC's
ethylene plant at Westlake (LA0127268, outfall 001, 'TCS', to Maple Fork-Bayou D'Inde). They are industrial combined
outfalls (process water, stormwater and the plant's own sanitary water), not a municipal sewer system's overflow
points: Louisiana has no municipal combined sewer system in EPA's inventory. Each row here is EPA's row with
outfall_kind "other" and kind_note saying why, so it is kept off the map's combined sewer outlets, out of the outfall
count and out of the rain caution (a regional file outranks the national one, common.outfall_file_rank). EPA's rows
stay in data/outfalls-us.json, named in supersedes.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "outfalls-la.json"
READ = "2026-11-14"
NOTE = ("EPA's combined sewer inventory lists this industrial plant's outfall ({status}): a petrochemical plant's "
        "combined process, storm and sanitary outfall under its own permit, not a municipal sewer system's overflow "
        "point; kept off the map's combined sewer outlets and out of the outfall count and the rain caution.")


def main() -> int:
    rows = []
    for r in json.loads((ROOT / "data" / "outfalls-us.json").read_text())["outfalls"]:
        if r.get("state") == "LA":
            rows.append({**r, "outfall_kind": "other", "kind_note": NOTE.format(status=r.get("outfall_status")),
                         "checked": READ,
                         "supersedes": f"data/outfalls-us.json {r['npdes_permit']} {r.get('outfall') or ''}".strip()})
    doc = {"source": f"EPA ECHO national CSO inventory rows for Louisiana (data/outfalls-us.json), read {READ}; EPA's rows "
                     "are kept and named in supersedes",
           "rule": "an industrial plant's combined outfall in EPA's CSO inventory is kind other: no municipal combined "
                   "sewer outlet", "count": len(rows),
           "outfalls": sorted(rows, key=lambda r: (r["npdes_permit"], str(r.get("outfall") or "")))}
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    print(f"{OUT.name}: {len(rows)} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
