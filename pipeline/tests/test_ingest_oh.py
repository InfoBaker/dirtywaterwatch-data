"""Ohio: NEORSD's CSO alerts layers (snapshot to dated records, metered or modelled, day-bounded rows, end revisions,
the house-number scrub, the excluded staff fields), Akron's overflow-status layer (status 1 opens, 0 ends at the poll,
status 0 alone makes nothing, an undecoded status is caution only), Ohio EPA's spills layer (the sewage rows, the
waterway's county number, cases with two rows, a missing spill day) and ODH BeachGuard (types to categories, the lift at
the poll, an empty list held, the comment scrub). No network: the fixtures are real rows with invented names and
addresses ("Example")."""
import copy
import json
from pathlib import Path

from ingest import oh_akron_cso as AK
from ingest import oh_epa_spills as SP
from ingest import oh_neorsd_cso as NE
from ingest import oh_odh_beachguard as BG

FIX = Path(__file__).parent / "fixtures"
NOW = "2026-11-08T00:10:00Z"
LATER = "2026-11-08T01:10:00Z"


def _load(name):
    return json.loads((FIX / name).read_text())


def _neorsd_docs():
    return {4: _load("oh_neorsd_layer4.json"), 5: _load("oh_neorsd_layer5.json")}


def _by_id(recs):
    return {r["source_record_id"]: r for r in recs}


# NEORSD ---------------------------------------------------------------------------------------------------------------

def test_neorsd_records_per_outfall_kind_and_start(tmp_path):
    recs, meta = NE.run(_neorsd_docs(), NOW, tmp_path / "s.json")
    ids = _by_id(recs)
    # CSO-057 metered: a wet-weather and a dry-weather overflow, each its own record keyed on the UTC start
    assert "057:wet:2026-11-04T23:00:00Z" in ids and "057:dry:2026-10-03T06:59:00Z" in ids
    r = ids["057:wet:2026-11-04T23:00:00Z"]
    assert r["event_type"] == "cso" and r["status"] == "ended" and r["npdes_permit"] == "OH0043991"
    assert r["outfall_id"] == "057" and r["waterbody_text"] == "Big Creek"       # NEORSD's trailing space dropped
    assert r["started_at"] == "2026-11-04T23:00:00Z" and r["ended_at"] == "2026-11-05T00:20:00Z"
    assert r["time_precision"] == "minute" and r["raw"]["ended_at_precision"] == "minute"
    assert r["raw"]["time_zone"] == "America/New_York" and r["raw"]["state"] == "OH"
    assert r["raw"]["measurement"] == "metered by NEORSD" and "metered" in r["authority"]
    assert r["volume_gal"] == 200000 and r["estimate_flag"] == "measured"
    assert r["reported_at"] is None and r["published_at"] is None
    assert r["raw"]["_last_seen_in_source"] == NOW and r["fetched_at"] == NOW
    assert "for display purposes only" in r["raw"]["display_terms"]
    assert r["advice_text"].startswith("When a CSO is overflowing, public health officials advise")
    assert meta["poll"]["outfalls"] == 4


def test_neorsd_modelled_outfall_is_labelled(tmp_path):
    recs, _ = NE.run(_neorsd_docs(), NOW, tmp_path / "s.json")
    r = next(x for x in recs if x["outfall_id"] == "205")
    assert r["raw"]["measurement"] == "modelled by NEORSD" and "modelled by NEORSD" in r["authority"]
    assert r["estimate_flag"] == "estimated"


def test_neorsd_day_bounded_row_is_day_precision(tmp_path):
    # CSO-002: local midnight 17 October to local midnight 18 October, 0.45 hours: a day-bounded report
    recs, _ = NE.run(_neorsd_docs(), NOW, tmp_path / "s.json")
    r = next(x for x in recs if x["outfall_id"] == "002" and x["raw"]["weather"] == "wet weather")
    assert r["started_at"] == "2026-10-17" and r["ended_at"] == "2026-10-17"
    assert r["time_precision"] == "day" and r["raw"]["ended_at_precision"] == "day" and r["raw"]["day_bounds"]


def test_neorsd_future_edit_time_is_not_the_source_time(tmp_path):
    recs, _ = NE.run(_neorsd_docs(), NOW, tmp_path / "s.json")
    assert all(r["source_updated_at"] is None for r in recs)      # LAST_EDITED_DATE is never used (review P3-4)
    assert all("update_time_note" in r["raw"] and "LAST_EDITED_DATE" not in r["raw"]["layer"] for r in recs)


def test_neorsd_house_number_and_staff_fields_never_reach_records(tmp_path):
    recs, _ = NE.run(_neorsd_docs(), NOW, tmp_path / "s.json")
    text = json.dumps(recs) + (tmp_path / "s.json").read_text()
    assert "1234" not in text and "[house number removed] W. 114th St." in text
    assert "EXAMPLE.PERSON" not in text and "Example Person" not in text
    assert "LAST_EDITED_USER" not in text and "CREATED_USER" not in text
    assert NE.scrub_location("West of E. 81 St. & Vista Ave.") == "West of E. 81 St. & Vista Ave."
    assert NE.scrub_location("Approx. 300 Yds West of Beach") == "Approx. 300 Yds West of Beach"
    assert NE.scrub_location("9999 Example Road") == "[house number removed] Example Road"


