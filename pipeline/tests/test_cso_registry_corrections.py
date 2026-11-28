"""The combined sewer registry corrections of 2026-11-16 (research/cso-registry-2026-11-16/corrections.json, applied by
scripts/outfall_point_corrections.py; EPA's inventory refetched by scripts/match_outfalls.py DWW_PERMITS): the outfalls
the authorities list (GLWA, Ecology, Spokane, Pennsylvania DEP), the closed ones (DC Water, DEP's former CSOs), and one
outfall listed under two permits counted once without taking the rain caution from any water. Data tests on the files
as committed, the rebuild path, the counts and the export; no network.
Run from pipeline/: python -m pytest tests/test_cso_registry_corrections.py -q
"""
from __future__ import annotations

import copy
import csv
import importlib.util
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import common  # noqa: E402
from build.rain_likely import cso_counted, cso_open  # noqa: E402
from export import outfalls as X  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
FIXES = json.loads((ROOT / "research" / "cso-registry-2026-11-16" / "corrections.json").read_text())


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture(scope="module")
def mod():
    return _load("outfall_point_corrections")


@pytest.fixture(scope="module")
def docs(mod):
    return {n: json.loads((DATA / n).read_text()) for n in mod.files()}


@pytest.fixture(scope="module")
def registry():
    return common.load_outfall_registry(DATA, provisional=False)


def rows_of(docs, f, permit):
    return [o for o in docs[f]["outfalls"] if o.get("npdes_permit") == permit]


def one(docs, f, permit, outfall):
    got = [o for o in rows_of(docs, f, permit) if o.get("outfall") == outfall]
    assert len(got) == 1, (f, permit, outfall)
    return got[0]


# ------------------------------------------------ the tables as committed

def test_every_change_names_its_source_and_keeps_epas_value(docs):
    # add: GLWA's 61 untreated outfalls, and its closed outfall 082 (Oakwood; untraced-outfall fixes 2026-11-28)
    assert len(FIXES["status"]) == 97 and len(FIXES["add"]) == 62 and len(FIXES["shared"]) == 213
    for e in FIXES["status"]:
        o = one(docs, e["file"], e["npdes_permit"], e["outfall"])
        assert o["outfall_status"] == e["status"] and o["epa_outfall_status"] == e["expect_status"]
        assert o["status_source"] and all(s["url"].startswith("https://") and s["read_at"] for s in o["status_source"])
    for e in FIXES["add"]:
        o = one(docs, e["file"], e["row"]["npdes_permit"], e["row"]["outfall"])
        assert o["added_source"][0]["url"].startswith("https://www.glwater.org/") and o["added_from"]


def test_glwa_untreated_outfalls_are_added_without_an_invented_point(docs, registry):
    rows = rows_of(docs, "outfalls-us.json", "MI0022802")
    added = [o for o in rows if o.get("added_from")]
    # EPA's nine control facilities stay; 082 (Oakwood, closed in 2012) is added from the permit's control program
    assert len(added) == 62 and len(rows) == 71
    assert [o["outfall"] for o in added if not cso_open(o)] == ["082"]
    for o in added:
        assert o["lat"] is None and o["lon"] is None and o["coords_from"] is None
        # a row with no water says why; one a hand correction ties (082) keeps it in replaced_match
        assert "no point is used" in o["no_point_reason"] and (o.get("no_water_reason") or o["water_slug"])
    glwa = [o for o in registry if o["npdes_permit"] == "MI0022802" and cso_open(o)]
    assert len(glwa) == 70


def test_the_research_points_are_not_copied_onto_glwa_or_other_rows(docs):
    pts = Counter((o["lat"], o["lon"]) for o in rows_of(docs, "outfalls-us.json", "MI0022802") if o["lat"] is not None)
    assert sum(pts.values()) == 9


@pytest.mark.parametrize("permit,n", [("WA0024473", 18), ("WA0024490", 13), ("WA0020257", 2), ("WA0024074", 2),
                                      ("WA0029289", 15)])
def test_washington_outfalls_ecology_lists_are_open(docs, permit, n):
    opened = [o for o in rows_of(docs, "outfalls-us.json", permit) if cso_open(o)]
    assert len(opened) == n
    for o in opened:
        if "epa_outfall_status" in o:
            assert o["epa_outfall_status"].startswith("CLS") and "Ecology" in o["status_note"]


def test_spokane_keeps_closed_what_the_citys_table_does_not_list(docs):
    o = one(docs, "outfalls-us.json", "WA0024473", "022")          # Main @ Oak: not on the city's table
    assert o["outfall_status"] == "CLS" and "epa_outfall_status" not in o


