"""South Carolina: the City of Florence's sanitary sewer overflow notices (ingest/sc_florence_sso.py), DES's beach
station advisories and bloom watches (ingest/sc_des_advisories.py), and the state's registry rows, register, rules row,
state text and missing-waters list. Fixtures: rows of the 2026-11-14 fetches (DES's layers and table) and a Florence
notice whose contact block, telephone numbers and street numbers are invented (Example names). No network."""
import copy
import json
import re
from collections import Counter
from pathlib import Path

from ingest import sc_des_advisories as A
from ingest import sc_florence_sso as F

ROOT = Path(__file__).resolve().parents[2]
FIX = Path(__file__).resolve().parent / "fixtures" / "sc"
T0, T1, T2 = "2026-11-14T18:00:00Z", "2026-11-14T19:00:00Z", "2026-11-14T20:00:00Z"
PERSONAL = ["Pat Example", "pexample@example.org", "843-555-0142", "555-0142", "555-0199", "1234 W", "5678 Sample"]


def notice(page: str | None = None):
    nid, title, paras = F.article(page or (FIX / "florence_notice.html").read_text())
    return nid, F.parse_notice(title, paras)


def florence_records(state):
    return {r["source_record_id"]: r for r in F.records(state, T0)}


# ---------------------------------------------------------------- Florence

def test_the_notice_is_read_from_its_dateline_with_the_contacts_cut():
    nid, p = notice()
    assert nid == "1929"
    assert p["release_date"] == "2025-08-15" and p["incident_day"] == "2025-08-15"
    assert p["start_basis"].startswith("the day the City received notice")
    assert p["volume_gal"] is None and p["volume_text"].startswith("more than 5,000 gallons")   # a lower bound
    assert p["waters"] == ["Jeffries Creek"] and p["until_further_notice"]
    assert "Avoid swimming" in p["advice"] and "W Example Street" in p["advice"]
    assert "policy" not in (p["volume_text"] or "")


def test_no_personal_string_reaches_a_record():
    nid, p = notice()
    st = {"notices": {}}
    F.update_notice(st, "/news/notification-sanitary-sewer-overflow-jeffries-creek-1", nid, p, T0)
    blob = json.dumps(F.records(st, T0)) + json.dumps(st)
    for s in PERSONAL:
        assert s not in blob, s
    assert "[house number removed]" in blob


def test_the_record_is_a_sewage_report_with_no_invented_start_and_the_advice_its_own_record():
    # re-review P1-1: the notification and release days are kept as such, never the overflow's start; the advice to
    # avoid the creek is its own record, not evidence that sewage is still flowing
    nid, p = notice()
    st = {"notices": {}}
    F.update_notice(st, "/news/x", nid, p, T0)
    recs = florence_records(st)
    assert set(recs) == {"1929", "1929-advice"}
    r = recs["1929"]
    assert r["event_type"] == "sso" and r["status"] == "unknown" and r["ended_at"] is None
    assert r["started_at"] is None and r["time_precision"] is None
    assert r["reported_at"] == "2025-08-15" and r["published_at"] == "2025-08-15"
    assert r["raw"]["notification_day"] == "2025-08-15" and r["raw"]["release_date"] == "2025-08-15"
    assert r["raw"]["time_zone"] == "America/New_York"
    assert r["discharger_id"] == "sc-florence" and r["npdes_permit"] is None
    assert r["waterbody_text"] == "Jeffries Creek" and r["raw"]["county"] == "Florence"
    assert r["lat"] is None and r["lon"] is None
    a = recs["1929-advice"]
    assert a["status"] == "advisory_active" and a["started_at"] == "2025-08-15" and a["ended_at"] is None
    assert a["raw"]["until_further_notice"] and a["raw"]["_ages_after_confirmation"] is True
    assert a["raw"]["overflow_record"] == r["event_id"] and "not the overflow's start" in a["raw"]["start_basis"]


def _ivs(rec, now):
    from build import status
    rules = json.loads((ROOT / "data" / "rules.json").read_text())
    return status.event_intervals(rec, "SC", now, None, rules)


def test_the_advice_holds_while_the_city_reconfirms_it_and_an_archive_reread_is_no_confirmation():
    from datetime import datetime, timezone
    nid, p = notice()
    st = {"notices": {}}
    F.update_notice(st, "/news/x", nid, p, "2025-08-16T12:00:00Z")
    # weekly rereads of the unchanged page in the archive: no confirmation
    F.update_notice(st, "/news/x", nid, copy.deepcopy(p), "2025-10-01T12:00:00Z")
    a = florence_records(st)["1929-advice"]
    assert a["raw"]["_last_seen_in_source"] == "2025-08-15"
    ivs = _ivs(a, datetime(2025, 10, 1, 12, tzinfo=timezone.utc))
    red = [i for i in ivs if i["rule"] == "advisory_active"]
    assert red and red[0]["end"].date().isoformat() == "2025-08-29"          # 14 days after the release, then not reconfirmed
    # the City edits the notice months later and still advises avoiding the creek: confirmed again
    p2 = copy.deepcopy(p)
    p2["advice"] += " The advisory remains in effect."
    assert F.update_notice(st, "/news/x", nid, p2, "2025-12-01T12:00:00Z") == "revised"
    a = florence_records(st)["1929-advice"]
    assert a["raw"]["_last_seen_in_source"] == "2025-12-01T12:00:00Z"
    red = [i for i in _ivs(a, datetime(2025, 12, 5, tzinfo=timezone.utc)) if i["rule"] == "advisory_active"]
    assert red and red[0]["end"].date().isoformat() == "2025-12-15"
    # the overflow record still has no start, whatever the advice does, and still draws the site's caution from the
    # notification day (never red: no window of the City's own)
    o = florence_records(st)["1929"]
    assert o["started_at"] is None
    ov = _ivs(o, datetime(2025, 8, 20, tzinfo=timezone.utc))
    assert ov and ov[0]["start"].date().isoformat() == "2025-08-15" and ov[0]["rule"] != "advisory_active"


def test_an_edit_that_drops_the_advice_ends_it_at_a_poll_bound():
    nid, p = notice()
    st = {"notices": {}}
    F.update_notice(st, "/news/x", nid, p, T0)
    p2 = copy.deepcopy(p)
    p2.update(advice=None, until_further_notice=False)
    F.update_notice(st, "/news/x", nid, p2, T2)
    a = florence_records(st)["1929-advice"]
    assert a["ended_at"] == T2 and a["raw"]["ended_at_precision"] == "poll"
    assert a["raw"]["lift_observed_between"] == [T0, T2]