def test_neorsd_new_start_opens_a_record_and_keeps_the_old(tmp_path):
    st = tmp_path / "s.json"
    NE.run(_neorsd_docs(), NOW, st)
    docs = _neorsd_docs()
    a = next(f["attributes"] for f in docs[4]["features"] if f["attributes"]["CSONUMBER"] == "CSO-057")
    start, end = 1794200000000, None              # a new overflow, running at the update
    a.update(WWOVERFLOWSTART=start, WWOVERFLOWEND=end, LASTOVERFLOWSTART=start, LASTOVERFLOWEND=end,
             WWOVERFLOWVOLUME=None, CURRENTLYOVERFLOWING=1.0)
    recs, meta = NE.run(docs, LATER, st)
    ids = _by_id(recs)
    assert ids["057:wet:2026-11-04T23:00:00Z"]["status"] == "ended"          # the earlier overflow stays as it was
    new = [r for r in recs if r["outfall_id"] == "057" and r["status"] == "ongoing"]
    assert len(new) == 1 and new[0]["ended_at"] is None and "no end is given yet" in new[0]["raw"]["end_note"]
    assert meta["poll"]["opened"] == 1
    # the next update gives the end: the same record ends, nothing new
    a.update(WWOVERFLOWEND=start + 3_600_000, LASTOVERFLOWEND=start + 3_600_000, CURRENTLYOVERFLOWING=0.0)
    recs, meta = NE.run(docs, "2026-11-08T02:10:00Z", st)
    done = _by_id(recs)[new[0]["source_record_id"]]
    assert done["status"] == "ended" and done["ended_at"] and meta["poll"]["opened"] == 0
    # a revised end replaces the earlier and is kept in end_revisions
    a.update(WWOVERFLOWEND=start + 7_200_000)
    recs, _ = NE.run(docs, "2026-11-08T03:10:00Z", st)
    rev = _by_id(recs)[new[0]["source_record_id"]]
    assert rev["raw"]["end_revisions"][0]["end"] == done["ended_at"] and rev["ended_at"] != done["ended_at"]


def _cso057(docs):
    return next(f["attributes"] for f in docs[4]["features"] if f["attributes"]["CSONUMBER"] == "CSO-057")


def test_neorsd_missed_end_is_bounded_by_the_next_start(tmp_path):
    """Review P2-1 (a): an overflow seen running, then a newer start at the next successful poll (its end never seen):
    the earlier record is no longer ongoing; it ends at the newer start, precision bound."""
    st = tmp_path / "s.json"
    docs = _neorsd_docs()
    a = _cso057(docs)
    s1, s2 = 1794200000000, 1794300000000
    a.update(WWOVERFLOWSTART=s1, WWOVERFLOWEND=None, LASTOVERFLOWSTART=s1, LASTOVERFLOWEND=None, CURRENTLYOVERFLOWING=1.0)
    recs, _ = NE.run(docs, NOW, st)
    first = next(r for r in recs if r["outfall_id"] == "057" and r["status"] == "ongoing")
    a.update(WWOVERFLOWSTART=s2, WWOVERFLOWEND=s2 + 600_000, LASTOVERFLOWSTART=s2, LASTOVERFLOWEND=s2 + 600_000,
             CURRENTLYOVERFLOWING=0.0)
    recs, meta = NE.run(docs, LATER, st)
    old = _by_id(recs)[first["source_record_id"]]
    assert old["status"] == "ended" and old["ended_at"] == NE.iso(NE.utc(s2))
    assert old["raw"]["ended_at_precision"] == "bound" and "at or before" in old["raw"]["_end_basis"]
    assert old["volume_gal"] is None and meta["poll"]["bounded"] == 1
    assert not [r for r in recs if r["status"] == "ongoing"]


def test_neorsd_overflowing_flag_never_erases_a_published_end(tmp_path):
    """Review P2-1 (b): CURRENTLYOVERFLOWING 1 while the start fields still show the last overflow, which has an end."""
    st = tmp_path / "s.json"
    NE.run(_neorsd_docs(), NOW, st)
    docs = _neorsd_docs()
    _cso057(docs)["CURRENTLYOVERFLOWING"] = 1.0
    recs, _ = NE.run(docs, LATER, st)
    r = _by_id(recs)["057:wet:2026-11-04T23:00:00Z"]
    assert r["status"] == "ended" and r["ended_at"] == "2026-11-05T00:20:00Z" and "end_revisions" not in r["raw"]
    assert not [x for x in recs if x["status"] == "ongoing"]


def test_neorsd_midnight_row_without_duration_is_day_bounded():
    """Review P3-1: a midnight-to-midnight row with no duration is a day-bounded report, not 24 exact hours."""
    s = NE.utc(1792209600000)                         # 2026-10-17 04:00Z, local midnight
    t = NE.times(s, s + NE.timedelta(days=1), None)
    assert t["time_precision"] == "day" and t["started_at"] == "2026-10-17" and t["ended_at"] == "2026-10-17"


