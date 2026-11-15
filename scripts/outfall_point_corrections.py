"""Cited point corrections to registry outfall rows that EPA's data gets wrong or leaves without a point, kept through a
rebuild of the files (2026-11-15).

Usage: pipeline/.venv/bin/python -I scripts/outfall_point_corrections.py [--check] [--offline]
  --check:   change nothing; exit 1 when a row is not as the tables say.
  --offline: re-tie a moved row's water from cached responses only.

The registry files these rows live in are rebuilt from EPA's and the states' data: data/outfalls-us.json by
scripts/match_outfalls.py --national (the state batch's registry step), data/outfalls-ky.json by
scripts/ky_outfall_corrections.py and data/outfalls-in.json by scripts/build_in_outfalls.py. Each of those builders calls
apply_rows() on its rows before it writes, so a rebuild writes the corrections again; this script applies them to the
files on disk, re-ties a moved row's water (ingest.outfall_waters.match_cso_row, as the state batch's ties step does),
and --check verifies every promised field. pipeline/tests/test_outfall_point_corrections.py runs the check on the files
as committed. The pattern is scripts/cso_coord_corrections.py's: EPA's own value stays on the row (epa_lat/epa_lon,
epa_reach_id), the row cites its source (coords_note, coords_source), and the source's precision is kept (registry
outfalls are not rounded; the Indiana file's own three-decimal rule aside, 2 below).

1. SIGN: EPA gives the longitude with its sign flipped (a point in Asia for an outfall in Ohio or Kentucky). The
   corrected point is EPA's with the sign of the longitude reversed. A rebuild meets EPA's row in one of two shapes:
   lat/lon as EPA gives them, or (scripts/match_outfalls.py's state-outline check, ingest.outfall_waters' guard) lat/lon
   null with EPA's point set aside in echo_lat/echo_lon and coords_problem saying why; both are corrected, when EPA's
   reach for the point is the one recorded (kept in epa_reach_id, which --check requires).
2. FEATURE: an Indiana outfall IDEM's CSO outfall layer lists without a point, and EPA's ICIS gives a point for the same
   permit feature (EPA's discharge-point file, data/outfalls-plants-us.json): that point, cited, at three decimals
   (scripts/build_in_outfalls.py rounds every point of data/outfalls-in.json so, EPA's included: Indiana review
   2026-11-14 P1-5; coords_source gives EPA's full value). The point is used only while EPA's row still holds it: one
   row for the permit and feature in data/outfalls-plants-us.json, at the recorded full-precision point, coords_from
   permitted_feature; otherwise a builder stops and --check fails (review 2026-11-15).
3. NO_POINT: an Indiana outfall no source places: no point, and no_point_reason says what was searched.

Every entry states the row it expects. A row that is neither as expected nor already corrected is reported and left as
it is (changed EPA evidence must be looked at, not overwritten); the script writes nothing then.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

BY = "scripts/outfall_point_corrections.py (2026-11-15)"
READ = "2026-11-15"
CSO_LAYER = ("EPA's map of active combined sewer outfalls (https://services.arcgis.com/cJ9YHowT8TU7DUyn/arcgis/rest/"
             "services/Combined_Sewer_Overflows/FeatureServer/0)")
OUTFALL_LAYER = ("ECHO's NPDES outfall layer (https://services.arcgis.com/cJ9YHowT8TU7DUyn/arcgis/rest/services/"
                 "oeca__echo__npdes_facilities_outfalls/FeatureServer/0)")
IDEM_LAYER = ("IDEM's CSO outfall layer (https://services5.arcgis.com/w1CjlfkUGYWS5MJd/arcgis/rest/services/"
              "CSO_Locations_Map_WFL1/FeatureServer/0)")
DISCHARGE_POINTS = ("EPA ECHO ICIS-NPDES discharge points (npdes_outfalls_layer.zip, NPDES_OUTFALLS_LAYER.csv, file "
                    "dated 2026-11-01; the row of data/outfalls-plants-us.json for the same permit and feature)")

# (file, permit, outfall): EPA's point, the corrected point, coords_note, the source read, EPA's reach for its point
# (kept in epa_reach_id; None when EPA gives none)
SIGN = {
    ("outfalls-us.json", "OH0020974", "014"): (
        (41.574444, 83.994722), (41.574444, -83.994722),
        "EPA gives this outfall's longitude as +83.994722, a point in Asia; the Village of Delta, Ohio, and the "
        "permit's other outfalls (001, 004, 006, 010) lie at 84.00 to 84.01 W, and the facility at 41.568056, "
        "-84.001667. The point used is EPA's with the longitude's sign reversed, 0.9 km from the facility; EPA's value "
        "is kept in epa_lat/epa_lon, and EPA's reach for it (epa_reach_id, in the St. Joseph River basin, not the "
        "Maumee's) is not used",
        {"name": "EPA ECHO: " + CSO_LAYER + " and " + OUTFALL_LAYER + ", permit OH0020974 feature 014: pf_lat 41.574444, "
                 "pf_lon 83.994722",
         "url": "https://echo.epa.gov/detailed-facility-report?fid=110006322247", "read_at": READ},
        "4050001002139"),
    ("outfalls-ky.json", "KYP000081", "001"): (
        (38.644, 83.834), (38.644, -83.834),
        "EPA gives this feature's longitude as +83.834, a point in Asia; the Western Mason County Sanitation District "
        "is in Mason County, Kentucky, and ECHO places the permit's facility at 38.64569, -83.76106. The point used is "
        "EPA's with the longitude's sign reversed, 6.3 km west of that facility point, in western Mason County; EPA's "
        "value is kept in epa_lat/epa_lon",
        {"name": "EPA ECHO ICIS-NPDES discharge points (NPDES_PERM_FEATURE_COORDS, read 2026-11-03), permit KYP000081 "
                 "feature 001: 38.644, 83.834; ECHO detailed facility report service, facility 38.64569, -83.76106 "
                 "(not in " + OUTFALL_LAYER + ": a state-issued permit)",
         "url": "https://echo.epa.gov/detailed-facility-report?fid=110040608955", "read_at": READ},
        None),
}

# the evidence a FEATURE point rests on: EPA's row for the same permit and feature in this file, at EPA's precision
EVIDENCE = DATA / "outfalls-plants-us.json"

# (file, permit, outfall): the point, coords_from, coords_note, the source read, EPA's own point and coords_from as
# EVIDENCE must still hold them (checked before the point is used, by the builders and --check alike)
FEATURE = {
    ("outfalls-in.json", "IN0023183", "005"): (
        (39.726, -86.19), "EPA permitted feature (IDEM's layer gives no point)",
        "IDEM's layer lists outfall 005 ('CSO', Active, Treated CSO) without a point, and EPA's CSO inventory does not "
        "list it; EPA's ICIS gives the permit's feature 005 its own point (EPA's discharge-point file, the Belmont "
        "plant's outfall to the West Fork White River), used here at three decimals, as every point of this file is",
        {"name": IDEM_LAYER + ", OBJECTID 383; " + DISCHARGE_POINTS + ": 39.726167, -86.190389",
         "url": "https://echo.epa.gov/detailed-facility-report?fid=110011829129", "read_at": READ},
        ((39.726167, -86.190389), "permitted_feature")),
    ("outfalls-in.json", "IN0032191", "001"): (
        (41.078, -85.098), "EPA permitted feature (IDEM's layer gives no point)",
        "IDEM's layer lists outfall 001 ('CSO - EPA requested 5/2005', Active, Untreated CSO) without a point, and EPA's "
        "CSO inventory does not list it; EPA's ICIS gives the permit's feature 001 its own point, and that feature "
        "carries the limit set 'CSO - EPA requested 05/2005' beside the plant's main outfall (EPA's discharge-point "
        "file; " + OUTFALL_LAYER + ": the same point), used here at three decimals, as every point of this file is",
        {"name": IDEM_LAYER + ", OBJECTID 238; " + DISCHARGE_POINTS + ": 41.0775, -85.097778; " + OUTFALL_LAYER,
         "url": "https://echo.epa.gov/detailed-facility-report?fid=110009390756", "read_at": READ},
        ((41.0775, -85.097778), "permitted_feature")),
}


def _searched(idem: str, cso: str, outfalls: str) -> str:
    return (f"EPA's national CSO inventory gives only the treatment plant's point for this outfall, and no source "
            f"found places it (read {READ}): {IDEM_LAYER} lists {idem}; {CSO_LAYER} lists {cso}; {OUTFALL_LAYER} lists "
            f"{outfalls}. No point is used.")


# (file, permit, outfall): EPA's outfall text, no_point_reason
NO_POINT = {
    ("outfalls-in.json", "IN0020001", "102"): ("", _searched(
        "five Ridgeville points (002, 003, 004 twice, 101), none 102", "004 and 101 for this permit",
        "features 001 to 004 and 101")),
    ("outfalls-in.json", "IN0020133", "002"): ("", _searched(
        "one Greensburg point (006, inactive)", "007 for this permit", "features 001, 006 and 007")),
    ("outfalls-in.json", "IN0020133", "005"): ("", _searched(
        "one Greensburg point (006, inactive)", "007 for this permit", "features 001, 006 and 007")),
    ("outfalls-in.json", "IN0032468", "022"): ("CSO - Greenbush St bending weir (emergency overflow)", _searched(
        "thirteen Lafayette points, none 022", "ten outfalls for this permit, not 022",
        "seventeen features, not 022 (ECHO's effluent service lists feature 022's monitoring, without a location)")),
}

GONE = ("coords_problem", "echo_lat", "echo_lon", "echo_coords_from", "no_point_reason", "point_note")


def _key(o: dict) -> tuple[str, str]:
    return str(o.get("npdes_permit") or ""), str(o.get("outfall") or "")


def _no_point(o: dict) -> bool:
    return o.get("lat") is None and o.get("lon") is None


def _pt(o: dict, a: str = "lat", b: str = "lon") -> tuple:
    return o.get(a), o.get(b)


def entries(name: str):
    """Every table entry for registry file `name`: (table, (permit, outfall), value)."""
    for table, t in (("sign", SIGN), ("feature", FEATURE), ("nopoint", NO_POINT)):
        for (f, p, n), v in t.items():
            if f == name:
                yield table, (p, n), v


def files() -> list[str]:
    return sorted({k[0] for t in (SIGN, FEATURE, NO_POINT) for k in t})


def state(table: str, o: dict, v) -> str:
    """'original' (the row as EPA's or the state's data gives it), 'corrected', or why neither."""
    k = f"{o.get('npdes_permit')} {o.get('outfall')}"
    if table == "sign":
        epa, fix = v[0], v[1]
        if _pt(o) == fix and _pt(o, "epa_lat", "epa_lon") == epa:
            return "corrected"
        if "epa_lat" not in o and (_pt(o) == epa or (_no_point(o) and _pt(o, "echo_lat", "echo_lon") == epa)):
            if o.get("reach_id") != v[4]:
                return (f"{k}: EPA's reach for its point is now {o.get('reach_id')!r}, not {v[4]!r}: look at it; not "
                        f"changed")
            return "original"
        return (f"{k}: neither EPA's row as expected (EPA's point {epa}) nor the corrected row: lat/lon {_pt(o)}, echo "
                f"{_pt(o, 'echo_lat', 'echo_lon')}, epa {_pt(o, 'epa_lat', 'epa_lon')}; not changed")
    if table == "feature":
        if _pt(o) == v[0]:
            return "corrected"
        if _no_point(o) and o.get("echo_lat") is None:
            return "original"
        return f"{k}: has a point now ({o.get('lat')}, {o.get('lon')}), not the table's {v[0]}; not changed"
    if str(o.get("outfall_name") or "") != v[0]:
        return f"{k}: the outfall text is now {o.get('outfall_name')!r}, not {v[0]!r}; not changed"
    if not _no_point(o):
        return f"{k}: the row has a point now ({o.get('lat')}, {o.get('lon')}): look at its source; not changed"
    return "corrected" if o.get("no_point_reason") == v[1] else "original"


def write(table: str, o: dict, v) -> bool:
    """Write an entry into a row state() accepted (in place). True when the row's point moved."""
    if table == "nopoint":
        o["no_point_reason"] = v[1]
        return False
    moved = _pt(o) != (v[0] if table == "feature" else v[1])
    for f in GONE:
        o.pop(f, None)
    if table == "sign":
        (o["epa_lat"], o["epa_lon"]), (o["lat"], o["lon"]) = v[0], v[1]
        if v[4] is not None:                     # EPA's reach for its own wrong point: evidence of the wrong place
            o["epa_reach_id"] = v[4]
            if o.get("reach_id") == v[4]:
                o["reach_id"] = None
        o["coords_from"] = "permitted_feature"
        o["coords_note"], src = v[2], v[3]
    else:
        o["lat"], o["lon"] = v[0]
        o["coords_from"], o["coords_note"], src = v[1], v[2], v[3]
    o["coords_source"] = {**src, "by": BY}
    return moved