def test_dc_waters_separated_outfalls_are_closed_and_the_others_open(docs):
    dc = rows_of(docs, "outfalls-mid-atlantic.json", "DC0021199")
    closed = sorted(o["outfall"] for o in dc if not cso_open(o))
    assert closed == ["006", "025", "026", "031", "037", "053", "057", "058"]
    assert sum(cso_open(o) for o in dc) == 48 and len(dc) == 56        # never deleted
    o = one(docs, "outfalls-mid-atlantic.json", "DC0021199", "057")
    assert o["epa_outfall_status"] == "CSO" and "separated" in o["status_note"] and "permitting authority" in o["status_note"]


@pytest.mark.parametrize("permit,closed", [("PA0253901", 8), ("PA0037818", 5), ("PA0254690", 5), ("PA0037711", 2),
                                           ("PA0252751", 1), ("PAG066132", 1)])
def test_deps_former_csos_are_closed(docs, permit, closed):
    rows = rows_of(docs, "outfalls-mid-atlantic.json", permit)       # the regional file repeats some (one per version)
    assert len({o["outfall"] for o in rows if not cso_open(o)}) == closed and not any(cso_open(o) for o in rows)


def test_deps_existing_csos_reopen_epas_closed_rows(docs):
    assert sum(cso_open(o) for o in rows_of(docs, "outfalls-mid-atlantic.json", "PAG066109")) == 20
    assert sum(cso_open(o) for o in rows_of(docs, "outfalls-mid-atlantic.json", "PAG066141")) == 2


# ------------------------------------------------ one outfall under two permits: counted once, caution unchanged

def test_a_shared_outfall_is_counted_once_and_the_caution_still_reads_both_rows(registry):
    by = {(o["npdes_permit"], o["outfall"]): o for o in registry}
    marked = [o for o in registry if o.get("same_outfall_as")]
    assert len(marked) == 213
    for o in marked:
        keep = by[(o["same_outfall_as"]["npdes_permit"], o["same_outfall_as"]["outfall"])]
        assert cso_open(o) and not cso_counted(o)                   # the rain caution still reads it
        assert cso_counted(keep) and (round(keep["lat"], 4), round(keep["lon"], 4)) == (round(o["lat"], 4), round(o["lon"], 4))
        assert {"npdes_permit": o["npdes_permit"], "outfall": o["outfall"]} in keep["also_permits"]
    pa = Counter(o["npdes_permit"] for o in marked)
    assert pa["PA0217611"] == 134 and pa["RISS00032"] == 36 and pa["RISS00024"] == 25


def test_the_unsettled_shared_points_stay_counted_twice(registry):
    for p in FIXES["shared_unsettled"]["points"]:
        for r in p["rows"]:
            o = next(o for o in registry if (o["npdes_permit"], o["outfall"]) == (r["permit"], r["outfall"]))
            assert cso_counted(o)


def test_the_export_draws_and_counts_a_shared_outfall_once(registry):
    live = {"PA", "RI"}
    rows = X.outfall_rows([o for o in registry if o["npdes_permit"] in ("PA0025984", "PA0217611", "RI0100315",
                                                                        "RISS00032")], live)
    alias = [r for r in rows if r.get("alias_of")]
    kept = {f"{r['npdes_permit']}:{r['outfall_id']}" for r in rows if not r.get("alias_of")}
    assert alias and all(r["alias_of"] in kept and r["same_outfall"] for r in alias)
    k = next(r for r in rows if r.get("also_permits"))
    assert all(set(x) == {"npdes_permit", "outfall_id", "discharger_id"} for x in k["also_permits"])
    counted = [r for r in rows if not r.get("alias_of") and r["outfall_kind"] == "cso"
               and not str(r["outfall_status"]).startswith("CLS")]
    assert len(counted) == sum(cso_counted(o) for o in registry if o["npdes_permit"] in
                               ("PA0025984", "PA0217611", "RI0100315", "RISS00032"))


def test_the_state_profiles_count_a_shared_outfall_once_and_closed_rows_as_closed():
    m = _load("merge_state_profiles")
    fed = m.federal_counts()
    reg = common.load_outfall_registry(DATA, provisional=False)
    for st in ("PA", "RI", "DC"):
        want = sum(1 for o in reg if o["_file"] in ("data/outfalls-mid-atlantic.json", "data/outfalls-new-england.json")
                   and o.get("state") == st and cso_counted(o))
        assert fed[st]["cso_open_outfalls"] == want


# ------------------------------------------------ durable through a rebuild

def _as_epa_gives_it(o: dict) -> dict:
    o = copy.deepcopy(o)
    if "epa_outfall_status" in o:
        o["outfall_status"] = o.pop("epa_outfall_status")
    for k in ("status_note", "status_source", "same_outfall_as", "also_permits"):
        o.pop(k, None)
    return o