def test_neorsd_source_record_id_is_stable(tmp_path):
    a, _ = NE.run(_neorsd_docs(), NOW, tmp_path / "a.json")
    b, _ = NE.run(_neorsd_docs(), LATER, tmp_path / "b.json")
    assert sorted(r["event_id"] for r in a) == sorted(r["event_id"] for r in b)


# Akron ----------------------------------------------------------------------------------------------------------------

def test_akron_status_zero_makes_no_record(tmp_path):
    recs, meta = AK.run(_load("oh_akron_cso.json"), NOW, tmp_path / "s.json")
    assert recs == [] and meta["poll"]["overflowing"] == 0


def test_akron_overflow_opens_and_ends_at_the_poll(tmp_path):
    st = tmp_path / "s.json"
    doc = _load("oh_akron_cso.json")
    doc["features"][0]["attributes"].update(status="1", updatetime="2026-11-08 08:15:00",
                                            icon="http://maps.google.com/mapfiles/ms/icons/red-dot.png")
    recs, _ = AK.run(doc, NOW, st)
    assert len(recs) == 1
    r = recs[0]
    assert r["status"] == "ongoing" and r["ended_at"] is None and r["time_precision"] == "poll"
    assert r["started_at"] == "2026-11-08T08:15:00-05:00" and r["raw"]["time_zone"] == "America/New_York"
    assert r["npdes_permit"] == "OH0023833" and r["waterbody_text"] == "Little Cuyahoga River"
    assert "not yet been reviewed for accuracy" in r["advice_text"]
    assert "icon" not in r["raw"]["layer"] and "green" not in json.dumps(r)
    doc2 = _load("oh_akron_cso.json")
    doc2["features"][0]["attributes"].update(status="0", updatetime="2026-11-08 10:04:00")
    recs, _ = AK.run(doc2, LATER, st)
    r = recs[0]
    assert r["status"] == "ended" and r["ended_at"] == "2026-11-08T10:04:00-05:00"
    assert r["raw"]["ended_at_precision"] == "poll"
    assert r["raw"]["end_bounds"] == ["2026-11-08T08:15:00-05:00", "2026-11-08T10:04:00-05:00"]


def test_akron_undecoded_status_is_caution_only(tmp_path):
    doc = _load("oh_akron_cso.json")
    doc["features"][1]["attributes"]["status"] = "2"
    recs, _ = AK.run(doc, NOW, tmp_path / "s.json")
    assert len(recs) == 1 and "code_undecoded" in recs[0]["raw"]


# Ohio EPA spills ------------------------------------------------------------------------------------------------------

def _spills():
    return SP.run({0: SP.rows_of(_load("oh_epa_spills.json")), 1: []}, NOW)[0]


def test_spills_waterway_county_number_cut_and_no_water():
    recs = _spills()
    named = [r for r in recs if r["waterbody_text"]]
    assert sorted(r["waterbody_text"] for r in named) == ["Alum Creek", "Mill Creek", "Sally Buffalo Creek"]
    r = next(x for x in named if x["waterbody_text"] == "Alum Creek")
    assert r["raw"]["county"] and r["raw"]["waterway"].startswith("25 - ")
    unnamed = next(r for r in recs if (r["raw"]["waterway"] or "").startswith("99 - UNNAMED"))
    assert unnamed["waterbody_text"] is None and "no water named" in unnamed["raw"]["waterway_note"]


def test_spills_times_and_limits():
    for r in _spills():
        assert r["event_type"] == "sso" and r["status"] == "unknown"
        assert r["ended_at"] is None and r["time_precision"] == "day"
        assert r["raw"]["time_zone"] == "America/New_York" and r["raw"]["state"] == "OH"
        assert r["reported_at"][-6:] in ("-04:00", "-05:00") and r["source_updated_at"] is None
        assert "no operator" in r["raw"]["limits"] and r["advice_text"] is None
        assert r["coord_source"] == ("source" if "point_not_used" not in r["raw"] else None)
        assert r["material"].startswith(("human sewage", "sewage sludge / biosolids", "waste water"))


def test_spills_volume_case_rows_and_missing_day():
    recs = _spills()
    gal = [r for r in recs if r["volume_gal"]]
    assert gal and all(r["volume_text"].endswith("gallons") for r in gal)
    two = [r for r in recs if r["raw"].get("case_rows") == 2]
    assert len(two) == 1 and two[0]["source_record_id"] == "2407EPA0001295"
    noday = next(r for r in recs if r["source_record_id"] == "2106EPA0000944")
    assert noday["started_at"] == "2021-01-06"       # the call's Eastern day (midnight typed) and "no spill day" in noday["raw"]["start_basis"]
    assert len({r["event_id"] for r in recs}) == len(recs) == 8


def test_spills_products_requested():
    assert "SEWAGE HUMAN" in SP.WHERE and "SEWAGE SLUDGE" in SP.WHERE and "WASTE WATER" in SP.WHERE
    assert "ODOR" not in SP.WHERE


