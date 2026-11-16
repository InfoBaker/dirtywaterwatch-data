"""Colorado's, Montana's or Wyoming's water names that data/receiving-waters-national.json lacks for the state ->
research/<st>/receiving-waters-missing.json

Usage (after the state's ingesters have written their events files):
    pipeline/.venv/bin/python -I scripts/mountain_report_water_names.py CO|MT|WY [--dry-run]

Reads the waters the state's records name (waterbody_text, "; " between names; a lake's qualifier the source adds, kept
in raw.place, is not part of the name); a name the national list holds for the state (its name, key, the names seen
or its GNIS names, compared without case or punctuation) is resolved, any other is a row with the number of records
naming it, how many are open now, the county the record gives (raw.county), up to five of its points ([lat, lon], 0.001
degree) and its sources. A row per name and county, so the names pass builds each name where the records are. Records
naming no water are counted in by_reason. Rows sorted by records, then name.

Wyoming's DEQ spill list (wy-deq-spill-list, MERGE) is then merged into the file by scripts/report_names_merge.py: each
sewage report judged as the status build judges it (a report the list marks as not reaching water names none), one row
per name and county, a point only where the record keeps one (public sewer works), the file's other rows and resolved
names kept with every field. When the bulletins are not built here, their rows in the file are kept as they are.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NATIONAL = ROOT / "data" / "receiving-waters-national.json"
SOURCES = {"CO": ("co-cdphe-toxic-algae", "co-official-notices"),
           "MT": ("mt-deq-hab-map",),
           "WY": ("wy-deq-hcb-bulletins",)}
NAMES = {"CO": "Colorado", "MT": "Montana", "WY": "Wyoming"}
OPEN = {"advisory_active", "ongoing"}
MERGE = {"WY": ("wy-deq-spill-list",)}
EVENTS = ROOT / "data" / "build" / "events"


def k(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def build(st: str) -> dict:
    nat = json.loads(NATIONAL.read_text())["states"].get(st) or {}
    have = {k(n) for w in nat.get("waters") or []
            for n in [w.get("name"), w.get("key"), *(w.get("names_seen") or []), *(w.get("gnis_names") or [])] if n}
    rows: dict[tuple[str, str], dict] = {}
    reasons, resolved = Counter(), Counter()
    for sid in SOURCES[st]:
        f = ROOT / "data" / "build" / "events" / f"{sid}.json"
        for r in (json.loads(f.read_text()).get("records") if f.exists() else []):
            names = [n.strip() for n in (r.get("waterbody_text") or "").split(";") if n.strip()]
            if not names:
                reasons["no water named"] += 1
                continue
            raw = r.get("raw") or {}
            county = raw.get("county") or ""
            county = f"{county.title()} County" if county and not county.lower().endswith("county") else county
            for n in names:
                if k(n) in have:
                    resolved[n] += 1
                    continue
                row = rows.setdefault((n, county), {"name": n, "reports": 0, "open": 0, "county": county or None,
                                                    "points": [], "sources": defaultdict(int)})
                row["reports"] += 1
                row["open"] += int(r.get("status") in OPEN and not r.get("ended_at"))
                row["sources"][sid] += 1
                if r.get("lat") is not None and len(row["points"]) < 5:
                    pt = [round(float(r["lat"]), 3), round(float(r["lon"]), 3)]
                    if pt not in row["points"]:
                        row["points"].append(pt)
    for (n, c), row in list(rows.items()):     # a record with no county joins the one county row of its name
        if c:
            continue
        others = [rr for (n2, c2), rr in rows.items() if n2 == n and c2]
        if len(others) == 1:
            o = others[0]
            o["reports"] += row["reports"]
            o["open"] += row["open"]
            for s_, v in row["sources"].items():
                o["sources"][s_] += v
            del rows[(n, c)]
    out_rows = sorted(rows.values(), key=lambda x: (-x["reports"], x["name"]))
    for x in out_rows:
        x["sources"] = dict(x["sources"])
    return {"about": (f"Water names in {NAMES[st]}'s records that data/receiving-waters-national.json does not hold for "
                      f"{st}: the waters the state's advisory and notice records name, one row per name and county, "
                      "with the number of records, how many are open, the county and up to five points where the "
                      "source gives them. Records naming no water are counted in by_reason. EPA's outfall registry "
                      "gives every plant outfall its receiving water separately. Written by "
                      "scripts/mountain_report_water_names.py."),
            "state": st, "waters": len(out_rows), "reports": sum(x["reports"] for x in out_rows),
            "by_reason": dict(reasons), "resolved_names": len(resolved), "resolved_reports": sum(resolved.values()),
            "rows": out_rows}


def main(argv) -> int:
    st = argv[0].upper()
    path = ROOT / "research" / st.lower() / "receiving-waters-missing.json"
    if all((EVENTS / f"{sid}.json").exists() for sid in SOURCES[st]) or st not in MERGE:
        doc = build(st)
        print(json.dumps({k_: v for k_, v in doc.items() if k_ not in ("rows", "about")}), [x["name"] for x in doc["rows"]])
        if "--dry-run" not in argv:
            path.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    else:
        print(f"{st}: {', '.join(SOURCES[st])} not built; their rows in the file are kept as they are")
    if st in MERGE and "--dry-run" not in argv:
        sys.path.insert(0, str(ROOT / "scripts"))
        import report_names_merge as M
        judged, read, resolver = {}, {}, None
        for sid in MERGE[st]:
            recs, read[sid] = M.read_feed(EVENTS, sid)
            if recs is not None:
                resolver = resolver or M.make_resolver(st)
                judged[sid] = M.judge(recs, st, resolver)
        if judged:
            print(f"{path.relative_to(ROOT)}: merged {', '.join(judged)}: {M.merge(path, st, judged, read)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
