"""Delaware: DNREC's DERNS Recent Releases (ingest/de_dnrec_derns.py) and its recreational-water advisories
(ingest/de_dnrec_recwater.py), and the state's registry rows, register, rules row, state text and missing-waters list.
Fixtures: a list page and three detail pages in DERNS's markup with invented rows (Example names, placeholder house and
telephone numbers), and rows of the 2026-11-14 fetch of the advisory history and the FirstMap stations. No network."""
import copy
import json
import re
from collections import Counter
from datetime import date
from pathlib import Path

import pytest

from ingest import de_dnrec_derns as D
from ingest import de_dnrec_recwater as W

ROOT = Path(__file__).resolve().parents[2]
FIX = Path(__file__).resolve().parent / "fixtures" / "de"
T0, T1, T2 = "2026-11-14T18:00:00Z", "2026-11-14T19:00:00Z", "2026-11-14T20:00:00Z"
PERSONAL = ["Pat Example", "pat.example@example.org", "3025550142", "302-555-0142", "555-0142", "9876 Example",
            "1234 Example", "4321 Sample", "5678 Sample"]


def listing():
    return D.list_rows((FIX / "derns_list.html").read_text())


def state_with_details():
    st = {"rows": {}}
    D.merge(st, listing(), T0)
    pages = {"2026-2850": "derns_detail_water.html", "2026-2849": "derns_detail_ground.html",
             "2026-2844": "derns_detail_textwater.html"}
    for key, f in pages.items():
        d = D.safe_detail(D.parse_detail((FIX / f).read_text()))
        st["rows"][key].update(detail=d, detail_hash="h0", detail_read_at=T0)
    return st


def records(st=None):
    recs, reasons = D.build(st or state_with_details(), T0)
    return {r["source_record_id"]: r for r in recs}, reasons


# ---------------------------------------------------------------- DERNS

def test_the_list_and_the_pager_are_read():
    rows = listing()
    assert len(rows) == 7 and rows[0]["key"] == "2026-2850" and rows[0]["release_number"] == "17770"
    page = (FIX / "derns_list.html").read_text()
    assert D.page_count(page) == 3
    nxt = D.Client._next(page, "SEWAGE")
    assert nxt["__VIEWSTATE"] == "EXAMPLEVIEWSTATE" and any(k.endswith("btnNext") for k in nxt)
    assert nxt[D.P + "txtSearchValue"] == "SEWAGE"


def test_only_candidate_substances_are_kept_at_all():
    st = {"rows": {}}
    n = D.merge(st, listing(), T0)
    assert n == {"rows_read": 7, "not_candidate": 1, "candidates": 6}
    assert "2026-2847" not in st["rows"]                          # fuel oil at a home: never saved


@pytest.mark.parametrize("substance,facility,location,detail,want", [
    ("SEWAGE", "SPILL LOCATION", "Example Road", None, "sewage"),
    ("Raw Sewage", "", "", None, "sewage"),
    ("SEWAGE/GREYWATER", "", "", None, "sewage"),
    ("WASTEWATER", "SPILL LOCATION", "Example Pump Station #3, Dover", None, "sewage"),
    ("UNTREATED WASTEWATER", "DISCHARGE LOCATION", "Example Avenue", None, "sewage"),
    ("Poultry process wastewater", "EXAMPLE FOODS LLC", "", None, "industrial"),
    ("WASTEWATER", "PERDUE PROCESSING", "Example Road", None, "industrial"),
    ("Treated effluent", "LEWES BOARD OF PUBLIC WORKS", "", None, "treated_effluent"),
    ("WASTEWATER", "DISCHARGE LOCATION", "Example Avenue", None, "pending"),
    ("WASTEWATER", "DISCHARGE LOCATION", "Example Avenue", {"text": "Water spilled from a truck."}, "wastewater_unattributed"),
    ("WASTEWATER", "DISCHARGE LOCATION", "Example Avenue", {"text": "A force main broke."}, "sewage"),
    ("Non-sanitary poultry process wastewater", "", "", None, "industrial"),
    ("FUEL OIL, [DIESEL]", "RESIDENCE", "", None, "not_candidate"),
])
def test_sewage_by_rule(substance, facility, location, detail, want):
    assert D.classify({"substance": substance, "facility": facility, "location": location}, detail)[0] == want


def test_kept_and_dropped_rows_by_reason():
    recs, reasons = records()
    assert set(recs) == {"2026-2850", "2026-2849", "2026-2845", "2026-2844"}
    assert reasons == {"sewage": 4, "industrial": 1, "treated_effluent": 1}


def test_times_in_eastern_time_with_no_end_and_the_report_time_apart():
    recs, _ = records()
    r = recs["2026-2850"]
    assert r["started_at"] == "2026-11-12T07:30:00-05:00" and r["time_precision"] == "minute"
    assert r["reported_at"] == "2026-11-12T09:05:00-05:00" and r["published_at"] is None
    assert r["ended_at"] is None and r["status"] == "unknown" and r["raw"]["time_zone"] == "America/New_York"
    assert r["raw"]["release_duration"] == "3 hours" and r["raw"]["derns_status"] == "Final"
    assert "never read as an end" in r["raw"]["end_basis"]
    midnight = recs["2026-2849"]
    assert midnight["started_at"] == "2026-11-11" and midnight["time_precision"] == "day"
    summer = D.parse_time("7/4/2026 2:00:00 PM")
    assert summer == ("2026-07-04T14:00:00-04:00", "minute")