def test_spills_call_time_is_ohio_wall_clock():
    """Review P2-2: reporteddate holds the Eastern hour typed; read as UTC it fell before the spill's own day."""
    r = next(x for x in _spills() if x["source_record_id"] == "2609EPA0001779")
    assert r["reported_at"] == "2026-09-22T00:00:00-04:00" and r["started_at"] == "2026-09-22"
    for x in _spills():
        if x["reported_at"] and x["started_at"]:
            assert x["reported_at"][:10] >= x["started_at"]          # no call before its spill's day
    assert "wall clock" in r["raw"]["time_note"]


def test_spills_waste_water_is_kept_as_a_possible_sewage_release():
    """Review P2-3: a WASTE WATER row is a report with the product and its uncertainty stated, under the day-start
    caution (never red)."""
    from datetime import datetime, timedelta, timezone
    import common
    from build import status as S
    r = next(x for x in _spills() if x["source_record_id"] == "2608EPA0001434")
    assert r["event_type"] == "sso" and r["material"].startswith("waste water") and "may be" in r["material"]
    assert "not sewage" in r["raw"]["product_note"] and r["waterbody_text"] == "Mill Creek"
    rules = json.loads((common.DATA_DIR / "rules.json").read_text())
    now = datetime.fromisoformat(r["started_at"]).replace(tzinfo=timezone.utc) + timedelta(days=1)
    ivs = S.event_intervals(r, "OH", now, rules=rules)
    assert ivs[0]["rule"] == "day_start_caution" and all(i["color"] != "red" for i in ivs)


# ODH BeachGuard -------------------------------------------------------------------------------------------------------

def test_beachguard_types_and_times(tmp_path):
    recs, _ = BG.run({}, BG.rows_of(_load("oh_odh_beachguard.json")), NOW)
    by_type = {r["event_type"]: r for r in recs}
    hab, bac = by_type["hab_advisory"], by_type["beach_advisory"]
    assert hab["started_at"] == "2026-05-20T11:10:00-04:00" and hab["waterbody_text"] == "Grand Lake"
    assert hab["status"] == "advisory_active" and "Ohio Department of Natural Resources" in hab["authority"]
    assert bac["raw"]["county"] == "Summit" and bac["raw"]["time_zone"] == "America/New_York"
    assert bac["source_updated_at"] is None and bac["raw"]["_last_seen_in_source"] == NOW
    assert BG.event_type_of("HAB_WATCH_ADV", None) == ("hab_advisory", True)
    assert BG.event_type_of("SOMETHING_NEW", "Beach Closed")[0] == "beach_closure"


def test_beachguard_comment_scrub_keeps_measurements():
    recs, _ = BG.run({}, BG.rows_of(_load("oh_odh_beachguard.json")), NOW)
    text = json.dumps(recs)
    assert "555-201-3344" not in text and "Example Person" not in text
    assert "252 cfu/100mL" in text
    assert "countyId" not in text and "thisObject" not in text


def test_beachguard_lift_at_poll_and_empty_list_held():
    state = {}
    rows = BG.rows_of(_load("oh_odh_beachguard.json"))
    BG.run(state, rows, NOW)
    recs, _ = BG.run(state, rows[:1], LATER)                 # the bacteria advisory is no longer listed
    lifted = [r for r in recs if r["status"] == "advisory_lifted"]
    assert len(lifted) == 1 and lifted[0]["ended_at"] == LATER
    assert lifted[0]["raw"]["ended_at_precision"] == "poll" and lifted[0]["raw"]["lift_observed_between"] == [NOW, LATER]
    held = copy.deepcopy(state)
    recs, meta = BG.run(held, [], "2026-11-08T02:10:00Z")      # one empty answer lifts nothing
    assert meta["poll"].get("held") == 1 and sum(r["status"] == "advisory_active" for r in recs) == 1
    recs, _ = BG.run(held, [], "2026-11-08T03:10:00Z")         # the second empty answer lifts, dated at the first
    assert all(r["status"] == "advisory_lifted" for r in recs)
    assert next(r for r in recs if r["event_type"] == "hab_advisory")["ended_at"] == "2026-11-08T02:10:00Z"


# County-aware placement (build/status.py COUNTY_STATES) --------------------------------------------------------------

def test_ohio_name_placement_is_county_aware(monkeypatch):
    from build import status as S
    monkeypatch.setattr(S, "_STATES", set(S.states()) | {"OH"})     # as once Ohio is live
    assert S.point_county("OH", 41.445, -81.764)[1] == "Cuyahoga County"          # NEORSD's Big Creek outfall
    assert S.point_county("OH", 39.10, -84.51)[1] == "Hamilton County"            # Cincinnati
    waters = {"mill-creek-cuyahoga-oh": {"state": "OH", "bbox": [-81.66, 41.40, -81.58, 41.46]},
              "mill-creek-hamilton-oh": {"state": "OH", "bbox": [-84.55, 39.10, -84.40, 39.30]}}
    ev = {"source_id": "oh-epa-spills-opendata", "event_id": "oh-epa-spills-opendata:x", "lat": 39.15, "lon": -84.47,
          "raw": {"state": "OH"}}
    kept, why = S.county_slugs(list(waters), ev, waters, lambda slug, lat, lon: 50_000)
    assert kept == ["mill-creek-hamilton-oh"] and "Hamilton" in why


