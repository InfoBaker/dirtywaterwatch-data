"""Cited point corrections a registry rebuild writes again (scripts/outfall_point_corrections.py, 2026-11-15): two
sign-flipped longitudes from EPA (Delta, Ohio OH0020974 014; Western Mason County, Kentucky KYP000081 001), two Indiana
outfalls IDEM lists without a point that EPA's ICIS places (IN0023183 005, IN0032191 001), and four Indiana outfalls no
source places, with the reason. Data tests on the files as committed, the transformation from the rows a rebuild
writes, and the three builders' hooks; no network.
Run from pipeline/: python -m pytest tests/test_outfall_point_corrections.py -q
"""
from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import common  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
OH, KY = ("OH0020974", "014"), ("KYP000081", "001")
BELMONT, FORT_WAYNE = ("IN0023183", "005"), ("IN0032191", "001")
NO_POINT = [("IN0020001", "102"), ("IN0020133", "002"), ("IN0020133", "005"), ("IN0032468", "022")]
FILE = {OH: "outfalls-us.json", KY: "outfalls-ky.json", BELMONT: "outfalls-in.json", FORT_WAYNE: "outfalls-in.json",
        **{k: "outfalls-in.json" for k in NO_POINT}}
EPA = {OH: (41.574444, 83.994722), KY: (38.644, 83.834)}
FIXED = {OH: (41.574444, -83.994722), KY: (38.644, -83.834), BELMONT: (39.726, -86.19), FORT_WAYNE: (41.078, -85.098)}
# EPA's discharge-point file's own values for the two Indiana features (data/outfalls-plants-us.json)
ICIS = {BELMONT: (39.726167, -86.190389), FORT_WAYNE: (41.0775, -85.097778)}


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture(scope="module")
def mod():
    return _load("outfall_point_corrections")


@pytest.fixture(scope="module")
def committed(mod):
    return {n: json.loads((DATA / n).read_text()) for n in mod.files()}


def _row(docs, key):
    rows = [o for o in docs[FILE[key]]["outfalls"] if (o.get("npdes_permit"), o.get("outfall")) == key]
    assert len(rows) == 1, key
    return rows[0]


def _strip(o: dict) -> dict:
    o = dict(o)
    for k in ("epa_lat", "epa_lon", "epa_reach_id", "coords_note", "coords_source"):
        o.pop(k, None)
    return o


def _as_epa_gives_it(o: dict, key, set_aside: bool) -> dict:
    """The row as a rebuild writes it from EPA's data: lat/lon EPA's, or (scripts/match_outfalls.py's state-outline
    check, the plants build) EPA's point set aside in echo_lat/echo_lon with coords_problem."""
    o = _strip(o)
    if key == OH:
        o["reach_id"] = "4050001002139"                         # EPA's reach for its own wrong point
    if set_aside:
        o.update(lat=None, lon=None, echo_lat=EPA[key][0], echo_lon=EPA[key][1], coords_from=None,
                 echo_coords_from="permitted_feature",
                 coords_problem=f"EPA's point ({EPA[key][0]}, {EPA[key][1]}) lies more than about 2 km outside the state")
    else:
        o.update(lat=EPA[key][0], lon=EPA[key][1])
    return o


def test_the_committed_files_are_as_the_tables_say(mod, committed):
    assert mod.check(committed) == []
    assert mod.main(["--check"]) == 0


@pytest.mark.parametrize("key", [OH, KY])
def test_a_sign_flipped_longitude_is_corrected_and_epas_value_kept(committed, key):
    o = _row(committed, key)
    assert (o["lat"], o["lon"]) == FIXED[key] and (o["epa_lat"], o["epa_lon"]) == EPA[key]
    assert o["coords_from"] == "permitted_feature" and "sign reversed" in o["coords_note"]
    assert o["coords_source"]["url"].startswith("https://echo.epa.gov/") and o["coords_source"]["read_at"] == "2026-11-15"
    for f in ("coords_problem", "echo_lat", "echo_lon", "echo_coords_from"):
        assert f not in o


def test_delta_014_lies_among_the_permits_other_outfalls_and_epas_wrong_reach_is_set_aside(committed):
    o = _row(committed, OH)
    others = [r for r in committed["outfalls-us.json"]["outfalls"] if r["npdes_permit"] == OH[0] and r["outfall"] != "014"
              and r.get("lat") is not None]
    assert others and all(abs(r["lon"] - o["lon"]) < 0.05 and abs(r["lat"] - o["lat"]) < 0.05 for r in others)
    assert o["epa_reach_id"] == "4050001002139" and not o.get("reach_id")