def problems(table: str, o: dict, v) -> list[str]:
    """What a corrected row lacks of the table's promise (empty when nothing)."""
    k = f"{o.get('npdes_permit')} {o.get('outfall')}"
    st = state(table, o, v)
    if st != "corrected":
        return [st if st != "original" else f"{k}: not corrected"]
    if table == "nopoint":
        return []
    want = dict(zip(("lat", "lon"), v[1] if table == "sign" else v[0]))
    if table == "sign":
        want.update(epa_lat=v[0][0], epa_lon=v[0][1], coords_from="permitted_feature", coords_note=v[2],
                    coords_source={**v[3], "by": BY})
    else:
        want.update(coords_from=v[1], coords_note=v[2], coords_source={**v[3], "by": BY})
    bad = [f"{k}: {f} is {o.get(f)!r}, not {w!r}" for f, w in want.items() if o.get(f) != w]
    bad += [f"{k}: {f} present" for f in GONE if f in o]
    if table == "sign" and v[4] is not None:
        if o.get("epa_reach_id") != v[4]:
            bad.append(f"{k}: epa_reach_id is {o.get('epa_reach_id')!r}, not EPA's {v[4]!r}")
        if o.get("reach_id") == v[4]:
            bad.append(f"{k}: reach_id is EPA's reach for its wrong point again")
    return bad