# Bowling Green ----------------------------------------------------------------------------------------------------------

def test_bowling_green_table_rows():
    from ingest import oh_bowling_green_cso as BGC
    recs, meta = BGC.run((FIX / "oh_bowling_green_cso.html").read_text(), NOW)
    assert meta["rows"] == 3 and len(recs) == 3
    ids = _by_id(recs)
    r = ids["mercer-poe-rd:20260721T0733"]
    assert r["started_at"] == "2026-07-21T07:33:00-04:00" and r["ended_at"] == "2026-07-21T10:05:00-04:00"
    assert r["status"] == "ended" and r["raw"]["ended_at_precision"] == "minute" and r["raw"]["time_zone"] == "America/New_York"
    assert r["volume_gal"] == 2340000 and r["estimate_flag"] == "estimated"
    assert r["npdes_permit"] == "OH0024139" and r["outfall_id"] == "002" and r["coord_source"] == "outfall_layer"
    assert r["waterbody_text"] == "North Branch Portage River" and "place_basis" in r["raw"]
    winter = ids["mercer-poe-rd:20260331T1939"]                 # across days, daylight time
    assert winter["ended_at"] == "2026-04-02T00:50:00-04:00" and winter["raw"]["rainfall_in"] == '1.20"'
    open_ = ids["mercer-poe-rd:20260110T2330"]                  # no end given: never invented
    assert open_["ended_at"] is None and open_["status"] == "unknown" and "ended_at_precision" not in open_["raw"]
    assert open_["started_at"] == "2026-01-10T23:30:00-05:00" and open_["volume_gal"] is None


# Columbus -----------------------------------------------------------------------------------------------------------

def test_columbus_events():
    from ingest import oh_columbus_overflows as CO
    pts = CO.rows_of(_load("oh_columbus_points.json"), CO.POINT_FIELDS)
    evs = CO.rows_of(_load("oh_columbus_events.json"), CO.EVENT_FIELDS)
    recs, meta = CO.run(pts, evs, NOW)
    assert len(recs) == len(evs) == meta["rows"] and len({r["event_id"] for r in recs}) == len(recs)
    tank = next(r for r in recs if r["source_record_id"].startswith("cso-44:2026-04-01"))
    assert tank["event_type"] == "cso" and tank["started_at"] == "2026-04-01" and tank["time_precision"] == "day"
    assert tank["ended_at"] is None and tank["status"] == "unknown" and tank["raw"]["time_zone"] == "America/New_York"
    assert tank["volume_gal"] == 81_630_000 and tank["waterbody_text"] == "Alum Creek" and tank["coord_source"] == "source"
    assert tank["npdes_permit"] == "OH0024741" and tank["outfall_id"] == "006"         # Southerly (review P2-4)
    assert tank["raw"]["ohio_epa_station"] == "4PF00001006" and "permit_basis" in tank["raw"]
    assert all(r["discharger_id"] == CO.OPERATOR_ID for r in recs)
    rush = next(r for r in recs if "Example Springs" in (r["outfall_name"] or ""))
    assert "1234" not in json.dumps(rush) and rush["waterbody_text"] == "Rush Run"
    ditch = next(r for r in recs if (r["outfall_name"] or "").startswith("ditch"))
    assert ditch["event_type"] == "sso" and ditch["waterbody_text"] is None and ditch["volume_gal"] is None
    ids = {r["source_record_id"] for r in recs}
    assert {"cso-1:2005-01-03:018", "cso-1:2005-01-03:019", "cso-1:2005-01-01"} <= ids    # stable, not by object id
    tanks = next(r for r in recs if r["source_record_id"] == "cso-1:2005-01-03:018")
    assert tanks["npdes_permit"] == "OH0024732" and tanks["outfall_id"] == "018"          # Jackson Pike
    assert tanks["coord_source"] == "source" and tanks["lat"] is not None    # the city's own "CSO/SSO 1" point
    sso1 = next(r for r in recs if r["outfall_id"] == "SSO 1")              # go-live audit P2-3: had no point
    assert sso1["coord_source"] == "source" and (sso1["lat"], sso1["lon"]) == (tanks["lat"], tanks["lon"])
    # without the city's point, EPA's permitted-feature point for the paired outfall is used
    alone = CO.run([], [e for e in evs if e.get("NPDES_ID") == "4PF00000018"][:1], NOW)[0][0]
    assert alone["coord_source"] == "outfall_layer" and "EPA's point" in alone["raw"]["place_note"]
    assert CO.station_outfall("4PF00000018") == ("OH0024732", "018") and CO.station_outfall("") == (None, None)
    assert "inspection" in tanks["authority"] and tanks["advice_text"].startswith("To avoid any possible health effects")
    assert CO.water_of("Olentangy River below Fifth Ave. dam") == "Olentangy River"
    assert CO.water_of("Adena Brook/Indian Spring Run n/o gauging station") == "Adena Brook"
    assert CO.water_of("ditch e/o Perdue & n/o Aberdeen") is None