def test_yesterday_and_a_spelling_and_an_estimate():
    page = (FIX / "florence_notice.html").read_text()
    page = page.replace("On Friday, August 15, the City of Florence received notice of",
                        "The City of Florence is currently experiencing")
    page = page.replace("Staff responded immediately upon being notified", "Staff responded to the area yesterday")
    page = page.replace("more than 5,000 gallons", "an estimated 115,200 gallons").replace("Jeffries Creek", "Jefferies Creek")
    _, p = notice(page)
    assert p["incident_day"] == "2025-08-14" and "yesterday" in p["start_basis"] and "derived" in p["start_basis"]
    assert p["volume_gal"] == 115200.0 and p["estimate_flag"] == "estimated"
    assert p["waters"] == ["Jeffries Creek"] and p["aliases_seen"] == ["Jefferies Creek"]


def test_a_reused_page_address_never_overwrites_the_earlier_record():
    nid, p = notice()
    st = {"notices": {}}
    assert F.update_notice(st, "/news/x", nid, p, T0) == "new"
    assert F.update_notice(st, "/news/x", nid, copy.deepcopy(p), T1) == "same"
    # an edit to the same overflow (same dates): the record is revised in place
    p2 = copy.deepcopy(p)
    p2["advice"] = (p2["advice"] or "") + " Signs have been posted."
    assert F.update_notice(st, "/news/x", nid, p2, T1) == "revised"
    recs = florence_records(st)
    assert set(recs) == {"1929", "1929-advice"} and recs["1929"]["raw"]["_revisions"]
    # the page rewritten for a later overflow: a second record, the first kept as it was
    p3 = copy.deepcopy(p)
    p3.update(release_date="2025-11-03", incident_day="2025-11-02", volume_text="an unknown volume")
    first_before = florence_records(st)["1929"]
    assert F.update_notice(st, "/news/x", nid, p3, T2) == "new_version"
    recs = florence_records(st)
    assert set(recs) == {"1929", "1929-advice", "1929-v2", "1929-v2-advice"}
    assert recs["1929"]["reported_at"] == first_before["reported_at"] == "2025-08-15"
    assert recs["1929"]["volume_text"] == first_before["volume_text"]
    assert recs["1929"]["raw"]["later_version"]["seen_at"] == T2
    assert recs["1929-v2"]["reported_at"] == "2025-11-02" and recs["1929-v2"]["raw"]["earlier_version_of_page"] == "1929"


def test_a_contact_block_of_several_paragraphs_is_cut_whole():
    page = (FIX / "florence_notice.html").read_text()
    block = ("<h4><strong>Media Contacts:</strong></h4><p>Pat Example</p><p>Utilities Director</p>"
             "<p>843-555-0142</p><p>pexample@example.org</p>")
    page = page.replace(re.search(r"<h4>.*?</h4>", page, re.S).group(0), block)
    # and a second block after the dateline
    page = page.replace("<p>It is estimated", block + "<p>It is estimated")
    nid, p = notice(page)
    st = {"notices": {}}
    F.update_notice(st, "/news/x", nid, p, T0)
    blob = json.dumps(st) + json.dumps(F.records(st, T0))
    for s_ in PERSONAL + ["Utilities Director"]:
        assert s_ not in blob, s_
    assert p["volume_text"].startswith("more than 5,000 gallons")


def test_a_sampling_reassurance_is_never_kept_as_record_text():
    page = (FIX / "florence_notice.html").read_text().replace(
        "<p>Residents are advised", "<p>The analyzed bacteriological samples from Jeffries Creek document that there "
        "is no threat to public health or the environment.</p><p>Residents are advised")
    nid, p = notice(page)
    st = {"notices": {}}
    F.update_notice(st, "/news/x", nid, p, T0)
    r = F.records(st, T0)[0]
    assert p["sampling_statement_cut"] and "no threat" not in json.dumps(r)
    assert r["raw"]["_placement"] == "named_water_only"