def load_evidence() -> list[dict] | None:
    try:
        return json.loads(EVIDENCE.read_text())["outfalls"]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def evidence_problems(name: str, evidence: list[dict] | None = None) -> list[str]:
    """Each FEATURE point of data/<name> against EPA's row it rests on (EVIDENCE, or the rows given): exactly one row
    for the permit and feature, at EPA's full-precision point and with EPA's coords_from. Empty when all hold."""
    feats = [(key, v) for table, key, v in entries(name) if table == "feature"]
    if not feats:
        return []
    rows = load_evidence() if evidence is None else evidence
    if rows is None:
        return [f"{p} {n}: the evidence file data/{EVIDENCE.name} cannot be read" for (p, n), _ in feats]
    bad = []
    for (p, n), v in feats:
        (epa, cf) = v[4]
        got = [r for r in rows if (str(r.get("npdes_permit") or ""), str(r.get("outfall") or "")) == (p, n)]
        if len(got) != 1:
            bad.append(f"{p} {n}: the evidence, EPA's row in data/{EVIDENCE.name}, is {len(got)} rows, expected 1")
        elif _pt(got[0]) != epa or got[0].get("coords_from") != cf:
            bad.append(f"{p} {n}: the evidence changed: EPA's row in data/{EVIDENCE.name} has {_pt(got[0])} "
                       f"({got[0].get('coords_from')!r}), not {epa} ({cf!r})")
    return bad