# Status rules for Ohio's day-only feeds --------------------------------------------------------------------------------

def test_spill_and_columbus_records_get_the_day_start_caution():
    """A day-only report with no end (Ohio EPA's spills, Columbus's inspection-dated overflows): 72 hours of the site's
    caution from the start of that Eastern day, then the end unconfirmed to day 30; never red."""
    from datetime import datetime, timedelta, timezone
    import common
    from build import status as S
    rules = json.loads((common.DATA_DIR / "rules.json").read_text())
    rec = next(r for r in _spills() if r["source_record_id"] == "2407EPA0001295")
    now = datetime.fromisoformat(rec["started_at"]).replace(tzinfo=timezone.utc) + timedelta(days=2)
    ivs = S.event_intervals(rec, "OH", now, rules=rules)
    day0 = S.parse_time(rec["started_at"], S.event_zone(rec))
    assert day0.utcoffset() is None or day0.astimezone(timezone.utc).hour in (4, 5)     # Eastern midnight
    assert [(i["rule"], i["color"]) for i in ivs[:2]] == [("day_start_caution", "yellow"), ("unresolved", "unresolved")]
    assert ivs[0]["end"] - ivs[0]["start"] == timedelta(hours=72)
    assert all(i["color"] != "red" for i in ivs)
    assert "oh-columbus-sewer-overflow" in rules["unresolved"]["day_start_caution"]["sources"]


def test_columbus_raw_save_is_scrubbed(tmp_path, monkeypatch):
    """Review P2-5: the location texts are cut before the raw save."""
    import common
    from ingest import oh_columbus_overflows as CO
    pts, evs = _load("oh_columbus_points.json"), _load("oh_columbus_events.json")

    class Resp:
        def __init__(self, d):
            self.d = d

        def raise_for_status(self):
            pass

        def json(self):
            return self.d

    class Sess:
        headers: dict = {}

        def get(self, url, params=None, timeout=None):
            if url.endswith("/0/query"):
                return Resp(pts)
            return Resp(evs if not params.get("resultOffset") else {"features": []})

    saved = {}
    monkeypatch.setattr(CO.requests, "Session", lambda: Sess())
    monkeypatch.setattr(CO, "save_raw", lambda sid, content, ext: saved.setdefault("raw", content))
    monkeypatch.setattr(CO, "write_events", lambda *a, **k: tmp_path / "x.json")
    assert CO.main([]) == 0
    assert "Example Springs" in saved["raw"] and "1234" not in saved["raw"]


def test_advice_text_is_only_the_authorities_own_words(tmp_path):
    """Review P2-6: the site's sentences never sit in advice_text, which the event page shows as the authority's
    quotation; each feed's advice is the authority's verbatim words or nothing."""
    from ingest import oh_bowling_green_cso as BGC
    from ingest import oh_columbus_overflows as CO
    akron = _load("oh_akron_cso.json")
    akron["features"][0]["attributes"].update(status="1", updatetime="2026-11-08 08:15:00")
    recs = (NE.run(_neorsd_docs(), NOW, tmp_path / "n.json")[0] + AK.run(akron, NOW, tmp_path / "a.json")[0]
            + _spills() + BG.run({}, BG.rows_of(_load("oh_odh_beachguard.json")), NOW)[0]
            + BGC.run((FIX / "oh_bowling_green_cso.html").read_text(), NOW)[0]
            + CO.run(CO.rows_of(_load("oh_columbus_points.json"), CO.POINT_FIELDS),
                     CO.rows_of(_load("oh_columbus_events.json"), CO.EVENT_FIELDS), NOW)[0])
    site_words = ("this record", "this site", "records each", "table of", "called in", "the layer", "NEORSD's CSO alerts",
                  "map marks")
    for r in recs:
        a = r["advice_text"] or ""
        assert not any(w.lower() in a.lower() for w in site_words), (r["source_id"], a)
    allowed = {NE.ADVICE, AK.ADVICE, CO.ADVICE}
    for r in recs:
        if r["source_id"] in (NE.SOURCE_ID, AK.SOURCE_ID, CO.SOURCE_ID):
            assert r["advice_text"] in allowed
        elif r["source_id"] in (SP.SOURCE_ID, BGC.SOURCE_ID):
            assert r["advice_text"] is None


# Clyde ------------------------------------------------------------------------------------------------------------------

def test_clyde_yearly_report_rows(tmp_path):
    """Review P2-7: Clyde's yearly table read cleanly; the staff contact on the page never reaches a record or state."""
    from ingest import oh_clyde_cso as CL
    page = (FIX / "oh_clyde_cso.html").read_text()
    rows = CL.parse(page)
    assert len(rows) == 2 and rows[0]["rain_before_in"] == "N/A"
    recs, meta = CL.run({2017: rows}, NOW, tmp_path / "s.json")
    r = _by_id(recs)["20170505T1200"]
    assert r["started_at"] == "2017-05-05T12:00:00-04:00" and r["ended_at"] == "2017-05-05T12:30:00-04:00"
    assert r["status"] == "ended" and r["raw"]["ended_at_precision"] == "minute" and r["raw"]["time_zone"] == "America/New_York"
    assert r["npdes_permit"] == "OH0024686" and r["outfall_id"] == "010" and r["waterbody_text"] == "Raccoon Creek"
    assert r["volume_gal"] == 59700 and r["advice_text"] is None and r["coord_source"] == "outfall_layer"
    text = json.dumps(recs) + (tmp_path / "s.json").read_text()
    assert "Example Person" not in text and "example.org" not in text and "555-201-3344" not in text


