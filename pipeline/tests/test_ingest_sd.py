"""South Dakota: the South Dakota rules of EPA's overflow tables (the zone by the event's point against the
Mountain-time counties, the wordings for no water, the emergency pond, the free-text scrub, --file), on real South
Dakota rows (tests/fixtures/sd_sobe_rows.json: thirteen events of the 2026-11-04 extract; one house address replaced by
a placeholder), and the proof that adding the state changes no other state's record."""
import copy
import csv
import io
import json
import zipfile
from pathlib import Path

import common
from ingest import echo_sewer_overflow_events as E

FIX = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).resolve().parents[2]


def _fixture() -> dict:
    return json.loads((FIX / "sd_sobe_rows.json").read_text())


def _build(tables=None):
    t = copy.deepcopy(tables or _fixture())
    return E.build(t, {"extract_date": "2026-11-04", "last_modified": "2026-11-04T12:21:15Z"})


def test_south_dakota_is_read_with_the_point_zone_and_the_scrub():
    assert "SD" in E.STATES and E.STATE_TZ["SD"] == "America/Chicago" and E.STATE_TZ["IL"] == "America/Chicago"
    assert E.POINT_ZONE_FILES == {"SD": "sd-mountain-time-counties.json"}
    assert "SD" in E.FREE_TEXT_STATES and "SD" not in E.REPEATED_POINT_STATES


def test_the_mountain_counties_file_cites_the_boundary_and_holds_fifteen_counties():
    doc = json.loads((ROOT / "data" / "reference" / "sd-mountain-time-counties.json").read_text())
    assert doc["law"]["cite"] == "49 CFR 71.7(b)" and doc["zone"] == "America/Denver"
    assert sorted(c["county"] for c in doc["counties"]) == [
        f"{n} County" for n in ("Bennett", "Butte", "Corson", "Custer", "Dewey", "Fall River", "Haakon", "Harding",
                                "Jackson", "Lawrence", "Meade", "Oglala Lakota", "Pennington", "Perkins", "Ziebach")]
    assert [c["county"] for c in doc["split_counties"]] == ["Stanley County"]
    assert "tigerweb.geo.census.gov" in doc["source"]["url"]


def test_the_zone_is_the_zone_of_the_events_own_point():
    assert E.point_zone("SD", 44.08, -103.23)[0] == "America/Denver"           # Rapid City, Pennington County
    assert E.point_zone("SD", 44.356, -103.754)[0] == "America/Denver"         # Lead, Lawrence County
    assert E.point_zone("SD", 43.55, -96.73)[0] == "America/Chicago"           # Sioux Falls
    assert E.point_zone("SD", 44.37, -100.35)[0] == "America/Chicago"          # Pierre, Hughes County
    tz, basis = E.point_zone("SD", 44.355, -100.37)                           # Fort Pierre, Stanley County (split)
    assert tz == "America/Chicago" and "Stanley County" in basis and "split" in basis
    tz, basis = E.point_zone("SD", None, None)
    assert tz == "America/Chicago" and basis.startswith("no point given")
    assert E.point_zone("IL", 41.9, -87.6) == (None, None)                     # a one-zone state is not read by point
    assert E.zoned("2026-07-04T19:26:00", "SD", "America/Denver") == "2026-07-04T19:26:00-06:00"
    assert E.zoned("2026-07-04T19:26:00", "SD") == "2026-07-04T19:26:00-05:00"
    assert E.zoned("2026-07-04T19:26:00", "IL") == "2026-07-04T19:26:00-05:00"   # unchanged for Illinois


