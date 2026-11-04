"""research/federal/build_plant_outfalls.py: EPA separates several SIC / NAICS codes with spaces ("4952 8211"), so a
sewage permit carrying more than one code must still be read as a sewage permit (docs/reviews/2026-11-04-private-
utilities-review.md in the site repository, "The comma fix"); and research/federal/merge_plant_outfalls.py adds the
rows a rebuild finds without changing a committed row. Run from pipeline/: python -m pytest
tests/test_plant_outfalls_codes.py -q"""
import copy
import csv
import importlib.util
import json

import pytest

from common import ROOT

FIX = ROOT / "pipeline" / "tests" / "fixtures" / "plant-outfalls"


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "research" / "federal" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def build():
    return load("build_plant_outfalls")


@pytest.fixture(scope="module")
def merge_mod():
    return load("merge_plant_outfalls")


def test_codes_split_on_spaces_and_commas(build):
    assert build.codes("4952 8211") == {"4952", "8211"}
    assert build.codes("221310  221320") == {"221310", "221320"}
    assert build.codes("4941,4952") == {"4941", "4952"}
    assert build.codes("4941, 4952 4911") == {"4941", "4952", "4911"}
    assert build.codes("4952") == {"4952"}
    assert build.codes("") == set() and build.codes(None) == set()
    # a code is matched whole, never as part of another
    assert "4952" not in build.codes("49521 14952")


def test_a_permit_with_several_codes_is_a_sewage_permit_and_joins_the_universe(build):
    with open(FIX / "npdes_outfalls_layer_sample.csv", newline="") as fh:
        perm, dups = build.group_permits(csv.DictReader(fh))
    assert dups == 0
    universe = {p: build.basis(p, e, {}) for p, e in perm.items()}
    # the school district's plant: SIC "4952 8211", NAICS "221320 611110" (before the fix: no sewer code, left out)
    assert perm["PA9900001"]["sewer_code"] is True
    assert universe["PA9900001"] == "sewerage_code_public_owner"
    assert sorted(perm["PA9900001"]["exo"]) == ["1", "2"]
    # NAICS 221320 second of two codes, SIC another code
    assert universe["PA9900002"] == "sewerage_code_public_owner"
    # commas still read; a single code still read
    assert universe["PA9900003"] == "sewerage_code_public_owner"
    assert universe["PA9900007"] == "sewerage_code_public_owner"
    # several codes, none a sewerage code: not a sewage permit
    assert perm["PA9900004"]["sewer_code"] is False and universe["PA9900004"] is None
    # a sewage permit of a private owner, and a terminated one, stay out of the public plant universe
    assert perm["PA9900005"]["sewer_code"] is True and universe["PA9900005"] is None
    assert perm["PA9900006"]["sewer_code"] is True and universe["PA9900006"] is None
    # an operator we track joins whatever its codes
    assert build.basis("PA9900004", perm["PA9900004"], {"PA9900004": ["example-water-works"]}) == "tracked_operator"


def _row(p, o, **kw):
    r = {"npdes_permit": p, "permittee": "Example", "state": p[:2], "outfall": o, "lat": 40.0, "lon": -77.0,
         "outfall_kind": "plant", "source": "fed-echo-npdes-discharge-points", "fetched_at": "2026-11-03T21:02:45Z"}
    r.update(kw)
    return r


def _docs():
    committed = {"source": "S", "rule": "R", "fetched_at": "2026-11-03T21:02:45Z", "count": 2,
                 "counts": {"by_state": {"PA": 2}}, "cso_features_not_in_inventory": [],
                 "outfalls": [_row("PA0000001", "001", water_slug="example-creek-pa", match="geometry",
                                   water_match="geometry: ...", water_matched_by="ingest.outfall_waters (2026-11-04)"),
                              _row("PA0000002", None, coords_from="facility", water_slug=None,
                                   no_water_reason="no record", water_match="none: no record")]}
    rebuilt = {"source": "S2", "rule": "R", "fetched_at": "2026-11-04T05:35:49Z", "count": 3,
               "counts": {"by_state": {"PA": 3}}, "cso_features_not_in_inventory": [],
               "outfalls": [_row("PA0000001", "001", fetched_at="2026-11-04T05:35:49Z"),
                            _row("PA0000002", None, coords_from="facility", fetched_at="2026-11-04T05:35:49Z"),
                            _row("PA9900001", "001", fetched_at="2026-11-04T05:35:49Z")]}
    return committed, rebuilt


