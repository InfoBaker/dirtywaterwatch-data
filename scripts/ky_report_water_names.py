"""research/ky/receiving-waters-missing.json: the water names Kentucky's records give that
data/receiving-waters-national.json does not hold for KY, for `python -m ingest.waters_from_nhd --names ... --state KY`.

Usage (after pipeline/ingest/echo_sewer_overflow_events.py has written data/build/events, with the HAB Viewer layer's
response saved, by default at data/raw/ky-dow-hab/features.json):
    pipeline/.venv/bin/python -I scripts/ky_report_water_names.py [layer.json]

Four sources:
  - EPA's overflow tables (echo-sewer-overflow): the Kentucky records kept as reaching a water; a name is the record's
    waterbody_text split at semicolons, counted once per report (the form's placeholders 'Unnamed Tributary or Unknown'
    and 'Unnamed' are never names). Reports that say no water was reached are not records and do not count.
  - Louisville MSD's banner (ky-louisville-msd-overflow-advisory): the receiving stream an MSD-02 notice names, from
    the events file when it holds one (MSD-01 advisories sit on the outfalls' own waters).
  - The Division of Water's HAB Viewer (ky-dow-hab-viewer): every point's water in the layer's saved response, not only
    the points under an advisory today (a lake is sampled all season and becomes a record when an advisory is issued).
  - The Division's standing swimming advisories (ky-dow-swimming-advisories): the waters the feed places its records on
    (ingest/ky_dow_swimming_advisories.STRETCHES), each listed advisory counted as a report.
A name is compared with the national list's names and keys, case and punctuation aside. Each row: name, reports,
points (the report's or the HAB point's own, up to five), permits, sources.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVENTS = ROOT / "data" / "build" / "events"
HAB_DEFAULT = ROOT / "data" / "raw" / "ky-dow-hab" / "features.json"
OUT = ROOT / "research" / "ky" / "receiving-waters-missing.json"
PLACEHOLDER = re.compile(r"^\s*(?:unnamed(?:\s+tributary)?(?:\s+or\s+unknown)?|unknown)\s*$", re.I)
# the waters the Division's swimming advisories page names, as the feed places them (review 2026-11-08 P3-4: the
# national list's own spellings, "Clover Fork of the Cumberland River", "Poor Fork of the Cumberland River")
sys.path.insert(0, str(ROOT / "pipeline"))
from ingest.ky_dow_swimming_advisories import STRETCHES  # noqa: E402
SWIM = [(w, st, county, (pt[1], pt[2])) for _, _, w, st, _, county, pt in STRETCHES]


# EPA's NHDPlus reach codes (outfalls-us.json reach_id) for MSD's outfalls off the Ohio River (final audit 2026-11-08)
MSD_REACHES = {"5140101000472": "Beargrass Creek", "5140101000475": "Beargrass Creek",
               "5140101000471": "Beargrass Creek", "5140101000175": "Beargrass Creek",
               "5140101000484": "Mill Creek"}


def compact(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def main(argv: list[str]) -> int:
    hab_path = Path(argv[0]) if argv else HAB_DEFAULT
    nat = json.loads((ROOT / "data" / "receiving-waters-national.json").read_text())["states"]["KY"]["waters"]
    have = {compact(n) for w in nat for n in [w.get("name"), w.get("key"), *(w.get("names_seen") or [])] if n}
    # names a names pass already resolved stay in "resolved" (with their record), never back on the list
    prev = json.loads(OUT.read_text()) if OUT.exists() else {}
    resolved = [r for r in prev.get("resolved") or [] if isinstance(r, dict)]
    have |= {compact(r.get("name")) for r in resolved}
    reasons = {compact(r["name"]): r.get("reason") for r in prev.get("rows") or [] if r.get("reason")}
    reports, permits, sources = Counter(), defaultdict(set), defaultdict(set)
    points: dict[str, list] = defaultdict(list)
    stretches: dict[str, list] = defaultdict(list)
    spelling: dict[str, str] = {}

    counties: dict[str, set] = defaultdict(set)
    outfalls, reach_ids = Counter(), defaultdict(set)

    def add(n0: str, src: str, pt=None, permit=None, report=False, stretch=None, county=None):
        n = " ".join((n0 or "").split())
        if not n or PLACEHOLDER.match(n) or compact(n) in have:
            return
        n = spelling.setdefault(compact(n), n.title() if n.isupper() or n.islower() else n)
        reports[n] += report
        sources[n].add(src)
        if permit:
            permits[n].add(permit)
        if pt and pt not in points[n] and len(points[n]) < 5:
            points[n].append(pt)
        if stretch:
            stretches[n].append(stretch)
        if county:
            counties[n].add(county)

    p = EVENTS / "echo-sewer-overflow.json"
    for r in json.loads(p.read_text()).get("records", []) if p.exists() else []:
        if str(r.get("npdes_permit") or "")[:2] != "KY":
            continue
        for n0 in dict.fromkeys(x.strip() for x in (r.get("waterbody_text") or "").split(";") if x.strip()):
            add(n0, r["source_id"], [r["lat"], r["lon"]] if r.get("lat") is not None else None, r["npdes_permit"], True)
    p = EVENTS / "ky-louisville-msd-overflow-advisory.json"
    for r in json.loads(p.read_text()).get("records", []) if p.exists() else []:
        if (r.get("raw") or {}).get("advisory_code") == "MSD-02" and r.get("waterbody_text"):
            add(r["waterbody_text"], r["source_id"], None, None, True)
    if hab_path.exists():
        doc = json.loads(hab_path.read_text())
        for f in [f for pg in doc.get("pages", [doc]) for f in pg.get("features", [])]:
            a, g = f.get("attributes") or {}, f.get("geometry") or {}
            if a.get("HABNAME"):
                pt = [round(g["y"], 6), round(g["x"], 6)] if g.get("x") is not None else None
                add(a["HABNAME"], "ky-dow-hab-viewer", pt,
                    report=str(a.get("HABSTATUS") or "").lower() in ("warning", "danger"))
    for n, stretch, county, pt in SWIM:
        add(n, "ky-dow-swimming-advisories", list(pt), report=True, stretch=stretch, county=county)
    # MSD's combined sewer outfalls on Beargrass Creek and Mill Creek by EPA's reach index (final audit 2026-11-08
    # P2-1): EPA's text for every one reads "OHIO RIVER", so the creeks were on no list; each row carries the outfall
    # count, EPA's reach codes and the outfalls' points for the NHD pass, and outfall_waters' REACH_FIRST_PERMITS ties
    # the outfalls to the record built from their own reach
    us = json.loads((ROOT / "data" / "outfalls-us.json").read_text())["outfalls"]
    for o in us:
        if o.get("npdes_permit") != "KY0022411" or str(o.get("outfall_status") or "").upper().startswith("CLS"):
            continue
        name = MSD_REACHES.get(str(o.get("reach_id") or ""))
        if name:
            add(name, "ky-dow-cso-sites-layer", [o["lat"], o["lon"]] if o.get("lat") is not None else None,
                "KY0022411", county="Jefferson")
            outfalls[name] += 1
            reach_ids[name].add(str(o["reach_id"]))
    rows = [{"name": n, "reports": reports[n], "permits": sorted(permits[n]), "sources": sorted(sources[n])}
            | ({"points": points[n]} if points.get(n) else {}) | ({"stretches": stretches[n]} if stretches.get(n) else {})
            | ({"counties": sorted(counties[n])} if counties.get(n) else {})
            | ({"outfalls": outfalls[n], "reach_ids": sorted(reach_ids[n])} if outfalls.get(n) else {})
            for n in sorted(set(sources), key=lambda x: (-reports[x], -outfalls[x], x))]
    doc = {"about": ("Water names in Kentucky's records that data/receiving-waters-national.json does not hold for KY: "
                     "EPA's overflow tables (the 2026-11-04 extract read on 2026-11-07; the Kentucky reports kept as "
                     "reaching a water), Louisville MSD's discharge notices, the Division of Water's HAB Viewer (every "
                     "point's lake in the layer read on 2026-11-07) and the Division's standing swimming advisories (the "
                     "waters and stretches the page names), with the number of records giving each. The form's "
                     "placeholders ('Unnamed Tributary or Unknown', 'Unnamed') and reports that say the discharge "
                     "reached no water are left out."),
           "state": "KY", "waters": len(rows), "reports": sum(reports.values()), "rows": rows,
           **({"resolved": resolved} if resolved else {})}
    for r in rows:
        if reasons.get(compact(r["name"])):
            r["reason"] = reasons[compact(r["name"])]
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    print(f"{len(rows)} names, {sum(reports.values())} reports -> {OUT.relative_to(ROOT)}")
    for r in rows:
        print(" ", r["name"], r["reports"], r["sources"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
