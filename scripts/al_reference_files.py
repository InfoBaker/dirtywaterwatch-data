"""data/reference/al-adem-sso-permits.json: every permit in ADEM's SSO report layer, with the permittee and facility
names ADEM gives for it, so the Alabama operator rows (scripts/add_al_operators.py) rebuild from committed files.

Usage (after pipeline/ingest/al_adem_sso.py has written a full read):
    pipeline/.venv/bin/python -I scripts/al_reference_files.py

Per permit: reports (count), first and last start year, the permittee names as filed with their report counts and the
start of the latest report giving each (newest first), and the facility names. Names come from the events file, after
the ingester's scrub: a permittee that reads as a person's name is already "[name removed]" there and is left out here.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVENTS = ROOT / "data" / "build" / "events" / "al-adem-sso-history.json"
OUT = ROOT / "data" / "reference" / "al-adem-sso-permits.json"
REMOVED = "[name removed]"


def main() -> int:
    doc = json.loads(EVENTS.read_text())
    names, last, facs, starts = defaultdict(Counter), defaultdict(dict), defaultdict(Counter), defaultdict(list)
    for r in doc["records"]:
        p = r.get("npdes_permit")
        if not p:
            continue
        s = r.get("started_at") or ""
        starts[p].append(s)
        n = r.get("discharger_name")
        if n and n != REMOVED:
            names[p][n] += 1
            last[p][n] = max(last[p].get(n, ""), s)
        f = ((r.get("raw") or {}).get("row") or {}).get("facility_site_name")
        if f:
            facs[p][f] += 1
    permits = {}
    for p in sorted(starts):
        ss = sorted(x for x in starts[p] if x)
        permits[p] = {
            "reports": len(starts[p]), "first_year": int(ss[0][:4]) if ss else None, "last_year": int(ss[-1][:4]) if ss else None,
            "permittees": [{"name": n, "reports": c, "latest": last[p][n][:10]}
                           for n, c in sorted(names[p].items(), key=lambda x: last[p][x[0]], reverse=True)],
            "facilities": [f for f, _ in facs[p].most_common()],
            "permittee_removed": any(r.get("discharger_name") == REMOVED for r in doc["records"] if r.get("npdes_permit") == p),
        }
    out = {"about": ("Every permit in ADEM's SSO report layer (SSOs_ALL_OB_ID), the permittee and facility names ADEM "
                     "gives for it, newest first, and its report count; a permittee that reads as a person's name is "
                     "left out (permittee_removed). Written by scripts/al_reference_files.py."),
           "source": "https://gis.adem.alabama.gov/arcgis/rest/services/SSOs_ALL_OB_ID/MapServer/0",
           "read": (doc.get("fetched_at") or "")[:10], "permits": permits}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print(f"{len(permits)} permits -> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