def test_merge_keeps_committed_rows_and_their_ties_and_adds_the_new_rows(merge_mod):
    committed, rebuilt = _docs()
    before = copy.deepcopy(committed)
    doc, problems, added = merge_mod.merge(committed, rebuilt, "2026-11-04", "2026-11-04T05:35:49Z", "why")
    assert problems == []
    assert [r["npdes_permit"] for r in added] == ["PA9900001"]
    assert doc["outfalls"][:2] == before["outfalls"]                    # ties and fetched_at kept, unchanged
    assert doc["outfalls"][2]["fetched_at"] == "2026-11-04T05:35:49Z"     # the new row says which copy it came from
    assert "water_slug" not in doc["outfalls"][2]                         # no tie invented for it
    assert doc["source"] == "S" and doc["fetched_at"] == "2026-11-03T21:02:45Z"
    assert doc["count"] == 3 and doc["counts"] == rebuilt["counts"]
    assert doc["rebuilds"][-1]["rows_added"] == 1 and doc["rebuilds"][-1]["rows_added_by_state"] == {"PA": 1}


def test_merge_refuses_a_rebuild_that_changes_or_drops_a_committed_row(merge_mod, tmp_path):
    committed, rebuilt = _docs()
    rebuilt["outfalls"][0]["lat"] = 41.0
    _, problems, _ = merge_mod.merge(committed, rebuilt, "2026-11-04", "t", "why")
    assert problems == [{"npdes_permit": "PA0000001", "outfall": "001", "fields": ["lat"]}]
    committed, rebuilt = _docs()
    del rebuilt["outfalls"][1]
    _, problems, _ = merge_mod.merge(committed, rebuilt, "2026-11-04", "t", "why")
    assert problems == [{"npdes_permit": "PA0000002", "outfall": None, "fields": ["missing from the rebuild"]}]
    # the command line writes nothing when there is a problem
    (tmp_path / "c.json").write_text(json.dumps(committed))
    (tmp_path / "r.json").write_text(json.dumps(rebuilt))
    rc = merge_mod.main([str(tmp_path / "c.json"), str(tmp_path / "r.json"), str(tmp_path / "o.json"),
                         "--date", "2026-11-04", "--fetched-at", "t", "--why", "w"])
    assert rc == 1 and not (tmp_path / "o.json").exists()


def test_merge_writes_the_registry_layout(merge_mod, tmp_path):
    committed, rebuilt = _docs()
    doc, _, _ = merge_mod.merge(committed, rebuilt, "2026-11-04", "t", "why")
    merge_mod.write(tmp_path / "o.json", doc)
    text = (tmp_path / "o.json").read_text()
    assert json.loads(text) == doc
    lines = text.split("\n")
    assert lines[0] == "{" and lines[1].startswith('"source": ')
    assert sum(1 for x in lines if x.startswith('{"npdes_permit"')) == 3   # one row per line


def test_merge_accepts_only_the_named_field_on_a_committed_row(merge_mod):
    """The fix moves a tracked operator's permit that carries several codes to the sewerage-code basis: that field may
    change when named, nothing else."""
    committed, rebuilt = _docs()
    committed["outfalls"][0]["plant_basis"] = "tracked_operator"
    rebuilt["outfalls"][0]["plant_basis"] = "sewerage_code_public_owner"
    _, problems, _ = merge_mod.merge(committed, rebuilt, "2026-11-04", "t", "why")
    assert problems and problems[0]["fields"] == ["plant_basis"]
    before = copy.deepcopy(committed["outfalls"][0])
    doc, problems, _ = merge_mod.merge(committed, rebuilt, "2026-11-04", "t", "why", accept=["plant_basis"])
    assert problems == []
    row = doc["outfalls"][0]
    assert row["plant_basis"] == "sewerage_code_public_owner"
    assert list(row) == list(before) and {k: v for k, v in row.items() if k != "plant_basis"} == \
        {k: v for k, v in before.items() if k != "plant_basis"}           # ties, fetched_at and key order kept
    assert doc["rebuilds"][-1]["rows_changed"] == {"plant_basis": ["PA0000001 001"]}
    assert doc["rebuilds"][-1]["rows_unchanged"] == 1
    rebuilt["outfalls"][0]["lat"] = 41.0                                   # another field still refuses
    _, problems, _ = merge_mod.merge(committed, rebuilt, "2026-11-04", "t", "why", accept=["plant_basis"])
    assert problems[0]["fields"] == ["lat", "plant_basis"]