def test_a_notice_page_that_cannot_be_read_fails_the_run(monkeypatch, tmp_path):
    import common
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path)
    monkeypatch.setattr(F, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(F, "save_raw", lambda *a, **k: None)
    monkeypatch.setattr(F, "PAUSE_S", 0)
    (tmp_path / f"{F.SOURCE_ID}.json").write_text(json.dumps({"records": [{"event_id": "x"}], "meta": {}}))
    (tmp_path / "state.json").write_text(json.dumps({"notices": {}, "backfilled_at": T0}))
    listing = (FIX / "florence_list.html").read_text()

    class Resp:
        def __init__(self, text, code=200):
            self.text, self.code = text, code

        def raise_for_status(self):
            if self.code >= 400:
                raise F.requests.HTTPError(f"{self.code}")

    class Sess:
        headers = {}

        def get(self, url, **k):
            return Resp(listing) if "city-news" in url else Resp("refused", 403)
    monkeypatch.setattr(F.requests, "Session", Sess)
    assert F.main(["--pages", "1"]) == 1
    out = json.loads((tmp_path / f"{F.SOURCE_ID}.json").read_text())
    assert out["ok"] is False and out["records"] == [{"event_id": "x"}] and "not read" in out["error"]


def test_only_overflow_titles_are_read_from_the_list():
    items = F.list_items((FIX / "florence_list.html").read_text())
    assert len(items) == 4
    read = [s for s, t in items if F.TITLE_RE.search(t)]
    assert read == ["/news/notification-sanitary-sewer-overflow-jeffries-creek-1"]


# ---------------------------------------------------------------- DES beach stations and blooms

def saved():
    return json.loads((FIX / "advisories.json").read_text())


def test_long_term_advisories_are_standing_records_from_the_first_poll():
    s = saved()
    recs, state, n = A.beach_records(s["beach"], {}, T0)
    assert n["stations"] == 4 and n["Long-Term"] == 3 and n["No Advisory"] == 1
    assert len(recs) == 3 and {r["raw"]["station"] for r in recs} == {"LC-080", "LC-081", "WAC-035"}
    r = next(x for x in recs if x["raw"]["station"] == "LC-080")
    assert r["event_type"] == "beach_advisory" and r["status"] == "advisory_active"
    assert r["started_at"] == T0 and r["time_precision"] == "poll" and r["ended_at"] is None
    assert r["raw"]["advisory_kind"] == "long-term" and "began before this poll" in r["raw"]["start_basis"]
    assert r["lat"] == round(r["lat"], 3) and r["coord_source"] == "station" and r["raw"]["county"] == "Colleton"
    assert "NOT to swim" in r["advice_text"] and r["raw"]["time_zone"] == "America/New_York"


def key_at(stat, t):
    return f"{stat}-{re.sub(r'[^0-9T]', '', t)[:13]}"


def test_a_station_given_another_value_ends_at_that_poll_and_an_unknown_label_is_kept():
    s = saved()
    _, state, _ = A.beach_records(s["beach"], {}, T0)
    later = copy.deepcopy(s["beach"])
    for f in later:
        if f["attributes"]["STAT"] == "LC-080":
            f["attributes"]["ADVISORY"] = "No Advisory"
        if f["attributes"]["STAT"] == "LC-109":
            f["attributes"]["ADVISORY"] = "Advisory Pending"           # a value DES has not used: never grey
    recs, state2, _ = A.beach_records(later, {"beach": state}, T1)
    by = {r["source_record_id"]: r for r in recs}
    lc80 = by[key_at("LC-080", T0)]
    assert lc80["status"] == "advisory_lifted" and lc80["ended_at"] == T1 and lc80["raw"]["ended_at_precision"] == "poll"
    assert by[key_at("LC-081", T0)]["status"] == "advisory_active" and by[key_at("LC-081", T0)]["started_at"] == T0
    odd = by[key_at("LC-109", T1)]
    assert odd["status"] == "unknown" and odd["raw"]["_agency_label_only"] and odd["raw"]["_agency_label"] == "Advisory Pending"


def test_a_blank_value_or_an_absent_station_is_not_a_lift():
    s = saved()
    _, state, _ = A.beach_records(s["beach"], {}, T0)
    later = [copy.deepcopy(f) for f in s["beach"] if f["attributes"]["STAT"] != "WAC-035"]     # station left out
    for f in later:
        if f["attributes"]["STAT"] == "LC-080":
            f["attributes"]["ADVISORY"] = None                          # a blank field
    recs, _, _ = A.beach_records(later, {"beach": state}, T1)
    by = {r["raw"]["station"]: r for r in recs}
    for stat in ("LC-080", "WAC-035"):
        assert by[stat]["status"] == "advisory_active" and by[stat]["ended_at"] is None
        assert by[stat]["raw"]["_missing_from_source_since"] == T1
    assert "_missing_from_source_since" not in by["LC-081"]["raw"]


def test_an_advisory_reopened_the_same_day_is_a_second_record():
    s = saved()
    one = [copy.deepcopy(f) for f in s["beach"] if f["attributes"]["STAT"] == "LC-080"]
    _, st, _ = A.beach_records(one, {}, T0)
    one[0]["attributes"]["ADVISORY"] = "No Advisory"
    _, st, _ = A.beach_records(one, {"beach": st}, T1)
    one[0]["attributes"]["ADVISORY"] = "Long-Term"
    recs, st, _ = A.beach_records(one, {"beach": st}, T2)
    by = {r["source_record_id"]: r for r in recs}
    assert len(by) == 2
    assert by[key_at("LC-080", T0)]["ended_at"] == T1 and by[key_at("LC-080", T2)]["started_at"] == T2
    recs2, _, _ = A.beach_records(one, {"beach": st}, T2.replace("20:", "21:"))
    assert {r["source_record_id"] for r in recs2} == set(by)                          # stable across later runs


def test_a_station_reopened_within_the_same_minute_keeps_both_episodes():
    # re-review P2-1
    s = saved()
    one = [copy.deepcopy(f) for f in s["beach"] if f["attributes"]["STAT"] == "LC-080"]
    _, st, _ = A.beach_records(one, {}, "2026-11-14T18:00:01Z")
    one[0]["attributes"]["ADVISORY"] = "No Advisory"
    _, st, _ = A.beach_records(one, {"beach": st}, "2026-11-14T18:00:20Z")
    one[0]["attributes"]["ADVISORY"] = "Long-Term"
    recs, _, _ = A.beach_records(one, {"beach": st}, "2026-11-14T18:00:40Z")
    assert sorted((r["started_at"], r["ended_at"]) for r in recs) == [
        ("2026-11-14T18:00:01Z", "2026-11-14T18:00:20Z"), ("2026-11-14T18:00:40Z", None)]


def test_a_short_term_advisory_and_a_closure_by_label():
    s = saved()
    f = copy.deepcopy(s["beach"])
    f[0]["attributes"]["ADVISORY"], f[1]["attributes"]["ADVISORY"] = "Temporary", "Emergency Closure"
    recs, _, _ = A.beach_records(f, {}, T0)
    kinds = {r["raw"]["station"]: (r["event_type"], r["raw"]["advisory_kind"]) for r in recs}
    assert kinds[f[0]["attributes"]["STAT"]] == ("beach_advisory", "short-term")
    assert kinds[f[1]["attributes"]["STAT"]] == ("beach_closure", "closure")


def test_the_bloom_watch_is_des_own_dated_at_its_cove_and_ends_only_when_both_drop_it():
    s = saved()
    recs, state, n = A.hab_records(s["hab"], s["hab_table"], {}, T0)
    assert len(recs) == 1 and n["table_rows"] == 1
    r = recs[0]
    assert r["event_type"] == "hab_advisory" and r["status"] == "advisory_active"
    assert r["started_at"] == "2026-10-16" and r["time_precision"] == "day"
    assert r["raw"]["advisory_level"] == "Watch" and r["raw"]["advisory_area"] == "Cedar Point Cove"
    assert r["waterbody_text"] == "J. Strom Thurmond Reservoir" and r["outfall_name"] == "Cedar Point Cove"
    assert r["coord_source"] == "des_delineation" and 33.7 < r["lat"] < 33.9
    assert "Microcystis" in r["advice_text"]
    key = r["source_record_id"]
    # layer -> table only -> layer: one record, its point and organism kept, never ended in between
    recs2, state2, _ = A.hab_records([], s["hab_table"], {"hab": state}, T1)
    assert [x["source_record_id"] for x in recs2] == [key]
    assert recs2[0]["status"] == "advisory_active" and recs2[0]["lat"] == r["lat"] and recs2[0]["raw"]["organism"]
    recs3, state3, _ = A.hab_records(s["hab"], s["hab_table"], {"hab": state2}, T2)
    assert [x["source_record_id"] for x in recs3] == [key] and recs3[0]["ended_at"] is None
    # neither lists it: ended at that poll
    recs4, _, _ = A.hab_records([], [], {"hab": state3}, T2)
    assert recs4[0]["status"] == "advisory_lifted" and recs4[0]["ended_at"] == T2
    assert recs4[0]["raw"]["ended_at_precision"] == "poll"


def test_two_coves_issued_the_same_day_stay_two_records():
    table = [{"level": "Advisory", "area": "Example Cove", "water": "Lake Example", "issued": "07/04/2026"},
             {"level": "Advisory", "area": "Sample Cove", "water": "Lake Example", "issued": "07/04/2026"}]
    recs, st, _ = A.hab_records([], table, {}, T0)
    assert len(recs) == 2 and {r["raw"]["advisory_area"] for r in recs} == {"Example Cove", "Sample Cove"}
    recs2, _, _ = A.hab_records([], table, {"hab": st}, T1)
    assert {r["source_record_id"] for r in recs2} == {r["source_record_id"] for r in recs}


def _feat(gid, x, y, ms=1783137600000):
    return {"attributes": {"OBJECTID": 1, "NAME": "Lake Example", "Algal_Bloom": "Microcystis", "Date": ms,
                           "Advisory_Tier": "Advisory", "Recreational_Guidance": None, "GlobalID": gid},
            "centroid": {"x": x, "y": y}}


def test_two_coves_on_one_water_and_date_never_exchange_points():
    # re-review P1-4: a delineation is tied to a cove only by evidence; reordering never moves a point
    ex = {"level": "Advisory", "area": "Example Cove", "water": "Lake Example", "issued": "07/04/2026"}
    sa = {"level": "Advisory", "area": "Sample Cove", "water": "Lake Example", "issued": "07/04/2026"}
    fx, fy = _feat("gx", -81.101, 34.101), _feat("gy", -81.202, 34.202)
    # nothing tells two new delineations apart: two cove records, no point assigned, both orders alike
    for fs, tb in (([fx, fy], [ex, sa]), ([fy, fx], [sa, ex])):
        recs, _, n = A.hab_records(fs, tb, {}, T0)
        assert {r["outfall_name"]: r["lat"] for r in recs} == {"Example Cove": None, "Sample Cove": None}
        assert n["ambiguous_delineations"] == 2
    # Example Cove alone first: its delineation is tied to it
    recs, st, _ = A.hab_records([fx], [ex], {}, T0)
    assert recs[0]["lat"] == 34.101
    # Sample Cove joins; layer and table in either order: each keeps its own point
    for fs, tb in (([fy, fx], [sa, ex]), ([fx, fy], [ex, sa])):
        recs, st, _ = A.hab_records(fs, tb, {"hab": st}, T1)
        assert {r["outfall_name"]: r["lat"] for r in recs} == {"Example Cove": 34.101, "Sample Cove": 34.202}
    ids = {r["outfall_name"]: r["source_record_id"] for r in recs}
    # layer -> table only -> layer: identities and points held
    recs, st, _ = A.hab_records([], [sa, ex], {"hab": st}, T2)
    assert {r["outfall_name"]: (r["source_record_id"], r["lat"]) for r in recs} == {
        "Example Cove": (ids["Example Cove"], 34.101), "Sample Cove": (ids["Sample Cove"], 34.202)}
    recs, st, _ = A.hab_records([fy, fx], [ex, sa], {"hab": st}, T2.replace("20:", "21:"))
    assert {r["outfall_name"]: (r["source_record_id"], r["lat"], r["ended_at"]) for r in recs} == {
        "Example Cove": (ids["Example Cove"], 34.101, None), "Sample Cove": (ids["Sample Cove"], 34.202, None)}


def test_an_unreadable_table_fails_the_bloom_feed_and_keeps_its_records(monkeypatch, tmp_path):
    import common
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path)
    monkeypatch.setattr(A, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(A, "save_raw", lambda *a, **k: None)
    (tmp_path / "sc-des-hab.json").write_text(json.dumps({"records": [{"event_id": "x"}], "meta": {}}))
    s = saved()

    class Resp:
        def __init__(self, js=None, text=""):
            self._js, self.text = js, text

        def raise_for_status(self):
            pass

        def json(self):
            return self._js

    def fake_get(url, **k):
        if "BW_Monitoring" in url:
            return Resp({"features": s["beach"]})
        if "algal_hydro" in url:
            return Resp({"features": s["hab"]})
        return Resp(text="<html><body>Please enable cookies</body></html>")
    monkeypatch.setattr(A.requests, "get", fake_get)
    assert A.main([]) == 1
    out = json.loads((tmp_path / "sc-des-hab.json").read_text())
    assert out["ok"] is False and out["records"] == [{"event_id": "x"}]
    assert json.loads((tmp_path / "sc-des-beach-monitoring.json").read_text())["ok"] is True


def test_malformed_tables_and_incomplete_layers_fail_and_end_nothing(monkeypatch, tmp_path):
    # re-review P1-3: an error row, changed columns or a cut-off table is not an empty listing; an incomplete layer
    # response is refused; the previous records stay and no bloom ends
    head = "<h2>HAB Watches &amp; Advisories</h2><table><tr><th>Advisory Level</th></tr>"
    assert A.hab_table(head + "<tr><td>Service unavailable</td></tr></table>") is None
    assert A.hab_table("<h2>HAB Watches</h2><table><tr><th>Lake</th></tr><tr><td>Advisory</td><td>Example Cove</td>"
                       "<td>Lake Example</td><td>07/04/2026</td></tr></table>") is None
    assert A.hab_table(head + "<tr><td>Advisory</td><td>Example Cove</td><td>Lake Example</td><td>soon</td></tr>"
                       "</table>") is None
    assert A.hab_table(head + "<tr><td>Advisory</td><td>Example Cove</td>") is None          # cut off
    assert A.hab_table(head + "</table>") == []                                          # a whole, empty table
    import pytest
    for js in ({"error": {"code": 500}}, {"features": [], "exceededTransferLimit": True},
               {"features": [{"attributes": {"NAME": "Lake Example"}}]}, None):
        with pytest.raises(ValueError):
            A.check_layer(js, ("NAME", "Date", "Advisory_Tier"))
    import common
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path)
    monkeypatch.setattr(A, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(A, "save_raw", lambda *a, **k: None)
    s = saved()
    _, hstate, _ = A.hab_records(s["hab"], s["hab_table"], {}, T0)
    (tmp_path / "state.json").write_text(json.dumps({"hab": hstate}))
    (tmp_path / "sc-des-hab.json").write_text(json.dumps({"records": [{"event_id": "x"}], "meta": {}}))

    class Resp:
        def __init__(self, js=None, text=""):
            self._js, self.text = js, text

        def raise_for_status(self):
            pass

        def json(self):
            return self._js

    def fake_get(url, **k):
        if "BW_Monitoring" in url:
            return Resp({"features": s["beach"]})
        if "algal_hydro" in url:
            return Resp({"features": []})
        return Resp(text=head + "<tr><td>Service unavailable</td></tr></table>")
    monkeypatch.setattr(A.requests, "get", fake_get)
    assert A.main(["--at", T1]) == 1
    out = json.loads((tmp_path / "sc-des-hab.json").read_text())
    assert out["ok"] is False and out["records"] == [{"event_id": "x"}]
    st = json.loads((tmp_path / "state.json").read_text())
    assert all(not v.get("ended_at") for v in st["hab"].values())


SENTINELS = ["Pat Example", "Robin Sample", "302-555-0142", "803-555-0199", "pat@example.org", "1234 Sample Street"]


def test_no_sentinel_reaches_any_save_from_the_des_feeds(monkeypatch, tmp_path):
    # re-review P1-5: unexpected attributes and permitted text fields alike; every persistence call captured
    import common
    s = saved()
    beach = copy.deepcopy(s["beach"])
    beach[0]["attributes"].update(CONTACT="Pat Example", PHONE="302-555-0142", ADDR="1234 Sample Street")
    beach[0]["attributes"]["COUNTY"] = "Horry. Call Pat Example at 1234 Sample Street."
    hab = copy.deepcopy(s["hab"])
    hab[0]["attributes"].update(Reporter="Robin Sample", Email="pat@example.org")
    hab[0]["attributes"]["Recreational_Guidance"] = "Avoid contact. Contact: Robin Sample, 803-555-0199, pat@example.org"
    page = ("<h2>HAB Watches &amp; Advisories</h2><table><tr><th>Advisory Level</th></tr><tr><td>Watch</td>"
            "<td>Cedar Point Cove, call Pat Example at 803-555-0199</td><td>J. Strom Thurmond</td><td>10/16/2026</td>"
            "</tr></table>")
    saves = []
    monkeypatch.setattr(A, "save_raw", lambda *a, **k: saves.append(json.dumps(a, default=str)))
    monkeypatch.setattr(A, "write_json", lambda path, obj, *a, **k: saves.append(json.dumps(obj, default=str)))
    monkeypatch.setattr(A, "write_events", lambda sid, recs, **k: saves.append(json.dumps([recs, k], default=str)))

    class Resp:
        def __init__(self, js=None, text=""):
            self._js, self.text = js, text

        def raise_for_status(self):
            pass

        def json(self):
            return self._js

    def fake_get(url, **k):
        if "BW_Monitoring" in url:
            return Resp({"features": beach})
        if "algal_hydro" in url:
            return Resp({"features": hab})
        return Resp(text=page)
    monkeypatch.setattr(A.requests, "get", fake_get)
    monkeypatch.setattr(A, "STATE_PATH", tmp_path / "state.json")
    assert A.main(["--at", T0]) == 0
    blob = "\n".join(saves)
    assert len(saves) >= 4 and "Cedar Point Cove" in blob
    for x in SENTINELS:
        assert x not in blob, x


def test_points_are_rounded_before_anything_is_saved():
    f = [{"attributes": {"STAT": "X"}, "geometry": {"x": -79.123456, "y": 33.654321}}]
    assert A.safe_features(f, "geometry")[0]["geometry"] == {"x": -79.123, "y": 33.654}
    for feat in saved()["beach"] + saved()["hab"]:
        g = feat.get("geometry") or feat.get("centroid")
        assert g["x"] == round(g["x"], 3) and g["y"] == round(g["y"], 3)


def test_the_hab_table_reads_the_program_page_shape():
    page = ("<h2>HAB Watches &amp; Advisories</h2><p>Any active ...</p><table><tr><th>Advisory Level</th></tr>"
            "<tr><td>Advisory</td><td>Example Cove</td><td>Lake Example</td><td>07/04/2026</td></tr></table>")
    assert A.hab_table(page) == [{"level": "Advisory", "area": "Example Cove", "water": "Lake Example",
                                  "issued": "07/04/2026"}]
    assert A.hab_table("<p>no table here</p>") is None
    recs, _, _ = A.hab_records([], A.hab_table(page), {}, T0)
    assert recs[0]["raw"]["read_from"] == "table" and recs[0]["started_at"] == "2026-07-04" and recs[0]["lat"] is None


def test_the_layer_requests_name_no_staff_field():
    assert "Creator" not in A.HAB_LAYER and "Editor" not in A.HAB_LAYER and "GlobalID" not in A.BEACH_LAYER


# ---------------------------------------------------------------- registry, register, rules, text, waters

def ops():
    return [r for r in json.loads((ROOT / "data" / "dischargers.json").read_text()) if r.get("state") == "SC"]


def test_every_south_carolina_permit_is_in_exactly_one_row():
    from build import redact
    from ingest import dischargers_schema as DS
    every = Counter(p for r in json.loads((ROOT / "data" / "dischargers.json").read_text())
                    for p in dict.fromkeys([r.get("npdes_permit"), *(r.get("npdes_permits") or [])]) if p)
    plants = {r["npdes_permit"] for r in json.loads((ROOT / "data" / "outfalls-plants-us.json").read_text())["outfalls"]
              if r.get("state") == "SC"}
    cand = json.loads((ROOT / "research" / "sc" / "private-utilities-candidates.json").read_text())
    private = {c["npdes_permit"] for c in cand["candidates"]}
    assert len(plants) == 213 and len(private) == 26
    assert all(every[p] == 1 for p in plants | private), [p for p in plants | private if every[p] != 1]
    rows = ops()
    assert len({r["id"] for r in rows}) == len(rows)
    ids = {r["id"] for r in rows}
    research = {r["id"] for r in json.loads((ROOT / "research" / "sc" / "dischargers.json").read_text())}
    assert research <= ids
    assert not DS.check_legal_forms(rows)
    assert not [r["name"] for r in rows if redact.person_shaped(r["name"])]
    assert not [r for r in rows if "[name removed]" in r["name"]]
    flo = next(r for r in rows if r["id"] == "sc-florence")
    assert set(flo["npdes_permits"]) == {"SC0045462", "SC0025356"}


def test_drinking_water_and_land_application_rows_are_kind_other():
    doc = json.loads((ROOT / "data" / "outfalls-sc.json").read_text())
    assert doc["count"] == len(doc["outfalls"]) == 10
    assert all(r["outfall_kind"] == "other" and r["kind_note"] and r["supersedes"].startswith("data/outfalls-plants-us.json")
               for r in doc["outfalls"])
    assert {r["npdes_permit"] for r in doc["outfalls"]} == {"SC0048526", "SC0047724", "SC0049336", "SC0043583",
                                                            "SCG646061", "SC0048461"}
    import common
    reg = [r for r in common.load_outfall_registry(provisional=False) if str(r.get("state")).upper() == "SC"]
    assert sum(1 for r in reg if r.get("outfall_kind") == "other") == 10
    assert not [r for r in reg if r.get("npdes_permit") == "SCG646061" and r.get("outfall_kind") != "other"]


def test_register_rows_per_operator_and_the_state_channels():
    reg = {c["id"]: c for c in json.loads((ROOT / "data" / "notice-channels" / "sc.json").read_text())["channels"]}
    named = {c["operator_id"] for c in reg.values() if c.get("operator_id")}
    assert {r["id"] for r in ops()} <= named
    assert reg["sc-florence-sso-notices"]["feed_source_id"] == "sc-florence-sso-notices"
    assert reg["sc-des-beach-monitoring"]["feed_source_id"] == "sc-des-beach-monitoring"
    assert reg["sc-des-hab"]["feed_source_id"] == "sc-des-hab"
    assert reg["sc-charleston-water-news"]["monitored"] and reg["sc-charleston-water-news"]["records"] is False
    assert reg["sc-des-sso-reports"]["barrier"] == "no_web_page"
    assert reg["sc-des-freshwater-swim-advisories"]["barrier"] == "not_verified"
    assert reg["sc-rewa-public-notice"]["barrier"] == "not_verified" and "48-1-95(E)" in reg["sc-rewa-public-notice"]["legal_basis"]


def test_rules_row_cites_the_law_and_sets_no_window():
    rules = json.loads((ROOT / "data" / "rules.json").read_text())
    sc = rules["red"]["by_state"]["SC"]
    assert sc["hours"] is None and "48-1-95" in sc["source"]
    assert not re.search(r"\b(safe|clean)\b", sc["basis"], re.I)


def test_state_text_is_in_the_page_shape():
    t = (ROOT / "research" / "sc" / "state-text.md").read_text()
    assert t.startswith("---\nstate: SC\nname: South Carolina\nupdated: ")
    for h in ("What the law requires", "What is published", "What is not published", "What stands in the way",
              "Known problems in the data", "What this site does about it"):
        assert f"**{h}.**" in t
    assert "{{share_line}}" in t and "{{dated_share}}" in t and "{{latest_dated}}" in t and "{{grade}}" in t
    assert not re.search(r"\b(safe|clean)\b", t, re.I) and ".json" not in t and ".py" not in t
    assert "48-1-95" in t and "City of Florence" in t and "21 long-term" in t and "18 on the Grand Strand" in t


def test_missing_waters_list_leaves_out_the_national_lists_names():
    d = json.loads((ROOT / "research" / "sc" / "receiving-waters-missing.json").read_text())
    nat = json.loads((ROOT / "data" / "receiving-waters-national.json").read_text())

    def k(n):
        return re.sub(r"[^a-z0-9]", "", (n or "").lower())
    held = {k(n) for w in (nat["states"].get("SC") or {}).get("waters", [])
            for n in [w.get("name"), w.get("key"), *(w.get("names_seen") or []), *(w.get("gnis_names") or [])] if n}
    assert d["state"] == "SC" and d["waters"] == len(d["rows"])
    unresolved = [r for r in d["rows"] if not r.get("resolved")]
    assert not [r["name"] for r in unresolved if k(r["name"]) in held]


def test_adding_the_states_leaves_the_other_states_lists_as_they_were():
    from build import charts, status
    assert status.COUNTY_STATES["UT"] == "ut-counties.json" and status.COUNTY_STATES["OH"] == "oh-counties.json"
    assert {"TX", "OR", "UT", "TN", "OH"} <= status.COUNTY_FIELD_STATES
    assert status.COUNTY_STATES["SC"] == "sc-counties.json" and "SC" in status.COUNTY_FIELD_STATES
    assert charts.STATE_NAMES["SC"] == "South Carolina" and charts.STATE_NAMES["OH"] == "Ohio"


def test_a_des_bloom_never_colours_the_whole_water_whatever_its_area(monkeypatch):
    # re-review P2-3: the cove's delineation is the extent; absent, small and large area values alike
    import tempfile
    from datetime import datetime
    from build import status as S
    from tests.test_status import TEST_RULES
    monkeypatch.setattr(S, "_RULES", TEST_RULES)
    ex = {"level": "Advisory", "area": "Example Cove", "water": "Lake Example", "issued": "07/04/2026"}
    recs, _, _ = A.hab_records([_feat("gx", -81.101, 34.101)], [ex], {}, "2026-07-05T12:00:00Z")
    assert recs[0]["raw"]["_point_extent_only"] is True and recs[0]["lat"] == 34.101
    box = {"type": "Polygon", "coordinates": [[[-81.2, 34.0], [-81.0, 34.0], [-81.0, 34.2], [-81.2, 34.2], [-81.2, 34.0]]]}
    for area in (None, 30, 300):
        w = {"slug": "lake-example-sc", "name": "Lake Example", "kind": "reservoir", "state": "SC",
             "bbox": [-81.2, 34.0, -81.0, 34.2], "geometry": box}
        if area is not None:
            w["area_km2"] = area
        S._GEOM_CACHE.clear()
        S._REACH_WATERS.clear()
        d = Path(tempfile.mkdtemp())
        (d / "sc-des-hab.json").write_text(json.dumps({"source_id": "sc-des-hab", "ok": True, "last_ok_at": T0,
                                                       "meta": {}, "records": copy.deepcopy(recs)}))
        st, _ = S.build(now=datetime.fromisoformat("2026-07-06T12:00:00+00:00"), write=False, events_dir=d,
                        waters={"lake-example-sc": w}, outfalls=[], registry={}, reaches={}, flows=({}, {}),
                        rules=TEST_RULES, placement_cache=None)
        lake = st["waters"]["lake-example-sc"]
        assert recs[0]["event_id"] in lake["events"], area                    # listed on the water's page
        assert lake["status"] == "grey", area                                 # never coloured whole
        pts = {a["event_id"]: a for a in st["advisory_points"]}
        assert pts[recs[0]["event_id"]]["status"] == "red", area              # its marker carries the colour


def test_an_owner_is_named_from_epas_permittee_never_from_a_facility():
    # re-review P2-5: a permit whose owner is read only from a facility's name is its own row with no owner
    rows = {r["id"]: r for r in json.loads((ROOT / "data" / "dischargers.json").read_text()) if r.get("state") == "SC"}
    for rid in ("sc-sc0035700", "sc-sc0026735", "sc-sc0028801", "sc-sc0025194", "sc-sc0049372", "sc-sc0046892"):
        r = rows[rid]
        assert "owner not recorded by EPA" in r["name"] and not r.get("legal_form") and len(r["npdes_permits"]) == 1
    for gone in ("sc-pendleton-clemson-regional", "sc-west-pelzer", "sc-st-matthews", "sc-city-of-lancaster"):
        assert gone not in rows
    # EPA's permittee "Chesnee City of" is the City of Chesnee's own row, never Spartanburg Water's
    assert not any(p == "SC0025763" for p in rows["sc-spartanburg-water"]["npdes_permits"])
    assert any("Chesnee" in r["name"] and r.get("legal_form") == "city" for r in rows.values()
               if "SC0025763" in r["npdes_permits"])
    # a row that names no permittee for privacy keeps the convention (docs/legal-forms.md)
    assert rows["sc-sc0029475"]["legal_form"] == "facility (permittee not named)"


def test_the_state_texts_cite_their_reads_and_say_what_the_code_does():
    # re-review P2-6: direct links and read dates on empirical claims; calculated counts marked as this site's; the
    # Florence and bloom descriptions match the records (no start, separate advice, no whole-reservoir colour)
    rules = json.loads((ROOT / "data" / "rules.json").read_text())["unresolved"]
    sc = (ROOT / "research" / "sc" / "state-text.md").read_text()
    for url in ("https://www.cityofflorencesc.gov/city-news", "https://gis.des.sc.gov/beachaccess/",
                "https://des.sc.gov/programs/bureau-water/aquatic-science/harmful-algal-blooms"):
        assert f"]({url})" in sc
    assert "this site's count" in sc and "November 14, 2026" in sc
    assert "gives no start for the overflow" in sc and "never as the whole lake or reservoir" in sc
    assert f"for {int(rules['unknown_status_yellow_days'])} days from that day" in sc
    assert "50 square kilometres" not in sc and "red for up to 7 days" not in sc
    de = (ROOT / "research" / "de" / "state-text.md").read_text()
    for url in ("https://derns.dnrec.delaware.gov/Pub/RecentReleases.aspx",
                "https://data.delaware.gov/Energy-and-Environment/Recreational-Water-Advisories/ever-58ni",
                "https://recwaters.dnrec.delaware.gov/"):
        assert f"]({url})" in de
    assert "calculated from the Department's list" in de


# ---------------------------------------------------------------- last round (verify P1-2, P1-3, P1-6)

def _florence_one():
    nid, p = notice()
    st = {"notices": {}}
    F.update_notice(st, "/news/x", nid, p, "2025-08-16T12:00:00Z")
    return st, nid, p


def test_one_overflow_and_its_advice_count_as_one_discharge():
    from build import charts as C
    st, _, _ = _florence_one()

    class D:
        def __getattr__(self, name):              # the helpers gather calls that this test does not need
            return lambda *a, **k: None
    d = D()
    d.events, d.superseded, d.duplicates, d.effective, d.dropped = F.records(st, T0), set(), {}, {}, {}
    d.waters = {"jeffries-creek-sc": {"state": "SC", "kind": "stream", "name": "Jeffries Creek"}}
    d.status, d.slugs = {}, (lambda ev: ["jeffries-creek-sc"])
    d.origin, d.operator_short = (lambda ev: ("SC", None)), (lambda ev: "Florence")
    d.water_links = lambda ev: [("jeffries-creek-sc", "local")]
    buckets, stats, _ = C.gather(d)
    evs = buckets[("water", "jeffries-creek-sc")].events
    assert len(evs) == 1 and stats["advice_not_a_discharge"] == 1
    assert not buckets[("water", "jeffries-creek-sc")].advisories       # no cited extent: listed, not coloured


def test_the_citys_advice_never_colours_the_whole_creek(monkeypatch):
    import tempfile
    from datetime import datetime
    from build import status as S
    from tests.test_status import TEST_RULES
    monkeypatch.setattr(S, "_RULES", TEST_RULES)
    st, _, _ = _florence_one()
    recs = F.records(st, T0)
    line = {"type": "LineString", "coordinates": [[-79.80, 34.15], [-79.75, 34.18], [-79.70, 34.20]]}
    w = {"slug": "jeffries-creek-sc", "name": "Jeffries Creek", "kind": "stream", "state": "SC",
         "bbox": [-79.80, 34.15, -79.70, 34.20], "geometry": line}
    S._GEOM_CACHE.clear()
    S._REACH_WATERS.clear()
    d = Path(tempfile.mkdtemp())
    (d / f"{F.SOURCE_ID}.json").write_text(json.dumps({"source_id": F.SOURCE_ID, "ok": True, "last_ok_at": T0,
                                                       "meta": {}, "records": recs}))
    out, _ = S.build(now=datetime.fromisoformat("2025-08-20T12:00:00+00:00"), write=False, events_dir=d,
                     waters={"jeffries-creek-sc": w}, outfalls=[], registry={}, reaches={}, flows=({}, {}),
                     rules=TEST_RULES, placement_cache=None)
    creek = out["waters"]["jeffries-creek-sc"]
    advice = next(r for r in recs if r["source_record_id"].endswith("-advice"))
    assert advice["event_id"] in creek["events"]                         # listed on the creek's page
    assert creek["status"] != "red"                                      # never the City's red over the whole creek


def test_a_months_late_withdrawal_never_fills_the_unconfirmed_months_with_red():
    from datetime import datetime, timezone
    st, nid, p = _florence_one()
    jan = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)

    def colour_on(rec, at):
        return [i["color"] for i in _ivs(rec, at) if i["start"] <= at and (i["end"] is None or i["end"] > at)]
    before = florence_records(st)["1929-advice"]
    assert "red" not in colour_on(before, jan)
    p2 = copy.deepcopy(p)
    p2.update(advice=None, until_further_notice=False)
    F.update_notice(st, "/news/x", nid, p2, "2026-11-01T12:00:00Z")
    after = florence_records(st)["1929-advice"]
    assert after["ended_at"] == "2026-11-01T12:00:00Z" and after["raw"]["ended_at_precision"] == "poll"
    assert "red" not in colour_on(after, jan)
    red = [i for i in _ivs(after, datetime(2026, 11, 2, tzinfo=timezone.utc)) if i["color"] == "red"]
    assert red and red[0]["end"].date().isoformat() == "2025-08-29"        # 14 days after the release


