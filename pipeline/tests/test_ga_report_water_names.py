"""Georgia's report names rebuilt from the whole backfilled history (2026-11-04 final audit, P1-1):
scripts/ga_report_water_names.py (names counted once per spill, the reports that name no water left out, the file
merged so every row and resolved name keeps its fields), the name-pass rules the audit's names needed (Utoy Creek is
not 'UT oy Creek'; EPD's 'Dryland' is no water), the status resolver's town match for a consolidated city-county
(Butler Creek at Augusta), the aliases added for Georgia's reported spellings (each with the operator and place that
make its identity certain), the batch's names step, and the committed names file itself.
Run from pipeline/: python -m pytest tests -q
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from build import status as S  # noqa: E402
from common import ROOT, event  # noqa: E402
from ingest import waters_from_nhd as N  # noqa: E402

_spec = importlib.util.spec_from_file_location("ga_report_water_names", ROOT / "scripts" / "ga_report_water_names.py")
G = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(G)

if "state_batch" in sys.modules:             # tests/test_state_batch.py loaded it already
    B = sys.modules["state_batch"]
else:
    _bspec = importlib.util.spec_from_file_location("state_batch", ROOT / "scripts" / "state_batch.py")
    B = importlib.util.module_from_spec(_bspec)
    sys.modules["state_batch"] = B          # dataclasses look their module up there
    _bspec.loader.exec_module(B)


def epd(rid, water, dup=None, **kw):
    return {"event_id": f"ga-epd-spills:{rid}", "source_id": "ga-epd-spills", "waterbody_text": water,
            "duplicate_of": dup and f"ga-epd-spills:{dup}", "npdes_permit": kw.pop("permit", "GA0000001"),
            "raw": {"posting_date": kw.pop("posted", "2026-11-02"), "_first_seen_posting": kw.pop("first", None)}, **kw}


def epa(rid, water, pair=None, permit="GA0000001"):
    return {"event_id": f"echo-sewer-overflow:{rid}", "source_id": "echo-sewer-overflow", "waterbody_text": water,
            "duplicate_of": pair and f"ga-epd-spills:{pair}", "npdes_permit": permit, "raw": {}}


class NoWater:
    """The status resolver's verdict, stubbed: these texts name no receiving water."""

    def __init__(self, *texts):
        self.texts = {t.lower() for t in texts}

    def resolve(self, ev):
        return {"no_receiving_water": "placeholder" if str(ev.get("waterbody_text")).lower() in self.texts else None}


# ---------------------------------------------------------------- names and spills

def test_a_name_is_case_and_punctuation_aside_but_its_words_stay_apart():
    assert G.key("NANCY CREEK") == G.key("Nancy Creek.") == "nancy creek"
    assert G.key("SOUTHRIVER") != G.key("South River")      # a spelling a record does not hold, kept apart for an alias
    assert G.split_names("Utoy Creek; UTOY CREEK;  Sandy  Creek ;") == ["Utoy Creek", "Sandy Creek"]
    assert G.split_names(None) == [] and G.split_names(" ; ") == []


def test_a_spill_is_counted_once_whichever_reports_give_it():
    recs = [epd("a", "Nancy Creek"), epa("1", "NANCY CREEK", pair="a"),              # EPA's copy of EPD's row
            epd("b", "Utoy Creek"), epd("b2", "Utoy Creek", dup="b"),                 # a row and its correction
            epd("c", "Proctor Creek"), epa("2", "Tributary to Proctor Creek", pair="c"),   # two spellings, one spill
            epa("3", "Nancy Creek")]                                                   # EPA alone: another spill
    assert len(G.spills(recs)) == 4
    reports, spell, seen = G.count_names(recs)
    assert reports == {"nancy creek": 2, "utoy creek": 1, "proctor creek": 1, "tributary to proctor creek": 1}
    assert spell["nancy creek"] == {"Nancy Creek": 2, "NANCY CREEK": 1}
    assert seen["nancy creek"] == {"EPD list", "EPA reports"} and seen["utoy creek"] == {"EPD list"}
    assert G.spelling(spell["nancy creek"]) == "Nancy Creek"
    assert G.spelling({"UTOY CREEK": 1, "Utoy Creek": 1}) == "Utoy Creek"          # a tie: not the one in capitals


