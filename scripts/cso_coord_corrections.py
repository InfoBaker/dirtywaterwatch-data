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
   coords_problem). The row's water is then re-tied alone, by ingest.outfall_waters.match_cso_row at the new point,
   and must land on the water the correction expects. Only rows of the regional files ingest.outfall_waters ties
   (FILES) can be corrected here; a national row needs run_state's context and is refused.
2. KIND_OTHER: EPA lists three Massachusetts collection-system co-permittees as combined sewer permits with one
   "outfall" 001 whose text is a reporting note, not a place. Each becomes outfall_kind "other" with kind_note citing
   the parent permit (the rows stay; kind other keeps them off the map and out of the outfall counts and the caution,
   as scripts/ky_outfall_corrections.py does for Kentucky's collection-system permits).
3. NO_POINT: four Michigan rows of terminated permits keep no point and get a no_point_reason that says so (the old
   text said they were read at the operator's plant; neither permit has a plant row, so nothing was read).

Every entry states the row it expects (EPA's outfall text, EPA's point, no point, the permit's status). A row that is
neither as expected nor already corrected is reported and nothing is written (a pointed co-permittee listing would
otherwise lose its rain reading; changed EPA evidence must be looked at, not overwritten). --check verifies every
field the corrections promise.
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
INVENTORY = "EPA's national CSO inventory (ECHO ALL_CSO_DOWNLOADS.csv, fetched 2026-11-01)"

# (permit, outfall): (file, EPA's outfall text, kind_note)
KIND_OTHER = {
    ("MAC010510", "001"): (
        "outfalls-new-england.json", "COLLECTION SYSTEM REPORTS WITH CO-PERMITTEE HOOSAC",
        INVENTORY + " lists permit MAC010510 ('Williamstown Sewer Collection System') with one outfall 001 whose text, "
        "'collection system reports with co-permittee Hoosac', is a reporting note: a sewer collection system that "
        "reports as a co-permittee of the Hoosac Water Quality District's permit MA0100510, which has no combined "
        "sewer outfall in the inventory. Not an outfall at a place: kept off the map and out of the outfall counts and "
        "the rain caution."),
    ("MAC010617", "001"): (
        "outfalls-new-england.json", "COLLECTION SYSTEM REPORTS WITH COPERMITTEE LEOMINSTER",
        INVENTORY + " lists permit MAC010617 ('Lunenberg Sewer Collection System') with one outfall 001 whose text, "
        "'collection system reports with copermittee Leominster', is a reporting note: the Town of Lunenburg is a "
        "co-permittee of the permit issued to Leominster (MA0100617) for operation and maintenance of the collection "
        "system it owns (" + FITCHBURG + ", fact sheet, co-permittees), and Leominster's permit has no combined sewer "
        "outfall in the inventory. Not an outfall at a place: kept off the map and out of the outfall counts and the "
        "rain caution."),
    ("MAC010986", "001"): (
        "outfalls-new-england.json", "CO-PERMITTEE CSOs",
        INVENTORY + " lists permit MAC010986 ('Westminster Department of Public Works') with one outfall 001 whose "
        "text, 'co-permittee CSOs', is a reporting note: MAC010986 is the reporting number the Fitchburg Easterly "
        "permit MA0100986 assigns the Town of Westminster, a co-permittee for Parts I.B (unauthorized discharges), I.C "
        "(operation and maintenance of its sanitary collection system) and I.D only (" + FITCHBURG + ", page 1). The "
        "permit's nine combined sewer overflows are the City of Fitchburg's and are registry rows of MA0100986. Not an "
        "outfall at a place: kept off the map and out of the outfall counts and the rain caution."),
}


def _terminated(permit: str, expired: str) -> str:
    return (f"EPA lists permit {permit} as terminated (ICIS through ECHO's facility report service, read 2026-11-15; "
            f"the permit expired {expired}) and its outfalls are not in EPA's map of active combined sewer outfalls. "
            f"No source found places this outfall: EPA's inventory gives no point, and EGLE, the Oakland County Water "
            f"Resources Commissioner and the Rouge River program were searched on 2026-11-15. No point is used; the row "
            f"drives no rain reading (the permit has no plant row to stand in).")


# (permit, outfall): (file, EPA's outfall text, EPA's receiving-water text, no_point_reason)
NO_POINT = {
    ("MI0037621", "001"): ("outfalls-us.json", "", "ROUGE RIVER", _terminated("MI0037621", "1982-03-31")),
    ("MI0037621", "002"): ("outfalls-us.json", "", "ROUGE RIVER", _terminated("MI0037621", "1982-03-31")),
    ("MI0037621", "003"): ("outfalls-us.json", "", "ROUGE RIVER", _terminated("MI0037621", "1982-03-31")),
    ("MI0051497", "M23"): ("outfalls-us.json", "", "MIDDLE ROUGE RIVER", _terminated("MI0051497", "2001-10-01")),
}

POINT_FIELDS_GONE = ("coords_problem", "echo_lat", "echo_lon", "no_point_reason", "replaced_match")


def load_points(path: Path = CORRECTIONS) -> list[dict]:
    return json.loads(path.read_text())["corrections"]


def _key(o: dict) -> tuple[str, str]:
    return str(o.get("npdes_permit") or ""), str(o.get("outfall") or "")


def _index(docs: dict[str, dict]) -> dict[str, dict[tuple[str, str], list[dict]]]:
    out: dict[str, dict[tuple[str, str], list[dict]]] = {}
    for name, doc in docs.items():
        idx = out.setdefault(name, {})
        for o in doc["outfalls"]:
            idx.setdefault(_key(o), []).append(o)
    return out


def _one(idx, name: str, key: tuple[str, str]) -> tuple[dict | None, str | None]:
    rows = idx.get(name, {}).get(key) or []
    if len(rows) != 1:
        return None, f"{key[0]} {key[1]}: {len(rows)} rows in data/{name}, expected 1"
    return rows[0], None


def _no_point(o: dict) -> bool:
    return o.get("lat") is None and o.get("lon") is None


def _source(c: dict) -> dict:
    return {"name": c["source_name"], "url": c["source_url"], "read_at": c["read_at"], "by": BY}


def point_state(o: dict, c: dict) -> str:
    """'original' (EPA's row as the correction expects it), 'corrected' (already as it says, tie aside), or why
    neither."""
    e, k = c["expect"], f"{c['npdes_permit']} {c['outfall']}"
    if str(o.get("outfall_name") or "") != e["outfall_name"]:
        return f"{k}: EPA's outfall text is now {o.get('outfall_name')!r}, not {e['outfall_name']!r}"
    if (o.get("outfall_kind") or "cso") != "cso":
        return f"{k}: kind {o.get('outfall_kind')!r}, not cso"
    epa = (e["epa_lat"], e["epa_lon"])
    if _no_point(o) and (o.get("echo_lat"), o.get("echo_lon")) == epa and "epa_lat" not in o:
        return "original"
    if ((o.get("lat"), o.get("lon")) == (c["lat"], c["lon"]) and (o.get("epa_lat"), o.get("epa_lon")) == epa
            and o.get("echo_lat") is None and o.get("echo_lon") is None):
        return "corrected"
    return (f"{k}: neither EPA's row as expected (no point, EPA's point {epa} set aside) nor the corrected row: lat/lon "
            f"{o.get('lat')}, {o.get('lon')}, echo {o.get('echo_lat')}, {o.get('echo_lon')}, epa {o.get('epa_lat')}, "
            f"{o.get('epa_lon')}; not changed")


def point_problems(o: dict, c: dict) -> list[str]:
    """Every promised field of a corrected point row that is not as promised (empty when all are)."""
    e, k = c["expect"], f"{c['npdes_permit']} {c['outfall']}"
    want = {"lat": c["lat"], "lon": c["lon"], "coords_from": c["coords_from"], "coords_note": c["coords_note"],
            "coords_source": _source(c), "epa_lat": e["epa_lat"], "epa_lon": e["epa_lon"],
            "epa_reach_id": e["epa_reach_id"], "outfall_name": e["outfall_name"], "water_slug": e["water_slug"]}
    bad = [f"{k}: {f} is {o.get(f)!r}, not {v!r}" for f, v in want.items() if o.get(f) != v]
    if (o.get("outfall_kind") or "cso") != "cso":
        bad.append(f"{k}: kind {o.get('outfall_kind')!r}, not cso")
    if o.get("reach_id") and o.get("reach_id") == e["epa_reach_id"]:
        bad.append(f"{k}: reach_id is EPA's reach for its own point again")
    bad += [f"{k}: {f} present" for f in POINT_FIELDS_GONE if f in o]
    if "geometry" not in str(o.get("match") or "") or o.get("distance_m") is None:
        bad.append(f"{k}: not tied by its point (match {o.get('match')!r}, distance_m {o.get('distance_m')!r})")
    return bad


def write_point(o: dict, c: dict) -> bool:
    """Write the correction's fields into a row point_state accepted (in place). True when the point moved."""
    e = c["expect"]
    moved = _no_point(o)
    if moved:
        o["epa_lat"], o["epa_lon"] = o["echo_lat"], o["echo_lon"]
    if o.get("reach_id") == e["epa_reach_id"]:       # EPA's NHD reach for its own point: evidence of the wrong place
        o["reach_id"] = None
    o["epa_reach_id"] = e["epa_reach_id"]
    for k in POINT_FIELDS_GONE:
        o.pop(k, None)
    o["lat"], o["lon"] = c["lat"], c["lon"]
    o["coords_from"] = c["coords_from"]
    o["coords_note"] = c["coords_note"]
    o["coords_source"] = _source(c)
    return moved


def listing_problems(o: dict, permit: str, outfall: str, text: str, note: str | None) -> list[str]:
    k = f"{permit} {outfall}"
    bad = []
    if str(o.get("outfall_name") or "").upper() != text.upper():
        bad.append(f"{k}: EPA's outfall text is now {o.get('outfall_name')!r}, not {text!r}")
    if not _no_point(o):
        bad.append(f"{k}: the row has a point now ({o.get('lat')}, {o.get('lon')}): it may be an outfall after all")
    if note is not None and (o.get("outfall_kind") != "other" or o.get("kind_note") != note):
        bad.append(f"{k}: not kind other with the table's note")
    return bad


def terminated_problems(o: dict, permit: str, outfall: str, text: str, water: str, reason: str | None) -> list[str]:
    k = f"{permit} {outfall}"
    bad = []
    if str(o.get("outfall_name") or "") != text or str(o.get("receiving_water_echo") or "") != water:
        bad.append(f"{k}: EPA's text is now {o.get('outfall_name')!r} / {o.get('receiving_water_echo')!r}")
    if o.get("permit_status") != "TRM":
        bad.append(f"{k}: permit status {o.get('permit_status')!r}, not TRM")
    if not _no_point(o):
        bad.append(f"{k}: the row has a point now ({o.get('lat')}, {o.get('lon')})")
    if reason is not None and o.get("no_point_reason") != reason:
        bad.append(f"{k}: no_point_reason not the table's")
    return bad


def apply_tables(docs: dict[str, dict], points: list[dict]) -> tuple[list[tuple[str, dict]], list[str]]:
    """Write every table into the loaded files (in place), after checking every row is as expected first. Returns
    the point rows to re-tie (file, row) and the problems; when there is any problem nothing is changed."""
    from ingest import outfall_waters as ow
    idx = _index(docs)
    problems, todo = [], []
    for c in points:
        name = Path(c["registry_file"]).name
        o, why = _one(idx, name, (c["npdes_permit"], c["outfall"]))
        if why:
            problems.append(why)
            continue
        if name not in ow.FILES:
            problems.append(f"{c['npdes_permit']} {c['outfall']}: data/{name} is not a regional file "
                            f"ingest.outfall_waters ties; a national row is not corrected here")
            continue
        state = point_state(o, c)
        if state not in ("original", "corrected"):
            problems.append(state)
            continue
        todo.append(("point", name, o, c))
    for (permit, outfall), (name, text, note) in KIND_OTHER.items():
        o, why = _one(idx, name, (permit, outfall))
        bad = [why] if why else listing_problems(o, permit, outfall, text, None)
        problems += bad
        if not bad:
            todo.append(("other", name, o, note))
    for (permit, outfall), (name, text, water, reason) in NO_POINT.items():
        o, why = _one(idx, name, (permit, outfall))
        bad = [why] if why else terminated_problems(o, permit, outfall, text, water, None)
        problems += bad
        if not bad:
            todo.append(("nopoint", name, o, reason))
    if problems:
        return [], problems
    retie_rows = []
    for kind, name, o, x in todo:
        if kind == "point":
            moved = write_point(o, x)
            if moved or point_problems(o, x):
                retie_rows.append((name, o))
        elif kind == "other":
            o["outfall_kind"], o["kind_note"], o["checked"] = "other", x, "2026-11-15"
        else:
            o["no_point_reason"] = x
    return retie_rows, []


def check(docs: dict[str, dict], points: list[dict]) -> list[str]:
    """What is not as the tables say (empty when every row is)."""
    idx = _index(docs)
    bad = []
    for c in points:
        o, why = _one(idx, Path(c["registry_file"]).name, (c["npdes_permit"], c["outfall"]))
        bad += [why] if why else point_problems(o, c)
    for (permit, outfall), (name, text, note) in KIND_OTHER.items():
        o, why = _one(idx, name, (permit, outfall))
        bad += [why] if why else listing_problems(o, permit, outfall, text, note)
    for (permit, outfall), (name, text, water, reason) in NO_POINT.items():
        o, why = _one(idx, name, (permit, outfall))
        bad += [why] if why else terminated_problems(o, permit, outfall, text, water, reason)
    return bad


def retie(docs: dict[str, dict], rows: list[tuple[str, dict]], offline: bool = False) -> None:
    """Re-tie each corrected row alone at its new point (ingest.outfall_waters.match_cso_row), with the shared-point
    count outfall_waters.run() builds over its regional files (points set aside count as the point ECHO gave)."""
    if not rows:
        return
    from ingest import outfall_waters as ow
    mt = ow.Matcher(offline=offline)
    all_rows = [o for n in ow.FILES for o in (docs[n] if n in docs else json.loads((DATA / n).read_text()))["outfalls"]]
    shared = Counter((o["npdes_permit"], round(o["lat"], 4), round(o["lon"], 4)) for o in all_rows
                     if o.get("lat") is not None and o.get("lon") is not None)
    for o in all_rows:
        if o.get("echo_lat") is not None and o.get("lat") is None:
            shared[(o["npdes_permit"], round(o["echo_lat"], 4), round(o["echo_lon"], 4))] += 1
    for name, o in rows:
        ow.match_cso_row(mt, name, o, shared, [], defaultdict(Counter))


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
        print("ok" if not bad else f"{len(bad)} problem(s)")
        return 1 if bad else 0
    before = {n: dumps(d) for n, d in docs.items()}
    rows, problems = apply_tables(docs, points)
    if problems:
        for p in problems:
            print("not changed:", p)
        print("nothing written")
        return 1
    retie(docs, rows, offline=args.offline)
    bad = check(docs, points)
    if bad:
        for b in bad:
            print("after the corrections:", b)
        print("nothing written")
        return 1
    written = []
    for n, d in docs.items():
        new = dumps(d)
        if new != before[n]:
            tmp = DATA / (n + ".tmp")
            tmp.write_text(new)
            tmp.replace(DATA / n)
            written.append(n)
    print(f"re-tied: {len(rows)}; written: {', '.join(written) or 'nothing'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
