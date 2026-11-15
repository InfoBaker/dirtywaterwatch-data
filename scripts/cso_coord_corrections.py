"""Cited corrections to open combined sewer outfall rows that EPA's inventory leaves without a usable point (2026-11-15).

Usage: pipeline/.venv/bin/python -I scripts/cso_coord_corrections.py [--check] [--offline]
  --check:   change nothing; exit 1 when a row is not as the tables say (rerun this script after a ties run or an
             inventory re-read that rewrote a row).
  --offline: re-tie a corrected row's water from cached responses only.

On 2026-11-15, 26 open CSO rows in the live states had no point (lat or lon null), so the rain caution never read
them (ingest.rainfall.cso_outfalls). research/cso-missing-coords/report.md has the sources searched for each; this
script writes what those sources support, in place in the row's own registry file. In place, because the CT and MD
rows live in regional files: a second file of the same rank would tie with them (common.outfall_file_rank), and the
loader would keep whichever file name sorts first.

1. POINTS, from research/cso-missing-coords/corrections.json (only rows a public source places with coordinates):
   lat/lon become the source's, at the source's precision (registry outfalls are not rounded); coords_from names the
   kind of source; coords_note and coords_source cite it; EPA's set-aside point moves from echo_lat/echo_lon to
   epa_lat/epa_lon, and EPA's NHD reach for that point (reach_id, which the matchers read as evidence) to
   epa_reach_id; coords_problem, no_point_reason and replaced_match (whose reason was EPA's point) are removed, so a
   later ingest.outfall_waters run cannot restore EPA's point (it restores echo_lat/echo_lon on a row that still has
   coords_problem). The row's water is then re-tied alone, by ingest.outfall_waters.match_cso_row at the new point.
   A row that has a point of its own from another source is never overwritten: it is reported instead.
2. KIND_OTHER: EPA lists three Massachusetts collection-system co-permittees as combined sewer permits with one
   "outfall" 001 whose text is a reporting note, not a place. Each becomes outfall_kind "other" with kind_note citing
   the parent permit (the rows stay; kind other keeps them off the map and out of the outfall counts and the caution,
   as scripts/ky_outfall_corrections.py does for Kentucky's collection-system permits).
3. NO_POINT: four Michigan rows of terminated permits keep no point and get a no_point_reason that says so (the old
   text said they were read at the operator's plant; neither permit has a plant row, so nothing was read).

Every table entry names the row's file and EPA's own outfall text; a row whose text differs is reported, not changed.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CORRECTIONS = ROOT / "research" / "cso-missing-coords" / "corrections.json"
sys.path.insert(0, str(ROOT / "pipeline"))

BY = "scripts/cso_coord_corrections.py (2026-11-15)"
FITCHBURG = ("EPA Region 1, draft NPDES permit MA0100986 (Fitchburg Easterly WWTF) and fact sheet, December 2023, "
             "https://www.epa.gov/system/files/documents/2023-12/draftma0100986permit2023.pdf, read 2026-11-15")

# (permit, outfall): (file, EPA's outfall text, kind_note)
KIND_OTHER = {
    ("MAC010510", "001"): (
        "outfalls-new-england.json", "COLLECTION SYSTEM REPORTS WITH CO-PERMITTEE HOOSAC",
        "EPA lists this as outfall 001 of MAC010510 with the text 'collection system reports with co-permittee "
        "Hoosac': the reporting number of the Town of Williamstown's sewer collection system, a co-permittee under the "
        "Hoosac Water Quality District's permit MA0100510, which has no combined sewer outfall in EPA's inventory. A "
        "reporting listing, not an outfall at a place: kept off the map and out of the outfall counts and the rain "
        "caution."),
    ("MAC010617", "001"): (
        "outfalls-new-england.json", "COLLECTION SYSTEM REPORTS WITH COPERMITTEE LEOMINSTER",
        "EPA lists this as outfall 001 of MAC010617 with the text 'collection system reports with copermittee "
        "Leominster': the reporting number of the Town of Lunenburg's sewer collection system, a co-permittee of the "
        "permit issued to Leominster (MA0100617) for operation and maintenance of the system it owns (" + FITCHBURG +
        ", fact sheet, co-permittees); Leominster's permit has no combined sewer outfall in EPA's inventory. A "
        "reporting listing, not an outfall at a place: kept off the map and out of the outfall counts and the rain "
        "caution."),
    ("MAC010986", "001"): (
        "outfalls-new-england.json", "CO-PERMITTEE CSOs",
        "EPA lists this as outfall 001 of MAC010986 with the text 'co-permittee CSOs': the reporting number the "
        "permit assigns the Town of Westminster, a co-permittee of Fitchburg Easterly's permit MA0100986 for Parts I.B "
        "(unauthorized discharges), I.C (operation and maintenance of its sanitary collection system) and I.D only ("
        + FITCHBURG + ", page 1). The permit's nine combined sewer overflows are the City of Fitchburg's and are "
        "registry rows of MA0100986. A reporting listing, not an outfall at a place: kept off the map and out of the "
        "outfall counts and the rain caution."),
}


def _terminated(permit: str, expired: str) -> str:
    return (f"EPA lists permit {permit} as terminated (ICIS through ECHO's facility report service, read 2026-11-15; "
            f"the permit expired {expired}) and its outfalls are not in EPA's map of active combined sewer outfalls. "
            f"No source found places this outfall: EPA's inventory gives no point, and EGLE, the Oakland County Water "
            f"Resources Commissioner and the Rouge River program were searched on 2026-11-15. No point is used; the row "
            f"drives no rain reading (the permit has no plant row to stand in).")


# (permit, outfall): (file, no_point_reason)
NO_POINT = {
    ("MI0037621", "001"): ("outfalls-us.json", _terminated("MI0037621", "1982-03-31")),
    ("MI0037621", "002"): ("outfalls-us.json", _terminated("MI0037621", "1982-03-31")),
    ("MI0037621", "003"): ("outfalls-us.json", _terminated("MI0037621", "1982-03-31")),
    ("MI0051497", "M23"): ("outfalls-us.json", _terminated("MI0051497", "2001-10-01")),
}

POINT_FIELDS_GONE = ("coords_problem", "echo_lat", "echo_lon", "no_point_reason", "replaced_match")


def load_points(path: Path = CORRECTIONS) -> list[dict]:
    return json.loads(path.read_text())["corrections"]


def _key(o: dict) -> tuple[str, str]:
    return str(o.get("npdes_permit") or ""), str(o.get("outfall") or "")


def _index(doc: dict) -> dict[tuple[str, str], dict]:
    return {_key(o): o for o in doc["outfalls"]}


def point_ok(o: dict, c: dict) -> bool:
    """The row is as the correction says."""
    return (o.get("lat") == c["lat"] and o.get("lon") == c["lon"] and o.get("coords_from") == c["coords_from"]
            and (o.get("coords_source") or {}).get("url") == c["source_url"]
            and not any(k in o for k in POINT_FIELDS_GONE)
            and not (o.get("epa_reach_id") and o.get("reach_id") == o["epa_reach_id"]))


def apply_point(o: dict, c: dict) -> str | None:
    """Write one correction into its row (in place). Returns why it was refused, else None."""
    if point_ok(o, c):
        return None
    if (o.get("outfall_kind") or "cso") != "cso":
        return f"{c['npdes_permit']} {c['outfall']}: kind {o.get('outfall_kind')}, not cso"
    own = (o.get("coords_source") or {}).get("url")
    if o.get("lat") is not None and own != c["source_url"]:
        return (f"{c['npdes_permit']} {c['outfall']}: the row has a point of its own now ({o.get('lat')}, "
                f"{o.get('lon')}, coords_from {o.get('coords_from')!r}); not overwritten")
    if o.get("echo_lat") is not None:
        o["epa_lat"], o["epa_lon"] = o["echo_lat"], o["echo_lon"]
        if o.get("reach_id"):           # EPA's NHD reach for its own (set-aside) point: evidence of the wrong place
            o["epa_reach_id"], o["reach_id"] = o["reach_id"], None
    for k in POINT_FIELDS_GONE:
        o.pop(k, None)
    o["lat"], o["lon"] = c["lat"], c["lon"]
    o["coords_from"] = c["coords_from"]
    o["coords_note"] = c["coords_note"]
    o["coords_source"] = {"name": c["source_name"], "url": c["source_url"], "read_at": c["read_at"], "by": BY}
    return None


def apply_tables(docs: dict[str, dict], points: list[dict]) -> tuple[list[tuple[str, dict]], list[str]]:
    """Write every table into the loaded files (in place). Returns the corrected point rows (file, row) and the
    problems (a row not found, or not as the table expects)."""
    idx = {name: _index(doc) for name, doc in docs.items()}
    moved, problems = [], []
    for c in points:
        name = Path(c["registry_file"]).name
        o = idx.get(name, {}).get((c["npdes_permit"], c["outfall"]))
        if o is None:
            problems.append(f"{c['npdes_permit']} {c['outfall']}: no row in data/{name}")
            continue
        was_ok = point_ok(o, c)
        why = apply_point(o, c)
        if why:
            problems.append(why)
        elif not was_ok:
            moved.append((name, o))
    for (permit, outfall), (name, text, note) in KIND_OTHER.items():
        o = idx.get(name, {}).get((permit, outfall))
        if o is None or str(o.get("outfall_name") or "").upper() != text.upper():
            problems.append(f"{permit} {outfall}: no row in data/{name} with EPA's text {text!r}")
            continue
        o["outfall_kind"] = "other"
        o["kind_note"] = note
        o["checked"] = "2026-11-15"
    for (permit, outfall), (name, reason) in NO_POINT.items():
        o = idx.get(name, {}).get((permit, outfall))
        if o is None or o.get("lat") is not None:
            problems.append(f"{permit} {outfall}: no pointless row in data/{name}")
            continue
        o["no_point_reason"] = reason
    return moved, problems


def check(docs: dict[str, dict], points: list[dict]) -> list[str]:
    """What is not as the tables say (empty when every row is)."""
    idx = {name: _index(doc) for name, doc in docs.items()}
    bad = []
    for c in points:
        o = idx.get(Path(c["registry_file"]).name, {}).get((c["npdes_permit"], c["outfall"]))
        if o is None or not point_ok(o, c):
            bad.append(f"{c['npdes_permit']} {c['outfall']}: point not as corrections.json says")
    for (permit, outfall), (name, _text, note) in KIND_OTHER.items():
        o = idx.get(name, {}).get((permit, outfall))
        if o is None or o.get("outfall_kind") != "other" or o.get("kind_note") != note:
            bad.append(f"{permit} {outfall}: not kind other with the table's note")
    for (permit, outfall), (name, reason) in NO_POINT.items():
        o = idx.get(name, {}).get((permit, outfall))
        if o is None or o.get("no_point_reason") != reason:
            bad.append(f"{permit} {outfall}: no_point_reason not the table's")
    return bad


def retie(docs: dict[str, dict], moved: list[tuple[str, dict]], offline: bool = False) -> None:
    """Re-tie each corrected row alone at its new point (ingest.outfall_waters.match_cso_row; the rest of its file is
    left as it is). The shared-point count is the file's own, as outfall_waters.run() builds it."""
    if not moved:
        return
    from ingest import outfall_waters as ow
    mt = ow.Matcher(offline=offline)
    for name, o in moved:
        rows = docs[name]["outfalls"]
        shared = Counter((r["npdes_permit"], round(r["lat"], 4), round(r["lon"], 4)) for r in rows
                         if r.get("lat") is not None and r.get("lon") is not None)
        ow.match_cso_row(mt, name, o, shared, [], defaultdict(Counter),
                         state_build=name not in ow.FILES)