def test_real_rows_kept_and_dropped_by_reason():
    kept, dropped, why = _build()
    assert sorted(r["source_record_id"] for r in kept) == sorted([
        "SD0023574:23:1", "SD0022128:20:1", "SD0027481:3:1", "SD0023582:3:1", "SDG821580:1:1", "SD0023574:11:1"])
    reasons = {d["source_record_id"]: d["reason"] for d in dropped}
    assert reasons == {
        "SD0023574:22:1": "building backup",                                   # a basement backup
        "SD0023370:4:1": "building backup",
        "SD0022918:12:1": "receiving water stated as none",                    # 'Does not apply- Do not discharge ...'
        "SD0023361:8:2": "receiving water stated as none",                     # 'Cell # 3', a lagoon cell
        "SD0023361:3:1": "receiving water stated as none",                     # '... Water never entered lake'
        "SDG922705:3:1": "no evidence the discharge reached a water",          # 'discharge to emergency pond'
        "SD0022128:4:1": "no evidence the discharge reached a water",          # a manhole SSO naming no water
    }
    assert {(o, r): n for (st, o, r), n in why.items() if st == "SD"} == {
        ("kept", "receiving water named"): 5, ("kept", "text names a water (pond)"): 1,
        ("dropped", "building backup"): 2, ("dropped", "receiving water stated as none"): 3,
        ("dropped", "no evidence the discharge reached a water"): 2}
    by = {r["source_record_id"]: r for r in kept}
    assert by["SD0023574:23:1"]["event_type"] == "bypass" and by["SD0023574:23:1"]["raw"]["reached_water_rule"] == \
        "receiving water named"                                                # a bypass to Rapid Creek, kept
    assert by["SD0023574:11:1"]["raw"]["reached_water_rule"] == "text names a water (pond)"   # a detention pond stays
    assert by["SDG821580:1:1"]["event_type"] == "cso" and by["SDG821580:1:1"]["time_precision"] == "day"


def test_times_carry_the_zone_of_the_point_and_say_which_county_decided():
    by = {r["source_record_id"]: r for r in _build()[0]}
    rc = by["SD0023574:23:1"]                                                  # Rapid City, 2 November 2026: MST
    assert rc["started_at"] == "2026-11-02T17:00:00-07:00"
    assert "America/Denver" in rc["raw"]["timezone_note"] and "Pennington County" in rc["raw"]["timezone_note"]
    lead = by["SD0027481:3:1"]                                                 # Lead, August: MDT
    assert lead["started_at"].endswith("-06:00") and "Lawrence County" in lead["raw"]["timezone_note"]
    sf = by["SD0022128:20:1"]                                                  # Sioux Falls, October: CDT
    assert sf["started_at"] == "2026-10-16T18:00:00-05:00" and "America/Chicago" in sf["raw"]["timezone_note"]
    fp = by["SD0023582:3:1"]                                                   # Fort Pierre, January: CST
    assert fp["started_at"].endswith("-06:00") and "Stanley County" in fp["raw"]["timezone_note"]
    assert by["SDG821580:1:1"]["started_at"] == "2025-07-29"                   # an extreme-event report's date stays


def test_the_receiving_water_text_is_kept_as_reported():
    by = {r["source_record_id"]: r for r in _build()[0]}
    assert by["SD0027481:3:1"]["waterbody_text"] == "gold run creek"           # Lead's CSO permit, filed as an SSO
    assert by["SD0023574:23:1"]["waterbody_text"] == "Rapid Creek"
    assert by["SD0023582:3:1"]["waterbody_text"] == "Bad River"
    assert by["SD0023574:11:1"]["waterbody_text"] is None
    assert by["SD0027481:3:1"]["raw"]["receiving_waters"] == ["gold run creek"]


def test_south_dakota_wordings_that_name_no_water():
    for t in ("Does not apply- Do not discharge to any waters", "NA, all water was filtered before discharged. ",
              "Sanitation system of CIty of Pierre", "City of Pierre Wastewater Facility", "Apple Springs WWTP",
              "Box Elder sewer system/POTW", "Cell # 3", "Cell 4 at the Lagoons", "Excavated hole.  No waterbody. ",
              "water is discharged out into a field", "Ditch by Lake Mitchell.  Water never entered lake", "none", "NA"):
        assert E.no_water(t, "SD"), t
    for t in ("Spearfish Creek / Rubble Site Cell", "Unnamed", "Scatterwood via Drainage ditch", "gold run creek",
              "Tributary to the Big Sioux River", "McCook Lake", "Lake Francis Case"):
        assert not E.no_water(t, "SD"), t
    for st in ("MA", "GA", "IL", "WA"):                                        # the South Dakota wordings are SD's only
        assert not E.no_water("Cell # 3", st) and not E.no_water("Does not apply- Do not discharge to any waters", st)
    ev = {"sewer_overflow_bypass_description_text": "discharge to emergency pond"}
    assert not E.reached_water(ev, ["SSO"], [], [], "SD")[0]
    assert E.reached_water(ev, ["SSO"], [], [], "MA")[0]                       # elsewhere the general rule is unchanged