def test_reports_that_name_no_water_are_not_counted():
    recs = [epd("a", "Not Applicable"), epd("b", ""), epd("c", None), epd("d", "Nancy Creek"),
            epa("1", "Nancy Creek", pair="a")]                     # EPD said N/A, EPA named the creek: it counts once
    named = G.with_a_water(recs, NoWater("not applicable"))
    assert [r["event_id"] for r in named] == ["ga-epd-spills:d", "echo-sewer-overflow:1"]
    assert G.count_names(named)[0] == {"nancy creek": 2}


def test_the_status_resolvers_own_no_water_verdict_is_the_one_used():
    res = S.Resolver({}, [], {}, {}, {})
    for text in ("Not Applicable", "N/A", "Did Not Enter State Waters", "None"):
        ev = event(source_id="ga-epd-spills", source_record_id=text, event_type="sso", waterbody_text=text,
                   raw={"state": "GA"})
        assert res.resolve(ev).get("no_receiving_water"), text
    ev = event(source_id="ga-epd-spills", source_record_id="n", event_type="sso", waterbody_text="Nancy Creek",
               raw={"state": "GA"})
    assert not res.resolve(ev).get("no_receiving_water")


def test_kinds_for_new_rows():
    assert G.kind_of("Nancy Creek") == "named water"
    assert G.kind_of("Tributary of Utoy Creek") == "tributary of a named water"
    assert G.kind_of("stormwater system") == G.kind_of("Dryland") == "storm system or not a named water"


# ---------------------------------------------------------------- the merge

OLD = {"about": "old", "checked": "2026-11-04", "state": "GA", "waters": 2, "reports": 9,
       "build": {"date": "2026-11-04", "command": "python -m ingest.waters_from_nhd --names x --state GA"},
       "rows": [
           {"name": "Shoals Creek", "reports": 8, "seen_in": ["EPA reports"], "kind": "named water",
            "points": [[33.7, -84.2]], "towns": ["Decatur"], "reason": "1 NHD water of that name in GA, none within reach",
            "places_failed": [{"town": "Decatur", "reason": "far"}]},
           {"name": "Panther Ct.", "reports": 1, "kind": "storm system or not a named water",
            "reason": "a street name, not a water"}],
       "resolved": [{"name": "Peachtree Creek", "reports": 30, "slugs": ["peachtree-creek-ga"],
                     "how": "record built from the name", "towns": ["Atlanta"]}]}


