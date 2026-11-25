DFR = {"Results": {
    "Message": "Success",
    "SystemExtractDates": {"Dates": [{"EPASystem": "ICIS-NPDES", "SystemExtractDate": "10/30/2026"}]},
    "SBEEventTotals": {"Sources": []},
    "CWASECompliance": {"Header": {"Qtr1Start": "07/01/2026", "Qtr1End": "09/30/2026"},
                        "Sources": [{"Violations": [
                            {"ViolationDesc": "Bypass of treatment unit", "NPDESViolationId": "v1", "SourceID": "s1",
                             "Agency": "State", "Qtr1Value": "08/03/2026"},
                            {"ViolationDesc": "Dry weather SSO", "NPDESViolationId": "v2", "SourceID": "s1",
                             "Agency": "State", "Qtr1Value": "08/10/2026 - 08/11/2026"}]}]}}}
PERMIT = "RI0100999"
"""Public records pass unchanged; internal repository notes remain private."""
import json
import sys
from pathlib import Path
import pytest
import common
from export import build as X
from ingest import ri_echo_dfr as D, ri_nbc as N


def strings(o):
    if isinstance(o, dict):
        for v in o.values():
            yield from strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from strings(v)
    elif isinstance(o, str):
        yield o

def test_name_scrub_leaves_ordinary_wording_alone():
    for t in ("The DH Inspector conducted re-inspection on November 3", "The inspector got in touch with the landlord",
              "Inspector General report", "Avoid contact with these water bodies for 48 hours after the discharge",
              "Chlorine Contact Tank at the plant", "lagoon flowed into the Contact Chamber at 3 am",
              "Property owner contact WPCA 12:20 p.m.", "Contacted DEEP by phone at 9:45 a.m.",
              "contact Customer Service at the city", "DPH contacted Jacobs to investigate"):
        assert common.scrub_text(t) == t, t

def test_repo_paths_are_told_from_source_text():
    assert common.has_repo_path("first receiving water in research/ri/dischargers.json")
    assert common.has_repo_path("research/ri/raw/nbc-outfalls-from-api.csv (inferred from site names and coordinates)")
    assert common.has_repo_path("ECHO outfall registry (data/outfalls-new-england.json)")
    assert common.has_repo_path("cached in data/raw/ri-nbc/")
    for t in ("Because there is no flow data/pump speed data, the City reported the maximum",
              "https://www.ri.gov/data/press/release.pdf", "20240404_Cessation_SSO_Pearl_St.pdf", "in/out/of service", 42, None):
        assert not common.has_repo_path(t), t

def test_path_notes_move_from_raw_to_meta():
    recs = [{"event_id": "x:1", "raw": {"keep": "ECHO says 3 days", "water_basis": "first receiving water in research/ri/dischargers.json",
                                        "placement": {"basis": "research/ri/raw/a.csv", "by": "Wilson Reservoir"},
                                        "list": ["ok", "data/outfalls-new-england.json"]}},
            {"event_id": "x:2", "raw": {"keep": 1}}]
    meta = common.path_notes_to_meta(recs, {"records": 2})
    assert recs[0]["raw"] == {"keep": "ECHO says 3 days", "placement": {"by": "Wilson Reservoir"}, "list": ["ok"]}
    assert meta == {"records": 2, "internal_notes": {"x:1": {
        "water_basis": "first receiving water in research/ri/dischargers.json",
        "placement.basis": "research/ri/raw/a.csv", "list[1]": "data/outfalls-new-england.json"}}}
    assert recs[1]["raw"] == {"keep": 1}