def _has_feature_rows(name: str, rows: list[dict]) -> bool:
    keys = {key for table, key, _ in entries(name) if table == "feature"}
    return bool(keys) and any(_key(o) in keys for o in rows)


def apply_rows(name: str, rows: list[dict], strict: bool = False,
               evidence: list[dict] | None = None) -> tuple[list[dict], list[str]]:
    """Write the tables' entries for registry file `name` into its rows (in place). Returns the rows whose point moved
    and the problems (a row not as expected, or with strict, a row missing). A builder calls this before it writes: a
    row of another state or not in this build is simply absent, and a row not as expected is left as it is and named.
    A FEATURE point is used only while its evidence holds (evidence_problems); otherwise none is, and the problems
    say why."""
    idx: dict[tuple[str, str], list[dict]] = {}
    for o in rows:
        idx.setdefault(_key(o), []).append(o)
    moved, todo = [], []
    bad = evidence_problems(name, evidence) if strict or _has_feature_rows(name, rows) else []
    for table, key, v in entries(name):
        if table == "feature" and bad:          # bad holds only the evidence problems here: no FEATURE point is used
            continue
        got = idx.get(key) or []
        if len(got) != 1:
            if got or strict:
                bad.append(f"{key[0]} {key[1]}: {len(got)} rows in data/{name}, expected 1")
            continue
        st = state(table, got[0], v)
        if st in ("original", "corrected"):
            todo.append((table, got[0], v))
        else:
            bad.append(st)
    if strict and bad:
        return [], bad
    for table, o, v in todo:
        if write(table, o, v):
            moved.append(o)
    return moved, bad


