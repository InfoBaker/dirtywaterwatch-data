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


# ---------------------------------------------------------------- not every sewerage-code permit is a sewage plant
# (docs/reviews/2026-11-04-plant-outfalls-codes-review.md in the site repository): SIC 4952 among several codes also
# marks drinking-water plants (filter backwash), construction projects and sites with no sewage outfall

def _universe(build, kinds=None):
    with open(FIX / "npdes_outfalls_layer_sample.csv", newline="") as fh:
        perm, _ = build.group_permits(csv.DictReader(fh))
    kinds = kinds or {}
    out = {}
    for p, e in perm.items():
        b = build.basis(p, e, {})
        if b:
            out[p] = (b, build.not_sewage(p, e, b, kinds.get(p)))
    return perm, out


def test_a_water_plant_or_a_construction_project_with_the_sewerage_code_is_no_sewage_plant(build):
    _, u = _universe(build, {"PA9900008": {"disinfection"}})
    assert u["PA9900008"] == ("sewerage_code_public_owner", "water_treatment_plant")   # a water plant chlorinates too
    assert u["PA9900011"][1] == "water_treatment_plant"                                  # 4952 alone, a water plant's name
    assert u["PA9900009"][1] == "construction_project"                                   # "Sanitary Sewer Project"
    # limits that show sewage keep the permit whatever its name ("... WTP" can be a wastewater plant; a project office)
    _, u = _universe(build, {"PA9900008": {"fecal"}, "PA9900011": {"bod", "disinfection"}, "PA9900009": {"fecal"}})
    assert u["PA9900008"][1] is None and u["PA9900011"][1] is None and u["PA9900009"][1] is None
    assert build.WATER_PLANT_NAME.search("Example WWTP") is None
    assert build.WATER_PLANT_NAME.search("Example Wastewater Treatment Plant") is None


def test_a_multi_code_permit_needs_a_sewage_name_or_sewage_limits(build):
    _, u = _universe(build)
    assert u["PA9900001"][1] is None                  # "... WWTP": the name shows sewage
    assert u["PA9900003"][1] is None                  # "... STP" with the water supply code
    assert u["PA9900007"][1] is None                  # the sewerage code alone: no evidence needed
    assert u["PA9900010"][1] == "no_sewage_evidence"  # a park, no limits on file
    for kinds, held in (({"fecal"}, False), ({"bod", "disinfection"}, False), ({"ammonia", "disinfection"}, False),
                        ({"tkn", "disinfection"}, False), ({"bod", "tkn"}, True), ({"disinfection"}, True), (set(), True)):
        _, u = _universe(build, {"PA9900010": kinds})
        assert (u["PA9900010"][1] == "no_sewage_evidence") is held, kinds


def test_a_potw_or_tracked_permit_is_never_held_back(build):
    perm, _ = _universe(build)
    e = perm["PA9900008"]
    assert build.not_sewage("PA9900008", e, "potw_component", set()) is None
    assert build.not_sewage("PA9900008", e, "tracked_operator", set()) is None
    # a domestic-sewage general permit (NC's single-family and small systems) is a sewage discharge whatever its codes
    school = dict(r=dict(e["r"], FACILITY_NAME="Example Alternate School", SIC_CODES="8211", NAICS_CODES="221320"))
    assert build.not_sewage("NCG559999", school, "sewerage_code_public_owner", set()) is None
    assert build.not_sewage("NC0099999", school, "sewerage_code_public_owner", set()) == "no_sewage_evidence"


def test_limit_kinds_come_from_the_limits_pass_and_an_older_limits_file_is_refused(build):
    lp = load("plant_outfalls_limits_pass")
    assert lp.sewage_kinds("Coliform, fecal general") == ["fecal"]
    assert lp.sewage_kinds("E. coli") == ["fecal"]
    assert lp.sewage_kinds("Enterococci") == ["fecal"]
    assert lp.sewage_kinds("BOD, 5-day, 20 deg. C") == ["bod"]
    assert lp.sewage_kinds("BOD, carbonaceous [5 day, 20 C]") == ["bod"]
    assert lp.sewage_kinds("Nitrogen, ammonia total [as N]") == ["ammonia"]
    assert lp.sewage_kinds("Nitrogen, Kjeldahl, total [as N]") == ["tkn"]
    assert lp.sewage_kinds("Chlorine, total residual") == ["disinfection"]
    assert lp.sewage_kinds("Ultraviolet light intensity") == ["disinfection"]
    for water_plant in ("Aluminum, total [as Al]", "Iron, total [as Fe]", "Oxygen demand, chem. [high level] (COD)",
                        "Solids, total suspended", "pH"):
        assert lp.sewage_kinds(water_plant) == []
    kinds = build.permit_limit_kinds({"PA1|1": {"sewage": ["bod"]}, "PA1|2": {"sewage": ["disinfection"]},
                                      "PA2|1": {"sewage": []}})
    assert kinds["PA1"] == {"bod", "disinfection"} and build.sewage_limits(kinds["PA1"])
    assert not build.sewage_limits(kinds["PA2"])
    with pytest.raises(SystemExit):
        build.permit_limit_kinds({"PA1|1": {"names": [], "types": ["EXO"]}})