def test_water_ground_and_the_text_over_the_form():
    recs, _ = records()
    w = recs["2026-2850"]
    assert w["raw"]["released_to"] == ["Ground", "Water"] and w["raw"]["reached_water"] is True
    assert w["waterbody_text"] == "White Clay Creek" and w["advice_text"].startswith("Avoid contact")
    g = recs["2026-2849"]
    assert g["raw"]["reached_water"] is False and "ground only" in g["raw"]["_no_water_reason"]
    assert g["waterbody_text"] is None and g["advice_text"] is None
    t = recs["2026-2844"]
    assert t["raw"]["reached_water"] == "text" and t["waterbody_text"] == "Shellpot Creek"
    assert "ground only" in t["raw"]["_reached_water_basis"]
    # a list row whose detail is not read yet: no water claim either way
    assert "reached_water" not in recs["2026-2845"]["raw"]


def test_operator_type_volume_and_county():
    recs, _ = records()
    r = recs["2026-2850"]
    assert r["event_type"] == "sso" and r["discharger_id"] == "de-new-castle-county"
    assert r["volume_gal"] == 12000.0 and r["estimate_flag"] == "estimated"
    assert r["raw"]["county"] == "New Castle" and r["raw"]["town"] == "Newark"
    assert recs["2026-2849"]["raw"]["county"] == "Kent" and recs["2026-2849"]["discharger_id"] is None
    assert D.county_of("Example Road, Rehoboth Beach, DE 19971") == "Sussex"
    assert D.county_of("Example Road, Milford, DE 19963") is None                       # a ZIP across two counties
    assert D.county_of("Example Road, Smyrna") == "Kent"


def test_a_release_at_a_private_home_keeps_its_county_only():
    recs, _ = records()
    r = recs["2026-2845"]
    assert r["raw"]["private_source"] and r["raw"]["county"] == "Sussex" and r["raw"]["town"] == "Milton"
    assert "location_text" not in r["raw"] and "facility_text" not in r["raw"] and r["outfall_name"] is None
    assert r["discharger_id"] is None


def test_no_personal_field_or_string_reaches_a_record_or_the_saved_state():
    st = state_with_details()
    recs, _ = records(st)
    blob = json.dumps(list(recs.values())) + json.dumps(st)
    for s in PERSONAL:
        assert s not in blob, s
    assert "[house number removed]" in blob and "[phone removed]" in blob and "Call [name removed]" in blob
    assert D.scrub("Spoke with Ms. Sample about the spill; called New Castle County.") == \
        "Spoke with [name removed] about the spill; called New Castle County."
    assert "lblContact" not in json.dumps(D.DETAIL_SPANS) and "lblFacAddress" not in json.dumps(D.DETAIL_SPANS)


def test_a_changed_detail_is_kept_with_its_revision_and_the_key_is_stable():
    st = state_with_details()

    class Fake:
        def detail(self, key):
            d = D.parse_detail((FIX / "derns_detail_water.html").read_text())
            d["quantity"] = "15,000 gallons"
            return d
    n = D.read_details(Fake(), st, ["2026-2850"], T1)
    assert n["details_changed"] == 1
    recs, _ = records(st)
    r = recs["2026-2850"]
    assert r["event_id"] == "de-dnrec-derns-recent-releases:2026-2850" and r["volume_gal"] == 15000.0
    assert r["raw"]["_revisions"][0]["seen_at"] == T1 and r["raw"]["release_number"] == "17770"
    assert r["source_url"].endswith("ReleaseID=2026-2850")


def test_details_are_due_newest_first_and_capped():
    st = {"rows": {}}
    D.merge(st, listing(), T0)
    from datetime import datetime, timezone
    due = D.due_for_detail(st, datetime(2026, 11, 14, 18, tzinfo=timezone.utc), 3)
    assert due == ["2026-2850", "2026-2849", "2026-2848"]


def test_a_failed_list_keeps_the_previous_records(monkeypatch, tmp_path):
    import common
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path)
    (tmp_path / f"{D.SOURCE_ID}.json").write_text(json.dumps({"records": [{"event_id": "x"}], "meta": {"m": 1}}))

    class Boom(D.Client):
        def recent(self, pages):
            raise RuntimeError("the Recent Releases list showed no rows")
    monkeypatch.setattr(D, "Client", Boom)
    monkeypatch.setattr(D, "STATE_PATH", tmp_path / "state.json")
    assert D.main([]) == 1
    out = json.loads((tmp_path / f"{D.SOURCE_ID}.json").read_text())
    assert out["ok"] is False and out["records"] == [{"event_id": "x"}] and "no rows" in out["error"]


# ---------------------------------------------------------------- recreational water

def rec():
    s = json.loads((FIX / "recwater.json").read_text())
    return s


