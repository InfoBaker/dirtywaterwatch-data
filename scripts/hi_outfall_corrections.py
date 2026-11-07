"""data/outfalls-hi.json: Hawaii's corrections to EPA's plant outfall rows, each cited (final audit 2026-11-07 P2-3).

Usage: pipeline/.venv/bin/python -I scripts/hi_outfall_corrections.py

A row here wins over EPA's row for the same permit and outfall (common.load_outfall_registry: a state file ranks above
data/outfalls-plants-us.json, which is left as it is):
  - HI0020877 outfall 001 (the Honouliuli plant's individual NPDES permit): EPA ECHO lists the permit "Terminated",
    terminated 05/31/2026 (read 2026-11-07); the national plant file still says ADC. The row is closed (CLS); the plant
    keeps its other permit row, HI0021954.
  - HIF014798 (the Wailua plant): ECHO lists a "General Permit Covered Facility" under master permit HIR000000 (other id
    R90H876), effective 07/10/2025, with no POTW component: Hawaii's NPDES general-permit series, very probably the
    storm-water coverage of the plant site, not a sewage discharge permit. The row is kind "other" (no sewage outfall);
    the plant's sewage outfall is HI0020257.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLANTS = ROOT / "data" / "outfalls-plants-us.json"
OUT = ROOT / "data" / "outfalls-hi.json"
READ = "2026-11-07"
ECHO = "https://echodata.epa.gov/echo/cwa_rest_services.get_facilities?output=JSON&p_pid={p}"
FIX = {
    "HI0020877": {"outfall_status": "CLS (permit terminated)", "permit_status": "TRM", "outfall_kind": "plant",
                  "kind_note": ("EPA ECHO lists permit HI0020877 as Terminated (termination date 05/31/2026; individual "
                                "NPDES permit, POTW), read 2026-11-07; the national plant file still says ADC. The "
                                "Honouliuli plant keeps its row under HI0021954.")},
    "HIF014798": {"outfall_kind": "other", "permit_status": "EFF",
                  "kind_note": ("EPA ECHO lists HIF014798 as a General Permit Covered Facility under master permit "
                                "HIR000000 (other id R90H876), effective 07/10/2025, no POTW component, read 2026-11-07: "
                                "Hawaii's NPDES general-permit series, very probably the plant site's storm-water "
                                "coverage, not a sewage discharge permit. The Wailua plant's sewage outfall is "
                                "HI0020257. Not confirmed in the coverage notice itself.")},
}


def main() -> int:
    plants = json.loads(PLANTS.read_text())
    rows = []
    for r in plants["outfalls"]:
        p = r.get("npdes_permit")
        if p in FIX:
            rows.append({**r, **FIX[p], "source": "fed-echo-cwa-rest-services", "source_url": ECHO.format(p=p),
                         "checked": READ, "supersedes": f"data/outfalls-plants-us.json {p} {r.get('outfall') or ''}".strip()})
    missing = set(FIX) - {r["npdes_permit"] for r in rows}
    if missing:
        raise SystemExit(f"not in the plant file: {sorted(missing)}")
    doc = {"source": ("EPA ECHO facility search (cwa_rest_services.get_facilities, the permit's status, type and master "
                      f"permit), read {READ}; EPA's rows for the same permit and outfall (data/outfalls-plants-us.json) "
                      "are kept and named in supersedes"),
           "rule": "a terminated permit's outfall is closed (CLS); a general-permit coverage that is no sewage permit is kind other",
           "count": len(rows), "outfalls": sorted(rows, key=lambda r: r["npdes_permit"])}
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    print(f"{OUT.name}: {len(rows)} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