def _docs_with_exclusion():
    committed, rebuilt = _docs()
    rebuilt["rule"] = "R2"
    del rebuilt["outfalls"][1]                         # PA0000002: now held back as no sewage plant
    rebuilt["excluded_not_sewage"] = [{"npdes_permit": "PA0000002", "state": "PA", "reason": "water_treatment_plant"}]
    return committed, rebuilt


def test_merge_drops_a_committed_row_of_a_held_back_permit_only_when_told(merge_mod):
    committed, rebuilt = _docs_with_exclusion()
    _, problems, _ = merge_mod.merge(committed, rebuilt, "2026-11-04", "t", "why")
    assert problems == [{"npdes_permit": "PA0000002", "outfall": None, "fields": ["missing from the rebuild"]}]
    doc, problems, _ = merge_mod.merge(committed, rebuilt, "2026-11-04", "t", "why", drop_excluded=True)
    assert problems == []
    assert [r["npdes_permit"] for r in doc["outfalls"]] == ["PA0000001", "PA9900001"]
    assert doc["outfalls"][0] == committed["outfalls"][0]
    assert doc["excluded_not_sewage"] == rebuilt["excluded_not_sewage"] and doc["rule"] == "R2"
    assert doc["rebuilds"][-1]["rows_dropped"] == {"water_treatment_plant": ["PA0000002 None"]}
    # a row missing for another reason still refuses
    del rebuilt["outfalls"][0]
    _, problems, _ = merge_mod.merge(committed, rebuilt, "2026-11-04", "t", "why", drop_excluded=True)
    assert problems == [{"npdes_permit": "PA0000001", "outfall": "001", "fields": ["missing from the rebuild"]}]


def test_the_registry_never_reads_a_row_of_a_held_back_permit(tmp_path):
    """Even when a later step writes a row back into the outfall list, the loader and the map leave it out."""
    import common
    from export import outfalls as export_outfalls
    doc = {"source": "S", "excluded_not_sewage": [{"npdes_permit": "PA0217905", "reason": "water_treatment_plant"}],
           "outfalls": [_row("PA0217905", "001"), _row("PA0000001", "001")]}
    (tmp_path / "outfalls-plants-us.json").write_text(json.dumps(doc))
    reg = common.load_outfall_registry(tmp_path, provisional=False)
    assert [r["npdes_permit"] for r in reg] == ["PA0000001"]
    rows = export_outfalls.outfall_rows(reg, {"PA"})
    assert [r["npdes_permit"] for r in rows] == ["PA0000001"]


def test_the_committed_registry_draws_no_water_plant_and_no_held_back_permit():
    """data/outfalls-plants-us.json: the drinking-water plants the code split let in (filter backwash outfalls) are
    held back with their reason, have no row, and have no operator page made for them."""
    doc = json.loads((ROOT / "data" / "outfalls-plants-us.json").read_text())
    held = {x["npdes_permit"]: x for x in doc.get("excluded_not_sewage") or []}
    for p in ("PA0217905", "PA0217158", "PA0098779", "SR0026417", "PA0084638"):
        assert held.get(p, {}).get("reason") in ("water_treatment_plant", "no_sewage_evidence"), p
    assert held["PAC100021"]["reason"] == "construction_project"
    assert all(x["reason"] in ("water_treatment_plant", "construction_project", "no_sewage_evidence",
                                   "not_a_sewage_plant") and x["why"]
               for x in held.values())
    assert not [r for r in doc["outfalls"] if r["npdes_permit"] in held]
    dis = json.loads((ROOT / "data" / "dischargers.json").read_text())
    for d in dis:
        ps = d.get("npdes_permits") or [d.get("npdes_permit")]
        assert not (d.get("source_areas") == ["federal"] and ps and all(p in held for p in ps)), d["id"]


def test_a_person_in_place_of_a_body_is_no_permit_name(build):
    """EPA's PERMIT_NAME is often a contact person: a whole person's name, or a couple's, becomes null; a body's name
    stays as EPA spells it (placeholder names)."""
    assert build.public_permit_name("Jane Q Doe") is None
    assert build.public_permit_name("DOE JOHN & JANE") is None
    assert build.public_permit_name("Doe, Jane") is None
    assert build.public_permit_name("HOWARD COUNTY PUBLIC SCHOOL SYSTEM") == "HOWARD COUNTY PUBLIC SCHOOL SYSTEM"
    assert build.public_permit_name("City of Example") == "City of Example"
    assert build.public_permit_name("  ") is None and build.public_permit_name(None) is None