def test_a_contact_name_outside_the_contact_block_never_reaches_a_save(monkeypatch, tmp_path):
    page = (FIX / "florence_notice.html").read_text()
    page = page.replace("Staff responded immediately upon being notified",
                        "For questions call Robin Sample. Staff responded immediately upon being notified")
    nid, title, paras = F.article(page)
    assert "Robin Sample" not in json.dumps(paras) and "[name removed]" in json.dumps(paras)
    st = {"notices": {}}
    F.update_notice(st, "/news/x", nid, F.parse_notice(title, paras), T0)
    assert "Robin Sample" not in json.dumps(st) + json.dumps(F.records(st, T0))
    assert F.scrub_person("Notification of Sanitary Sewer Overflow on Jeffries Creek") == \
        "Notification of Sanitary Sewer Overflow on Jeffries Creek"
    assert F.scrub_person("Please call the City at its office.") == "Please call the City at its office."


EXPLAIN = ("<h2>HAB Watches &amp; Advisories</h2><p>Any active, recreational watches and/or advisories will appear in "
           "the table below. If it is empty, there are no current watches and/or advisories listed.</p>")


def test_the_pages_conditional_explanation_is_never_an_empty_listing(monkeypatch, tmp_path):
    # verify P1-4: the paragraph stands with or without the table; missing or cut-off tables fail and end nothing
    assert A.hab_table(EXPLAIN) is None                                                  # no table
    assert A.hab_table(EXPLAIN + "<table><tr><th>Advisory Level</th></tr><tr><td>Watch</td>") is None   # cut off
    assert A.hab_table(EXPLAIN + "<table><tr><th>Advisory Level</th></tr></table>") == []    # a whole, empty table
    assert A.hab_table("<h2>HAB Watches</h2><p>There are currently no active watches or advisories.</p>") == []
    import common
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path)
    monkeypatch.setattr(A, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(A, "save_raw", lambda *a, **k: None)
    s = saved()
    _, hstate, _ = A.hab_records(s["hab"], s["hab_table"], {}, T0)
    assert hstate
    (tmp_path / "state.json").write_text(json.dumps({"hab": hstate}))
    (tmp_path / "sc-des-hab.json").write_text(json.dumps({"records": [{"event_id": "x"}], "meta": {}}))

    class Resp:
        def __init__(self, js=None, text=""):
            self._js, self.text = js, text

        def raise_for_status(self):
            pass

        def json(self):
            return self._js

    for page in (EXPLAIN, EXPLAIN + "<table><tr><th>Advisory Level</th></tr><tr><td>Watch</td>"):
        monkeypatch.setattr(A.requests, "get", lambda url, page=page, **k: Resp({"features": s["beach"]})
                            if "BW_Monitoring" in url else Resp({"features": []}) if "algal_hydro" in url
                            else Resp(text=page))
        assert A.main(["--at", T1]) == 1
        out = json.loads((tmp_path / "sc-des-hab.json").read_text())
        assert out["ok"] is False and out["records"] == [{"event_id": "x"}]
        st = json.loads((tmp_path / "state.json").read_text())
        assert all(not v.get("ended_at") for v in st["hab"].values())


def _named_feat(gid, name, x, y, ms=1783137600000):
    f = _feat(gid, x, y, ms)
    f["attributes"]["NAME"] = name
    return f


def test_qualified_water_names_never_join_or_exchange_points():
    # verify P1-5: "Little Example Lake" and "Example Lake", same date, layer and table in both orders
    little = _named_feat("gl", "Little Example Lake", -81.101, 34.101)
    plain = {"level": "Advisory", "area": "Example Cove", "water": "Example Lake", "issued": "07/04/2026"}
    recs, _, _ = A.hab_records([little], [plain], {}, T0)
    by = {(r["waterbody_text"], r["outfall_name"]): r["lat"] for r in recs}
    assert by == {("Little Example Lake", None): 34.101, ("Example Lake", "Example Cove"): None}
    plain_f = _named_feat("gp", "Example Lake", -81.202, 34.202)
    lit_row = {"level": "Watch", "area": "Little Cove", "water": "Little Example Lake", "issued": "07/04/2026"}
    recs, _, _ = A.hab_records([plain_f], [lit_row], {}, T0)
    by = {(r["waterbody_text"], r["outfall_name"]): r["lat"] for r in recs}
    assert by == {("Example Lake", None): 34.202, ("Little Example Lake", "Little Cove"): None}
    # both waters on both sides, in either order: each row joins its own water's delineation only
    for fs, tb in (([little, plain_f], [plain, lit_row]), ([plain_f, little], [lit_row, plain])):
        recs, _, _ = A.hab_records(fs, tb, {}, T0)
        by = {(r["waterbody_text"], r["outfall_name"]): r["lat"] for r in recs}
        assert by == {("Little Example Lake", "Little Cove"): 34.101, ("Example Lake", "Example Cove"): 34.202}
    # the same water in both, generic word cut: still joined (DES's "J. Strom Thurmond" table name)
    t = _named_feat("gt", "J. Strom Thurmond Reservoir", -82.3, 33.7)
    row = {"level": "Watch", "area": "Cedar Point Cove", "water": "J. Strom Thurmond", "issued": "07/04/2026"}
    recs, _, _ = A.hab_records([t], [row], {}, T0)
    assert len(recs) == 1 and recs[0]["outfall_name"] == "Cedar Point Cove" and recs[0]["lat"] == 33.7


def test_a_revised_des_date_or_water_for_one_globalid_is_taken_and_a_later_episode_is_its_own_record():
    # verify P2-2
    day = 86400000
    recs, st, _ = A.hab_records([_feat("gx", -81.101, 34.101)], [], {}, "2026-07-06T12:00:00Z")
    assert recs[0]["started_at"] == "2026-07-04"
    # DES corrects the date to July 5 (on or before the day first seen): the record takes it, the earlier kept
    f = _feat("gx", -81.101, 34.101, 1783137600000 + day)
    f["attributes"]["NAME"] = "Lake Example Arm"
    recs, st, _ = A.hab_records([f], [], {"hab": st}, "2026-07-07T12:00:00Z")
    assert len(recs) == 1
    r = recs[0]
    assert r["started_at"] == "2026-07-05" and r["waterbody_text"] == "Lake Example Arm" and r["ended_at"] is None
    assert {x["field"] for x in r["raw"]["revisions"]} == {"started_at", "water"}
    # a month on, DES dates the same delineation August 10: a later advisory, never backdated to July
    g = _feat("gx", -81.101, 34.101, 1783137600000 + 37 * day)
    g["attributes"]["NAME"] = "Lake Example Arm"
    recs, st, _ = A.hab_records([g], [], {"hab": st}, "2026-08-11T12:00:00Z")
    by = {r["started_at"]: r for r in recs}
    assert set(by) == {"2026-07-05", "2026-08-10"}
    assert by["2026-07-05"]["ended_at"] == "2026-08-11T12:00:00Z" and by["2026-07-05"]["raw"]["ended_at_precision"] == "poll"
    assert by["2026-08-10"]["ended_at"] is None and by["2026-08-10"]["raw"]["follows"] == by["2026-07-05"]["source_record_id"]
    # the next read keeps the new record open and the earlier one ended
    recs, st, _ = A.hab_records([g], [], {"hab": st}, "2026-08-11T13:00:00Z")
    assert sorted((r["started_at"], r["ended_at"] is None) for r in recs) == [("2026-07-05", False), ("2026-08-10", True)]
