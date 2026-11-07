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


def _build(tables=None, now="2026-11-07T12:00:00Z"):
    t = copy.deepcopy(tables or _fixture())
    return E.build(t, {"extract_date": "2026-11-04", "last_modified": "2026-11-04T12:21:15Z", "now": now})


def test_south_dakota_is_read_with_the_point_zone_and_the_scrub():
    assert "SD" in E.STATES and E.STATE_TZ["SD"] == "America/Chicago" and E.STATE_TZ["IL"] == "America/Chicago"
    assert E.POINT_ZONE_FILES["SD"] == "sd-mountain-time-counties.json"
    assert "SD" in E.FREE_TEXT_STATES and "SD" not in E.REPEATED_POINT_STATES


def test_the_mountain_counties_file_cites_the_boundary_and_holds_fifteen_counties():
    doc = json.loads((ROOT / "data" / "reference" / "sd-mountain-time-counties.json").read_text())
    assert doc["law"]["cite"] == "49 CFR 71.7(b)" and doc["zone"] == "America/Denver"
    assert sorted(c["county"] for c in doc["counties"]) == [
        f"{n} County" for n in ("Bennett", "Butte", "Corson", "Custer", "Dewey", "Fall River", "Haakon", "Harding",
                                "Jackson", "Lawrence", "Meade", "Oglala Lakota", "Pennington", "Perkins", "Ziebach")]
    assert [c["county"] for c in doc["split_counties"]] == ["Stanley County"]
    assert doc["split_counties"][0]["central_part"] and doc["split_counties"][0]["mountain_share"] > 0.8
    assert "tigerweb.geo.census.gov" in doc["source"]["url"]


