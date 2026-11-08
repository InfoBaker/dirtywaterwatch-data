"""Tennessee's receiving-water names that data/receiving-waters-national.json does not hold for TN ->
research/tn/receiving-waters-missing.json (the list the cloud water batch builds records from).

Names read:
  - TDEC's HAB advisory layer (data/build/events/tn-tdec-hab-advisory-status.json, the records the feed wrote): the
    water each bloom report names, with up to five of its points. A name that is not a water's own ("pond", "Unnamed
    (...)", a description of a place) is left out and counted.
  - TDEC's posted-streams list (the PDF behind its Bacteriological and Fishing Advisories page, Rev. August 2026, read
    2026-11-07): the 25 stream segments (the McCrory Creek tributary is listed under McCrory Creek here) under a standing water-contact advisory, with their counties (POSTED below,
    read by hand from the PDF; the list is watched in the notice register, not read into records yet).
TDEC's Events Report names no receiving water, so it adds none.
Names are compared without case, spaces or punctuation against each TN water's name, names seen and GNIS names, and
by county (review 2026-11-08 P2-5): a name is held only when a water of that name has a point (an outfall on it) in
the record's county; Tennessee has many streams of one name (Beaver, Cypress and Richland creeks), so a name whose
waters all lie in other counties is listed as missing, with its county. A HAB record's county is the one its point
lies in (or the county kept when TDEC marks the water a private residence). RENAME gives a water's own name where the
report's words name another water's (Lake Watauga in Nashville's Centennial Park, not Watauga Lake in East
Tennessee).

Run from the repository root: pipeline/.venv/bin/python -I scripts/tn_report_water_names.py
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NATIONAL = ROOT / "data" / "receiving-waters-national.json"
HAB = ROOT / "data" / "build" / "events" / "tn-tdec-hab-advisory-status.json"
OUT = ROOT / "research" / "tn" / "receiving-waters-missing.json"
NOT_A_NAME = re.compile(r"^\s*(pond\b.*|lake|creek|river|unknown|unnamed\b.*|.*\bnear\b.*|.*\[.*removed\].*)\s*$", re.I)
# (stream, counties) from TDEC's posted-streams list, bacteriological section
POSTED = [
    ("Beaver Creek", ["Sullivan"]), ("Coal Creek", ["Anderson"]), ("East Fork Poplar Creek", ["Roane", "Anderson"]),
    ("First Creek", ["Knox"]), ("Second Creek", ["Knox"]), ("Goose Creek", ["Knox"]), ("Sinking Creek", ["Washington"]),
    ("Third Creek", ["Knox"]), ("East Fork Third Creek", ["Knox"]), ("Turkey Creek", ["Hamblen"]),
    ("Dudley Creek", ["Sevier"]), ("Citico Creek", ["Hamilton"]), ("Chattanooga Creek", ["Hamilton"]),
    ("Stringers Branch", ["Hamilton"]), ("Little Duck River", ["Coffee"]), ("Browns Creek", ["Davidson"]),
    ("Cumberland River", ["Davidson"]), ("Dry Creek", ["Davidson"]), ("Gibson Creek", ["Davidson"]),
    ("McCrory Creek", ["Davidson"]), ("Richland Creek", ["Davidson"]), ("Trace Creek", ["Clay"]),
    ("Wilson Branch", ["Clay"]), ("Cypress Creek", ["Shelby"]),
]


RENAME = {("watauga lake", "Davidson County"): "Lake Watauga (Centennial Park)"}


def key(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def main() -> int:
    sys.path.insert(0, str(ROOT / "pipeline"))
    from ingest import tn_tdec_posted_streams as PS
    from ingest.tn_transforms import point_county
    nat = json.loads(NATIONAL.read_text())["states"].get("TN") or {}
    held: dict[str, set] = defaultdict(set)            # name key -> counties of the waters of that name
    for w in nat.get("waters") or []:
        counties = {point_county(p[0], p[1]) for p in w.get("points") or []} - {None}
        for n in [w.get("name"), *(w.get("names_seen") or []), *(w.get("gnis_names") or [])]:
            if n:
                held[key(n)] |= counties
    rows: dict[str, dict] = {}
    left_out = defaultdict(int)
    resolved = defaultdict(int)

    def is_held(name: str, counties: list[str]) -> bool:
        k = key(name)
        return k in held and (not counties or bool(held[k] & set(counties)))

    hab = json.loads(HAB.read_text()) if HAB.exists() else {"records": []}
    for r in hab.get("records") or []:
        name = re.sub(r"\s+", " ", (r.get("waterbody_text") or "").strip())
        if not name or NOT_A_NAME.match(name):
            # a description of a place may point at a home: counted, never quoted
            left_out[name if re.fullmatch(r"(?i)pond|lake|creek|river|unknown", name) else
                     "(a description, not a water's name)" if name else "(none)"] += 1
            continue
        county = (r.get("raw") or {}).get("county")
        name = RENAME.get((name.lower(), county), name)
        if is_held(name, [county] if county else []):
            resolved[name] += 1
            continue
        row = rows.setdefault(key(name) + "|" + (county or ""), {"name": name, "reports": 0,
                                                                 "sources": ["tn-tdec-hab-advisory-status"],
                                                                 "counties": [county] if county else [], "points": []})
        row["reports"] += 1
        if r.get("lat") is not None and len(row["points"]) < 5:
            row["points"].append([r["lat"], r["lon"]])
    for name, counties in POSTED:
        cs = [f"{c} County" for c in counties]
        if is_held(name, cs):
            resolved[name] += 1
            continue
        row = rows.setdefault(key(name) + "|" + cs[0], {"name": name, "reports": 0, "sources": [], "counties": cs,
                                                        "points": []})
        row["reports"] += 1
        row["sources"] = sorted(set(row["sources"]) | {"tn-tdec-bacteriological-advisories"})
        row["counties"] = sorted(set(row["counties"]) | set(cs))
        # the stream's GNIS mouth (or the posting's bridge) as the place the names pass chooses the NHD water by,
        # and the GNIS id (final audit 2026-11-08 P2-2: "the reports give no place to choose one")
        for c in counties:
            m = PS.MOUTHS.get((name, c))
            if m:
                row.setdefault("gnis_ids", [])
                if str(m[0]) not in row["gnis_ids"]:
                    row["gnis_ids"].append(str(m[0]))
                if [m[1], m[2]] not in row["points"]:
                    row["points"].append([m[1], m[2]])
            b = PS.BRIDGES.get((name, c))
            if b and [b[1], b[2]] not in row["points"]:
                row["points"].append([b[1], b[2]])
    out = sorted(rows.values(), key=lambda r: (-r["reports"], r["name"]))
    for r in out:
        if r.get("counties"):
            r["county"] = r["counties"][0]     # the names pass reads one county per row (COUNTY_FIELD_STATES)
        if not r["points"]:
            r.pop("points")
        if not r.get("counties"):
            r.pop("counties", None)
    doc = {
        "about": ("Receiving-water names in Tennessee's records that data/receiving-waters-national.json does not hold for "
                  "TN: the waters TDEC's HAB advisory layer names (the records read on 2026-11-07, with up to five of "
                  "their points; rounded to 0.001 degree) and the 25 stream segments of TDEC's posted-streams list under a "
                  "standing water-contact advisory (Rev. August 2026, 25 segments, with their counties). Spellings that differ only in "
                  "case, spaces or punctuation are counted together. TDEC's Events Report names no receiving water. Names "
                  "that are not a water's own ('pond', 'Unnamed (...)', a description of a place) are left out and "
                  "counted in left_out."),
        "state": "TN",
        "waters": len(out),
        "reports": sum(r["reports"] for r in out),
        "rows": out,
        "resolved": [{"name": n, "reports": c, "how": "the national list holds a water of that name in the same county"}
                     for n, c in sorted(resolved.items())],
        "left_out": [{"text": n, "reports": c} for n, c in sorted(left_out.items())],
    }
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(out)} names, {len(resolved)} held, {sum(left_out.values())} left out")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
