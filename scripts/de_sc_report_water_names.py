"""The water names in Delaware's and South Carolina's records that data/receiving-waters-national.json does not hold
for the state: research/<st>/receiving-waters-missing.json, one row per name and county, in the names pass's shape
(scripts/ut_report_water_names.py), so the cloud batch builds each name where the reports are.

Inputs: the events files this build writes (data/build/events/): Delaware's de-dnrec-derns-recent-releases (the waters a
release's text names; a release DNREC's form marks to ground only, with no water in its text, is left out) and
de-dnrec-recreational-water (the water each beach lies on); South Carolina's sc-florence-sso-notices and sc-des-hab.
South Carolina's DES overflow list (sc-des-overflow-list, MERGE) is then merged into the file by
scripts/report_names_merge.py: each report judged as the status build judges it, one row per name and county (the list's
county; the list gives no point) with the towns of the operator its permit names (the names pass chooses among the
state's waters of a name by them), the file's other rows and resolved names kept with every field. When Florence's
notices or the HAB layer are not built here, their rows in the file are kept as they are and only the list is merged.
Each row: the name as the records give it, the county (the record's own, else none), the number of records and how
many are open, up to five points ([lat, lon], 0.001 degree), towns, sources. A name the national list holds for the
state (its name, key, names seen or GNIS names) is listed under "resolved" with "a water record already holds the
name" when one is listed there.

Run from the repository root: pipeline/.venv/bin/python -I scripts/de_sc_report_water_names.py DE|SC [--events DIR]
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVENTS = ROOT / "data" / "build" / "events"
SOURCES = {"DE": ["de-dnrec-derns-recent-releases", "de-dnrec-recreational-water"],
           "SC": ["sc-florence-sso-notices", "sc-des-hab"]}
OPEN = {"ongoing", "advisory_active"}
MERGE = {"SC": ["sc-des-overflow-list"]}


def k(n: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (n or "").lower())


def main(argv) -> int:
    global EVENTS
    st = argv[0].upper()
    if "--events" in argv:
        EVENTS = Path(argv[argv.index("--events") + 1])
    if all((EVENTS / f"{sid}.json").exists() for sid in SOURCES[st]):
        legacy(st)
    elif st not in MERGE:
        print(f"{st}: the events files of {', '.join(SOURCES[st])} are not all built; nothing written")
        return 1
    else:
        print(f"{st}: {', '.join(SOURCES[st])} not all built; their rows in the file are kept as they are")
    if st in MERGE:
        return merge_lists(st)
    return 0


def merge_lists(st: str) -> int:
    sys.path.insert(0, str(ROOT / "scripts"))
    import report_names_merge as M
    path = ROOT / "research" / st.lower() / "receiving-waters-missing.json"
    resolver = None
    judged, read = {}, {}
    for sid in MERGE[st]:
        recs, line = M.read_feed(EVENTS, sid)
        read[sid] = line
        if recs is None:
            continue
        resolver = resolver or M.make_resolver(st)
        judged[sid] = M.judge(recs, st, resolver, towns_of=M.operator_towns(st))
    if not judged:
        print(f"{st}: {', '.join(MERGE[st])} not built; nothing merged")
        return 1
    counts = M.merge(path, st, judged, read)
    print(f"{path.relative_to(ROOT)}: merged {', '.join(judged)}: {counts}")
    return 0


def legacy(st: str) -> int:
    nat = json.loads((ROOT / "data" / "receiving-waters-national.json").read_text())
    held = {}
    for w in (nat["states"].get(st) or {}).get("waters", []):
        for n in [w.get("name"), w.get("key"), *(w.get("names_seen") or []), *(w.get("gnis_names") or [])]:
            if n:
                held[k(n)] = w
    rows: dict[tuple, dict] = {}
    left_out = defaultdict(int)
    for sid in SOURCES[st]:
        doc = json.loads((EVENTS / f"{sid}.json").read_text())
        for r in doc["records"]:
            raw = r.get("raw") or {}
            if raw.get("reached_water") is False:
                left_out["the report says it reached no water"] += 1
                continue
            names = [n.strip() for n in (r.get("waterbody_text") or "").split(";") if n.strip()]
            if not names:
                left_out["names no water"] += 1
                continue
            if sid == "de-dnrec-recreational-water" and not raw.get("water_basis") and not raw.get("county"):
                left_out["a beach whose water this build does not name"] += 1
                continue
            for n in names:
                key = (n, raw.get("county"))
                row = rows.setdefault(key, {"name": n, "county": raw.get("county"), "reports": 0, "open": 0,
                                            "points": [], "towns": [], "sources": {}})
                row["reports"] += 1
                row["open"] += r.get("status") in OPEN
                if r.get("lat") is not None and len(row["points"]) < 5:
                    pt = [round(r["lat"], 3), round(r["lon"], 3)]
                    if pt not in row["points"]:
                        row["points"].append(pt)
                t = raw.get("town")
                if t and t not in row["towns"]:
                    row["towns"].append(t)
                row["sources"][sid] = row["sources"].get(sid, 0) + 1
    missing, resolved = [], []
    for row in sorted(rows.values(), key=lambda x: (-x["reports"], x["name"], x["county"] or "")):
        w = held.get(k(row["name"]))
        if w:
            resolved.append({**row, "how": "the national list holds the name", "national_key": w.get("key") or w.get("name")})
        else:
            missing.append({**row, "reason": f"no water of that name in {st} on the national list"})
    out = {"about": (f"Water names in {st}'s records that data/receiving-waters-national.json does not hold for {st}, one "
                     "row per name and county with the number of records, how many are open now, up to five points "
                     "([lat, lon], 0.001 degree), towns and sources, for the names pass. Records naming no water and "
                     "releases DNREC's form marks to ground only are left out (by_reason). Written by "
                     "scripts/de_sc_report_water_names.py."),
           "state": st, "waters": len(missing), "reports": sum(r["reports"] for r in missing),
           "by_reason": dict(left_out), "rows": missing, "resolved": resolved}
    p = ROOT / "research" / st.lower() / "receiving-waters-missing.json"
    p.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print(f"{p.relative_to(ROOT)}: {len(missing)} names missing ({out['reports']} records), {len(resolved)} held")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