def test_the_zone_is_the_zone_of_the_events_own_point():
    assert E.point_zone("SD", 44.08, -103.23)[0] == "America/Denver"           # Rapid City, Pennington County
    assert E.point_zone("SD", 44.356, -103.754)[0] == "America/Denver"         # Lead, Lawrence County
    assert E.point_zone("SD", 43.55, -96.73)[0] == "America/Chicago"           # Sioux Falls
    assert E.point_zone("SD", 44.37, -100.35)[0] == "America/Chicago"          # Pierre, Hughes County
    tz, basis = E.point_zone("SD", 44.355, -100.37)                           # Fort Pierre, Stanley County (split)
    assert tz == "America/Chicago" and "Stanley County" in basis and "split" in basis
    tz, basis = E.point_zone("SD", 44.4382, -100.3926)                        # Oahe Dam, western Stanley County
    assert tz == "America/Denver" and "west of the boundary" in basis and "Fort Pierre" not in basis
    tz, basis = E.point_zone("SD", 43.0, -100.0)                              # Todd County, Central
    assert tz == "America/Chicago" and "outside the fifteen" in basis
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
    for t in ("Does not apply- Do not discharge to any waters", "NA, the flow stayed in the plant",
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
    assert r["event_type"] == "hab_advisory" and r["status"] == "advisory_active" and r["ended_at"] == "2026-12-31"
    assert r["raw"]["placement_hint"] == {"name": "Twin Lakes", "county": "Spink County", "state": "SD",
                                          "basis": r["raw"]["placement_hint"]["basis"]}
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


def test_a_bloom_advisory_colours_its_lake_to_the_end_of_the_year():
    """Review 2026-11-07 P1-1: with no end the status build aged the advisories out 14 days after their date; DANR's
    own window is the calendar year."""
    from datetime import UTC, datetime
    from build import status
    from ingest import sd_danr_hab_advisories as H
    recs, _ = H.build(_hab_page(), "2026-11-07T12:00:00Z", [])
    twin = next(r for r in recs if r["waterbody_text"] == "Twin Lakes")       # dated 2026-06-15
    now = datetime(2026, 11, 7, 12, tzinfo=UTC)
    ivs = status.event_intervals(twin, "SD", now)
    live = [iv for iv in ivs if iv["start"] <= now and (iv["end"] is None or iv["end"] > now)]
    assert live and live[0]["rule"] == "advisory_active" and live[0]["red_rule"]["rule"] == "red.authority_advisory"
    assert live[0]["end"].astimezone(status.LOCAL).date().isoformat() in ("2026-12-31", "2027-01-01")
    later, _ = H.build(_hab_page(), "2027-01-02T12:00:00Z", recs)
    twin2 = next(r for r in later if r["waterbody_text"] == "Twin Lakes")
    then = datetime(2027, 1, 2, 12, tzinfo=UTC)
    assert not [iv for iv in status.event_intervals(twin2, "SD", then)
                if iv["start"] <= then and (iv["end"] is None or iv["end"] > then) and iv["color"]]


# ---------------------------------------------------------------- planned bypasses (every state)

def test_a_planned_bypass_runs_to_its_planned_end_and_is_coloured_to_it():
    """Review 2026-11-07 P2-3: Rapid City's anticipated bypass of its UV building to Rapid Creek, planned to
    2027-04-30, was written 'ended' and its end thrown away by the 31-day check."""
    from datetime import UTC, datetime
    from build import status
    rc = next(r for r in _build()[0] if r["source_record_id"] == "SD0023574:23:1")
    assert E.planned_notice(rc["raw"]) and rc["status"] == "ongoing" and rc["raw"]["end_is_planned"] is True
    assert rc["ended_at"] == "2027-04-30T21:00:00-06:00" and "planned end" in rc["raw"]["planned_end_note"]
    now = datetime(2026, 11, 20, 12, tzinfo=UTC)
    assert status.end_not_credible(rc, now) is None
    ivs = status.event_intervals(rc, "SD", now)
    assert ivs[0]["rule"] == "discharge" and ivs[0]["end"] == status.parse_time("2027-04-30T21:00:00-06:00")
    after = next(r for r in _build(now="2027-05-02T00:00:00Z")[0] if r["source_record_id"] == "SD0023574:23:1")
    assert after["status"] == "ended" and "end_is_planned" not in after["raw"]       # once passed, an ordinary end


def test_a_far_end_on_an_ordinary_report_is_still_taken_for_a_typo():
    from datetime import UTC, datetime
    from build import status
    sf = next(r for r in _build()[0] if r["source_record_id"] == "SD0022128:20:1")
    assert not E.planned_notice(sf["raw"])
    typo = {**sf, "ended_at": "2036-10-16T20:00:00-05:00", "raw": dict(sf["raw"])}
    assert "more than" in status.end_not_credible(typo, datetime(2026, 11, 7, 12, tzinfo=UTC))
    labelled_elsewhere = {**typo, "raw": {**typo["raw"], "end_is_planned": "yes"}}   # only a True label counts
    assert status.end_not_credible(labelled_elsewhere, datetime(2026, 11, 7, 12, tzinfo=UTC))


def test_na_with_the_water_discharged_is_no_name_and_the_bypass_is_kept():
    """Review 2026-11-07 P2-4: SD0028615's bypass, 'NA, all water was filtered before discharged.'"""
    w = "NA, all water was filtered before discharged. "
    assert not E.no_water(w, "SD") and E.named([w], "SD") == [] and E.named([w], "IL") == [w]
    ok, why = E.reached_water({}, ["BYP"], [w], [], "SD")
    assert ok and why.startswith("bypass")
    assert not E.reached_water({}, ["BYP"], ["Does not apply- Do not discharge to any waters"], [], "SD")[0]
    assert not E.reached_water({}, ["SSO"], [w], [], "SD")[0]                  # an SSO naming none still needs evidence


# ---------------------------------------------------------------- register (scripts/add_sd_register_rows.py)

def test_register_rows_say_per_permit_what_is_filed_and_how_the_authority_was_read():
    doc = json.loads((ROOT / "data" / "notice-channels" / "sd.json").read_text())
    rows = {r["id"]: r for r in doc["channels"]}
    ld = rows["sd-lead-deadwood-sd-cso-public-notification"]
    assert "Gold Run" not in ld["note"] and "no report of this permit" in ld["note"]
    assert "Gold Run Creek" in rows["sd-lead-cso-cso-public-notification"]["note"]
    epa = [r for r in rows.values() if r["id"].endswith("-overflow-report") and "EPA Region 8" in r["note"]]
    assert epa and all("not from the permit text" in r["note"] for r in epa)
    assert not any("No public notice is required" in r["note"] for r in rows.values())


def test_missing_water_names_are_normalised_and_the_bloom_lakes_carry_their_counties():
    import importlib.util
    spec = importlib.util.spec_from_file_location("sd_names", ROOT / "scripts" / "sd_report_water_names.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    assert m.norm("gold run creek") == "Gold Run Creek"
    assert m.norm("Scatterwood via Drainage ditch") == "Scatterwood"
    assert m.norm("Spearfish Creek / Rubble Site Cell") == "Spearfish Creek"
    assert m.norm("unname tributary of snake creek") == "Unnamed tributary of Snake Creek"
    assert m.norm("Tributary to the Big Sioux River") == "Unnamed tributary of Big Sioux River"
    assert m.norm("Unnamed") is None
    doc = json.loads((ROOT / "research" / "sd" / "receiving-waters-missing.json").read_text())
    lakes = {r["name"]: r.get("counties") for r in doc["rows"] if "sd-danr-hab-advisories" in r["sources"]}
    assert lakes == {"Clear Lake": ["Hamlin County"], "Lake Albert": ["Kingsbury County"],
                     "Lake Poinsett": ["Hamlin County"], "Twin Lakes": ["Spink County"],
                     "Wall Lake": ["Minnehaha County"]}
    assert all(r["name"] != "Unnamed" for r in doc["rows"])


# ---------------------------------------------------------------- final audit 2026-11-07: a general permit's state

def test_a_general_permits_report_counts_under_its_state(monkeypatch):
    """SDG821580's bypass to the Big Sioux River had no state (the permit's prefix was read only before a digit), so
    it was not placed by name, not counted and not coloured; the same held for ILG, GAU, RIS and NHG permits."""
    from build import status as S
    monkeypatch.setattr(S, "_STATES", {"SD", "IL", "GA", "RI", "NH"})
    for permit, st in [("SDG821580", "SD"), ("SD0023574", "SD"), ("ILG640063", "IL"), ("GAU020000", "GA"),
                       ("RIS000002", "RI"), ("NHG580001", "NH")]:
        assert S.event_state({"npdes_permit": permit, "source_id": "echo-sewer-overflow"}) == st
    assert S.event_state({"npdes_permit": "NN0020001", "source_id": "echo-sewer-overflow"}) is None
    assert S.event_state({"npdes_permit": "SDGX21580", "source_id": "echo-sewer-overflow"}) is None
    W = {"big-sioux-river-sd": {"slug": "big-sioux-river-sd", "name": "Big Sioux River", "kind": "river",
                                "state": "SD", "towns": [], "bbox": [-97.21, 42.49, -96.44, 45.32]}}
    R = S.Resolver(W, [], {}, {}, {})
    ev = {"event_id": "echo-sewer-overflow:SDG821580:2:1", "source_id": "echo-sewer-overflow",
          "npdes_permit": "SDG821580", "event_type": "bypass", "waterbody_text": "Big Sioux River",
          "lat": 44.721946, "lon": -97.041613, "water_slugs": [], "water_match": "none", "raw": {}}
    assert R.resolve(ev)["water_slugs"] == ["big-sioux-river-sd"]


def test_operator_rows_state_no_unread_permit_duty_as_fact():
    """Final audit 2026-11-07 (review P2-1 carried to the operator rows): the public channel text says no statute was
    found and that the two combined sewer permits are expected to require notice; neither permit was read."""
    rows = [o for o in json.loads((ROOT / "data" / "dischargers.json").read_text()) if o["state"] == "SD"]
    text = [o["notification_channel"] for o in rows]
    assert len(rows) == 369
    assert all(t.startswith("No South Dakota statute or rule was found that requires") for t in text)
    assert not any("must notify the public" in t for t in text)
    cso = [o for o in rows if o["kind"] == "cso"]
    assert len(cso) == 2 and all("is expected to require public notice" in o["notification_channel"] for o in cso)
