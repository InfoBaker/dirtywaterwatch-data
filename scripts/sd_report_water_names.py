"""research/sd/receiving-waters-missing.json: the receiving-water names South Dakota reports give that
data/receiving-waters-national.json does not hold for SD, for `python -m ingest.waters_from_nhd --names ... --state SD`.

Usage (after the South Dakota feeds have written data/build/events): pipeline/.venv/bin/python -I scripts/sd_report_water_names.py

Reads EPA's overflow tables (SD permits: the receiving-waters child table, free text, as the eRule module keeps it in
waterbody_text, several waters joined by semicolons) and DANR's bloom advisories (the lake named on each line). A name is
counted once per report and compared with the national list's names, keys and the names seen there, case and
punctuation aside (as for Illinois). Reports that say no water was reached are not records and do not count. Each row:
name, reports, permits, sources, and up to five of the reports' points (EPA's reports give the event's own point; the
bloom list gives none, so its rows carry the county instead).

Names are normalised as Illinois's were (review 2026-11-07 P3-5; the text as typed stays in as_typed): case put in order
('gold run creek' -> 'Gold Run Creek'), a 'via ...' tail and a ' / ...' second part cut ('Scatterwood via Drainage
ditch' -> 'Scatterwood'; 'Spearfish Creek / Rubble Site Cell' -> 'Spearfish Creek', the cell being the plant's),
'unname' read as 'unnamed', and a tributary written one way ('tributary to mud creek' -> 'Unnamed tributary of Mud
Creek'). A text that names no water ('Unnamed') is listed under left_out with the reason. Every bloom advisory lake is
listed with its county whether or not the national list holds the name (review P2-5: a same-named lake in another
county is not the one under advisory).
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVENTS = ROOT / "data" / "build" / "events"
FEEDS = ["echo-sewer-overflow", "sd-danr-hab-advisories"]
OUT = ROOT / "research" / "sd" / "receiving-waters-missing.json"


def compact(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


SMALL = {"of", "to", "the", "and", "at", "in"}


def norm(name: str) -> str | None:
    """The name as the water batch should look for it, or None when it names no water."""
    t = re.sub(r"\s+", " ", name or "").strip()
    t = re.sub(r"\s+via\s+.*$", "", t, flags=re.I)
    t = re.split(r"\s+/\s+", t)[0]
    t = re.sub(r"\bunname\b", "unnamed", t, flags=re.I)
    m = re.match(r"^(?:unnamed\s+)?trib(?:utary)?\.?\s+(?:to|of)\s+(?:the\s+)?(.+)$", t, re.I)
    if m:
        t = "unnamed tributary of " + m.group(1)
    if re.fullmatch(r"(?i)unnamed|unknown|none", t):
        return None
    words = t.split(" ")
    t = " ".join(w if (w[:1].isupper() and not t.islower()) else (w if i and w.lower() in SMALL else w.capitalize())
                 for i, w in enumerate(w.lower() if t.islower() else w for w in words))
    t = t[:1].upper() + t[1:]
    return re.sub(r"^Unnamed [Tt]ributary [Oo]f ", "Unnamed tributary of ", t)


def main() -> int:
    nat = json.loads((ROOT / "data" / "receiving-waters-national.json").read_text())["states"]["SD"]["waters"]
    have = {compact(n) for w in nat for n in [w.get("name"), w.get("key"), *(w.get("names_seen") or [])] if n}
    reports, permits, sources = Counter(), defaultdict(set), defaultdict(set)
    typed, left_out = defaultdict(set), Counter()
    points, counties = defaultdict(list), defaultdict(set)
    dated = {}
    for f in FEEDS:
        p = EVENTS / f"{f}.json"
        if not p.exists():
            raise SystemExit(f"{p.relative_to(ROOT)} is missing: run the feed first")
        doc = json.loads(p.read_text())
        dated[f] = doc.get("meta", {}).get("extract_date") or doc.get("fetched_at", "")[:10]
        for r in doc.get("records", []):
            if f == "echo-sewer-overflow" and not str(r.get("npdes_permit") or "").startswith("SD"):
                continue
            bloom = f == "sd-danr-hab-advisories"
            for raw_n in dict.fromkeys(x.strip() for x in (r.get("waterbody_text") or "").split(";") if x.strip()):
                n = norm(raw_n)
                if n is None:
                    left_out[raw_n] += 1
                    continue
                if (compact(n) in have or compact(raw_n) in have) and not bloom:
                    continue
                typed[n].add(raw_n)
                reports[n] += 1
                if r.get("npdes_permit"):
                    permits[n].add(r["npdes_permit"])
                sources[n].add(r["source_id"])
                if r.get("lat") is not None and len(points[n]) < 5 and [r["lat"], r["lon"]] not in points[n]:
                    points[n].append([r["lat"], r["lon"]])
                if (r.get("raw") or {}).get("county"):
                    counties[n].add(r["raw"]["county"])
    rows = [{"name": n, "reports": c, "permits": sorted(permits[n]), "sources": sorted(sources[n])}
            | ({"points": points[n]} if points.get(n) else {})
            | ({"counties": sorted(counties[n])} if counties.get(n) else {})
            | {"as_typed": sorted(typed[n])}
            | ({"in_national_list": True} if compact(n) in have else {})
            for n, c in sorted(reports.items(), key=lambda x: (-x[1], x[0]))]
    doc = {"about": ("Receiving-water names in SD's reports (EPA's overflow tables for South Dakota permits, the "
                     f"extract of {dated.get('echo-sewer-overflow')}, and DANR's harmful algal bloom advisories, read "
                     f"{dated.get('sd-danr-hab-advisories')}) that data/receiving-waters-national.json does not hold for "
                     "SD, by name as typed, with the number of reports giving each. Reports that say the discharge "
                     "reached no water are left out."),
           "state": "SD", "waters": len(rows), "reports": sum(reports.values()), "rows": rows,
           "left_out": [{"name": n, "reports": c, "reason": "names no water"} for n, c in sorted(left_out.items())]}
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    print(f"{len(rows)} names, {sum(reports.values())} reports -> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
