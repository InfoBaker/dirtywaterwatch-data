"""The report names of feeds added after a state's names file was written (scripts/report_names_merge.py): South
Carolina's DES overflow list (scripts/de_sc_report_water_names.py), Wyoming's DEQ spill list
(scripts/mountain_report_water_names.py) and Ohio's city overflow notices (scripts/oh_report_water_names.py
--merge-notices). A named water with no record is a row with its county; a water a record holds is resolved; no water,
a storm drain, a tributary and a description are no row; a rerun replaces a feed's counts; the file's other rows keep
every field; nothing but water names, counties, counts, towns and source ids is written. Invented fixtures.
Run from pipeline/: python -m pytest tests -q
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from build import status as S  # noqa: E402
from common import ROOT  # noqa: E402


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


M = _load("report_names_merge")
OH = _load("oh_report_water_names")


class Stub:
    """The status resolver, stubbed: HELD names are placed on their record; the status build's own no-water reading
    (S.no_receiving_water) gives the rest's 'names no receiving water'."""

    def __init__(self, held=None, names=None):
        self.held = {M.key(k): v for k, v in (held or {}).items()}
        self.waters = {v: {"name": (names or {}).get(v, k)} for k, v in (held or {}).items()}

    def resolve(self, ev):
        slug = self.held.get(M.key(ev.get("waterbody_text")))
        if slug:
            return {"water_slugs": [slug]}
        nw = S.no_receiving_water(ev)
        return {"water_slugs": [], "no_receiving_water": nw} if nw else {"water_slugs": []}


def rec(i, water, county="Greenville", sid="sc-des-overflow-list", **kw):
    return {"event_id": f"{sid}:{i}", "source_id": sid, "event_type": "sso", "status": "ended",
            "waterbody_text": water, "npdes_permit": kw.pop("permit", None), "lat": kw.pop("lat", None),
            "lon": kw.pop("lon", None), "raw": {"state": kw.pop("state", "SC"), "county": county, **kw.pop("raw", {})},
            **kw}


def rows_of(j):
    return {(r["name"], r["county"]): r["reports"] for r in j["rows"].values()}


# ---------------------------------------------------------------- judging one feed

def test_a_named_water_with_no_record_is_a_row_with_its_county():
    j = M.judge([rec(1, "Maple Creek", "Spartanburg"), rec(2, "MAPLE CREEK", "Spartanburg")], "SC", Stub())
    assert rows_of(j) == {("Maple Creek", "Spartanburg County"): 2}       # a tie goes to the spelling not in capitals
    row = next(iter(j["rows"].values()))
    assert row["sources"] == {"sc-des-overflow-list": 2} and row["reports_by_source"] == {"sc-des-overflow-list": 2}
    assert "points" not in row          # the list gives no point


def test_one_name_in_two_counties_is_two_rows():
    j = M.judge([rec(1, "Brushy Creek", "Greenville"), rec(2, "Brushy Creek", "Anderson")], "SC", Stub())
    assert rows_of(j) == {("Brushy Creek", "Greenville County"): 1, ("Brushy Creek", "Anderson County"): 1}


def test_a_held_water_is_resolved_under_the_records_name():
    j = M.judge([rec(1, "Lake Murray", "Lexington"), rec(2, "lake murray", "Lexington")], "SC",
                Stub({"Lake Murray": "lake-murray-sc"}))
    assert not j["rows"]
    (e,) = j["resolved"].values()
    assert e["name"] == "Lake Murray" and e["reports"] == 2 and e["slugs"] == ["lake-murray-sc"]
    assert e["county"] == "Lexington County"


def test_a_filers_text_placed_on_a_record_is_listed_by_the_records_name():
    j = M.judge([rec(1, "possibly Flat Creek through a storm drain", "Teton", state="WY", sid="wy-deq-spill-list")],
                "WY", Stub({"possibly Flat Creek through a storm drain": "flat-creek-wy"}, {"flat-creek-wy": "Flat Creek"}))
    (e,) = j["resolved"].values()
    assert e["name"] == "Flat Creek" and e["slugs"] == ["flat-creek-wy"] and e["county"] == "Teton County"