def test_register_monitors_the_operator_pages_and_clyde_has_its_real_permit():
    """Review P2-7: Lakewood's, Clyde's, MSD Cincinnati's and Upper Sandusky's pages are monitored (health, no
    records); Clyde's rows sit on OH0024686 and its yearly tables are read by a feed; no row names OH0024868."""
    import common
    rows = json.loads((common.DATA_DIR / "notice-channels" / "oh.json").read_text())["channels"]
    dis = {d["id"]: d for d in json.loads((common.DATA_DIR / "dischargers.json").read_text())}
    by_permit = {}
    for r in rows:
        by_permit.setdefault(r.get("permit"), []).append(r)
    for permit in ("OH0026018", "OH0024686", "OH0105457", "OH0020001"):
        mon = [r for r in by_permit[permit] if r["monitored"]]
        assert mon and all(r.get("records") is False and r["urls"] for r in mon), permit
    clyde = by_permit["OH0024686"]
    assert any(r.get("feed_source_id") == "oh-clyde-cso-notification" for r in clyde)
    assert all("OH0024686" in dis[r["operator_id"]]["npdes_permits"] for r in clyde)
    assert "OH0024868" not in json.dumps(rows) and not any("OH0024868" in (d.get("npdes_permits") or [])
                                                           for d in dis.values())


def test_ohio_sources_in_the_shared_day_rule_leave_other_states_unchanged():
    """Review P3-3 and brief item 8: adding Ohio's sources to unresolved.day_start_caution changes no other state's
    intervals, and the rule's text (quoted in their rule_applied) names no Ohio feed."""
    import copy
    from datetime import datetime, timezone
    import common
    from build import status as S
    rules = json.loads((common.DATA_DIR / "rules.json").read_text())
    ds = rules["unresolved"]["day_start_caution"]
    assert "Ohio" not in ds["rationale"] and "oh-epa-spills-opendata" in ds["sources"]
    before = copy.deepcopy(rules)
    before["unresolved"]["day_start_caution"]["sources"] = [s for s in ds["sources"] if not s.startswith("oh-")]
    now = datetime(2026, 11, 4, 12, tzinfo=timezone.utc)
    others = [{"event_id": "ga-epd-spills:x", "source_id": "ga-epd-spills", "event_type": "sso", "status": "unknown",
               "started_at": "2026-10-29", "time_precision": "day", "raw": {}},
              {"event_id": "tx-tceq-sso-opendata:x", "source_id": "tx-tceq-sso-opendata", "event_type": "sso",
               "status": "unknown", "started_at": "2026-10-30", "time_precision": "day", "raw": {}},
              {"event_id": "md-x:1", "source_id": "md-mde-overflows", "event_type": "sso", "status": "ended",
               "started_at": "2026-10-30T10:00:00Z", "ended_at": "2026-10-30T12:00:00Z", "time_precision": "minute",
               "raw": {}}]
    for ev, st in zip(others, ("GA", "TX", "MD")):
        assert S.event_intervals(ev, st, now, rules=rules) == S.event_intervals(ev, st, now, rules=before)


# Go-live audit 2026-11-08 ---------------------------------------------------------------------------------------------

def _line(slug, name, state, coords):
    xs, ys = [c[0] for c in coords], [c[1] for c in coords]
    return {"slug": slug, "name": name, "kind": "stream", "state": state, "towns": [], "aliases": [],
            "bbox": [min(xs), min(ys), max(xs), max(ys)], "geometry": {"type": "LineString", "coordinates": coords}}


def test_a_qualified_water_is_not_placed_on_its_plain_namesake():
    """Audit P2-2: "Little Cuyahoga River" (Akron's note) and "West Branch Huron River" have no record: they are not
    placed on the Cuyahoga's or the Huron's; the plain name still resolves, in Ohio and elsewhere."""
    from build import status as S
    ws = {"cuyahoga-river-oh": _line("cuyahoga-river-oh", "Cuyahoga River", "OH", [[-81.55, 41.10], [-81.65, 41.45]]),
          "huron-river-oh": _line("huron-river-oh", "Huron River", "OH", [[-82.55, 41.25], [-82.55, 41.39]]),
          "huron-river-mi": _line("huron-river-mi", "Huron River", "MI", [[-83.75, 42.27], [-83.60, 42.23]])}
    res = S.Resolver(ws, [], placement_rules={})
    akron = "The receiving water for this overflow is the Little Cuyahoga River."
    assert res.by_name(akron, "OH", 41.11, -81.52)[0] == []
    assert res.by_name("West Branch Huron River", "OH", 41.3, -82.6)[0] == []
    assert res.by_name("East Fork of the Little Miami River", "OH", 39.1, -84.2)[0] == []
    assert res.by_name("The receiving water for this overflow is the Cuyahoga River.", "OH", 41.13, -81.55)[0] == \
        ["cuyahoga-river-oh"]
    assert res.by_name("Little Cuyahoga River to the Cuyahoga River", "OH", 41.13, -81.55)[0] == ["cuyahoga-river-oh"]
    assert res.by_name("Huron River", "MI", 42.25, -83.7)[0] == ["huron-river-mi"]
    assert S.qualified_only("huron river", " west branch huron river ")
    assert not S.qualified_only("west creek", " west creek ")