def files_needed(points: list[dict]) -> list[str]:
    names = {Path(c["registry_file"]).name for c in points}
    names |= {v[0] for v in KIND_OTHER.values()} | {v[0] for v in NO_POINT.values()}
    return sorted(names)


def dumps(doc: dict) -> str:
    return json.dumps(doc, indent=1)          # the registry files' own format (ingest.outfall_waters writes them so)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="change nothing; exit 1 when a row is not as the tables say")
    ap.add_argument("--offline", action="store_true", help="re-tie from cached responses only")
    args = ap.parse_args(argv)
    points = load_points()
    docs = {n: json.loads((DATA / n).read_text()) for n in files_needed(points)}
    if args.check:
        bad = check(docs, points)
        for b in bad:
            print("not as the table says:", b)
        print("ok" if not bad else f"{len(bad)} row(s) not as the tables say")
        return 1 if bad else 0
    before = {n: dumps(d) for n, d in docs.items()}
    moved, problems = apply_tables(docs, points)
    retie(docs, moved, offline=args.offline)
    for p in problems:
        print("not changed:", p)
    written = []
    for n, d in docs.items():
        new = dumps(d)
        if new != before[n]:
            tmp = DATA / (n + ".tmp")
            tmp.write_text(new)
            tmp.replace(DATA / n)
            written.append(n)
    print(f"points moved: {len(moved)}; written: {', '.join(written) or 'nothing'}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