@pytest.mark.parametrize("f", ["outfalls-us.json", "outfalls-mid-atlantic.json", "outfalls-new-england.json"])
def test_a_rebuilt_file_gets_every_correction_again(mod, docs, f):
    from ingest import outfall_water_corrections as H
    rebuilt = [_as_epa_gives_it(o) for o in docs[f]["outfalls"] if not o.get("added_from")]
    bad = mod.for_builder(f, rebuilt)
    assert H.apply_rows(f, rebuilt) == []          # scripts/match_outfalls.py writes the hand ties after (GLWA 082)
    assert bad == [] and rebuilt == docs[f]["outfalls"]


def test_a_build_without_glwas_permit_adds_no_row(mod):
    rows = [{"npdes_permit": "OH0000001", "outfall": "001", "outfall_status": "CSO"}]
    mod.apply_rows("outfalls-us.json", rows)
    assert len(rows) == 1


def test_epa_reopening_a_row_itself_is_reported_not_overwritten(mod, docs):
    o = _as_epa_gives_it(one(docs, "outfalls-us.json", "WA0024490", "005"))
    o["outfall_status"] = "CSO"                                  # EPA's own list changed: look at it
    before = dict(o)
    _, bad = mod.apply_rows("outfalls-us.json", [o])
    assert any("WA0024490 005" in b for b in bad) and o == before


def test_a_shared_row_whose_point_moved_is_reported_not_marked(mod, docs):
    e = FIXES["shared"][0]
    o = _as_epa_gives_it(one(docs, e["file"], e["npdes_permit"], e["outfall"]))
    o["lat"] += 0.01
    _, bad = mod.apply_rows(e["file"], [o])
    assert any(f"{e['npdes_permit']} {e['outfall']}" in b for b in bad) and "same_outfall_as" not in o


def test_check_fails_when_a_kept_row_closes(mod, docs):
    d = copy.deepcopy(docs)
    e = FIXES["shared"][0]
    one(d, e["same_as"]["file"], e["same_as"]["npdes_permit"], e["same_as"]["outfall"])["outfall_status"] = "CLS"
    assert any("kept row" in b for b in mod.check(d))


def test_the_refetch_rewrites_only_the_permits_named_and_keeps_a_row_epa_dropped(tmp_path):
    """scripts/match_outfalls.py DWW_PERMITS with --append on a small file: the other permit's row is kept byte for byte
    (ties included), a row EPA no longer lists is kept and marked, and the file's date is on the rows written."""
    head = ["NPDES_ID", "STATE_CODE", "FACILITY_NAME", "FACILITY_CITY", "PERM_FEATURE_NMBR", "PERM_FEATURE_TEXT",
            "PF_CHARACTER", "PERM_FEATURE_TYPE_CODE", "PF_STATE_WATERBODY_NAME", "PF_STATE_AUTO_NAME", "PF_REACH_ID",
            "IN_ICIS", "PERMIT_STATUS_CODE", "ECHO_DFR_LINK", "PF_LAT", "PF_LON", "FACILITY_LAT", "FACILITY_LON"]
    with open(tmp_path / "ALL_CSO_DOWNLOADS.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(head)
        w.writerow(["PA9999991", "PA", "TEST A", "X", "001", "", "CSO", "EXO", "Test Creek", "", "", "YES", "EFF", "",
                    "40.1", "-77.1", "", ""])
        w.writerow(["PA9999992", "PA", "TEST B", "X", "001", "", "CLS", "EXO", "Test Creek", "", "", "YES", "EFF", "",
                    "40.2", "-77.2", "", ""])
    keep = {"npdes_permit": "PA9999992", "state": "PA", "outfall": "001", "outfall_status": "CSO",
            "water_slug": "tied-by-the-ties-step", "match": "geometry"}
    old = {"npdes_permit": "PA9999991", "state": "PA", "outfall": "009", "outfall_status": "CSO", "match": "none"}
    (tmp_path / "out.json").write_text(json.dumps({"source": "x", "outfalls": [old, keep]}))
    (tmp_path / "water").mkdir()
    env = {**os.environ, "DWW_STATES": "PA", "DWW_PERMITS": "PA9999991", "DWW_CSO_FILE_DATE": "2026-11-14"}
    r = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "match_outfalls.py"),
                        str(tmp_path / "ALL_CSO_DOWNLOADS.csv"), str(tmp_path / "water"), str(tmp_path / "out.json"),
                        "--append"], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-800:]
    out = json.loads((tmp_path / "out.json").read_text())
    got = {(o["npdes_permit"], o["outfall"]): o for o in out["outfalls"]}
    assert got[("PA9999992", "001")] == keep                         # not named: untouched, its tie kept
    assert "2026-11-14" in got[("PA9999991", "001")]["inventory_file"]
    assert "no longer lists" in got[("PA9999991", "009")]["not_in_inventory"]
    assert out["appended"][-1]["permits"] == ["PA9999991"]


