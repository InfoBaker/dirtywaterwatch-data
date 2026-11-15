"""Write research/ia/receiving-waters-missing.json and research/id/receiving-waters-missing.json: the water names
Iowa's and Idaho's records give that data/receiving-waters-national.json does not hold for the state, one row per name
and county.

Usage (after the Iowa and Idaho feeds have written their events files):
    pipeline/.venv/bin/python -I scripts/ia_id_report_water_names.py

Inputs: data/build/events/ia-dnr-focomp-incoming-reports.json (the receiving stream DNR's field offices entered),
ia-dnr-news-releases.json (the waters DNR's releases name, and the other waters a release names), ia-waterloo-sso-notices.json
(Waterloo's notices name no water) and id-deq-cyanohab-risk-table.json (the waters DEQ's bloom table lists, with
the county DEQ gives and the Department of Health and Welfare's point). A name is compared without case or punctuation
with the national list's name, key, names seen and GNIS names for the state. Records naming no water are left out and
counted by reason. Each row keeps its county (the county the record gives), the report count, the open count, up to
five points (0.001 degree), the part of the water a listing names, and the operators.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVENTS = ROOT / "data" / "build" / "events"
NATIONAL = ROOT / "data" / "receiving-waters-national.json"
FEEDS = {"IA": ("ia-dnr-focomp-incoming-reports", "ia-dnr-news-releases", "ia-waterloo-sso-notices"),
         "ID": ("id-deq-cyanohab-risk-table",)}
ABOUT = {
    "IA": ("Water names in Iowa's records that data/receiving-waters-national.json does not hold for IA: the receiving "
           "streams the Department of Natural Resources' field offices entered on the incoming reports read for the "
           "major municipal facilities, and the waters the Department's news releases name; Waterloo's notices name no "
           "water. One row per name and county (the county the record gives), with the number of reports, how many are "
           "open now, and the operators; the reports give no point. Records naming no water are left out (by_reason). "
           "Written by scripts/ia_id_report_water_names.py."),
    "ID": ("Water names in Idaho's records that data/receiving-waters-national.json does not hold for ID: the lakes, "
           "reservoirs and ponds on the Department of Environmental Quality's CyanoHAB Risk Data Table, with the county "
           "the table gives and the Department of Health and Welfare's point for the listing ([lat, lon], 0.001 degree); "
           "a listing of one arm or part of a water keeps its part. Idaho publishes no sewage report, so no sewage "
           "record names a water. Written by scripts/ia_id_report_water_names.py."),
}
MULTIPLE = re.compile(r"^\s*(?:multiple|several|various)\b", re.I)
NOT_A_WATER = re.compile(r"^(?:none|n/?a|varies|unknown|ground|land|storm\s*(?:water|drain|sewer).*|ditch|street)$", re.I)


def key(s: str) -> str:
    """'Tributary to Honey Creek' and 'Honey Creek' are the same name here (the national list keys them so)."""
    s = re.sub(r"^\s*(?:trib(?:utary|\.)?\s+to|tributary of)\s+", "", (s or "").lower())
    s = re.sub(r"\s+tributary$", "", s)
    return re.sub(r"\br\.?$", "river", re.sub(r"[^a-z0-9 ]", "", s)).replace(" ", "")


def held_names(nat: dict, st: str) -> set[str]:
    return {key(n) for w in ((nat.get("states") or {}).get(st) or {}).get("waters") or []
            for n in [w.get("name"), w.get("key"), *(w.get("names_seen") or []), *(w.get("gnis_names") or [])] if n}


def build(st: str, records_by_feed: dict[str, list[dict]], held: set[str]) -> dict:
    rows: dict[tuple, dict] = {}
    left_out: dict[str, int] = defaultdict(int)
    listed = 0
    for sid, records in records_by_feed.items():
        for r in records:
            raw = r.get("raw") or {}
            if r.get("duplicate_of"):
                left_out["the same report as another source's"] += 1
                continue
            text = (r.get("waterbody_text") or "").strip()
            names = [text] + [n.strip() for n in (raw.get("other_waters") or []) if n and str(n).strip()]
            typed = (raw.get("receiving_stream_as_typed") or "").strip()
            if not text:
                if typed and NOT_A_WATER.match(typed):
                    left_out["the report's receiving stream is not a water (None, Varies, unknown)"] += 1
                elif sid.startswith("ia-waterloo"):
                    left_out["Waterloo's notices name a street, not a water"] += 1
                else:
                    left_out["no water named"] += 1
                if len(names) == 1:
                    continue
                names = names[1:]
            for name in names:
                if MULTIPLE.match(name):
                    left_out["the report names no one water (\"multiple, see report\")"] += 1
                    continue
                if key(name) in held:
                    listed += 1
                    continue
                county = raw.get("county") or None
                row = rows.setdefault((name, county), {"name": name, "reports": 0, "county": county, "points": [],
                                                       "parts": [], "operators": [], "sources": {}, "open": 0,
                                                       "as_typed": []})
                row["reports"] += 1
                row["sources"][sid] = row["sources"].get(sid, 0) + 1
                if r.get("status") in ("advisory_active", "ongoing"):
                    row["open"] += 1
                lat, lon = r.get("lat"), r.get("lon")
                if lat is not None and lon is not None:
                    pt = [round(float(lat), 3), round(float(lon), 3)]
                    if pt not in row["points"] and len(row["points"]) < 5:
                        row["points"].append(pt)
                part = raw.get("part")
                if part and part not in row["parts"]:
                    row["parts"].append(part)
                as_typed = raw.get("waterbody_as_listed") or typed or name
                if name == text and as_typed not in row["as_typed"]:
                    row["as_typed"].append(as_typed)
                op = r.get("discharger_name")
                if op and op not in row["operators"]:
                    row["operators"].append(op)
    out = []
    for row in rows.values():
        row["operators"] = row["operators"][:4]
        for k in ("parts", "as_typed", "operators", "points"):
            if not row[k]:
                del row[k]
        out.append(row)
    out.sort(key=lambda r: (-r["reports"], r["name"], r["county"] or ""))
    return {"about": ABOUT[st], "state": st, "waters": len(out), "reports": sum(r["reports"] for r in out),
            "reports_on_listed_waters": listed, "by_reason": dict(sorted(left_out.items())), "rows": out}


def main() -> int:
    nat = json.loads(NATIONAL.read_text())
    for st, feeds in FEEDS.items():
        recs = {sid: json.loads((EVENTS / f"{sid}.json").read_text()).get("records", []) for sid in feeds}
        doc = build(st, recs, held_names(nat, st))
        out = ROOT / "research" / st.lower() / "receiving-waters-missing.json"
        out.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
        print(st, json.dumps({k: v for k, v in doc.items() if k not in ("rows", "about")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
