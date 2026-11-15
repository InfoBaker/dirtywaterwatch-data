"""research/pr/receiving-waters-missing.json: the water names Puerto Rico's records give that
data/receiving-waters-national.json does not hold for PR.

Usage (after pipeline/ingest/echo_sewer_overflow_events.py has written its events file):
    pipeline/.venv/bin/python -I scripts/pr_report_water_names.py

Names: the waterbody_text of every Puerto Rico record EPA's overflow module keeps (the receiving-water texts as filed,
English, Spanish or both; the generic texts with no name, such as 'unnamed creek', are not names and are left out),
and the receiving waters PRASA's layer gives its 12 combined sewer outfalls (data/outfalls-pr.json). A name is held
when its folded form (lower case, accents off) equals a PR water's name, a name seen for it or its GNIS name in the
national list. Each row keeps the name as written, the number of records, the permits, the sources and the report
points (three decimals), so the water batch can place it county-aware. Two spellings of one water ('RIO BAIROA',
'BAIROA RIVER') stay two rows: the batch resolves each.
"""
from __future__ import annotations

import json
import unicodedata
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVENTS = ROOT / "data" / "build" / "events" / "echo-sewer-overflow.json"
OUTFALLS = ROOT / "data" / "outfalls-pr.json"
NATIONAL = ROOT / "data" / "receiving-waters-national.json"
OUT = ROOT / "research" / "pr" / "receiving-waters-missing.json"


# the same water under the national list's spelling (English and Spanish forms of one name, a typing slip), for the
# batch to confirm on the points; never a translation of the report's own text, which stays as filed
SAME_AS = {"CABO CARIBE": "CANO CABO CARIBE", "CANO CARIBE": "CANO CABO CARIBE", "Caño Martín Peña": "Martin Pena Channel",
           "Bahía de San Juan": "San Juan Bay", "Río de Puerto Nuevo": "Puerto Nuevo River",
           "OCEANO ATLANTICO": "ATLANTIC OCEAN", "Oceano Atlantico": "ATLANTIC OCEAN", "Caribe Ocean": "CARIBBEAN SEA",
           "Morovis River": "RIO MOROVIS", "OROCOVIS RIVER": "RIO OROCOVIS", "Jayuya River": "RIO GRANDE DE JAYUYA",
           "Mondongo Creek": "MONDONGO GREEK", "CIBUCO RIVER": "RIO CIBUCO", "Cibuco River": "RIO CIBUCO",
           "RIO GRANDE DE LOIZA RIVER": "RIO LOISA", "Manatí River": "RIO GRANDE DE MANATI",
           "RIO GRANDE MANATI": "RIO GRANDE DE MANATI"}


def fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return " ".join("".join(c for c in s if not unicodedata.combining(c)).lower().split())


def main() -> int:
    nat = json.loads(NATIONAL.read_text())["states"].get("PR", {}).get("waters", [])
    held = {fold(n) for w in nat for n in [w.get("name"), *(w.get("names_seen") or []), *(w.get("gnis_names") or [])] if n}
    rows: dict[str, dict] = defaultdict(lambda: {"reports": 0, "permits": set(), "sources": set(), "points": set()})
    for r in json.loads(EVENTS.read_text())["records"]:
        if not str(r.get("npdes_permit") or "").startswith("PR") or not r.get("waterbody_text"):
            continue
        for name in r["waterbody_text"].split("; "):
            x = rows[" ".join(name.split())]
            x["reports"] += 1
            x["permits"].add(r["npdes_permit"])
            x["sources"].add(r["source_id"])
            if r.get("lat") is not None:
                x["points"].add((round(r["lat"], 3), round(r["lon"], 3)))
    for o in json.loads(OUTFALLS.read_text())["outfalls"]:
        x = rows[o["receiving_water_echo"]]
        x["outfalls"] = x.get("outfalls", 0) + 1
        x["permits"].add(o["npdes_permit"])
        x["sources"].add("pr-prasa-cso-data")
        x["points"].add((round(o["lat"], 3), round(o["lon"], 3)))
    out = [{"name": n, "reports": x["reports"], **({"outfalls": x["outfalls"]} if x.get("outfalls") else {}),
            "permits": sorted(x["permits"]), "sources": sorted(x["sources"]), "points": sorted(x["points"]),
            **({"possibly_same_as": SAME_AS[n]} if n in SAME_AS else {})}
           for n, x in rows.items() if fold(n) not in held]
    out.sort(key=lambda r: (-r["reports"] - r.get("outfalls", 0), r["name"]))
    kept = [n for n in rows if fold(n) in held]
    doc = {"about": ("Water names in Puerto Rico's records that data/receiving-waters-national.json does not hold for PR: "
                     "EPA's overflow tables (the 2026-11-12 extract read on 2026-11-14; the reports kept as reaching a "
                     "water, names as filed in English, Spanish or both) and the receiving waters PRASA's layer gives "
                     "its 12 combined sewer outfalls, with the number of records giving each and their points. Generic "
                     "texts that name no water ('unnamed creek', 'CREEK (UNKNOWN THE NAME)') are left out. DRNA's beach "
                     "advisories are placed by their stations' points and name no receiving water."),
           "state": "PR", "waters": len(out), "reports": sum(r["reports"] for r in out),
           "held_in_national_list": sorted(kept), "rows": out}
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    print(f"{OUT.name}: {len(out)} names missing ({doc['reports']} reports); {len(kept)} held")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