def test_history_types_lifts_tests_and_the_label_only_resampling():
    s = rec()
    recs, n = W.history_records(s["advisories"], W.station_index(s["stations"]), date(2026, 11, 14), T0)
    by = {r["source_record_id"]: r for r in recs}
    assert n["test_rows"] == 2 and "adv-319" not in by and "adv-352" not in by
    assert "adv-628" not in by and "adv-695" not in by and "adv-716" not in by and "adv-479" not in by
    assert "adv-331" not in by                                   # an advisory row whose text is a lift
    a = by["adv-625"]
    assert a["event_type"] == "beach_advisory" and a["status"] == "advisory_lifted"
    assert (a["started_at"], a["ended_at"], a["time_precision"]) == ("2025-06-17", "2025-06-18", "day")
    assert a["raw"]["ended_at_precision"] == "day" and a["raw"]["time_zone"] == "America/New_York"
    assert a["waterbody_text"] == "Lake Como" and a["lat"] == round(a["lat"], 3) and a["coord_source"] == "station"
    assert by["adv-264"]["event_type"] == "beach_closure" and by["adv-266"]["event_type"] == "hab_advisory"
    assert by["adv-264"]["waterbody_text"] == "Silver Lake" and by["adv-264"]["raw"]["county"] == "Kent"
    r = by["adv-727"]
    assert r["status"] == "unknown" and r["raw"]["_agency_label_only"] and r["raw"]["_caution_to_notice_end"]
    assert r["raw"]["_agency_label"] == "Recreational Water Quality Resampling Underway"
    assert r["raw"]["_notice_closed_at"] == "2026-07-30T00:00:00-04:00"          # the end of DNREC's last day
    assert r["waterbody_text"] == "Atlantic Ocean"
    assert W.end_of_day("2026-11-01") == "2026-11-02T00:00:00-05:00"             # across the clock change
    assert by["adv-274"]["status"] == "unknown" and "no end date" in by["adv-274"]["raw"]["status_basis"]
    assert by["adv-274"]["waterbody_text"] == "Delaware Bay" and by["adv-274"]["lat"] is None


def test_the_map_status_opens_and_closes_records_at_polls():
    s = rec()
    st = copy.deepcopy(s["stations"])
    for x in st:
        x["CurrentAdvisory"] = 0 if x["UnitName"] == "Slaughter Beach" else (2 if x["UnitName"].startswith("Lewes") else 4)
    hist, _ = W.history_records(s["advisories"], W.station_index(st), date(2026, 7, 1), T0)
    recs, state = W.poll_records(st, hist, {}, T0, date(2026, 7, 1))
    by = {r["raw"]["unit_name"]: r for r in recs}
    sl = by["Slaughter Beach"]
    assert sl["status"] == "advisory_active" and sl["started_at"] == T0 and sl["time_precision"] == "poll"
    assert sl["waterbody_text"] == "Delaware Bay" and sl["raw"]["current_advisory_label"] == "Monitoring – Current Advisory"
    lw = by["Lewes Beach (Savannah Beach)"]
    assert lw["status"] == "unknown" and lw["raw"]["_agency_label_only"]
    for x in st:
        x["CurrentAdvisory"] = 3
    recs2, _ = W.poll_records(st, hist, state, T1, date(2026, 7, 1))
    ended = {r["raw"]["unit_name"]: r for r in recs2}
    assert ended["Slaughter Beach"]["status"] == "advisory_lifted" and ended["Slaughter Beach"]["ended_at"] == T1
    assert ended["Slaughter Beach"]["raw"]["ended_at_precision"] == "poll"
    # winter, outside the advisory area and no advisory: no record
    recs3, _ = W.poll_records(st, hist, {}, T2, date(2026, 11, 14))
    assert recs3 == []


def test_a_history_row_in_effect_is_not_doubled_by_the_map():
    s = rec()
    st = copy.deepcopy(s["stations"])
    for x in st:
        x["CurrentAdvisory"] = 2 if x["UnitName"].startswith("Rehoboth Beach - Rehoboth") else 4
    hist, _ = W.history_records(s["advisories"], W.station_index(st), date(2026, 7, 28), T0)
    recs, _ = W.poll_records(st, hist, {}, T0, date(2026, 7, 28))
    assert recs == []                                        # adv-727 covers that day


def map_codes(stations, codes):
    st = copy.deepcopy(stations)
    for x in st:
        x["CurrentAdvisory"] = codes.get(x["UnitName"], 4)
    return st


def test_an_aged_history_row_or_another_kind_never_hides_the_maps_advisory():
    s = rec()
    old = [r for r in s["advisories"] if r["advisoryid"] == "274"]          # Prime Hook 2009, no end: aged out
    st = map_codes(s["stations"], {"Slaughter Beach": 0})
    old[0] = {**old[0], "unitname": "Slaughter Beach"}
    hist, _ = W.history_records(old, W.station_index(st), date(2026, 7, 1), T0)
    recs, _ = W.poll_records(st, hist, {}, T0, date(2026, 7, 1))
    assert [r["raw"]["unit_name"] for r in recs] == ["Slaughter Beach"] and recs[0]["status"] == "advisory_active"
    # a resampling notice in effect does not hide an advisory the map shows for the same beach
    st2 = map_codes(s["stations"], {"Rehoboth Beach - Rehoboth Avenue": 0})
    hist2, _ = W.history_records(s["advisories"], W.station_index(st2), date(2026, 7, 28), T0)
    recs2, _ = W.poll_records(st2, hist2, {}, T0, date(2026, 7, 28))
    assert [r["status"] for r in recs2] == ["advisory_active"]


