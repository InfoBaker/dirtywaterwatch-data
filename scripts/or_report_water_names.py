"""research/or/receiving-waters-missing.json: the water names Oregon's records give that data/receiving-waters-national.json
does not hold for OR, for the water batch (the cloud state build's names pass).

Usage (after the Oregon ingesters have written data/build/events/):
    pipeline/.venv/bin/python -I scripts/or_report_water_names.py

Sources: DEQ's OERS spill archive (or-deq-oers-spills-2013-2025: Affected_Waterway, as the ingester reads it, with the
report's county and city), Portland Environmental Services' advisories (or-bes-news-rss: the waters each advisory
names, Multnomah County), OHA's bloom advisories (or-oha-hab-advisories: the water's name and county as OHA gives them).
A report that says the sewage reached no water, or names none, is left out (by_reason). One row per name and county,
with the number of records giving it, the towns (most reports first), the source ids and the permits. A name is held
when the national list has it (name, key, a spelling seen) for OR, compared without case or punctuation; the name is
kept as the source spells it, except a misspelling with an Oregon hand alias in data/water-aliases.json ("Tualitan
River", "Kellog Creek"), which is read as its record's name and counted in `aliased`. OHA's compound names arrive split
by the ingester ("Brownlee Reservoir - Powder Arm" as Brownlee Reservoir).
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
EVENTS = ROOT / "data" / "build" / "events"
OUT = ROOT / "research" / "or" / "receiving-waters-missing.json"
NATIONAL = ROOT / "data" / "receiving-waters-national.json"
SOURCES = ("or-deq-oers-spills-2013-2025", "or-bes-news-rss", "or-oha-hab-advisories")
NOT_A_WATER = re.compile(r"^(?:storm ?drains?|catch basins?|ground|soil|street|parking lot|ditch|drainage ditch|"
                         r"wetlands?|marsh|unnamed\b.*|various|multiple)$", re.I)
WATER_WORD = re.compile(r"\b(?:river|creek|slough|lake|bay|ocean|reservoir|pond|channel|estuary|harbor|canal|fork|"
                        r"run|branch|wetlands?|marsh|inlet|lagoon|spring|brook|stream|arm)\b", re.I)


ALIASES = ROOT / "data" / "water-aliases.json"


def spelling_map() -> dict[str, str]:
    """{misspelling key: the record's name} from the Oregon hand aliases (data/water-aliases.json, slugs ending "-or"):
    "Tualitan River" is the Tualatin River (review 2026-11-08 P2-6)."""
    d = json.loads(ALIASES.read_text())
    return {key(a): slug.removesuffix("-or").replace("-", " ").title() for slug, al in d.items() if slug.endswith("-or")
            for a in al}


def key(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def held_names() -> set[str]:
    d = json.loads(NATIONAL.read_text())
    ws = ((d.get("states") or {}).get("OR") or {}).get("waters") or []
    return {key(n) for w in ws for n in [w.get("name"), w.get("key"), *(w.get("names_seen") or [])] if n}


def county_of(r: dict) -> str | None:
    c = (r.get("raw") or {}).get("county") or ((r.get("raw") or {}).get("row") or {}).get("County_1")
    if c:
        c = re.sub(r"\s+county$", "", str(c).strip(), flags=re.I)
        return f"{c} County"
    if r.get("source_id") == "or-bes-news-rss":
        return "Multnomah County"           # Portland's advisories; the waters it names lie in the city
    if r.get("lat") is not None:
        from build.status import point_county     # the county whose Census outline holds the point
        here = point_county("OR", r["lat"], r["lon"])
        return here[1] if here else None
    return None


def main() -> int:
    held = held_names()
    spell = spelling_map()
    folded = Counter()
    rows: dict[tuple, dict] = {}
    towns: dict[tuple, Counter] = defaultdict(Counter)
    why = Counter()
    read = Counter()
    for sid in SOURCES:
        doc = json.loads((EVENTS / f"{sid}.json").read_text())
        for r in doc["records"]:
            read[sid] += 1
            raw = r.get("raw") or {}
            if raw.get("reached_water") is False:
                why["the report says the sewage reached no water"] += 1
                continue
            text = (r.get("waterbody_text") or "").strip()
            if not text:
                why["no water named"] += 1
                continue
            for name in [x.strip() for x in text.split(";") if x.strip()]:
                if NOT_A_WATER.match(name) or not WATER_WORD.search(name):
                    why["the text is not a water's name"] += 1
                    continue
                if key(name) in spell:                  # a misspelling with a hand alias: its record's name
                    folded[name] += 1
                    name = spell[key(name)]
                if key(name) in held:
                    why["held by the national list"] += 1
                    continue
                cty = county_of(r)
                k = (key(name), cty)                    # one row per name (any spelling of case) and county
                row = rows.setdefault(k, {"name": name, "county": cty, "reports": 0, "sources": [], "permits": [],
                                          "spellings": []})
                row["reports"] += 1
                if name not in row["spellings"]:
                    row["spellings"].append(name)
                if sid not in row["sources"]:
                    row["sources"].append(sid)
                if r.get("npdes_permit") and r["npdes_permit"] not in row["permits"]:
                    row["permits"].append(r["npdes_permit"])
                t = raw.get("city") or ("Portland" if sid == "or-bes-news-rss" else None)
                if t:
                    towns[k][t] += 1
    out_rows = []
    for k, row in sorted(rows.items(), key=lambda kv: (kv[0][0], kv[0][1] or "")):
        row["towns"] = [t for t, _ in towns[k].most_common()]
        # the spelling with a capital on every word, else the first seen
        row["name"] = next((x for x in row["spellings"] if x == x.title() or x.istitle()), row["spellings"][0])
        if len(row["spellings"]) == 1:
            row.pop("spellings")
        out_rows.append(row)
    out = {"about": ("Water names in OR's records that data/receiving-waters-national.json does not hold for OR: DEQ's "
                     "OERS spill archive (2013 to March 2025, the 2,371 sewage reports; Affected_Waterway, once per "
                     "report), Portland Environmental Services' advisories (the waters each names) and OHA's bloom "
                     "advisories (the water's name), read 2026-11-07. One row per name and county, with the towns "
                     "(most reports first), the source ids and the permits. Reports that say the sewage reached no "
                     "water, or name none, are left out (by_reason). Names are kept as the source spells them. Written "
                     "by scripts/or_report_water_names.py."),
           "state": "OR", "waters": len(out_rows), "names": len({r["name"] for r in out_rows}),
           "reports": sum(r["reports"] for r in out_rows), "records_read": dict(read),
           "by_reason": dict(why.most_common()),
           "aliased": {k: v for k, v in sorted(folded.items())},   # read as the name of their hand alias
           "rows": out_rows}
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print(f"{out['waters']} rows, {out['names']} names, {out['reports']} reports -> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
