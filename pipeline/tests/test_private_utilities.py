"""Private sewer utilities, national: scripts/private_utilities.py lists every individually permitted sewage permit whose
permittee is not a public body, per state, from EPA's ICIS-NPDES discharge points, for the state builder. The files are
public: no individual's name, no address, ZIP or coordinate. Run from pipeline/:
python -m pytest tests/test_private_utilities.py -q
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from common import NAME_REMOVED, ROOT

_spec = importlib.util.spec_from_file_location("private_utilities", ROOT / "scripts" / "private_utilities.py")
PU = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(PU)

FIX = Path(__file__).parent / "fixtures" / "private-utilities"
PERSON = "Quill"            # the invented individual of the fixture ("James T Quill", "QUILL JAMES T")


# ------------------------------------------------------------------ names

@pytest.mark.parametrize("name", [
    "James T Quill", "QUILL JAMES T", "Quill, James T.", "JAMES & MARY QUILL", "James T Quill MHP",
    "JAMES T QUILL TRUST", "Example Partners LP and James T Quill", "Estate of Example Quill",
    "12 EXAMPLE LN SRSTP", "4 Example Road", "QUILL RESIDENCE", "Example Quill",
])
def test_a_persons_name_never_survives(name):
    assert PU.public_name(name) == NAME_REMOVED


@pytest.mark.parametrize("name, kept", [
    ("Example Utility Company LLC", "Example Utility Company LLC"),
    ("SUNNY ACRES MHP", "SUNNY ACRES MHP"),
    ("Hilltop Sewer Co Inc", "Hilltop Sewer Co Inc"),
    ("Cross Creek Property Owners' Association", "Cross Creek Property Owners' Association"),
    ("8 MILE PARK, L.P.", "8 MILE PARK, L.P."),
    ("L.B.H., L.L.C.", "L.B.H., L.L.C."),
    ("James T Quill dba Sunny Acres MHP", "Sunny Acres MHP"),
    ("Example Capital Inc Attn James T Quill", "Example Capital Inc"),
    ("James T Quill - South Wind Water and Sewer Dist", "South Wind Water and Sewer Dist"),
])
def test_a_bodys_name_is_kept_and_a_person_inside_it_is_not(name, kept):
    assert PU.public_name(name) == kept


def test_a_name_with_no_organisation_word_is_removed_and_a_blank_stays_blank():
    assert PU.public_name("HIDDEN EXAMPLE") == NAME_REMOVED
    assert PU.public_name("") is None and PU.public_name(None) is None


def test_the_permittee_reads_before_the_facility_and_a_corporate_form_before_a_public_word():
    assert PU.owner_reading("EXETER TWP STP", "EXAMPLE AMER WATER CO") == "private"
    assert PU.owner_reading("DEER RUN WWTP", "Deer Run Water District, LLC") == "private"
    assert PU.owner_reading("SUNRISE RANCH WWTP", "EXAMPLE COUNTY MUD 138") == "public"
    assert PU.owner_reading("EXAMPLE COUNTY MUD 9 WWTP", "") == "public"
    assert PU.owner_reading("LAKEVIEW WWTP", "LAKEVIEW") is None


def test_several_codes_separated_by_spaces_are_each_read():
    assert PU.codes("4952 6515") == {"4952", "6515"}
    assert PU.codes("4952, 6515") == {"4952", "6515"}
    assert PU.us_date("01/02/2024") == "2024-01-02"


# ------------------------------------------------------------------ the run on the fixture

@pytest.fixture(scope="module")
def run(tmp_path_factory):
    out = tmp_path_factory.mktemp("research")
    rc = PU.main(["--icis", str(FIX / "icis-discharge-points.csv"), "--plants", str(FIX / "plants.json"),
                  "--registry", str(FIX / "dischargers.json"), "--out", str(out),
                  "--fetched-at", "2026-11-04T05:35:00Z"])
    assert rc == 0
    f = out / "zz" / "private-utilities-candidates.json"
    return out, f.read_text(), json.loads(f.read_text())


def test_the_rule_keeps_individual_active_private_sewage_permits(run):
    _, _, doc = run
    got = {r["npdes_permit"] for r in doc["candidates"]}
    assert got == {"ZZ0000001", "ZZ0000002", "ZZ0000004", "ZZ0000008", "ZZ0000011", "ZZ0000012", "ZZ0000013",
                   "ZZ0000014"}
    # general permit (6), terminated (7), public type (9), stormwater only (10), mixed type with a neutral name (5)
    assert {r["npdes_permit"] for r in doc["public_by_name"]} == {"ZZ0000003"}


def test_a_permit_with_several_codes_is_a_candidate(run):
    _, _, doc = run
    r = next(r for r in doc["candidates"] if r["npdes_permit"] == "ZZ0000002")
    assert r["sic_codes"] == ["4952", "6515"] and r["external_outfalls"] == 2
    assert r["receiving_waters_echo"] == ["EXAMPLE CREEK"]            # one water, however EPA cases it
    assert r["legal_form_proposed"] == "investor-owned utility"
    assert r["permit_effective"] == "2024-01-02"
    assert r["ownership"]["facility_type_code"] == "COR" and r["ownership"]["file_date"]


def test_a_held_permit_and_the_plants_file_are_marked(run):
    _, _, doc = run
    by = {r["npdes_permit"]: r for r in doc["candidates"]}
    assert by["ZZ0000011"]["registry_row"] == "zz-hilltop-sewer-co" and by["ZZ0000011"]["in_plant_registry"]
    assert by["ZZ0000013"]["ownership"]["source"] == PU.SUPP_SOURCE_ID       # only EPA's national dataset lists it
    assert by["ZZ0000004"]["legal_form_proposed"] == "campground or resort"
    assert by["ZZ0000004"]["ownership"]["basis"].endswith("the name reads as a private body")


def test_a_single_residence_has_both_names_removed(run):
    _, _, doc = run
    r = next(r for r in doc["candidates"] if r["npdes_permit"] == "ZZ0000008")
    assert r["system_kind"] == "single residence"
    assert r["facility"] == NAME_REMOVED and r["permittee_as_recorded"] == NAME_REMOVED
    assert r["legal_form_proposed"] == "facility (permittee not named)"
    assert r["receiving_waters_echo"] == []                            # a person's name in the water field is dropped


def test_no_individual_address_zip_or_point_reaches_the_public_file(run):
    out, text, doc = run
    every = text + (out / "federal" / "private-utilities-summary.json").read_text()
    for bad in (PERSON, PERSON.upper(), "EXAMPLE LN", "09876", "40.12", "75.65", "40.2", "75.2"):
        assert bad not in every, bad
    keys = {k for r in doc["candidates"] + doc["public_by_name"] for k in r}
    assert not keys & {"lat", "lon", "address", "zip", "location_address"}
    by = {r["npdes_permit"]: r for r in doc["candidates"]}
    assert by["ZZ0000001"]["permittee_as_recorded"] == NAME_REMOVED and by["ZZ0000001"]["facility"] == "SUNNY ACRES MHP"
    assert by["ZZ0000012"]["permittee_as_recorded"] == NAME_REMOVED


def test_the_summary_sets_the_count_against_the_earlier_one(run):
    out, _, _ = run
    s = json.loads((out / "federal" / "private-utilities-summary.json").read_text())
    assert s["national_candidates"] == 8 and s["earlier_count"]["value"] == 2359
    g = s["against_earlier_count"]
    assert g["candidate: several codes, one of them sewage (missed by the comma split)"] == 1
    assert g["candidate: POTW component with a private owner type: already in the outfall registry"] == 1


def test_two_states_researched_together_get_a_file_each():
    assert PU.state_file("NH").name == "private-utilities-candidates-nh.json"
    assert PU.state_file("NH").parent.name == "nh-vt"
    assert PU.state_file("TX") == ROOT / "research" / "tx" / "private-utilities-candidates.json"


# ------------------------------------------------------------------ the committed files

COMMITTED = sorted((ROOT / "research").glob("*/private-utilities-candidates*.json"))


def test_the_committed_files_exist_and_reconcile_with_the_earlier_count():
    assert len(COMMITTED) > 40
    s = json.loads((ROOT / "research" / "federal" / "private-utilities-summary.json").read_text())
    total = sum(len(json.loads(f.read_text())["candidates"]) for f in COMMITTED)
    assert total == s["national_candidates"]
    within = sum(n for k, n in s["against_earlier_count"].items() if k.endswith("in the 2,359 (one sewage code)"))
    assert within == s["earlier_count"]["value"] == 2359


def test_the_committed_files_carry_only_names_that_read_as_a_body():
    for f in COMMITTED:
        doc = json.loads(f.read_text())
        for r in doc["candidates"] + doc["public_by_name"]:
            assert not {"lat", "lon", "address", "zip"} & set(r), f
            for k in ("facility", "permittee_as_recorded"):
                v = r[k]
                assert v in (None, NAME_REMOVED) or PU.public_name(v) == v, (f.name, r["npdes_permit"], k)
            if r["system_kind"] == "single residence":
                assert r["facility"] == r["permittee_as_recorded"] == NAME_REMOVED