def test_an_absent_station_is_not_a_lift_and_a_same_day_reopening_is_a_second_record():
    s = rec()
    st = map_codes(s["stations"], {"Slaughter Beach": 0})
    _, state = W.poll_records(st, [], {}, T0, date(2026, 7, 1))
    gone = [x for x in st if x["UnitName"] != "Slaughter Beach"]
    recs, state = W.poll_records(gone, [], state, T1, date(2026, 7, 1))
    assert recs[0]["status"] == "advisory_active" and recs[0]["raw"]["_missing_from_source_since"] == T1
    _, state = W.poll_records(map_codes(s["stations"], {}), [], state, T1, date(2026, 7, 1))     # explicit 4: ended
    recs, state = W.poll_records(st, [], state, T2, date(2026, 7, 1))
    assert len(recs) == 2 and {r["status"] for r in recs} == {"advisory_lifted", "advisory_active"}
    assert len({r["source_record_id"] for r in recs}) == 2


def test_a_history_row_that_leaves_the_dataset_is_carried():
    s = rec()
    hist, _ = W.history_records(s["advisories"], W.station_index(s["stations"]), date(2026, 11, 14), T0)
    prev = {r["source_record_id"]: r for r in hist}
    fewer = [r for r in s["advisories"] if r["advisoryid"] != "625"]
    hist2, _ = W.history_records(fewer, W.station_index(s["stations"]), date(2026, 11, 14), T1)
    out, n = W.carry_missing(hist2, prev, T1)
    kept = next(r for r in out if r["source_record_id"] == "adv-625")
    assert n == 1 and kept["raw"]["_missing_from_source_since"] == T1 and kept["ended_at"] == "2025-06-18"


def test_the_saved_rows_are_scrubbed_and_rounded():
    rows = W.safe_rows([{"advisoryid": "1", "advcomment": "Call 302-555-0142 or pat.example@example.org",
                         "extra": "x"}])
    assert "555-0142" not in json.dumps(rows) and "example.org" not in json.dumps(rows) and "extra" not in rows[0]
    st = W.safe_stations([{"UnitName": "X", "UnitID": 1, "CurrentAdvisory": 3, "Latitude": 38.123456,
                           "Longitude": -75.987654}])
    assert (st[0]["Latitude"], st[0]["Longitude"]) == (38.123, -75.988)


def test_no_release_is_geolocated_from_its_street_or_plant():
    from build import provisional_outfalls as P
    recs, _ = records()
    assert all(P.named_water_only(r) for r in recs.values())