def test_the_merge_keeps_every_row_and_resolved_name_with_its_fields(tmp_path):
    f = tmp_path / "names.json"
    f.write_text(json.dumps(OLD))
    ev = tmp_path / "events"
    ev.mkdir()
    (ev / "ga-epd-spills.json").write_text(json.dumps({"records": [
        epd("a", "SHOALS CREEK"), epd("b", "Peachtree Creek"), epd("c", "Nancy Creek", first="2025-10-09"),
        epd("d", "Nancy Creek"), epd("e", "Not Applicable")]}))
    (ev / "echo-sewer-overflow.json").write_text(json.dumps({"records": [
        epa("1", "Shoals Creek", pair="a"), epa("2", "Utoy Creek"), epa("3", "Elsewhere Creek", permit="NC0000001")]}))
    out = G.build(ev, f, places=False, resolver=NoWater("not applicable"))
    meta, rows = N.read_names_file(f)                     # the shape waters_from_nhd --names reads
    d = json.loads(f.read_text())
    by = {r["name"]: r for r in rows}
    old = OLD["rows"][0]
    assert {k: by["Shoals Creek"][k] for k in old if k not in ("reports", "seen_in")} == \
        {k: v for k, v in old.items() if k not in ("reports", "seen_in")}           # reason, places, kind kept
    assert by["Shoals Creek"]["reports"] == 1 and by["Shoals Creek"]["seen_in"] == ["EPA reports", "EPD list"]
    assert by["Panther Ct."] == {**OLD["rows"][1]}                 # no report gives it now: kept, count and all
    assert by["Nancy Creek"] == {"name": "Nancy Creek", "reports": 2, "seen_in": ["EPD list"], "kind": "named water"}
    assert by["Utoy Creek"]["seen_in"] == ["EPA reports"]
    assert "Elsewhere Creek" not in by and "Not Applicable" not in by     # another state's permit; no water
    res = {r["name"]: r for r in d["resolved"]}
    assert res["Peachtree Creek"] == {**OLD["resolved"][0], "reports": 1}       # its own shape, its count brought up
    assert [r["name"] for r in rows] == ["Nancy Creek", "Panther Ct.", "Shoals Creek", "Utoy Creek"]   # most first
    assert d["checked"] == "2026-11-04" and d["build"] == OLD["build"] and d["waters"] == 4
    assert "2025-10-09 to 2026-11-02" in d["about"] and "2 records" in d["about"]
    assert out["before"]["names"] == 2 and out["after"]["names"] == 4 and out["new"] == 2
    again = G.build(ev, f, places=False, resolver=NoWater("not applicable"))     # a second run changes nothing
    assert again["new"] == 0 and json.loads(f.read_text()) == d


def test_no_epd_records_writes_nothing(tmp_path):
    f = tmp_path / "names.json"
    f.write_text(json.dumps(OLD))
    with pytest.raises(SystemExit, match="run the Georgia feeds first"):
        G.build(tmp_path, f, places=False, resolver=NoWater())
    assert json.loads(f.read_text()) == OLD


# ---------------------------------------------------------------- the name pass's rules

@pytest.mark.parametrize("text,parts,trib", [
    ("Utoy Creek", ["Utoy Creek"], False),
    ("UTOY CREEK", ["UTOY CREEK"], False),
    ("Tributary of Utoy Creek", ["Utoy Creek"], True),
    ("Utica Drain", ["Utica Drain"], False),
    ("Untitled Creek", ["Untitled Creek"], False),
    ("UT Eno River", ["Eno River"], True),
    ("UT of Mill Creek", ["Mill Creek"], True),
    ("UNT to Crooked Creek", ["Crooked Creek"], True),
    ("Trib. of Cooper Creek", ["Cooper Creek"], True),
])
def test_a_tributary_abbreviation_ends_at_a_words_end(text, parts, trib):
    got, why, t = N.report_name_parts(text)
    assert (got, why, t) == (parts, None, trib)


@pytest.mark.parametrize("text", ["Dryland", "Dry Land", "dry land overflow", "Dry-land"])
def test_dry_land_is_no_water(text):
    assert N.report_name_parts(text) == ([], "dry land, not a water: the report names no receiving water", False)


def test_a_creek_named_dry_is_still_a_water():
    assert N.report_name_parts("Dry Creek")[0] == ["Dry Creek"]
    assert N.report_name_parts("Dryland Creek")[0] == ["Dryland Creek"]


# ---------------------------------------------------------------- a consolidated city-county is its city's town

def test_consolidated_town_keys():
    assert S.water_town_keys(["Augusta-Richmond County consolidated government (balance)", "Grovetown"]) == \
        {"augusta richmond county consolidated government", "augusta", "grovetown"}
    assert "athens" in S.water_town_keys(["Athens-Clarke County unified government (balance)"])
    assert "macon" in S.water_town_keys(["Macon-Bibb County"])
    assert "louisville" in S.water_town_keys(["Louisville/Jefferson County metro government (balance)"])
    assert S.water_town_keys(["Lake County", "Johns Creek", "", None]) == {"lake county", "johns creek"}