def for_builder(name: str, rows: list[dict], evidence: list[dict] | None = None) -> list[str]:
    """A builder's call (scripts/match_outfalls.py, scripts/ky_outfall_corrections.py, scripts/build_in_outfalls.py):
    the tables' entries for data/<name> written into its rows before it writes the file. When a FEATURE point's
    evidence is missing, duplicated or changed, the build stops here (SystemExit, nothing applied): the point must be
    looked at again. A row not as expected is named on stderr and left as it is (the data test and --check then
    fail); returns those problems."""
    if _has_feature_rows(name, rows):
        ev = evidence_problems(name, evidence)
        if ev:
            raise SystemExit("outfall_point_corrections: refused, the evidence a point rests on is not as recorded: "
                             + "; ".join(ev))
    _, bad = apply_rows(name, rows, evidence=evidence)
    for b in bad:
        print(f"outfall_point_corrections: not changed: {b}", file=sys.stderr)
    return bad


def check(docs: dict[str, dict], evidence: list[dict] | None = None) -> list[str]:
    bad = []
    for name in files():
        bad += evidence_problems(name, evidence)
        idx: dict[tuple[str, str], list[dict]] = {}
        for o in docs[name]["outfalls"]:
            idx.setdefault(_key(o), []).append(o)
        for table, key, v in entries(name):
            got = idx.get(key) or []
            bad += ([f"{key[0]} {key[1]}: {len(got)} rows in data/{name}, expected 1"] if len(got) != 1
                    else problems(table, got[0], v))
    return bad


def retie(name: str, doc: dict, rows: list[dict], offline: bool = False) -> None:
    """Re-tie each moved row alone at its new point, as the state batch's ties step would (ingest.outfall_waters
    match_cso_row in a state build). A kind-other row (no outfall to a water) is not tied."""
    rows = [o for o in rows if (o.get("outfall_kind") or "cso") == "cso"]
    if not rows:
        return
    sys.path.insert(0, str(ROOT / "pipeline"))
    from ingest import outfall_waters as ow
    for st in sorted({o["state"] for o in rows}):
        mt = ow.Matcher(offline=offline, states=[st])
        mine = [o for o in doc["outfalls"] if o.get("state") == st]
        shared = Counter((o["npdes_permit"], round(o["lat"], 4), round(o["lon"], 4)) for o in mine
                         if o.get("lat") is not None and o.get("lon") is not None)
        for o in rows:
            if o["state"] == st:
                ow.match_cso_row(mt, name, o, shared, [], defaultdict(Counter), state_build=True)


def dumps(doc: dict, before: str) -> str:
    """The file's own format: indent 1, as ingest.outfall_waters writes the registry files (ASCII, no final newline);
    a file that had non-ASCII text or a final newline (its builder's own format) keeps them."""
    ascii_only = all(ord(c) < 128 for c in before)
    return json.dumps(doc, indent=1, ensure_ascii=ascii_only) + ("\n" if before.endswith("\n") else "")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="change nothing; exit 1 when a row is not as the tables say")
    ap.add_argument("--offline", action="store_true", help="re-tie from cached responses only")
    args = ap.parse_args(argv)
    docs = {n: json.loads((DATA / n).read_text()) for n in files()}
    if args.check:
        bad = check(docs)
        for b in bad:
            print("not as the table says:", b)
        print("ok" if not bad else f"{len(bad)} problem(s)")
        return 1 if bad else 0
    before = {n: (DATA / n).read_text() for n in docs}
    work = copy.deepcopy(docs)
    moved, problems_ = {}, []
    for n, d in work.items():
        moved[n], bad = apply_rows(n, d["outfalls"], strict=True)
        problems_ += bad
    if problems_:
        for p in problems_:
            print("not changed:", p)
        print("nothing written")
        return 1
    for n, d in work.items():
        retie(n, d, moved[n], offline=args.offline)
    bad = check(work)
    if bad:
        for b in bad:
            print("after the corrections:", b)
        print("nothing written")
        return 1
    written = []
    for n, d in work.items():
        new = dumps(d, before[n])
        if new != before[n]:
            tmp = DATA / (n + ".tmp")
            tmp.write_text(new)
            tmp.replace(DATA / n)
            written.append(n)
    print(f"moved: {sum(len(v) for v in moved.values())}; written: {', '.join(written) or 'nothing'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