@pytest.mark.parametrize("text", ["", "STORM DRAIN", "Not Applicable", "storm drain in parking lot", "DITCH",
                                  "Tributary to Gills Creek", "unnamed tributary of Rocky Creek",
                                  "storm drain to Gills Creek", "Pond on private property", "manhole",
                                  "EDGE OF CREEK", "Small Stream", "Conveyance Ditch", "Pond feeding Rawls Creek",
                                  "STREAM WEST OF KEITH DRIVE", "Monroeville", "Sediment Pond"])
def test_no_water_storm_drain_tributary_and_descriptions_give_no_row(text):
    j = M.judge([rec(1, text)], "SC", Stub())
    assert not j["rows"] and not j["resolved"]
    assert sum(j["left_out"].values()) == 1


def test_tributary_wording_is_counted_as_such():
    j = M.judge([rec(1, "Tributary to Gills Creek"), rec(2, "UT of Reedy River")], "SC", Stub())
    assert j["left_out"][M.TRIB] == 2


def test_a_chain_gives_its_first_water_as_the_names_pass_does():
    j = M.judge([rec(1, "Colleton Creek to Wappoo Cut to Ashley River", "Charleston")], "SC", Stub())
    assert rows_of(j) == {("Colleton Creek", "Charleston County"): 1}


def test_a_list_gives_each_water_and_a_held_part_is_resolved():
    j = M.judge([rec(1, "Broad River and Bush River", "Newberry")], "SC", Stub({"Broad River": "broad-river-sc"}))
    assert rows_of(j) == {("Bush River", "Newberry County"): 1}
    assert [e["name"] for e in j["resolved"].values()] == ["Broad River"]


def test_a_copy_counts_once():
    j = M.judge([rec(1, "Maple Creek"), rec(2, "Maple Creek", duplicate_of="sc-des-overflow-list:1")], "SC", Stub())
    assert sum(rows_of(j).values()) == 1 and j["left_out"][M.COPY] == 1


def test_a_record_point_is_kept_rounded_and_towns_come_from_the_operator():
    r = rec(1, "Garden Creek", "Natrona", state="WY", sid="wy-deq-spill-list", lat=42.81234, lon=-106.33456,
            permit="WY0000001")
    j = M.judge([r], "WY", Stub(), towns_of=lambda x: ["CASPER"] if x.get("npdes_permit") == "WY0000001" else [])
    (row,) = j["rows"].values()
    assert row["points"] == [[42.812, -106.335]] and row["towns"] == ["Casper"]


def test_willard_names_each_water_on_its_own_and_a_town_is_no_row():
    r = rec(1, "Jacob Creek; areas affected: West Branch of Huron River, Holiday Lakes, Monroeville", None,
            sid="oh-willard-cso-notices", state="OH",
            raw={"discharge_stream": "Jacob Creek",
                 "areas_affected": ["West Branch of Huron River", "Holiday Lakes", "Monroeville"]})
    r["raw"].pop("county")
    j = M.judge([r], "OH", Stub({"Holiday Lakes": "holiday-lakes-oh"}), names_of=OH.notice_names,
                county=OH.NOTICE_COUNTY["oh-willard-cso-notices"])
    assert rows_of(j) == {("Jacob Creek", "Huron County"): 1, ("West Branch of Huron River", "Huron County"): 1}
    assert [e["name"] for e in j["resolved"].values()] == ["Holiday Lakes"]
    assert j["left_out"][M.NO_KIND] == 1                 # Monroeville


def test_nothing_personal_passes():
    texts = ["STORM DRAIN AT [house number removed] N MARION STREET", "DITCH BEHIND CLANTONS",
             "[house number removed] spann road Ward South Carolina", "Mr. Smith's pond", "call 803-555-0100",
             "jdoe@example.com creek", "CREEK/DITCH LOCATED BETWEEN CARVING TRAIL AND S PARTRIDGE CIRCLE",
             "house number removed] LAZY COVE LANE"]
    j = M.judge([rec(i, t) for i, t in enumerate(texts)], "SC", Stub())
    assert not j["rows"]
    dumped = json.dumps({k: dict(v) for k, v in j.items() if k == "left_out"})
    for bit in ("MARION", "CLANTONS", "spann", "Smith", "555", "example.com", "PARTRIDGE", "LAZY"):
        assert bit not in dumped


