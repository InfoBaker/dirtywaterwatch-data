"""data/outfalls-ky.json: Kentucky's corrections to EPA's plant outfall rows (final audit 2026-11-08 P2-4).

Usage: pipeline/.venv/bin/python -I scripts/ky_outfall_corrections.py

A row here wins over EPA's row for the same permit and outfall (common.load_outfall_registry: a state file ranks above
data/outfalls-plants-us.json, which is left as it is). Kentucky's KYP... permits are KPDES permits for sewer collection
systems (EPA's permit type SIN, a state individual permit; 56 rows, 54 permits): a system that sends its sewage to
another operator's treatment plant, so EPA's "receiving water" is that plant (for example "ASHLAND STP") or nothing,
and 47 of the rows have no point. They are no outfall to a water: each row is kind "other" (kept off the map and out
of the outfall count and the share line, as Hawaii's HIF014798 is), with kind_note saying why. The permits stay in the
operator rows and the register as what they are (a collection system's duty to report to the Division of Water).

A plant EPA records under a person's name (final audit 2026-11-08 P3-8: KY0104027, the City of Bardstown's second
plant) is shown under its operator and permit instead (RENAME): the row is EPA's, kind "plant", with permittee and
permit_name replaced and a name_note; no person's name in a row the site shows.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLANTS = ROOT / "data" / "outfalls-plants-us.json"
OUT = ROOT / "data" / "outfalls-ky.json"
READ = "2026-11-08"
NOTE = ("A KPDES permit for a sewer collection system (KYP...; EPA permit type SIN): the system sends its sewage to "
        "another operator's treatment plant, which EPA gives as the receiving water{rw}; no outfall to a water, so the "
        "row is kept off the map and out of the outfall count. Its reports, if any, are the collection system's.")


RENAME = {"KY0104027": "City of Bardstown plant (KY0104027)"}


def main() -> int:
    plants = json.loads(PLANTS.read_text())
    rows = []
    for r in plants["outfalls"]:
        p = str(r.get("npdes_permit") or "")
        if p in RENAME:
            rows.append({**r, "permittee": RENAME[p], "permit_name": RENAME[p], "outfall_kind": "plant",
                         "name_note": "EPA records this plant under a person's name; shown under its operator and permit",
                         "checked": READ, "supersedes": f"data/outfalls-plants-us.json {p} {r.get('outfall') or ''}".strip()})
            continue
        if r.get("state") == "KY" and p.startswith("KYP"):
            rw = r.get("receiving_water_echo")
            rows.append({**r, "outfall_kind": "other", "kind_note": NOTE.format(rw=f" ('{rw}')" if rw else " (none given here)"),
                         "checked": READ, "supersedes": f"data/outfalls-plants-us.json {p} {r.get('outfall') or ''}".strip()})
    doc = {"source": ("EPA ICIS-NPDES plant rows (data/outfalls-plants-us.json) for Kentucky's KYP collection-system "
                      f"permits, read {READ}; EPA's rows are kept and named in supersedes"),
           "rule": ("a KPDES collection-system permit (KYP...) is kind other: no outfall to a water; a plant EPA records "
                    "under a person's name is shown under its operator and permit"),
           "count": len(rows), "outfalls": sorted(rows, key=lambda r: (r["npdes_permit"], str(r.get("outfall") or "")))}
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    print(f"{OUT.name}: {len(rows)} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