@pytest.mark.parametrize("key", [BELMONT, FORT_WAYNE])
def test_an_indiana_outfall_idem_lists_without_a_point_has_epas_point_for_the_same_feature(committed, key):
    o = _row(committed, key)
    # EPA's point for the same permit feature, at three decimals as every point of data/outfalls-in.json is
    # (scripts/build_in_outfalls.py, Indiana review 2026-11-14 P1-5); the citation gives EPA's full value
    assert (o["lat"], o["lon"]) == FIXED[key] == (round(ICIS[key][0], 3), round(ICIS[key][1], 3))
    plant = next(r for r in json.loads((DATA / "outfalls-plants-us.json").read_text())["outfalls"]
                 if (r.get("npdes_permit"), r.get("outfall")) == key)
    assert (plant["lat"], plant["lon"]) == ICIS[key] and plant["coords_from"] == "permitted_feature"
    assert f"{ICIS[key][0]}, {ICIS[key][1]}" in o["coords_source"]["name"]
    assert o["coords_from"] == "EPA permitted feature (IDEM's layer gives no point)" and "point_note" not in o
    assert "OBJECTID" in o["coords_source"]["name"] and o["coords_source"]["by"].startswith("scripts/outfall_point")


@pytest.mark.parametrize("key", NO_POINT)
def test_an_indiana_outfall_no_source_places_says_what_was_searched(committed, key):
    o = _row(committed, key)
    assert o["lat"] is None and o["lon"] is None
    r = o["no_point_reason"]
    assert "IDEM's CSO outfall layer" in r and "EPA's map of active combined sewer outfalls" in r
    assert "NPDES outfall layer" in r and "No point is used" in r


def test_no_open_indiana_combined_sewer_outfall_is_without_a_point_and_a_reason():
    rows = [o for o in common.load_outfall_registry(provisional=False) if o.get("state") == "IN"
            and o["outfall_kind"] == "cso" and not str(o.get("outfall_status") or "").upper().startswith("CLS")]
    assert rows
    assert [(o["npdes_permit"], o["outfall"]) for o in rows if o.get("lat") is None
            and not o.get("no_point_reason") and not o.get("coords_problem")] == []


@pytest.mark.parametrize("set_aside", [False, True])
def test_a_rebuilt_row_from_epas_data_is_corrected_again(mod, committed, set_aside):
    for key in (OH, KY):
        rows = [_as_epa_gives_it(_row(committed, key), key, set_aside)]
        assert mod.problems("sign", rows[0], mod.SIGN[(FILE[key], *key)])
        moved, bad = mod.apply_rows(FILE[key], rows)
        assert bad == [] and moved == rows
        assert mod.problems("sign", rows[0], mod.SIGN[(FILE[key], *key)]) == []
        assert (rows[0]["lat"], rows[0]["lon"]) == FIXED[key] and (rows[0]["epa_lat"], rows[0]["epa_lon"]) == EPA[key]


def test_the_indiana_rows_as_the_builder_writes_them_are_corrected_again(mod, committed):
    rows = []
    for key in (BELMONT, FORT_WAYNE):
        o = _strip(_row(committed, key))
        o.update(lat=None, lon=None, coords_from=None)
        rows.append(o)
    for key in NO_POINT:
        o = dict(_row(committed, key))
        o.pop("no_point_reason")
        rows.append(o)
    docs = {"outfalls-in.json": {"outfalls": rows}}
    moved, bad = mod.apply_rows("outfalls-in.json", rows)
    assert bad == [] and [(o["npdes_permit"], o["outfall"]) for o in moved] == [BELMONT, FORT_WAYNE]
    for key in (BELMONT, FORT_WAYNE):
        assert (_row(docs, key)["lat"], _row(docs, key)["lon"]) == FIXED[key]
    for key in NO_POINT:
        assert _row(docs, key)["no_point_reason"] == mod.NO_POINT[("outfalls-in.json", *key)][1]


def test_a_rerun_on_the_committed_files_changes_nothing(mod, committed):
    docs = copy.deepcopy(committed)
    for n, d in docs.items():
        moved, bad = mod.apply_rows(n, d["outfalls"], strict=True)
        assert moved == [] and bad == []
    assert docs == committed


