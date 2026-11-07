"""Personal data and pipeline notes stay out of the public record: staff-name keys and staff names in
free text (strip_personal / scrub_text), notes naming repository files moved from raw to the events
file's meta by the Rhode Island ingesters, and the export's second pass over events files written
before a rule existed. Run from pipeline/: python -m pytest tests -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import common  # noqa: E402
from export import build as X  # noqa: E402
from ingest import ri_echo_dfr as D  # noqa: E402
from ingest import ri_nbc as N  # noqa: E402


def strings(o):
    if isinstance(o, dict):
        for v in o.values():
            yield from strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from strings(v)
    elif isinstance(o, str):
        yield o


# ---------------------------------------------------------------- keys

def test_strip_personal_drops_staff_keys_in_any_spelling():
    out = common.strip_personal({
        "inspector": "Eddy", "Inspector Name": "Eddy", "investigator": "Wood", "INVESTIGATOR_EMAIL": "x",
        "signed_by": "Tom Watson", "Signed By": "Tom Watson", "submitted_by_name": "Ann Lee", "SubmittedBy": "Ann",
        "assigned_to": "Inspector Simoes", "reviewed-by": "R", "approved_by": "A", "certified_by": "C", "signature": "N. S.",
        "details": [{"investigator_name": "Ortiz", "step": "landlord called"}],
        # kinds and identifiers, not people; and the water a record names
        "inspector_id": "17", "inspection_type": "routine", "investigation": "closed",
        "Name of Receiving Water": "Charles River", "reporterClass": "Permittee"})
    assert out == {"details": [{"step": "landlord called"}], "inspector_id": "17", "inspection_type": "routine",
                   "investigation": "closed", "Name of Receiving Water": "Charles River", "reporterClass": "Permittee"}


# ---------------------------------------------------------------- free text

def test_staff_names_in_free_text_are_scrubbed():
    s = common.scrub_text
    assert s("•\tCase was assigned to Inspector Eddy on 11/18/2025.•\tInspector Eddy spoke with the landlord") == \
        "•\tCase was assigned to Inspector [name removed] on 11/18/2025.•\tInspector [name removed] spoke with the landlord"
    assert s("Case was assigned to Inspector Tom Watson on 03/12/2025") == "Case was assigned to Inspector [name removed] on 03/12/2025"
    assert s("DPH said they sent Inspector Harvey, who contacted landlord") == "DPH said they sent Inspector [name removed], who contacted landlord"
    assert s("Investigator J. Smith visited") == "Investigator [name removed] visited"
    assert s("Please contact Jane Doe at 413-555-1212 or contact Mr. Brown at the plant.") == \
        "Please contact [name removed] at [phone removed] or contact [name removed] at the plant."
    assert s("Contacted Bob at 9:45") == "Contacted [name removed] at 9:45"


def test_name_scrub_leaves_ordinary_wording_alone():
    for t in ("The DH Inspector conducted re-inspection on November 3", "The inspector got in touch with the landlord",
              "Inspector General report", "Avoid contact with these water bodies for 48 hours after the discharge",
              "Chlorine Contact Tank at the plant", "lagoon flowed into the Contact Chamber at 3 am",
              "Property owner contact WPCA 12:20 p.m.", "Contacted DEEP by phone at 9:45 a.m.",
              "contact Customer Service at the city", "DPH contacted Jacobs to investigate"):
        assert common.scrub_text(t) == t, t


def test_strip_personal_scrubs_names_at_any_depth():
    out = common.strip_personal({"How incident was resolved": "Inspector Wood spoke with the landlord",
                                 "steps": [{"note": "contact Ann Lee at the town hall"}]})
    assert out == {"How incident was resolved": "Inspector [name removed] spoke with the landlord",
                   "steps": [{"note": "contact [name removed] at the town hall"}]}


# ---------------------------------------------------------------- repository paths

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


# ---------------------------------------------------------------- Rhode Island ingesters

PERMIT = "RI0100999"
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
    assert str(N.OUTFALL_CSV.relative_to(N.ROOT)) == "research/ri/raw/nbc-outfalls-from-api.csv"   # named in meta instead


# ---------------------------------------------------------------- export

def test_export_scrubs_events_written_under_older_rules():
    e = {"event_id": "ct-deep-annual:1", "outfall_name": "Outfall 004 (Inspector Eddy)", "advice_text": "Avoid contact for 48 hours",
         "raw": {"How incident was resolved": "Case was assigned to Inspector Eddy on 04/11/2025.", "inspector": "Eddy",
                 "_water": {"via": "ECHO outfall registry (data/outfalls-new-england.json)", "slug": "x"}}}
    out = X.public_event(e)
    assert out["raw"] == {"How incident was resolved": "Case was assigned to Inspector [name removed] on 04/11/2025.",
                          "_water": {"slug": "x"}}
    assert out["outfall_name"] == "Outfall 004 (Inspector [name removed])"
    assert out["advice_text"] == "Avoid contact for 48 hours"
    assert e["raw"]["inspector"] == "Eddy"                       # the input is not changed


def test_number_ranges_with_units_are_not_phone_numbers():
    """common.scrub_text (and so strip_personal on every module's raw) keeps "500-1000 feet" and "10-20 gallons",
    and still removes phone numbers (review 2026-11-04 P2-1)."""
    from common import scrub_text, strip_personal
    for t in ("Hammond Branch, about 500-1000 feet away", "10-20 gallons", "spilled 100-1500 gallons",
              "from 830-1030 am", "rose 100-1500% overnight"):
        assert scrub_text(t) == t and strip_personal({"note": t}) == {"note": t}, t
    for t in ("call 410-555-0199", "or 555-0199 after hours", "(410) 555-0199", "410.555.0199"):
        assert "[phone removed]" in scrub_text(t), t


# ---------------------------------------------------------------- a person's name as the discharger (re-check R8)

def test_a_discharger_name_that_is_only_a_persons_name_is_removed_and_the_permit_stays():
    for name in ("Pat Example", "PAT EXAMPLE", "pat example", "Pat Q. Example"):
        r = common.event(source_id="x-test", source_record_id="1", discharger_name=name, npdes_permit="XX0000001",
                         discharger_id=name.lower().replace(".", "").replace(" ", "-"))
        assert r["discharger_name"] == "[name removed]", name
        assert r["npdes_permit"] == "XX0000001" and r["discharger_id"] == "XX0000001", name
        assert "example" not in json.dumps(r).lower(), name
    # an operator's own id that does not carry the name stays
    r = common.event(source_id="x-test", source_record_id="2", discharger_name="Pat Example", discharger_id="op-17")
    assert r["discharger_name"] == "[name removed]" and r["discharger_id"] == "op-17"


def test_operator_names_are_not_taken_for_a_persons_name():
    for name in ("Robert T Savely WRF", "Kelly Twp Muni Auth", "William E Dunn WRF", "Martha Elementary",
                 "Glen Echo Resort", "Calvin PWA", "Pat Example Utilities", "Town of Example", "Example Water Authority",
                 "[name removed]", "", None):
        r = common.event(source_id="x-test", source_record_id="3", discharger_name=name)
        assert r["discharger_name"] == name, name


def test_a_persons_name_from_an_owner_field_or_set_after_the_record_is_removed(tmp_path):
    """The generic runner's reviewed owner field (the reviewed_fields gate admits it) and a module that sets
    discharger_name after common.event: both reach the events file without the name."""
    from ingest.generic import csv_json, runner
    b = {"platform": "csv", "url": "https://example.invalid/reports.csv", "time_zone": "America/Chicago",
         "safe_fields": ["report_id", "start", "kind", "owner"], "reviewed_fields": {"owner": "test: a private system"},
         "record": {"source_record_id": "report_id", "started_at": "start", "discharger_name": "owner",
                    "npdes_permit": {"const": "XX0000002"},
                    "event_type": {"field": "kind", "map": {"CSO": "cso"}}}}
    text = "Report ID,Start,Kind,Owner\nP1,10/02/2026 14:30,CSO,Pat Example\n"
    r = runner.build("x-owner", b, csv_json.parse(b, text.encode()), "2026-11-04T12:00:00Z", [])[0][0]
    assert r["discharger_name"] == "[name removed]" and r["npdes_permit"] == "XX0000002"
    rec = common.event(source_id="x-late", source_record_id="1", npdes_permit="XX0000003")
    rec["discharger_name"] = "Pat Example"
    p = common.write_events("x-late", [rec], path=tmp_path / "x-late.json")
    out = json.loads(p.read_text())["records"][0]
    assert out["discharger_name"] == "[name removed]" and out["npdes_permit"] == "XX0000003"


def test_operator_names_with_a_facility_abbreviation_or_business_word_are_kept():
    """Operator names that read like a person's name but carry a facility abbreviation, a school or district
    abbreviation or a business word (placeholders here, not real operators)."""
    for name in ("Pat Example Foods", "Pat Example Elem", "Pat Example Elem Sch", "Pat Example PSD", "Pat Example WWSL",
                 "Pat Example RWRF", "Pat Example AWTF", "Pat Example WQTC", "Pat Example Subdiv", "Pat Example CSOs",
                 "Pat Example MUA", "Pat Example MSD", "Pat Example Univ", "Pat Example Products", "Pat Example Mfg",
                 "Pat Example Campground", "Pat Example Nursing Home", "Pat Example & Sons"):
        r = common.event(source_id="x-test", source_record_id="4", discharger_name=name, discharger_id="op-1")
        assert r["discharger_name"] == name and r["discharger_id"] == "op-1", name


# ---------------------------------------------------------------- name review 2026-11-04 (Florida)

def test_a_phone_number_typed_without_separators_after_a_contact_word_is_removed():
    from common import scrub_text
    assert scrub_text("my contact is 8505550100 .. some treatment") == "my contact is [phone removed] .. some treatment"
    assert scrub_text("CONTACT: 8635550101 AMOUNT: 15") == "CONTACT: [phone removed] AMOUNT: 15"
    for keep in ("Job Order #: 1003691899 Location", "MANHOLES 0050030080 - 0050030081", "Incident 2025123456 closed",
                 "30.412345, -86.512345 1234 Example Rd"):        # an id, a count, a coordinate and a house number
        assert scrub_text(keep) == keep, keep


def test_a_house_number_tied_to_a_residence_goes_and_the_street_stays():
    from common import scrub_text
    cases = {
        "we received a call from a home owner at 1619 Placeholder Ave regarding": "a home owner at [house number removed] Placeholder Ave",
        "Resident @ 813 Example reported a leak": "Resident @ [house number removed] Example reported",
        "sewage forced its way into the houses at, 6501, 6513, and 6527 Example Dr. At 1830": "the houses at, [house number removed] Example Dr. At 1830",
        "backed up into two homes at 105 and 107 Example Circle": "two homes at [house number removed] Example Circle",
        "the yard of a residence (1201 Example Harbor Dr). An": "a residence ([house number removed] Example Harbor Dr)",
        "a homeowner's sewer line at 501 Example Ave. They": "a homeowner's sewer line at [house number removed] Example Ave",
        "At 255 Example Drive NE, a homeowner unscrewed the cap": "At [house number removed] Example Drive NE, a homeowner",
        "cleanouts at 808 NW 39th Dr and 4002 NW 8th Ave. The customer at 808 NW 39th Dr reported":
            "cleanouts at [house number removed] NW 39th Dr and 4002 NW 8th Ave. The customer at [house number removed] NW 39th Dr",
    }
    for text, want in cases.items():
        got = scrub_text(text)
        assert want in got, (text, got)
    for keep in ("a neighbor reported an overflowing manhole at 700 Example Place at 8:12 AM",
                 "Customer noticed it at 2100 on 05/08/2022, called customer service at 1100 on 05/09/2022",
                 "a customer notified the utility that LS 2 located at 2213 Example Trail was in alarm",
                 "the home at 3 pm"):
        assert scrub_text(keep) == keep, keep


def test_every_house_number_of_a_text_can_be_stripped_but_not_a_route_number():
    from common import strip_house_numbers
    assert strip_house_numbers("3 houses down from 5073 Example Ave.") == "3 houses down from [house number removed] Example Ave."
    assert strip_house_numbers("the buildings at 226, 224 and 220 16th Ave N, Town") == \
        "the buildings at [house number removed] 16th Ave N, Town"
    assert strip_house_numbers("Location: 1234 N. 301 Hwy, Tampa") == "Location: [house number removed] N. 301 Hwy, Tampa"
    for keep in ("4745 US 98 N", "spill of 3000 gallons at 12 pm", "2,500 gallons"):
        assert strip_house_numbers(keep) == keep, keep


def test_a_works_building_a_complex_or_a_count_is_not_a_household():
    from common import scrub_text
    for keep in ("Pump House 2 Example Rd overflowed",
                 "300 ft south of the Gate House at 4650 Example Country Club Blvd",
                 "Example Lakes Apartment Homes at 100 Example Way reported a leak",
                 "a leak at Example Place Condo located at 120 S. Example Blvd",
                 "customers 1500 East of the plant lost service"):
        assert scrub_text(keep) == keep, keep
    assert scrub_text("Area Around SMH # 3800 & House 119 Example Ave") == \
        "Area Around SMH # 3800 & House [house number removed] Example Ave"
    assert scrub_text("BEHIND THE RESIDENTS OF 6328 EXAMPLE AVE") == "BEHIND THE RESIDENTS OF [house number removed] EXAMPLE AVE"


def test_export_removes_a_residence_number_from_the_free_text_fields_too():
    # raw loses it (strip_personal), so the outfall name and the water text quoting the same sentence must too
    e = {"event_id": "nc-dwr-sso:1", "outfall_name": "MH 12 about 100 feet from back of home at 124 Example Court",
         "waterbody_text": "Example Branch, a waterway behind the private residence at 205 Example Rd.",
         "raw": {"location": "MH 12 about 100 feet from back of home at 124 Example Court"}}
    out = X.public_event(e)
    assert out["outfall_name"] == "MH 12 about 100 feet from back of home at [house number removed] Example Court"
    assert out["waterbody_text"] == "Example Branch, a waterway behind the private residence at [house number removed] Example Rd."
    assert "124" not in json.dumps(out["raw"])


def test_a_closing_signature_name_is_scrubbed_and_place_names_in_text_stay():
    """An agency report's sign-off (2026-11-04, a bloom report): the name after a closing is removed, the credentials
    and office stay; a closing followed by a sentence, or a water name in running text, is untouched."""
    from common import scrub_text
    v = "The bloom had dispersed by the second visit. Very respectfully, Pat Example, P.G. Hydrogeologist, Mooresville Regional Office"
    out = scrub_text(v)
    assert "Pat Example" not in out and "[name removed], P.G. Hydrogeologist, Mooresville Regional Office" in out
    v2 = "Sampled at Lake Example today.\nSincerely,\nChris Q. Placeholder\nEnvironmental Specialist"
    out2 = scrub_text(v2)
    assert "Chris Q. Placeholder" not in out2 and "Lake Example" in out2 and "Environmental Specialist" in out2
    assert scrub_text("Thank you for the report. The creek was clear.") == "Thank you for the report. The creek was clear."
    assert scrub_text("Regards to the crew; Mill Creek was turbid.") == "Regards to the crew; Mill Creek was turbid."


# ---------------------------------------------------------------- EPA's permit name (2026-11-07)

def _permit_names():
    root = Path(__file__).resolve().parents[2]
    if str(root / "scripts") not in sys.path:
        sys.path.insert(0, str(root / "scripts"))
    import permit_names
    return permit_names


def test_a_contact_person_before_the_body_in_epas_permit_name_is_cut():
    """EPA's ICIS permit name often leads with a contact person ('<a person> - City of X'): the person goes, the body
    stays (invented names only)."""
    s = _permit_names().scrub_permit_name
    assert s("Pat Example - City of Exampleton") == ("City of Exampleton", True)
    assert s("Quill Placeholder- North Example Borough") == ("North Example Borough", True)
    assert s("Pat Q. Example, Jr. - Exampleton Village of Sampleville") == ("Exampleton Village of Sampleville", True)
    assert s("Pat Example-City of Exampleton") == ("City of Exampleton", True)
    assert s("Pat Example, City of Exampleton") == ("City of Exampleton", True)
    assert s("Pat Example - Example Bay Borough School District") == ("Example Bay Borough School District", True)
    assert s("Example County Water District c/o Pat Example") == ("Example County Water District", True)
    assert s("Quill Placeholder", "Exampleton", "EXAMPLETON LAGOON") == (None, True)    # a contact alone


def test_an_organisation_or_place_first_permit_name_is_untouched():
    s = _permit_names().scrub_permit_name
    for keep in ("Exampleton, City of", "EXAMPLETON, CITY AND BOROUGH OF", "Example Foods, Inc.",
                 "City of Exampleton - Example Utilities", "North Pole - City of North Pole",
                 "Example County Sanitary District, Inc. - Dept. of Example Utilities", "Matanuska-Susitna Borough",
                 "Example Creek - City of Exampleton", "Fort Example - City of Fort Example",
                 "Sample, Example, Placeholder Sewer Commission", "Example Hills - Example Hills WWTP",
                 "Example WPCP (Sample Plant)", "Example Lake Golf Club", "PAT EXAMPLE", None, ""):
        assert s(keep, facility="EXAMPLE HILLS WWTP")[1] is False, keep


def test_scrub_rows_keeps_the_other_fields_and_marks_the_row_without_the_removed_text():
    pn = _permit_names()
    rows = [{"npdes_permit": "ZZ0000001", "permittee": "EXAMPLETON WWTF", "permit_name": "Pat Example - City of Exampleton",
             "state": "ZZ", "city": "Exampleton", "outfall": "001"},
            {"npdes_permit": "ZZ0000002", "permittee": "SAMPLE WWTP", "permit_name": "Sampleville, City of", "state": "ZZ"}]
    assert pn.scrub_rows(rows) == {"ZZ": 1}
    assert rows[0] == {"npdes_permit": "ZZ0000001", "permittee": "EXAMPLETON WWTF", "permit_name": "City of Exampleton",
                       "permit_name_scrubbed": True, "state": "ZZ", "city": "Exampleton", "outfall": "001"}
    assert list(rows[0])[3] == "permit_name_scrubbed" and "Pat" not in json.dumps(rows)
    assert "permit_name_scrubbed" not in rows[1]
    assert pn.scrub_rows(rows) == {}                       # once is enough: the rule is stable on its own output


def test_no_registry_row_names_a_person_in_epas_permit_name():
    """Every registry file that carries permit_name: no row the rule would still cut, and no field that is a person's
    name alone (counts only; the names are never printed)."""
    pn = _permit_names()
    import private_utilities as pu
    root = Path(__file__).resolve().parents[2] / "data"
    seen = 0
    for path in sorted(root.glob("outfalls-*.json")):
        doc = json.loads(path.read_text())
        rows = doc["outfalls"] if isinstance(doc, dict) else doc
        cut = alone = 0
        for r in rows:
            v = r.get("permit_name")
            if not v:
                continue
            seen += 1
            cut += pn.scrub_permit_name(v, r.get("city"), r.get("permittee"))[1]
            alone += (not pu.has_org_word(v)) and pu.person_like(v)
        assert (cut, alone) == (0, 0), f"{path.name}: {cut} rows with a contact person, {alone} with a person alone"
        # independent of the parser under test (SOL wave 2 P1-4): its own bracket split and private_utilities'
        # person test; a part that is the row's facility name (words or their abbreviations) is the body's own name
        assert _bracketed_people(rows, pu) == 0, f"{path.name}: a person's name in or beside brackets"
    assert seen > 20000


def _bracketed_people(rows, pu) -> int:
    import re

    def words(s):
        return re.findall(r"[a-z0-9]+", (s or "").lower())
    n = 0
    for r in rows:
        v = r.get("permit_name")
        if not v or not re.search(r"[()\[\]]", v) or not pu.has_org_word(v):
            continue
        fac = words(r.get("permittee"))
        for x in re.split(r"\s*[()\[\]]\s*", v):
            x = x.strip(" .,;-")
            if (x and not pu.has_org_word(x) and pu.person_like(x)
                    and not all(any(f.startswith(w) for f in fac) for w in words(x))):
                n += 1
    return n


def test_the_independent_bracket_check_sees_a_contact_in_either_order():
    import private_utilities as pu
    _permit_names()
    for v in ("Pat Example (City of Exampleton)", "City of Exampleton (Pat Example)"):
        assert _bracketed_people([{"permit_name": v, "permittee": "EXAMPLETON WWTF"}], pu) == 1
    assert _bracketed_people([{"permit_name": "Example Co. (P Example Hill Water Res)",
                               "permittee": "EXAMPLE COUNTY (P EXAMPLE HILL WATER RESOURCES CENTER)"}], pu) == 0


def test_a_bracketed_contact_is_cut_in_either_order():
    """SOL wave 2 P1-4: '<a person> (City of X)' and 'City of X (<a person>)' passed unchanged."""
    s = _permit_names().scrub_permit_name
    for v in ("Pat Example (City of Exampleton)", "City of Exampleton (Pat Example)", "City of Exampleton [Pat Example]",
              "Pat Example (Exampleton Sewer Authority)", "Example County Water District (Attn Pat Example)"):
        out, changed = s(v, "Exampleton", "EXAMPLETON WWTF")
        assert changed and "Pat" not in out and "(" not in out and "[" not in out, v
    assert s("Pat Example (City of Exampleton)", "Exampleton")[0] == "City of Exampleton"
    assert s("City of Exampleton (Pat Example) - Example Utilities")[0] == "City of Exampleton - Example Utilities"
    for keep in ("City of Exampleton (North Plant)", "Example Foods (Plant 2)", "Example County (Sample Hill WRC)"):
        assert s(keep, "Exampleton", "EXAMPLETON WWTF") == (keep, False), keep


def test_a_bracketed_contact_is_cut_through_the_plant_build_and_the_row_scrub():
    """The plant build keeps a field with a body's word (public_permit_name) and its scrub_rows pass must cut the
    bracketed contact; the committed registry is rewritten by the same scrub_rows."""
    import importlib.util
    root = Path(__file__).resolve().parents[2]
    pn = _permit_names()
    spec = importlib.util.spec_from_file_location("bpo_privacy", root / "research" / "federal" / "build_plant_outfalls.py")
    bpo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bpo)
    for v in ("Pat Example (City of Exampleton)", "City of Exampleton (Pat Example)"):
        kept = bpo.public_permit_name(v)
        assert kept == v                                  # the plant build alone keeps it: a body's word
        rows = [{"npdes_permit": "ZZ0000001", "permittee": "EXAMPLETON WWTF", "permit_name": kept, "state": "ZZ",
                 "city": "Exampleton"}]
        assert pn.scrub_rows(rows) == {"ZZ": 1}
        assert rows[0]["permit_name"] == "City of Exampleton" and rows[0]["permit_name_scrubbed"] is True
        assert "Pat" not in json.dumps(rows)
        assert pn.scrub_rows(rows) == {}