def _butler():
    line = lambda x0, y0: {"type": "LineString", "coordinates": [[x0, y0], [x0 + 0.05, y0 + 0.02]]}  # noqa: E731
    waters = {
        "butler-creek-ga": {"slug": "butler-creek-ga", "name": "Butler Creek", "kind": "stream", "state": "GA",
                            "towns": ["Augusta-Richmond County consolidated government (balance)", "Grovetown"],
                            "bbox": [-82.1, 33.38, -82.05, 33.40], "geometry": line(-82.1, 33.38)},
        "butler-creek-kennesaw-ga": {"slug": "butler-creek-kennesaw-ga", "name": "Butler Creek", "kind": "stream",
                                     "state": "GA", "towns": ["Acworth", "Kennesaw"],
                                     "bbox": [-84.66, 34.0, -84.61, 34.02], "geometry": line(-84.66, 34.0)}}
    return S.Resolver(waters, [], {"ga-augusta-utilities": ["Augusta"]}, {}, {})


def test_a_report_with_no_point_takes_the_record_in_its_operators_consolidated_city():
    saved = S._STATES
    S._STATES = {"GA"}
    try:
        res = _butler()
        ev = event(source_id="echo-sewer-overflow", source_record_id="1", event_type="sso",
                   discharger_id="ga-augusta-utilities", waterbody_text="Butler Creek", raw={"state": "GA"})
        assert res.by_name("Butler Creek", "GA", None, None, ev)[0] == ["butler-creek-ga"]
        assert res.town_conflict(ev, "butler-creek-ga") is None
        assert res.town_conflict(ev, "butler-creek-kennesaw-ga")          # Kennesaw's is still another water
    finally:
        S._STATES = saved


# ---------------------------------------------------------------- the aliases, each with what makes it certain

# (record, the spelling as reported, the operator and permit that reported it, where: the report's city and county)
ALIASES = [
    ("chattahoochee-river-ga", "Chattachoochee", "Douglasville-Douglas County Water & Sewerage Authority", "GA0047201",
     "Douglasville (Chattahoochee basin)"),
    ("south-river-ga", "SOUTHRIVER", "City of Atlanta Department of Watershed Management", "GA0039012",
     "Atlanta, Fulton County"),
    ("intrenchment-creek-ga", "Intreachment Creek", "City of Atlanta Department of Watershed Management", "GA0039012",
     "Atlanta, DeKalb County"),
    ("south-fork-peachtree-creek-ga", "South Fork Peachtree Crek", "DeKalb County Department of Watershed Management",
     "GA0024147", "DeKalb County"),
    ("north-fork-peachtree-creek-ga", "North Fork Peachtree", "(none named)", None, "Atlanta, DeKalb County"),
    ("sugar-creek-valdosta-ga", "Sugar Crek", "City of Valdosta (Withlacoochee WPCP)", "GA0033235",
     "Valdosta, its point 3.6 km from the record"),
    ("spirit-creek-ga", "Spirt Creek", "Augusta Utilities (J.B. Messerly WPCP)", "GA0037621", "Augusta, Richmond County"),
    ("lake-tobesofkee-ga", "Lake Tobesofke", "Macon Water Authority (Rocky Creek WRF)", "GA0024546",
     "Macon, Bibb County"),
    ("lindsey-creek-ga", "Lindsay Creek", "Columbus Water Works (South WRF)", "GA0020516", "Columbus, Muscogee County"),
    ("mossy-creek-cleveland-ga", "Mossey Creek", "City of Cleveland (Cleveland WPCP)", "GA0036820",
     "Cleveland, White County, its point inside the record's extent"),
    ("barbashela-creek-ga", "Babashela Creek", "DeKalb County Department of Watershed Management", "GA0024147",
     "Stone Mountain, DeKalb County"),
    ("pipe-makers-canal-ga", "Pipemakers Canal", "City of Savannah (President Street reuse)", "GAU020198",
     "Savannah, Chatham County"),
    ("little-cotton-indian-creek-ga", "Litle Cotton Indian Creek", "Henry County Water Authority (Walnut Creek WRF)",
     None, "Stockbridge, Henry County"),
]