@pytest.mark.parametrize("key,change", [
    (OH, {"lat": 41.6, "lon": 83.99}),                       # EPA's point changed: look at it, do not overwrite
    (KY, {"lon": -83.9, "epa_lat": None}),
    (BELMONT, {"lat": 39.7, "lon": -86.2}),                  # a point from somewhere else now
    (("IN0032468", "022"), {"lat": 40.4, "lon": -86.9}),     # a row that gained a point
    (("IN0020001", "102"), {"outfall_name": "Main Street"}),
])
def test_changed_evidence_is_reported_and_the_row_left_as_it_is(mod, committed, key, change):
    o = {**_row(committed, key), **change}
    for f in ("epa_lat",) if key == KY else ():
        o.pop(f)
    before = dict(o)
    moved, bad = mod.apply_rows(FILE[key], [o])
    assert moved == [] and any(f"{key[0]} {key[1]}" in b for b in bad) and o == before


def test_check_catches_a_row_put_back_and_epas_reach_restored(mod, committed):
    docs = copy.deepcopy(committed)
    o = _row(docs, OH)
    o["reach_id"] = o["epa_reach_id"]
    _row(docs, KY)["coords_problem"] = "restored by hand"
    _row(docs, ("IN0020133", "005")).pop("no_point_reason")
    bad = mod.check(docs)
    assert any("OH0020974 014" in b and "reach" in b for b in bad)
    assert any("KYP000081 001" in b and "coords_problem" in b for b in bad)
    assert any("IN0020133 005" in b for b in bad)


def test_a_failed_run_writes_nothing(mod, committed, tmp_path, monkeypatch):
    docs = copy.deepcopy(committed)
    _row(docs, OH).update(lat=41.6, lon=83.99, epa_lat=None)
    for n, d in docs.items():
        (tmp_path / n).write_text(json.dumps(d, indent=1))
    before = {p.name: p.read_text() for p in tmp_path.iterdir()}
    monkeypatch.setattr(mod, "DATA", tmp_path)
    assert mod.main([]) == 1 and mod.main(["--check"]) == 1
    assert {p.name: p.read_text() for p in tmp_path.iterdir()} == before


def test_the_kentucky_builder_writes_the_correction_again(committed, tmp_path, monkeypatch):
    ky = _load("ky_outfall_corrections")
    plants = {"outfalls": [_as_epa_gives_it({**_row(committed, KY), "outfall_kind": "plant"}, KY, set_aside=True)]}
    for k in ("kind_note", "checked", "supersedes"):
        plants["outfalls"][0].pop(k, None)
    (tmp_path / "outfalls-plants-us.json").write_text(json.dumps(plants))
    monkeypatch.setattr(ky, "PLANTS", tmp_path / "outfalls-plants-us.json")
    monkeypatch.setattr(ky, "OUT", tmp_path / "outfalls-ky.json")
    assert ky.main() == 0
    o = json.loads((tmp_path / "outfalls-ky.json").read_text())["outfalls"][0]
    assert (o["lat"], o["lon"]) == FIXED[KY] and (o["epa_lat"], o["epa_lon"]) == EPA[KY]
    assert o["outfall_kind"] == "other" and "coords_problem" not in o


def test_the_indiana_builder_writes_the_corrections_again(committed):
    bi = _load("build_in_outfalls")
    feats = []
    for oid, (p, n), text in ((383, BELMONT, "005 -- CSO"), (238, FORT_WAYNE, "001 -- CSO - EPA requested 5/2005")):
        feats.append({"attributes": {"OBJECTID": oid, "NPDES_Number": p, "CSO_Number": text, "Status": "Active",
                                     "Wastewater_Type": "Untreated CSO"}, "geometry": None})
    epa = [{"npdes_permit": p, "outfall": n, "state": "IN", "outfall_status": "CSO|DSW|SW", "coords_from": "facility",
            "lat": 40.0, "lon": -85.0, "outfall_name": _row(committed, (p, n))["outfall_name"]} for p, n in NO_POINT]
    out = bi.build({"features": feats}, epa, "2026-11-15T00:00:00Z")
    got = {(o["npdes_permit"], o["outfall"]): o for o in out["outfalls"]}
    for key in (BELMONT, FORT_WAYNE):
        assert (got[key]["lat"], got[key]["lon"]) == FIXED[key]
    for key in NO_POINT:
        assert got[key]["lat"] is None and got[key]["no_point_reason"].startswith("EPA's national CSO inventory")


def test_the_national_build_calls_the_corrections_before_it_writes():
    src = (ROOT / "scripts" / "match_outfalls.py").read_text()
    hook = src.index('_opc.for_builder("outfalls-us.json", out["outfalls"])')
    assert hook < src.index('tmp = out_path + ".tmp"\nwith open(tmp, "w") as fh:\n    json.dump(out, fh, indent=1)')
