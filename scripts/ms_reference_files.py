"""The two committed inputs scripts/add_ms_operators.py reads besides the registries, so its rows rebuild from git:

  data/reference/ms-census-places.json   Mississippi's incorporated places and their class (city, town, village) from
                                         the U.S. Census Bureau's 2024 Gazetteer place file (NAME ends in the class;
                                         census-designated places left out)
  data/reference/ms-epa-sobe-permits.json the Mississippi permits in EPA's overflow tables, with the collection system
                                         names EPA gives and the report counts, from the events and dropped files
                                         pipeline/ingest/echo_sewer_overflow_events.py wrote (data/build, git-ignored)

Usage: pipeline/.venv/bin/python -I scripts/ms_reference_files.py [--census path/to/2024_gaz_place_28.txt]
(the Gazetteer file is fetched when no path is given)
"""
from __future__ import annotations

import csv
import io
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GAZ = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/2024_gaz_place_28.txt"
BUILD = ROOT / "data" / "build"
REF = ROOT / "data" / "reference"


def census(text: str) -> dict:
    places = {}
    for r in csv.DictReader(io.StringIO(text), delimiter="\t"):
        r = {k.strip(): (v or "").strip() for k, v in r.items()}
        name, _, cls = r["NAME"].rpartition(" ")
        if cls in ("city", "town", "village"):
            places[name] = {"class": cls, "geoid": r["GEOID"]}
    return {"source": GAZ, "about": "Mississippi's incorporated places and their class, from the Census Bureau's 2024 "
                                    "Gazetteer place file (census-designated places left out).",
            "places": dict(sorted(places.items()))}


def sobe() -> dict:
    ev = json.loads((BUILD / "events" / "echo-sewer-overflow.json").read_text())
    dropped = json.loads((BUILD / "echo-sewer-overflow-dropped.json").read_text())
    names, kept, drop = defaultdict(Counter), Counter(), Counter()
    for r in ev["records"]:
        p = r.get("npdes_permit") or ""
        if p.startswith("MS"):
            kept[p] += 1
            if (r.get("raw") or {}).get("collection_system_name"):
                names[p][r["raw"]["collection_system_name"].strip()] += 1
    for r in dropped["dropped"]:
        if str(r.get("permit") or "").startswith("MS"):
            drop[r["permit"]] += 1
    permits = {p: {"reports": kept[p] + drop[p], "kept": kept[p],
                   "collection_systems": [n for n, _ in names[p].most_common()]}
               for p in sorted(set(kept) | set(drop))}
    return {"about": ("The Mississippi permits in EPA's sewer overflow and bypass tables (extract of "
                      f"{ev.get('meta', {}).get('extract_date')}), with their report counts and the collection systems "
                      "EPA names for the reports kept."), "extract_date": ev.get("meta", {}).get("extract_date"),
            "permits": permits}


def main(argv) -> int:
    if "--census" in argv:
        text = Path(argv[argv.index("--census") + 1]).read_text()
    else:
        import requests
        text = requests.get(GAZ, timeout=60).text
    REF.mkdir(exist_ok=True)
    c = census(text)
    (REF / "ms-census-places.json").write_text(json.dumps(c, indent=1, ensure_ascii=False) + "\n")
    s = sobe()
    (REF / "ms-epa-sobe-permits.json").write_text(json.dumps(s, indent=1, ensure_ascii=False) + "\n")
    print(f"{len(c['places'])} places, {len(s['permits'])} permits")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