def test_one_unreadable_detail_page_never_freezes_the_feed_it_is_listed_unread_and_retried(monkeypatch, tmp_path):
    # coordinator, last round (replaces the earlier hold): the readable releases are written and updated, the one
    # broken detail page is listed in meta.unread with its reason and retried, and no record is lifted or removed
    import common
    from datetime import datetime, timezone
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path)
    monkeypatch.setattr(D, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(D, "save_raw", lambda *a, **k: None)
    (tmp_path / f"{D.SOURCE_ID}.json").write_text(json.dumps({"records": [{"event_id": "old"}], "meta": {}}))
    (tmp_path / "state.json").write_text(json.dumps({"rows": {}, "backfilled_at": T0}))
    broken = {"2026-2844"}
    pages = {"2026-2850": "derns_detail_water.html", "2026-2849": "derns_detail_ground.html",
             "2026-2844": "derns_detail_textwater.html"}

    class Half(D.Client):
        def __init__(self):
            super().__init__(pause=0)

        def recent(self, pages):
            return listing()

        def detail(self, key):
            if key in broken:
                return None                              # a page that is not a release's detail (an error page)
            return D.parse_detail((FIX / pages.get(key, "derns_detail_water.html")).read_text())
    monkeypatch.setattr(D, "Client", Half)
    clock = {"t": ""}
    monkeypatch.setattr(D, "now_iso", lambda: clock["t"])
    out_path = tmp_path / f"{D.SOURCE_ID}.json"
    for t in ("2026-11-14T18:00:00Z", "2026-11-14T19:00:00Z", "2026-11-14T20:00:00Z"):   # three failed reads
        clock["t"] = t
        assert D.main(["--details", "400"]) == 1
        out = json.loads(out_path.read_text())
        ids = {r["source_record_id"] for r in out["records"]}
        assert out["ok"] is False and "2026-2844" in out["error"]
        assert {"2026-2850", "2026-2849", "2026-2845"} <= ids and "old" not in ids   # readable ones written
        assert "2026-2844" not in ids                    # wastewater, detail unread: pending, not invented
        u = out["meta"]["unread"]["2026-2844"]
        assert u["reason"] and u["last_tried"] and u["release_number"] == "17764"
    # a run inside the backoff does not ask for the broken page: ok, records current, the page still listed unread
    clock["t"] = "2026-11-14T21:00:00Z"
    assert D.main(["--details", "400"]) == 0
    out = json.loads(out_path.read_text())
    assert out["ok"] is True and "2026-2844" in out["meta"]["unread"] and len(out["records"]) == 5
    st = json.loads((tmp_path / "state.json").read_text())
    assert "2026-2844" in D.due_for_detail(st, datetime(2026, 11, 15, 22, tzinfo=timezone.utc), 400)
    broken.clear()                                       # the page comes back after the backoff
    clock["t"] = "2026-11-15T22:00:00Z"
    assert D.main(["--details", "400"]) == 0
    out = json.loads(out_path.read_text())
    assert out["ok"] is True and out["meta"]["unread"] == {}
    assert "2026-2844" in {r["source_record_id"] for r in out["records"]}


def test_a_failed_recheck_of_a_read_release_keeps_its_record_and_detail(monkeypatch, tmp_path):
    import common
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path)
    monkeypatch.setattr(D, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(D, "save_raw", lambda *a, **k: None)
    st = state_with_details()
    st["backfilled_at"] = T0
    (tmp_path / "state.json").write_text(json.dumps(st))

    class Down(D.Client):
        def __init__(self):
            super().__init__(pause=0)

        def recent(self, pages):
            return listing()

        def detail(self, key):
            raise requests.ConnectionError("down")
    import requests
    monkeypatch.setattr(D, "Client", Down)
    monkeypatch.setattr(D, "now_iso", lambda: "2026-11-15T12:00:00Z")
    before, _ = records(copy.deepcopy(st))
    assert D.main(["--details", "400"]) == 1
    out = json.loads((tmp_path / f"{D.SOURCE_ID}.json").read_text())
    after = {r["source_record_id"]: r for r in out["records"]}
    assert set(after) == set(before) and after["2026-2850"]["volume_gal"] == before["2026-2850"]["volume_gal"]
    assert out["ok"] is False                            # read before: not unread, still in the records
    assert not {"2026-2850", "2026-2849", "2026-2844"} & set(out["meta"]["unread"])


def _search_client(result_page, list_page):
    class C(D.Client):
        def __init__(self):
            super().__init__(pause=0)

        def get(self, url):
            return list_page

        def post(self, data):
            return result_page["page"]
    return C


def test_an_unreadable_search_result_page_is_a_failed_read_not_no_results():
    page1 = (FIX / "derns_list.html").read_text()
    res = {"page": "<html><body><h1>Service Unavailable</h1></body></html>"}
    with pytest.raises(RuntimeError, match="not DERNS's search page"):
        _search_client(res, page1)().search("SEWAGE")
    # a real zero-result answer: the search page with its grid and no release rows
    empty = re.sub(r"<tr[^>]*>\s*<td[^>]*><a href=\"ReleaseDetail[^\n]*</tr>", "", page1)
    empty = re.sub(r"<select[^>]*ddlPageSelector.*?</select>", "", empty, flags=re.S)
    assert not D.list_rows(empty) and D.is_search_page(empty)
    res["page"] = empty
    assert _search_client(res, page1)().search("GREY WATER") == []


def test_a_refused_backfill_search_keeps_failure_health_and_is_retried_until_read(monkeypatch, tmp_path):
    import common
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path)
    monkeypatch.setattr(D, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(D, "save_raw", lambda *a, **k: None)
    monkeypatch.setattr(D, "now_iso", lambda: "2026-11-15T12:00:00Z")
    down = {"on": True}
    asked = []

    class S(D.Client):
        def __init__(self):
            super().__init__(pause=0)

        def recent(self, pages):
            return listing()

        def search(self, term):
            asked.append(term)
            if down["on"] and term == "SEWAGE":
                raise RuntimeError(f"search {term!r}: the result page is not DERNS's search page")
            return []

        def detail(self, key):
            return None
    monkeypatch.setattr(D, "Client", S)
    assert D.main(["--details", "0"]) == 1
    st = json.loads((tmp_path / "state.json").read_text())
    out = json.loads((tmp_path / f"{D.SOURCE_ID}.json").read_text())
    assert "backfilled_at" not in st and "SEWAGE" not in st["backfill_terms_done"]
    assert out["ok"] is False and "SEWAGE" in out["error"] and out["meta"]["backfill_terms_not_read"] == ["SEWAGE"]
    assert out["records"]                                # the list's readable releases are still written
    asked.clear()
    down["on"] = False
    assert D.main(["--details", "0"]) == 0
    st = json.loads((tmp_path / "state.json").read_text())
    assert asked == ["SEWAGE"] and st["backfilled_at"] and "backfill_terms_done" not in st


def test_an_error_page_in_place_of_a_requested_list_page_fails_the_read(monkeypatch):
    page1 = (FIX / "derns_list.html").read_text()

    class Two(D.Client):
        def __init__(self):
            super().__init__(pause=0)

        def get(self, url):
            return page1

        def post(self, data):
            return "<html><body><h1>Please accept the terms to continue</h1></body></html>"
    monkeypatch.setattr(D, "page_count", lambda p: 2)
    monkeypatch.setattr(D.Client, "_next", staticmethod(lambda page, term: {}))
    with pytest.raises(RuntimeError, match="page 2"):
        Two().recent(2)


# ---------------------------------------------------------------- registry, register, rules, text, waters

def ops():
    return [r for r in json.loads((ROOT / "data" / "dischargers.json").read_text()) if r.get("state") == "DE"]


def test_every_delaware_permit_is_in_exactly_one_row():
    from build import redact
    from ingest import dischargers_schema as DS
    every = Counter(p for r in json.loads((ROOT / "data" / "dischargers.json").read_text())
                    for p in dict.fromkeys([r.get("npdes_permit"), *(r.get("npdes_permits") or [])]) if p)
    permits = {r["npdes_permit"] for f in ("outfalls-plants-us.json", "outfalls-us.json")
               for r in json.loads((ROOT / "data" / f).read_text())["outfalls"] if r.get("state") == "DE"}
    assert len(permits) == 13 and all(every[p] == 1 for p in permits)
    rows = ops()
    assert not DS.check_legal_forms(rows) and not [r["name"] for r in rows if redact.person_shaped(r["name"])]
    wil = next(r for r in rows if r["id"] == "de-de0020320")
    assert wil["kind"] == "cso" and wil["outfall_count"] == 41 and "sign" in wil["notification_channel"]
    ids = {r["id"] for r in rows}
    assert {i for _, i in D.OPERATORS} <= ids                          # every operator the ingester names has a row


def test_the_storm_sewer_permit_is_kind_other():
    doc = json.loads((ROOT / "data" / "outfalls-de.json").read_text())
    assert [(r["npdes_permit"], r["outfall_kind"]) for r in doc["outfalls"]] == [("DE0051071", "other")]
    import common
    reg = [r for r in common.load_outfall_registry(provisional=False) if r.get("npdes_permit") == "DE0051071"]
    assert [r["outfall_kind"] for r in reg] == ["other"]
    ncc = next(r for r in ops() if r["id"] == "de-new-castle-county")
    assert "DE0051071" in ncc["npdes_permits"] and ncc["outfall_count"] == 1          # MOT only (re-review P2-5)


def test_register_rows_per_operator_and_the_state_channels():
    reg = {c["id"]: c for c in json.loads((ROOT / "data" / "notice-channels" / "de.json").read_text())["channels"]}
    for r in ops():
        row = reg[f"{r['id']}-dnrec-releases"]
        assert row["feed_source_id"] == "de-dnrec-derns-recent-releases" and "6028(a)" in row["legal_basis"]
    assert reg["de-wilmington-cso-signs"]["barrier"] == "signs_only"
    assert reg["de-dnrec-derns-alerts"]["barrier"] == "login_required"
    assert reg["de-dnrec-recreational-water"]["feed_source_id"] == "de-dnrec-recreational-water"
    assert reg["de-epa-echo-overflow-events"]["monitored"]


def test_rules_row_cites_the_law_and_sets_no_window():
    rules = json.loads((ROOT / "data" / "rules.json").read_text())
    de = rules["red"]["by_state"]["DE"]
    assert de["hours"] is None and "6028(a)" in de["source"] and "6002(20)" in de["source"]
    assert not re.search(r"\b(safe|clean)\b", de["basis"], re.I)
    assert "de-dnrec-recreational-water" in rules["unresolved"]["sample_caution"]["sources"]


def test_state_text_is_in_the_page_shape():
    t = (ROOT / "research" / "de" / "state-text.md").read_text()
    assert t.startswith("---\nstate: DE\nname: Delaware\nupdated: ")
    for h in ("What the law requires", "What is published", "What is not published", "What stands in the way",
              "Known problems in the data", "What this site does about it"):
        assert f"**{h}.**" in t
    assert "{{share_line}}" in t and "{{dated_share}}" in t and "{{latest_dated}}" in t and "{{grade}}" in t
    assert not re.search(r"\b(safe|clean)\b", t, re.I) and ".json" not in t and ".py" not in t
    assert "6028" in t and "10,000 gallons" in t and "41" in t


def test_missing_waters_list_leaves_out_the_national_lists_names():
    d = json.loads((ROOT / "research" / "de" / "receiving-waters-missing.json").read_text())
    nat = json.loads((ROOT / "data" / "receiving-waters-national.json").read_text())

    def k(n):
        return re.sub(r"[^a-z0-9]", "", (n or "").lower())
    held = {k(n) for w in nat["states"]["DE"]["waters"]
            for n in [w.get("name"), w.get("key"), *(w.get("names_seen") or []), *(w.get("gnis_names") or [])] if n}
    assert d["state"] == "DE" and d["waters"] == len(d["rows"])
    assert not [r["name"] for r in d["rows"] if k(r["name"]) in held]
    keys = [(r["name"], r["county"]) for r in d["rows"]]
    assert len(keys) == len(set(keys))


def test_adding_the_states_leaves_the_other_states_lists_as_they_were():
    from build import charts, report_geolocate, status
    assert status.COUNTY_STATES["DE"] == "de-counties.json" and "DE" in status.COUNTY_FIELD_STATES
    assert status.COUNTY_STATES["TN"] == "tn-counties.json" and status.COUNTY_STATES["AL"] == "al-counties.json"
    assert charts.STATE_NAMES["DE"] == "Delaware" and report_geolocate.STATE_NAMES["SC"] == "South Carolina"
    assert report_geolocate.STATE_NAMES["DE"] == "Delaware" and charts.STATE_NAMES["TN"] == "Tennessee"
    counties = json.loads((ROOT / "data" / "reference" / "de-counties.json").read_text())
    assert sorted(c["county"] for c in counties["counties"]) == ["Kent County", "New Castle County", "Sussex County"]


def test_the_shared_rule_texts_other_states_cite_are_unchanged():
    # review P2-5: a rationale is copied into every interval's rule_applied, so Delaware and South Carolina join the
    # source lists without changing the texts Georgia's, Hawaii's and the others' intervals carry
    rules = json.loads((ROOT / "data" / "rules.json").read_text())["unresolved"]
    for k in ("sample_caution", "day_start_caution"):
        assert not re.search(r"Delaware|Florence|DNREC", rules[k]["rationale"] + rules[k].get("source", ""))
    assert rules["sample_caution"]["sources"][-1] == "de-dnrec-recreational-water"
    assert rules["day_start_caution"]["sources"][-1] == "de-dnrec-derns-recent-releases"
    assert "sc-florence-sso-notices" not in rules["day_start_caution"]["sources"]    # no start: re-review P1-1


def test_the_notification_clock_and_an_unverified_owner_are_stated_as_the_sources_give_them():
    reg = {c["id"]: c for c in json.loads((ROOT / "data" / "notice-channels" / "de.json").read_text())["channels"]}
    assert "within 12 hours after DNREC is informed" in reg["de-dnrec-derns-alerts"]["legal_basis"]
    row = next(r for r in ops() if r["id"] == "de-de0021512")
    assert row["npdes_permits"] == ["DE0021512"] and "permittee not recorded by EPA" in row["name"]
    assert not row.get("legal_form")
    assert "DE0021512" not in next(r for r in ops() if r["id"] == "de-sussex-county")["npdes_permits"]


def test_no_sentinel_reaches_any_save_from_the_recreational_water_feed(monkeypatch, tmp_path):
    # re-review P1-5: DNREC's free text through the Delaware scrubber before the raw save, the state and the records
    s = rec()
    rows = copy.deepcopy(s["advisories"])
    rows[0]["advcomment"] = "Call Pat Example at 1234 Sample Street or 302-555-0142."
    rows[0]["advdesc"] = "Contact: Pat Example, pat@example.org"
    rows[0]["contact_name"] = "Robin Sample"
    saves = []
    monkeypatch.setattr(W, "save_raw", lambda *a, **k: saves.append(json.dumps(a, default=str)))
    monkeypatch.setattr(W, "write_json", lambda path, obj, *a, **k: saves.append(json.dumps(obj, default=str)))
    monkeypatch.setattr(W, "write_events", lambda sid, recs, **k: saves.append(json.dumps([recs, k], default=str)))
    monkeypatch.setattr(W, "STATE_PATH", tmp_path / "state.json")

    class Resp:
        def __init__(self, js):
            self._js = js

        def raise_for_status(self):
            pass

        def json(self):
            return self._js
    monkeypatch.setattr(W.requests, "get", lambda url, **k: Resp(rows) if url == W.SOCRATA else
                        Resp({"features": [{"attributes": a} for a in s["stations"]]}))
    assert W.main(["--at", T0]) == 0
    blob = "\n".join(saves)
    assert len(saves) >= 3
    for x in ("Pat Example", "Robin Sample", "1234 Sample", "302-555-0142", "pat@example.org"):
        assert x not in blob, x


def test_history_and_map_count_one_advisory_and_same_minute_reopenings_stay_apart():
    # re-review P2-1
    s = rec()
    st = map_codes(s["stations"], {"Slaughter Beach": 0})
    row = {"advisoryid": "9001", "advstartdate": "2026-07-01T00:00:00.000", "advdesc": "Example high result",
           "advreason": "Enterococcus Monitor", "advtype": "Recreational Water Quality Advisory",
           "unitname": "Slaughter Beach"}
    # a history row with no end yet, in effect, plus the map's matching status: one active record, not two
    hist, _ = W.history_records([row], W.station_index(st), date(2026, 7, 2), T0)
    assert hist[0]["status"] == "advisory_active" and hist[0]["ended_at"] is None
    recs, _ = W.poll_records(st, hist, {}, T0, date(2026, 7, 2))
    assert recs == []
    # the map first, the history row later: the poll record is kept but marked the history's duplicate
    _, state = W.poll_records(st, [], {}, "2026-07-02T18:00:00Z", date(2026, 7, 2))
    recs, state = W.poll_records(st, hist, state, "2026-07-02T19:00:00Z", date(2026, 7, 2))
    assert len(recs) == 1 and recs[0]["duplicate_of"] == hist[0]["event_id"]
    active = [r for r in hist + recs if r["status"] == "advisory_active" and not r.get("duplicate_of")]
    assert len(active) == 1
    # opened 18:00:01, closed 18:00:20, reopened 18:00:40: three polls, two episodes, both kept
    _, st1 = W.poll_records(st, [], {}, "2026-07-03T18:00:01Z", date(2026, 7, 3))
    _, st1 = W.poll_records(map_codes(s["stations"], {}), [], st1, "2026-07-03T18:00:20Z", date(2026, 7, 3))
    recs, _ = W.poll_records(st, [], st1, "2026-07-03T18:00:40Z", date(2026, 7, 3))
    assert sorted((r["started_at"], r["ended_at"]) for r in recs) == [
        ("2026-07-03T18:00:01Z", "2026-07-03T18:00:20Z"), ("2026-07-03T18:00:40Z", None)]


def test_a_still_listed_resampling_notice_is_current_at_and_after_its_confirming_poll():
    # re-review P2-2: first seen November 1, confirmed November 14 18:00: not grey at 18:00
    from datetime import datetime, timezone
    from build import status
    rules = json.loads((ROOT / "data" / "rules.json").read_text())
    s = rec()
    st = map_codes(s["stations"], {"Lewes Beach (Savannah Beach)": 2})
    _, state = W.poll_records(st, [], {}, "2026-11-01T18:00:00Z", date(2026, 11, 1))
    recs, state = W.poll_records(st, [], state, "2026-11-14T18:00:00Z", date(2026, 11, 14))
    r = recs[0]
    assert r["ended_at"] is None and "_notice_closed_at" not in r["raw"]
    for at in (datetime(2026, 11, 14, 18, tzinfo=timezone.utc), datetime(2026, 11, 15, 18, tzinfo=timezone.utc)):
        ivs = status.event_intervals(r, "DE", at, None, rules)
        assert any(i["start"] <= at and (i["end"] is None or i["end"] > at) for i in ivs), at
    # closed at a later poll: the caution runs to the closure, as before
    recs, _ = W.poll_records(map_codes(s["stations"], {}), [], state, "2026-11-15T18:00:00Z", date(2026, 11, 15))
    assert recs[0]["raw"]["_notice_closed_at"] == "2026-11-15T18:00:00Z"


@pytest.mark.parametrize("q,gal,bounds", [
    ("Equal To 1,500.00 GALLONS", 1500.0, None),                       # comma and decimals kept whole
    ("Equal to 250 GAL", 250.0, None),
    ("Less Than 1,000 GALLONS", None, {"kind": "upper_bound", "max_gal": 1000.0}),
    ("Greater Than 10,000 Gallons", None, {"kind": "lower_bound", "min_gal": 10000.0}),
    ("1,000-2,000 gallons", None, {"kind": "range", "min_gal": 1000.0, "max_gal": 2000.0}),
    ("1,000 – 2,000 gallons", None, {"kind": "range", "min_gal": 1000.0, "max_gal": 2000.0}),
    ("50 gallons per minute", None, {"kind": "rate", "text": "50 gallons per minute"}),
])
def test_a_quantity_is_a_figure_only_when_the_form_gives_one(q, gal, bounds):
    # re-review P2-4: bounds, ranges and rates are never numeric volumes
    v, text, flag = D.volume({"quantity": q})
    assert v == gal and text == q and flag == ("estimated" if gal is not None else "unknown")
    assert D.volume_bounds({"quantity": q}) == bounds


def test_the_state_texts_volume_statistics_count_only_figures():
    # re-review P2-4: the published median and threshold count only "equal to" figures, from the parser
    import statistics
    st = state_with_details()
    for k, q in zip(list(st["rows"])[:4], ["Equal To 100 GALLONS", "Equal To 300 GALLONS",
                                           "Less Than 50,000 GALLONS", "Greater Than 20,000 GALLONS"]):
        if st["rows"][k].get("detail"):
            st["rows"][k]["detail"]["quantity"] = q
    recs, _ = D.build(st, T0)
    vols = [r["volume_gal"] for r in recs if r["volume_gal"] is not None]
    assert all(v < 10000 for v in vols)                     # no bound counted among the 10,000-gallon figures
    text = (ROOT / "research" / "de" / "state-text.md").read_text()
    assert "median of 200 gallons" in text and "23 of them 10,000 gallons or more" in text
    assert "completed years 2017 to 2025" in text


def test_an_owner_is_named_only_where_epas_permittee_names_it():
    # re-review P2-5: a plant's town or a plant's name never makes its owner; such a permit is its own row, no owner
    rows = {r["id"]: r for r in ops()}
    epa = {}
    for f in ("outfalls-plants-us.json", "outfalls-us.json"):
        for r in json.loads((ROOT / "data" / f).read_text())["outfalls"]:
            if str(r.get("npdes_permit") or "").startswith("DE"):
                epa[r["npdes_permit"]] = (r.get("permittee") or "").upper()
    owner_words = {"city": "CITY OF", "county": "COUNTY", "town": "TOWN OF"}
    for r in rows.values():
        for p in r["npdes_permits"]:
            if r.get("legal_form") in owner_words and p in epa:
                name = epa[p]
                assert owner_words[r["legal_form"]] in name or "NCC" in name, (r["id"], p, name)
    for p in ("DE0020010", "DE0020028", "DE0020125", "DE0020265", "DE0021491", "DE0021512", "DE0050008",
              "DE0021539", "DE0021555"):
        row = next(r for r in rows.values() if p in r["npdes_permits"])
        assert row["npdes_permits"] == [p] and not row.get("legal_form"), p
        assert "permittee not recorded by EPA" in row["name"], p