# ---------------------------------------------------------------- merging into the file

def test_merge_keeps_other_rows_and_a_rerun_replaces_the_feeds_counts(tmp_path):
    p = tmp_path / "missing.json"
    p.write_text(json.dumps({"about": "x", "state": "SC", "rows": [
        {"name": "J. Strom Thurmond Reservoir", "county": None, "reports": 1, "sources": {"sc-des-hab": 1},
         "reason": "no NHD flowline or waterbody of that name in SC"}],
        "resolved": [{"name": "Jeffries Creek", "reports": 5, "slugs": ["jeffries-creek-sc"], "how": "record built"}],
        "build": {"date": "2026-11-15"}}))
    j = M.judge([rec(1, "Maple Creek", "Spartanburg"), rec(2, "Lake Murray", "Lexington")], "SC",
                Stub({"Lake Murray": "lake-murray-sc"}))
    for _ in range(2):
        M.merge(p, "SC", {"sc-des-overflow-list": j}, {"sc-des-overflow-list": "2 records"})
    d = json.loads(p.read_text())
    assert d["waters"] == 2 and d["reports"] == 2
    old = next(r for r in d["rows"] if r["name"] == "J. Strom Thurmond Reservoir")
    assert old["reason"].startswith("no NHD") and old["sources"] == {"sc-des-hab": 1}
    assert {r["name"]: r["reports"] for r in d["resolved"]} == {"Jeffries Creek": 5, "Lake Murray": 1}
    assert d["build"] == {"date": "2026-11-15"} and d["by_reason"]
    assert d["left_out"]["sc-des-overflow-list"] == {} and d["feeds_merged"]["sc-des-overflow-list"] == "2 records"


# ---------------------------------------------------------------- the committed files

PERSONAL = re.compile(r"@|\d{3}[-. )]\d{3}[-. ]\d{4}|\[|\]|\b(mr|mrs|ms|dr)\.?\s", re.I)


@pytest.mark.parametrize("st,sid", [("sc", "sc-des-overflow-list"), ("wy", "wy-deq-spill-list"),
                                    ("oh", "oh-willard-cso-notices")])
def test_committed_files_hold_only_water_names(st, sid):
    d = json.loads((ROOT / "research" / st / "receiving-waters-missing.json").read_text())
    mine = [r for r in d["rows"] if sid in (r.get("reports_by_source") or {})]
    assert mine, f"no {sid} row in research/{st}"
    for r in mine:
        assert M.name_problem(r["name"]) is None, r["name"]
        assert not PERSONAL.search(r["name"]), r["name"]
        assert set(r) <= {"name", "county", "reports", "open", "towns", "sources", "reports_by_source", "points",
                          "reason", "parts", "records", "places_failed", "kind"}
        assert r["county"] is None or r["county"].endswith("County")
    for reason in (d.get("left_out") or {}).get(sid, {}):
        assert not re.search(r"(^|\W)'|'(\W|$)", reason) and not PERSONAL.search(reason), reason


def test_committed_willard_rows():
    d = json.loads((ROOT / "research" / "oh" / "receiving-waters-missing.json").read_text())
    # Willard's two waters: a row while the names pass has not built the record, resolved once it has (Ohio's batch of
    # 2026-11-17 built west-branch-huron-river-oh; Jacob Creek has no NHD feature of that name and stays a row)
    names = {(r["name"], r.get("county")) for r in d["rows"] if "oh-willard-cso-notices" in (r.get("sources") or {})}
    want = {("Jacob Creek", "Huron County"), ("West Branch of Huron River", "Huron County")}
    built = {(r["name"], r.get("county")) for r in d.get("resolved") or [] if r.get("slugs")} & want
    assert names | built == want
    assert ("Jacob Creek", "Huron County") in names