# ------------------------------------------------ review 2026-11-16 (Astra)

def test_an_annotated_closed_status_is_closed_for_the_reaches():
    from build import reaches
    for s in ("CLS", "CLS|DSW", "CLS (separated: DC Water's quarterly CSO reports, 2026)",
              "CLS (former CSO: Pennsylvania DEP's CSO status spreadsheet)", "CLS (ended 2011-11-18 in DEP's layer)"):
        assert reaches.is_closed({"outfall_status": s}), s
    for s in ("CSO", "CSO|DSW", "CSO (open: Ecology's CSO table)", "TCS"):
        assert not reaches.is_closed({"outfall_status": s}), s


def test_every_shared_mark_cites_its_dated_source(registry):
    for o in (o for o in registry if o.get("same_outfall_as")):
        src = o["same_outfall_as"]["source"]
        assert src and all(s["url"].startswith("https://") and s["read_at"] == "2026-11-16" for s in src)
        assert "ALL_CSO_DOWNLOADS.csv" in src[0]["name"]


def test_a_shared_row_is_not_marked_when_its_kept_row_moved_in_the_same_build(mod, docs):
    e = next(e for e in FIXES["shared"] if e["same_as"]["file"] == e["file"])
    rows = [_as_epa_gives_it(o) for o in docs[e["file"]]["outfalls"]]
    keep = next(o for o in rows if (o["npdes_permit"], o["outfall"]) == (e["same_as"]["npdes_permit"], e["same_as"]["outfall"]))
    keep["lat"] += 0.01
    _, bad = mod.apply_rows(e["file"], rows)
    other = next(o for o in rows if (o["npdes_permit"], o["outfall"]) == (e["npdes_permit"], e["outfall"]))
    assert "same_outfall_as" not in other and any("kept row" in b for b in bad)


def test_the_refetch_keeps_the_values_epa_changed(docs):
    o = one(docs, "outfalls-us.json", "OH0052922", "005")
    assert o["outfall_status"] == "CLS" and o["replaces_inventory_row"]["outfall_status"] == "CSO"
    assert "2026-10-31" in o["replaces_inventory_row"]["from"]


def test_the_national_files_count_their_rows(docs):
    for n in ("outfalls-us.json",):
        assert docs[n]["count"] == len(docs[n]["outfalls"])


def test_a_named_permit_epa_dropped_whole_keeps_its_rows_marked(tmp_path):
    head = ["NPDES_ID", "STATE_CODE", "FACILITY_NAME", "FACILITY_CITY", "PERM_FEATURE_NMBR", "PERM_FEATURE_TEXT",
            "PF_CHARACTER", "PERM_FEATURE_TYPE_CODE", "PF_STATE_WATERBODY_NAME", "PF_STATE_AUTO_NAME", "PF_REACH_ID",
            "IN_ICIS", "PERMIT_STATUS_CODE", "ECHO_DFR_LINK", "PF_LAT", "PF_LON", "FACILITY_LAT", "FACILITY_LON"]
    with open(tmp_path / "ALL_CSO_DOWNLOADS.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(head)
        w.writerow(["PA9999991", "PA", "TEST A", "X", "001", "", "CLS", "EXO", "Test Creek", "", "", "YES", "EFF", "",
                    "40.1", "-77.1", "", ""])
    gone = {"npdes_permit": "PA9999993", "state": "PA", "outfall": "001", "outfall_status": "CSO", "match": "none"}
    was = {"npdes_permit": "PA9999991", "state": "PA", "outfall": "001", "outfall_status": "CSO", "match": "none",
           "lat": 40.1, "lon": -77.1}
    (tmp_path / "out.json").write_text(json.dumps({"source": "x", "outfalls": [was, gone]}))
    (tmp_path / "water").mkdir()
    env = {**os.environ, "DWW_STATES": "PA", "DWW_PERMITS": "PA9999991,PA9999993", "DWW_CSO_FILE_DATE": "2026-11-14"}
    r = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "match_outfalls.py"),
                        str(tmp_path / "ALL_CSO_DOWNLOADS.csv"), str(tmp_path / "water"), str(tmp_path / "out.json"),
                        "--append"], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-800:]
    got = {(o["npdes_permit"], o["outfall"]): o for o in json.loads((tmp_path / "out.json").read_text())["outfalls"]}
    assert "no longer lists" in got[("PA9999993", "001")]["not_in_inventory"]
    assert got[("PA9999991", "001")]["outfall_status"] == "CLS"
    assert got[("PA9999991", "001")]["replaces_inventory_row"]["outfall_status"] == "CSO"