def test_each_georgia_alias_is_on_file_for_a_georgia_record_in_the_reporting_operators_place():
    aliases = json.loads((ROOT / "data" / "water-aliases.json").read_text())
    waters = S.load_waters(include_nhd=True)
    for slug, text, operator, permit, where in ALIASES:
        assert text in aliases.get(slug, []), (slug, text)
        w = waters.get(slug)
        assert w and w.get("state") == "GA", slug
        assert G.key(text) != G.key(w["name"]), text                 # a spelling the record's name does not give
        assert operator and where


def test_a_report_of_each_aliased_spelling_reaches_its_record():
    waters = S.load_waters(include_nhd=True)
    saved = S._STATES
    S._STATES = {"GA"}
    try:
        res = S.Resolver(waters, [], {}, {}, {})
        for slug, text, *_ in ALIASES:
            got = res.by_name(text, "GA", None, None, {"raw": {"state": "GA"}, "waterbody_text": text})[0]
            assert slug in got, (text, got)
    finally:
        S._STATES = saved


# ---------------------------------------------------------------- the batch's names step

PY = "/py"
OBL_REL = "../../openboatlaunch/out/water"


def test_names_step_runs_the_report_names_pass():
    assert B.parse_steps("ties names waters") == ["waters", "names", "ties"]
    p = B.plan("GA", "names ties", "1500", "1000", py=PY)
    assert [(c.step, c.cwd, c.argv, c.env) for c in p.cmds] == [
        ("names", "pipeline", [PY, "-m", "ingest.waters_from_nhd", "--names", "../research/ga/receiving-waters-missing.json",
                               "--state", "GA", "--budget-s", "1500", "--max-requests", "1000"],
         {"OBL_WATER_DIR": OBL_REL}),
        ("ties", "pipeline", [PY, "-m", "ingest.outfall_waters", "--state", "GA"], {"OBL_WATER_DIR": OBL_REL})]
    assert "research/ga/receiving-waters-missing.json" in B.candidate_files("GA")
    assert B.count_lines("names", ["report names GA: 283 names, 141 waters to build", "noise", "3 records -> x"]) == \
        ["report names GA: 283 names, 141 waters to build", "3 records -> x"]


def test_names_step_refused_without_a_names_file_or_over_the_budget(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "receiving-waters-national.json").write_text(json.dumps({"states": {"GA": {}, "AL": {}}}))
    with pytest.raises(B.Refused, match="research/al/receiving-waters-missing.json is not on file"):
        B.plan("AL", "names ties", py=PY, root=tmp_path)
    assert B.plan("GA", "waters names ties", py=PY).cmds                  # 1500 twice and 180 twice: within 3,780
    with pytest.raises(B.Refused, match="second NHD pass"):
        B.plan("GA", "waters names ties", budget_s=1800, py=PY)
    with pytest.raises(B.Refused, match="second NHD pass"):
        B.plan("GA", "osm names ties", py=PY)                             # 1500 twice, 1200 and 180


def test_the_workflow_offers_the_names_step():
    text = (ROOT / ".github" / "workflows" / "state-build.yml").read_text()
    assert "registry waters osm names ties" in text


# ---------------------------------------------------------------- the committed file

def test_georgias_names_file_covers_every_name_with_a_record_or_a_reason():
    meta, rows = N.read_names_file(ROOT / "research" / "ga" / "receiving-waters-missing.json")
    d = json.loads((ROOT / "research" / "ga" / "receiving-waters-missing.json").read_text())
    assert meta["state"] == "GA" and all(r.get("reason") for r in rows)
    assert [r["reports"] for r in d["rows"]] == sorted((r["reports"] for r in d["rows"]), reverse=True)
    names = {r["name"] for r in rows} | {r["name"] for r in d["resolved"]}
    assert {"Nancy Creek", "Utoy Creek", "Rocky Creek", "Butler Creek", "Shoal Creek", "Camp Creek"} <= names
    res = {r["name"]: r for r in d["resolved"]}
    assert res["Butler Creek"]["slugs"] == ["butler-creek-ga"]
    assert "1,366 records" in d["about"] and "894 records" in d["about"]