def test_ri_echo_dfr_writes_no_file_paths_into_raw(tmp_path, monkeypatch):
    raw_dir, ev_dir, data_dir = tmp_path / "raw", tmp_path / "events", tmp_path / "data"
    (raw_dir / D.SOURCE_ID).mkdir(parents=True)
    (raw_dir / D.SOURCE_ID / f"20261101T000000Z.{PERMIT}.json").write_text(json.dumps(DFR))
    ev_dir.mkdir()
    data_dir.mkdir()
    (data_dir / "outfalls-new-england.json").write_text(json.dumps({"outfalls": []}))
    # a record from an earlier run that ECHO no longer lists, written when raw still carried the path
    old = common.event(source_id=D.SOURCE_ID, source_record_id="old", event_type="bypass", status="ended",
                       npdes_permit=PERMIT, raw={"water_basis": "bypass at the treatment plant; plant receiving water: "
                                                                "first receiving water in research/ri/dischargers.json"})
    (ev_dir / f"{D.SOURCE_ID}.json").write_text(json.dumps({"records": [old]}))
    monkeypatch.setattr(D, "RAW_DIR", raw_dir)
    monkeypatch.setattr(D, "EVENTS_DIR", ev_dir)
    monkeypatch.setattr(D, "DATA_DIR", data_dir)
    monkeypatch.setattr(common, "EVENTS_DIR", ev_dir)
    monkeypatch.setattr(D, "permits", lambda: [{"npdes_permit": PERMIT, "id": "ri-test", "name": "Test WWTF",
                                                "water_slugs": ["test-river-ri"], "receiving_waters": ["Test River"]}])
    assert D.main(["--from-raw"]) == 0
    out = json.loads((ev_dir / f"{D.SOURCE_ID}.json").read_text())
    recs = {r["source_record_id"]: r for r in out["records"]}
    assert set(recs) == {"v1", "v2", "old"}
    for r in out["records"]:
        assert not [t for t in strings(r["raw"]) if common.has_repo_path(t)], r["raw"]
    assert recs["v1"]["water_slugs"] == ["test-river-ri"]
    assert recs["v1"]["raw"]["water_basis"] == ("bypass at the treatment plant; plant receiving water: "
                                                "the discharger's first listed receiving water")
    assert out["meta"]["water_basis_files"] == D.WATER_BASIS_FILES
    assert out["meta"]["internal_notes"] == {old["event_id"]: {"water_basis": old["raw"]["water_basis"]}}

def test_ri_nbc_record_raw_names_no_files():
    info = {"system": next(iter(N.DISCHARGERS)), "code": "OF-035", "site": "Moshassuck River at Charles St",
            "placement": {"inferred_names": ["Moshassuck River"], "nearest_waters_m": []},
            "waterbody_text": "Moshassuck River", "water_slugs": [], "water_match": "none"}
    rec = N.to_record("OF-035|2026-11-01T10:00", {"info": info, "state": "ongoing", "started_at": "2026-11-01T10:00:00-04:00",
                                                  "first_seen_at": "2026-11-01T14:05:00Z", "pins_raw": {"SITE_ID": 35}})
    assert rec["raw"]["water_placement"]["basis"] == "inferred from the outfall's site name and coordinates"
    assert rec["raw"]["water_placement"]["inferred_names"] == ["Moshassuck River"]
    assert not [t for t in strings(rec["raw"]) if common.has_repo_path(t)]
    assert str(N.OUTFALL_CSV.relative_to(N.ROOT)) == "research/ri/raw/nbc-outfalls-from-api.csv"

def test_number_ranges_with_units_are_not_phone_numbers():
    """common.scrub_text (and so strip_personal on every module's raw) keeps "500-1000 feet" and "10-20 gallons",
    and still removes phone numbers (review 2026-11-04 P2-1)."""
    from common import scrub_text, strip_personal
    for t in ("Hammond Branch, about 500-1000 feet away", "10-20 gallons", "spilled 100-1500 gallons",
              "from 830-1030 am", "rose 100-1500% overnight"):
        assert scrub_text(t) == t and strip_personal({"note": t}) == {"note": t}, t
    for t in ("call 410-555-0199", "or 555-0199 after hours", "(410) 555-0199", "410.555.0199"):
        assert scrub_text(t) == t, t