def test_source_record_ids_are_stable_and_name_the_report():
    a, b = _build()[0], _build()[0]
    assert [r["event_id"] for r in a] == [r["event_id"] for r in b]
    assert all(r["source_record_id"].count(":") == 2 and r["source_record_id"].startswith("SD") for r in a)
    fx = _fixture()
    ev = next(e for e in fx["events"] if e["permit_identifier"] == "SD0023574" and e["program_report_form_set_id"] == "23")
    ev["program_report_form_id"] = "999"                                       # a later version of the same report
    assert "SD0023574:23:1" in {r["source_record_id"] for r in _build(fx)[0]}


def test_a_house_address_never_reaches_a_south_dakota_record():
    kept, dropped, _ = _build()
    blob = json.dumps(kept) + json.dumps(dropped)
    assert "1234" not in blob and "[house number removed] Sample Street SE" in blob


def test_adding_south_dakota_changes_no_other_states_record(monkeypatch):
    """The same tables built with and without SD give identical records for every other state (also checked on the
    real 2026-11-04 extract: 1,809 kept and 1,741 dropped records of the other states identical)."""
    from tests.test_ingest_dc import _row
    fx = _fixture()
    other = [_row(sewer_overflow_bypass_event_key="o1", latitude_measure="38.9300", longitude_measure="-77.0400"),
             _row(sewer_overflow_bypass_event_key="o2", permit_identifier="IL0000001", program_report_form_set_id="2",
                  sewer_overflow_bypass_description_text="Break at 4521 Sample Prairie Dr."),
             _row(sewer_overflow_bypass_event_key="o3", permit_identifier="NH0000001", program_report_form_set_id="3")]
    fx["events"] += other
    fx["types"] += [{"sewer_overflow_bypass_event_key": k, "sewer_overflow_bypass_type_code": "SSO",
                     "sewer_overflow_bypass_type_desc": "", "sewer_overflow_bypass_type_code_sequence": "1"}
                    for k in ("o1", "o2", "o3")]
    fx["waters"] += [{"sewer_overflow_bypass_event_key": "o1", "name_receiving_water": "Rock Creek"},
                     {"sewer_overflow_bypass_event_key": "o2", "name_receiving_water": "Cell # 3"},
                     {"sewer_overflow_bypass_event_key": "o3", "name_receiving_water": "Sample Brook"}]

    def others(states):
        monkeypatch.setattr(E, "STATES", states)
        kept, dropped, _ = _build(fx)
        return sorted(json.dumps({k: v for k, v in r.items() if k != "fetched_at"}, sort_keys=True)
                      for r in kept + dropped if not str(r.get("npdes_permit") or r.get("permit")).startswith("SD"))
    with_sd, without_sd = others(set(E.STATES)), others(set(E.STATES) - {"SD"})
    assert with_sd == without_sd and len(with_sd) == 3
    assert any('"waterbody_text": "Cell # 3"' in r for r in with_sd)          # Illinois still reads 'Cell # 3' as a water


def _zip(tmp_path, tables) -> Path:
    p = tmp_path / "sobe.zip"
    with zipfile.ZipFile(p, "w") as z:
        for k, name in E.TABLES.items():
            rows = tables.get(k) or []
            buf = io.StringIO()
            if rows:
                w = csv.DictWriter(buf, fieldnames=list(rows[0]))
                w.writeheader()
                w.writerows(rows)
            else:
                buf.write("sewer_overflow_bypass_event_key\n")
            z.writestr(name, buf.getvalue())
    return p