def _water_boxes() -> dict:
    """{slug: bbox} over every water file (openboatlaunch's extracts and the NHD build)."""
    out = {}
    for f in sorted((Path(__file__).parents[2] / "data").glob("waters-*.json")):
        try:
            d = json.loads(f.read_text())
        except ValueError:
            continue
        for w in (d.get("waters") if isinstance(d, dict) else d) or []:
            if isinstance(w, dict) and w.get("slug") and w.get("bbox"):
                out.setdefault(w["slug"], w["bbox"])
    return out


def test_the_missing_list_carries_akrons_and_neorsds_waters():
    """Audit P2-2 and the re-check of 2026-11-08: each water Akron's sites name is a missing row with its points, or
    resolved (the water batch) to a record that holds those points (the rerun batch built little-cuyahoga-river-oh);
    NEORSD's Mill Creek and Big Creek, which the batch did not build at Cleveland, are rows with the outfalls' points."""
    missing = json.loads((Path(__file__).parents[2] / "research" / "oh" / "receiving-waters-missing.json").read_text())
    rows = {r["name"]: r for r in missing["rows"]}
    resolved = {r["name"]: r for r in missing.get("resolved") or []}
    boxes = _water_boxes()
    for name in ("Little Cuyahoga River", "Ohio Canal", "Camp Brook"):
        assert name in rows or name in resolved, f"{name} is neither a missing row nor resolved"
        if name in rows:
            assert rows[name]["points"] and "oh-akron-cso-notifications" in rows[name]["sources"]
        else:
            r = resolved[name]
            assert r["slugs"] and r["points"]
            for slug in r["slugs"]:
                b = boxes.get(slug)
                if b:                  # the record is in this checkout: it holds the sites' points (about 1 km)
                    assert all(b[0] - 0.01 <= lon <= b[2] + 0.01 and b[1] - 0.01 <= lat <= b[3] + 0.01
                               for lat, lon in r["points"]), f"{name} resolved away from Akron's sites"
    for name, n in (("Mill Creek", 19), ("Big Creek", 14)):
        r = next((x for x in missing["rows"] if x["name"] == name and "OH0043991" in (x.get("permits") or [])), None)
        assert r, f"NEORSD's {name} is not on the missing list"
        assert len(r["points"]) == n and r["counties"] == ["Cuyahoga County"]
        assert all(41.3 < lat < 41.6 and -81.9 < lon < -81.5 for lat, lon in r["points"])     # Cleveland


def test_a_day_precision_start_prints_the_day_only():
    """Audit P2-4: start_txt (build/status.py; called by _short_reason for the unresolved reasons of every state)
    prints the day only for a report dated to the day; a minute-precision record prints as before."""
    from build import status as S
    day = {"started_at": "2026-09-15"}
    assert S.start_txt(day, {"time_precision": "day"}) == "Sep 15" and S.start_txt(day) == "Sep 15"
    iv = {"started_at": "2026-10-30T10:00:00Z"}
    assert S.start_txt(iv, {"time_precision": "minute"}) == S.start_txt(iv) == "Oct 30 06:00"
    ev = {"event_type": "sso", "time_precision": "day", "discharger_name": "City of Columbus"}
    text = S._short_reason({"rule": "unresolved", "started_at": "2026-09-15", "authority": "City of Columbus"}, ev)
    assert "00:00" not in text and "Sep 15" in text


def test_a_spill_point_outside_its_county_is_not_used():
    """Audit P3-4: 2610EPA0001939 gives Harrison County, but its point lies in West Virginia: the point stays in raw
    only; the report is placed by its county and the water it names (Ohio is a county-field state)."""
    from build import status as S
    r = next(x for x in _spills() if x["source_record_id"] == "2610EPA0001939")
    assert r["lat"] is None and r["lon"] is None and r["coord_source"] is None
    assert r["raw"]["point_not_used"]["point_county"] == "outside Ohio" and r["raw"]["county"] == "Harrison"
    assert r["waterbody_text"] and "OH" in S.COUNTY_FIELD_STATES
    assert all(x["lat"] is not None for x in _spills() if x["source_record_id"] == "2407EPA0001295")


def test_state_text_explains_grand_lake_markers():
    """Audit P2-5: Grand Lake St. Marys is over the 50 km² whole-water limit; the state text says why it shows
    markers."""
    text = (Path(__file__).parents[2] / "research" / "oh" / "state-text.md").read_text()
    assert "Grand Lake St. Marys" in text and "50 square kilometres" in text and "markers" in text