def test_operator_names_are_not_taken_for_a_persons_name():
    for name in ("Robert T Savely WRF", "Kelly Twp Muni Auth", "William E Dunn WRF", "Martha Elementary",
                 "Glen Echo Resort", "Calvin PWA", "Pat Example Utilities", "Town of Example", "Example Water Authority",
                 "[name removed]", "", None):
        r = common.event(source_id="x-test", source_record_id="3", discharger_name=name)
        assert r["discharger_name"] == name, name

def test_operator_names_with_a_facility_abbreviation_or_business_word_are_kept():
    """Operator names that read like a person's name but carry a facility abbreviation, a school or district
    abbreviation or a business word (placeholders here, not real operators)."""
    for name in ("Pat Example Foods", "Pat Example Elem", "Pat Example Elem Sch", "Pat Example PSD", "Pat Example WWSL",
                 "Pat Example RWRF", "Pat Example AWTF", "Pat Example WQTC", "Pat Example Subdiv", "Pat Example CSOs",
                 "Pat Example MUA", "Pat Example MSD", "Pat Example Univ", "Pat Example Products", "Pat Example Mfg",
                 "Pat Example Campground", "Pat Example Nursing Home", "Pat Example & Sons"):
        r = common.event(source_id="x-test", source_record_id="4", discharger_name=name, discharger_id="op-1")
        assert r["discharger_name"] == name and r["discharger_id"] == "op-1", name

def test_a_works_building_a_complex_or_a_count_is_not_a_household():
    from common import scrub_text
    for keep in ("Pump House 2 Example Rd overflowed",
                 "300 ft south of the Gate House at 4650 Example Country Club Blvd",
                 "Example Lakes Apartment Homes at 100 Example Way reported a leak",
                 "a leak at Example Place Condo located at 120 S. Example Blvd",
                 "customers 1500 East of the plant lost service"):
        assert scrub_text(keep) == keep, keep
    assert scrub_text("Area Around SMH # 3800 & House 119 Example Ave") == \
        "Area Around SMH # 3800 & House 119 Example Ave"
    assert scrub_text("BEHIND THE RESIDENTS OF 6328 EXAMPLE AVE") == "BEHIND THE RESIDENTS OF 6328 EXAMPLE AVE"

def _permit_names():
    root = Path(__file__).resolve().parents[2]
    if str(root / "scripts") not in sys.path:
        sys.path.insert(0, str(root / "scripts"))
    import permit_names
    return permit_names


@pytest.mark.parametrize('text', [
    'Inspector Jane Example contacted Pat Example at 212-555-0123.',
    'A resident at 123 Sample Road reported sewage; jane@example.org.',
    'Contact Jane Example at the plant. Very respectfully, Pat Example, P.G.',
    'Two homes at 123 and 125 Sample Road; Route 9; 3 hours.',
])
def test_public_text_and_contact_fields_are_preserved_at_every_depth(text):
    for fn in (common.scrub_text, common.scrub_names, common.scrub_residence_numbers, common.strip_house_numbers):
        assert fn(text) == text
    obj = {'inspector': text, 'email': text, 'raw': {'details': [{'contact': text}]}}
    assert common.strip_personal(obj) == obj
    assert X.public_event({'event_id': 's:1', 'source_id': 's', 'raw': obj, 'outfall_name': text})['raw'] == obj

@pytest.mark.parametrize('name', ['Jane Example', 'Pat Example - City of Exampleton',
                                  'Pat Example d/b/a Example Water', 'Quill Family Trust'])
def test_public_permit_holder_and_operator_names_stay(name, tmp_path):
    pn = _permit_names()
    import private_utilities as pu
    assert pn.scrub_permit_name(name) == (name, False)
    assert pn.holder_name(name, 'ZZ0000001') == (name, False)
    assert pu.public_name(name) == name
    rec = common.event(source_id='s', source_record_id='1', discharger_name=name)
    assert rec['discharger_name'] == name
    path = tmp_path / 'events.json'
    common.write_events('s', [rec], path=path)
    assert json.loads(path.read_text())['records'][0]['discharger_name'] == name
    rows = [{'permit_name': name}]
    assert pn.scrub_rows(rows) == {} and rows == [{'permit_name': name}]