def test_main_reads_a_saved_zip_of_south_dakota_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path / "events")
    monkeypatch.setattr(E, "BUILD_DIR", tmp_path)
    monkeypatch.setattr(E, "write_events", lambda sid, recs, **kw: common.write_events(
        sid, recs, path=tmp_path / "events" / f"{sid}.json", **kw))
    assert E.main(["--file", str(_zip(tmp_path, _fixture()))]) == 0
    doc = json.loads((tmp_path / "events" / "echo-sewer-overflow.json").read_text())
    assert doc["count"] == 6 and "SD" in doc["meta"]["states"]
    assert sum(x["count"] for x in doc["meta"]["by_rule"] if x["state"] == "SD" and x["outcome"] == "kept") == 6
    dropped = json.loads((tmp_path / "echo-sewer-overflow-dropped.json").read_text())
    assert dropped["count"] == 7


# ---------------------------------------------------------------- DANR's harmful algal bloom advisories

def _hab_page() -> str:
    return (FIX / "sd_danr_hab_page.html").read_text()


def test_the_hab_box_becomes_one_advisory_per_lake():
    from ingest import sd_danr_hab_advisories as H
    recs, meta = H.build(_hab_page(), "2026-11-07T12:00:00Z", [])
    assert meta["box_year"] == 2026 and meta["on_page"] == 5 and meta["advisory_active"] == 5
    by = {r["source_record_id"]: r for r in recs}
    r = by["2026:twin-lakes:spink-county"]
    assert r["event_type"] == "hab_advisory" and r["status"] == "advisory_active" and r["ended_at"] is None
    assert r["started_at"] == "2026-06-15" and r["time_precision"] == "day" and r["waterbody_text"] == "Twin Lakes"
    assert r["raw"]["county"] == "Spink County" and r["raw"]["expires_on"] == "2026-12-31"
    assert "expire at the end of the calendar year" in r["raw"]["end_basis"]
    assert r["lat"] is None and r["source_url"] == H.URL


def test_a_hab_advisory_ends_with_the_year_and_a_lake_that_leaves_is_kept():
    from ingest import sd_danr_hab_advisories as H
    recs, _ = H.build(_hab_page(), "2026-11-07T12:00:00Z", [])
    later, meta = H.build(_hab_page(), "2027-01-02T12:00:00Z", recs)
    assert all(r["status"] == "advisory_lifted" and r["ended_at"] == "2026-12-31" for r in later)
    fewer = _hab_page().replace("<p><strong>Wall Lake (Minnehaha County) </strong>8/11/2026 </p>", "")
    again, meta = H.build(fewer, "2026-11-08T12:00:00Z", recs)
    gone = next(r for r in again if r["waterbody_text"] == "Wall Lake")
    assert meta["on_page"] == 4 and meta["kept_from_previous"] == 1
    assert gone["raw"]["gone_from_page_since"] == "2026-11-08T12:00:00Z" and gone["status"] == "advisory_active"


def test_a_page_without_the_box_fails_and_keeps_the_previous_records(tmp_path, monkeypatch):
    from ingest import sd_danr_hab_advisories as H
    monkeypatch.setattr(H, "EVENTS_DIR", tmp_path)
    monkeypatch.setattr(H, "write_events", lambda sid, recs, **kw: common.write_events(
        sid, recs, path=tmp_path / f"{sid}.json", **kw))
    good = tmp_path / "good.html"
    good.write_text(_hab_page())
    assert H.main(["--file", str(good)]) == 0
    bad = tmp_path / "bad.html"
    bad.write_text("<html><body>moved</body></html>")
    assert H.main(["--file", str(bad)]) == 1
    doc = json.loads((tmp_path / "sd-danr-hab-advisories.json").read_text())
    assert doc["ok"] is False and doc["count"] == 5
