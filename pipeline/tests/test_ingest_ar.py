"""Arkansas: DEQ's Reported Noncompliance Incident Data (an HTML form search read by ingest/ar_deq_overflow_incidents.py,
mapped through the generic field map and ingest/ar_transforms.py), DEQ's harmful algal bloom advisories (the generic JSON
reader) and the Department of Health's closed swim beaches (ingest/ar_adh_swim_beaches.py): the search's count check and
window splitting, the kept and dropped rows, DEQ's impact kept apart from the water named, day-precision dates in
Central time, the key and DEQ's duplicate rows, the industrial reports left out, and the privacy rules (the comments are
never read; house numbers, names and phones never reach a record or data/raw; a private-property report keeps no
location). Every fixture row is invented."""
import json
from datetime import date
from pathlib import Path

import pytest

import zones
from ingest import ar_adh_swim_beaches as B
from ingest import ar_deq_overflow_incidents as M
from ingest import ar_transforms as T
from ingest.generic import runner as R

FIX = Path(__file__).resolve().parent / "fixtures"
FETCHED = "2026-11-14T18:00:00Z"
PERSONAL = ["Fixturename", "Jane", "555-0142", "1234 Example", "4321 Example", "77 Sample", "behind the house",
            "Called"]
SAMPLE_CREEK = "aaaaaaaa-0000-4000-8000-000000000001"


def page_rows(name="ar_deq_incidents_page.html"):
    return M.parse_page((FIX / name).read_text())


def incidents(prev=()):
    rows, found, pages, current = page_rows()
    _, block = R.load_source("ar-deq-overflow-incidents")
    safe = [R.F.safe_row(r, block)[0] for r in rows]
    recs, stats = R.build("ar-deq-overflow-incidents", block, safe, FETCHED, prev, None)
    return {r["source_record_id"]: r for r in recs}, stats, safe


def strings(o):
    if isinstance(o, dict):
        for v in o.values():
            yield from strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from strings(v)
    elif isinstance(o, str):
        yield o


def test_blocks_validate():
    for sid in ("ar-deq-overflow-incidents", "ar-deq-hab-advisories"):
        _, block = R.load_source(sid)
        assert R.validate_block(block, sid) == []
    # the incident block is run by its module only: never by make ingest on its own
    assert "ar-deq-overflow-incidents" not in R.live_ids() and "ar-deq-hab-advisories" not in R.live_ids()


def test_arkansas_is_central_time():
    assert zones.STATE_ZONES["AR"] == "America/Chicago"


def test_the_page_is_read_with_its_count_and_the_comments_are_never_read():
    rows, found, pages, current = page_rows()
    assert found == 8 and pages == 1 and current == "11/13/2026" and len(rows) == 8
    assert set(rows[0]) == set(M.SAFE_FIELDS)
    assert rows[0]["confirmation_no"] == SAMPLE_CREEK and rows[0]["incident_type"] == "SSO;"
    assert rows[0]["date_started"] == "11/02/2026" and rows[0]["volume_gal"] == "1,500"
    for s in strings(rows):
        assert "Fixturename" not in s and "555-0142" not in s and "Called" not in s
    # a count with a thousands separator is read whole
    _, found, pages, _ = page_rows("ar_deq_incidents_bad_count.html")
    assert found == 1203 and pages == 13


def test_a_private_property_report_keeps_no_location_before_anything_is_saved():
    rows, *_ = page_rows()
    by = {r["confirmation_no"][-1]: r for r in rows}
    assert by["2"]["location"] == "" and by["2"]["location_withheld"].startswith("private property")
    assert by["6"]["location"] == "" and "Basement" in by["6"]["impact"]
    assert by["1"]["location_withheld"] == ""


def test_the_search_fails_rather_than_read_a_short_or_missing_result(monkeypatch):
    pages = {"ok": (FIX / "ar_deq_incidents_page.html").read_text(),
             "short": (FIX / "ar_deq_incidents_bad_count.html").read_text()}
    monkeypatch.setattr(M.time, "sleep", lambda s: None)
    monkeypatch.setattr(M, "post", lambda sess, data: pages["ok"])
    rows, current = M.query(None, date(2026, 11, 1), date(2026, 11, 1))
    assert len(rows) == 8
    # a page that says 1,203 reports but holds two, for a single day: paged, and the shortfall fails the window
    monkeypatch.setattr(M, "post", lambda sess, data: pages["short"])
    with pytest.raises(M.SearchFailed, match="1203"):
        M.query(None, date(2026, 11, 1), date(2026, 11, 1))
    # a page without the result table (an error page) is a failure, never an empty window
    monkeypatch.setattr(M, "post", lambda sess, data: "<html>Server Error</html>")
    with pytest.raises(M.SearchFailed, match="missing"):
        M.query(None, date(2026, 11, 1), date(2026, 11, 30))


def test_a_window_with_more_than_a_page_is_split_in_halves(monkeypatch):
    asked = []
    big = (FIX / "ar_deq_incidents_bad_count.html").read_text().replace("1,203", "16")
    small = (FIX / "ar_deq_incidents_page.html").read_text()

    def fake(sess, data):
        asked.append((data["T_DateStart"], data["T_DateEnd"], data["PageNo"]))
        return big if data["T_DateStart"] == "11/01/2026" and data["T_DateEnd"] == "11/30/2026" else small
    monkeypatch.setattr(M.time, "sleep", lambda s: None)
    monkeypatch.setattr(M, "post", fake)
    rows, _ = M.query(None, date(2026, 11, 1), date(2026, 11, 30))
    assert len(rows) == 16
    assert asked == [("11/01/2026", "11/30/2026", "1"), ("11/01/2026", "11/15/2026", "1"),
                     ("11/16/2026", "11/30/2026", "1")]
    # no type box is ticked: two boxes return nothing on DEQ's search
    form = M.form(date(2026, 11, 1), date(2026, 11, 30))
    assert not any(k.startswith("C_") for k in form) and form["RecordsPerPage"] == "100"


def test_windows_are_calendar_months():
    assert list(M.windows(date(2026, 9, 15), date(2026, 11, 14))) == [
        (date(2026, 9, 15), date(2026, 9, 30)), (date(2026, 10, 1), date(2026, 10, 31)),
        (date(2026, 11, 1), date(2026, 11, 14))]


def test_records_types_dates_and_the_key():
    recs, stats, _ = incidents()
    assert stats["duplicates"]["not_sewage"] == 1                  # the paper mill's unpermitted discharge
    assert "aaaaaaaa-0000-4000-8000-000000000004" not in recs
    r = recs[SAMPLE_CREEK]
    assert r["event_id"] == f"ar-deq-overflow-incidents:{SAMPLE_CREEK}"
    assert r["event_type"] == "sso" and r["status"] == "ended" and r["time_precision"] == "day"
    assert r["started_at"] == "2026-11-02T00:00:00-06:00" and r["ended_at"] == "2026-11-02T00:00:00-06:00"
    assert r["reported_at"] == "2026-11-03T00:00:00-06:00"
    assert r["published_at"] is None and r["source_updated_at"] is None
    assert r["raw"]["time_zone"] == "America/Chicago" and r["raw"]["ended_at_precision"] == "day"
    assert r["volume_gal"] == 1500 and r["npdes_permit"] == "AR0021806"
    assert r["raw"]["_public_notification_ticked"] is True and r["raw"]["_cause"] == "Grease; Roots"
    # a bypass with no stop day: no end, the day-start caution applies
    b = recs["aaaaaaaa-0000-4000-8000-000000000003"]
    assert b["event_type"] == "plant_bypass" and b["status"] == "unknown" and b["ended_at"] is None
    rules = json.loads((R.ROOT / "data" / "rules.json").read_text())
    assert "ar-deq-overflow-incidents" in rules["unresolved"]["day_start_caution"]["sources"]
    # DEQ's state id (ARU) is not a federal permit
    u = recs["aaaaaaaa-0000-4000-8000-000000000005"]
    assert u["npdes_permit"] is None and u["raw"]["state_permit"] == "ARU999901"
    # DEQ lists one report twice: the copy is kept, duplicate_of the first
    copies = [x for x in recs.values() if x["source_record_id"].startswith("aaaaaaaa-0000-4000-8000-000000000007")]
    assert len(copies) == 2 and sum(1 for x in copies if x["duplicate_of"]) == 1


def test_impact_decides_whether_water_was_reached_and_the_named_water_is_placed_by_name_only():
    recs, _, _ = incidents()
    r = recs[SAMPLE_CREEK]
    assert r["raw"]["reached_water"] is True and r["waterbody_text"] == "Sample Creek"
    assert r["raw"]["_placement"] == "named_water_only" and r["lat"] is None
    assert r["raw"]["county"] == "Pulaski County" and "treatment plant" in r["raw"]["county_basis"]
    land = recs["aaaaaaaa-0000-4000-8000-000000000007"]
    assert land["raw"]["reached_water"] is False and land["waterbody_text"] is None
    assert "Public Land Only" in land["raw"]["_no_water_reason"]
    # an unnamed creek names no water
    b = recs["aaaaaaaa-0000-4000-8000-000000000003"]
    assert b["waterbody_text"] is None and b["raw"]["_water_text_unused"] == ["Unknown Creek"]
    assert "reached_water" not in b["raw"]                         # a blank impact leaves the question open
    # a permit with no plant point gives no county: its water name is not tied across the state
    u = recs["aaaaaaaa-0000-4000-8000-000000000005"]
    assert u["waterbody_text"] is None and u["raw"]["_water_text_unused"] == ["Faraway Creek"]


@pytest.mark.parametrize("text,names,unused", [
    ("MH 12 into Lake Catherine. Approximately 50", ["Lake Catherine"], []),
    ("Storm Drain Arkansas River", ["Arkansas River"], []),
    ("Davis Drive. Gin Creek", ["Gin Creek"], []),
    ("12 Lake Lane near Faulkner Lake", ["Faulkner Lake"], ["Lake Lane"]),
    ("trib to Mill Creek", [], ["a tributary of Mill Creek"]),
    ("Mill Creek Estates manhole 4", [], ["Mill Creek"]),
    ("St. Francis River", ["St. Francis River"], []),
    ("into Unknown Creek", [], ["Unknown Creek"]),
    ("Heber Springs. Creek", [], []),
    # a qualifier written in lower case stays: a qualified name is another water (review 2026-11-14 P1-4)
    ("overflowed into little Sample Creek", ["Little Sample Creek"], []),
    ("into the west fork of the Example River", ["West Fork of the Example River"], []),
    # a text in capitals is read; a lake's longer name is never cut
    ("MH 4 OVERFLOWED INTO FALLEN ASH CREEK", ["Fallen Ash Creek"], []),
    ("INTO TOWN CREEK", ["Town Creek"], []),
    ("Lake Little Example", ["Lake Little Example"], []),
    ("Lake Hamilton Due to rain", ["Lake Hamilton"], []),
    # re-review P1-4: a whole qualifier chain stays, a long name is never cut, capitals inside mixed text are read
    ("overflowed into upper little Sample Creek", ["Upper Little Sample Creek"], []),
    ("into upper Little Sample Creek", ["Upper Little Sample Creek"], []),
    ("Lake One Two Three Four", ["Lake One Two Three Four"], []),
    ("overflow into TOWN CREEK", ["Town Creek"], []),
    ("MH 7 at Example St overflowed INTO FALLEN ASH CREEK", ["Fallen Ash Creek"], []),
    ("SSO at MH 12 near Sample Creek", ["Sample Creek"], []),
    ("Into One Two Three Four Five Six Seven Creek", [], ["One Two Three Four Five Six Seven Creek"]),
])
def test_water_names_in_location_text(text, names, unused):
    assert T.water_names(text) == (names, unused)


def test_no_personal_string_reaches_a_record_or_the_saved_rows(tmp_path, monkeypatch):
    recs, _, safe = incidents()
    for s in list(strings(list(recs.values()))) + list(strings(safe)):
        for p in PERSONAL:
            assert p not in s, (p, s)
    r = recs[SAMPLE_CREEK]
    assert r["outfall_name"].startswith("[house number removed] Example Street")


def test_the_filers_own_impact_words_are_scrubbed_and_give_only_a_water_name():
    rows, *_ = page_rows()
    row = M.privacy_cut(dict(rows[0], impact="Jane Fixturename 501-555-0142 at 1234 Example Street saw it reach Sample Creek"))
    _, block = R.load_source("ar-deq-overflow-incidents")
    safe = R.F.safe_row(row, block)[0]
    assert safe["impact"] == "Sample Creek"
    for p in ("Fixturename", "555-0142", "1234 Example"):
        assert p not in safe["impact"]
    recs, _ = R.build("ar-deq-overflow-incidents", block, [safe], FETCHED, (), None)
    r = recs[0]
    assert r["waterbody_text"] == "Sample Creek"
    for s in strings(r):
        for p in ("Fixturename", "555-0142", "1234 Example"):
            assert p not in s, s
    # DEQ's own checkbox labels pass the scrub unchanged
    assert R.F.safe_row(rows[1], block)[0]["impact"] == "SSO Affected Private Property (ground)"


def test_the_module_replays_saved_rows_and_carries_records_before_the_window(tmp_path):
    rows, *_ = page_rows()
    _, block = R.load_source("ar-deq-overflow-incidents")
    safe = [R.F.safe_row(r, block)[0] for r in rows]
    saved = tmp_path / "rows.json"
    saved.write_text(json.dumps({"format": R.SAFE_ROWS_FORMAT, "rows": safe,
                                 "meta": {"ar_search": {"window_start": "2026-11-01", "window_end": "2026-11-14"}}}))
    out = tmp_path / "ev.json"
    assert M.main(["--file", str(saved), "--out", str(out)]) == 0
    first = json.loads(out.read_text())
    assert first["ok"] and first["meta"]["rows_polled"] == 8
    # the next poll's window starts after 2026-11-04: the earlier reports are carried, never marked missing
    later = [r for r in safe if r["date_started"] >= "11/05/2026"]
    saved.write_text(json.dumps({"format": R.SAFE_ROWS_FORMAT, "rows": later,
                                 "meta": {"ar_search": {"window_start": "2026-11-05", "window_end": "2026-11-14"}}}))
    assert M.main(["--file", str(saved), "--out", str(out)]) == 0
    second = json.loads(out.read_text())
    assert second["meta"]["rows_carried"] == 3        # 2, 3 and 4 November (the paper mill is not kept)
    assert not any(r["raw"].get("_missing_from_source_since") for r in second["records"])
    assert {r["event_id"] for r in second["records"]} == {r["event_id"] for r in first["records"]}


# ---------------------------------------------------------------- harmful algal bloom advisories

from ingest import ar_deq_hab_advisories as H  # noqa: E402

EXAMPLE_POINTS = {("lake exemplar", "Lasample"): (1, 35.5, -93.5)}


def habs(monkeypatch, tmp_path, doc=None, prev_out=None):
    monkeypatch.setattr(T, "GNIS_POINTS", EXAMPLE_POINTS)
    src = tmp_path / "hab.json"
    src.write_text(json.dumps(doc) if doc else (FIX / "ar_deq_hab_advisories.json").read_text())
    out = prev_out or tmp_path / "hab-ev.json"
    assert H.main(["--file", str(src), "--out", str(out)]) == 0
    recs = json.loads(out.read_text())["records"]
    return {(r["waterbody_text"] or r["raw"].get("_water_description")) + r["started_at"][:10]: r for r in recs}, out


def test_hab_advisories_keep_deqs_dates_and_lift(monkeypatch, tmp_path):
    recs, _ = habs(monkeypatch, tmp_path)
    assert len(recs) == 6
    ex = recs["Lake Exemplar2026-07-30"]
    assert ex["event_type"] == "hab_advisory" and ex["status"] == "advisory_active" and ex["ended_at"] is None
    assert ex["started_at"] == "2026-07-30T00:00:00-05:00" and ex["time_precision"] == "day"
    assert ex["raw"]["county"] == "Lasample County" and ex["raw"]["advisory_extent"] == "named_water"
    assert (ex["lat"], ex["lon"], ex["coord_source"]) == (35.5, -93.5, "gnis")
    spec = recs["Lake Specimen2026-07-21"]
    assert spec["status"] == "advisory_lifted" and spec["ended_at"] == "2026-08-06T00:00:00-05:00"
    assert spec["raw"]["ended_at_precision"] == "day" and spec["raw"]["counties"] == ["Sample County", "Example County"]
    # "N/A": DEQ shows it as no longer in effect but gives no lift date; none is invented
    river = recs["Sample River2020-08-06"]
    assert river["status"] == "advisory_lifted" and river["ended_at"] is None
    assert river["raw"]["_water_qualifier"] == "near Exampleville" and "_lift_date_not_given" in river["raw"]
    # a starred row is not DEQ's own advisory: the site's caution, never red
    star = recs["Example Lake2019-07-09"]
    assert star["status"] == "unknown" and star["raw"]["_agency_label_only"] is True
    rules = json.loads((R.ROOT / "data" / "rules.json").read_text())
    assert "ar-deq-hab-advisories" in rules["unresolved"]["sample_caution"]["sources"]


def test_a_hab_advisory_for_part_of_a_lake_or_a_described_place_never_colours_a_whole_water(monkeypatch, tmp_path):
    recs, _ = habs(monkeypatch, tmp_path)
    bay = recs["Lake Specimen2019-10-28"]
    assert bay["raw"]["_water_qualifier"] == "Example Bay" and bay["raw"]["advisory_extent"] == "part_of_water"
    assert bay["raw"]["counties"][1] == "Hot Spring County"
    # a stream described by a lake it lies near: the lake is not the affected water; DEQ's own point places it
    stream = [r for r in recs.values() if r["raw"].get("_water_description")][0]
    assert stream["waterbody_text"] is None and stream["raw"]["advisory_extent"] == "part_of_water"
    assert stream["raw"].get("_placement") != "named_water_only"
    assert (stream["lat"], stream["lon"], stream["coord_source"]) == (35.123, -93.654, "source")


def test_hab_coordinates_are_rounded_before_any_save_key_or_record(monkeypatch, tmp_path):
    recs, out = habs(monkeypatch, tmp_path)
    for s in strings(json.loads(out.read_text())):
        assert "123456" not in s and "654321" not in s, s
    stream = [r for r in recs.values() if r["raw"].get("_water_description")][0]
    assert "35-123" in stream["source_record_id"]


def test_a_corrected_posting_day_is_one_advisory(monkeypatch, tmp_path):
    doc = json.loads((FIX / "ar_deq_hab_advisories.json").read_text())
    _, out = habs(monkeypatch, tmp_path, doc)
    doc["advisories"][1]["date"] = "August 1, 2026"           # DEQ corrects Lake Exemplar's posting day
    recs, _ = habs(monkeypatch, tmp_path, doc, prev_out=out)
    ex = [r for r in recs.values() if r["waterbody_text"] == "Lake Exemplar"]
    assert len(ex) == 2 and sum(1 for r in ex if not r.get("duplicate_of")) == 1
    assert [r for r in ex if not r.get("duplicate_of")][0]["started_at"].startswith("2026-08-01")


# ---------------------------------------------------------------- the Department of Health's closed swim beaches

def test_closed_swim_beaches_are_a_standing_list_with_poll_dates(tmp_path):
    out = tmp_path / "adh.json"
    page = FIX / "ar_adh_swim_beaches.html"
    assert B.main(["--file", str(page), "--out", str(out), "--at", "2026-11-14T12:00:00Z"]) == 0
    doc = json.loads(out.read_text())
    recs = {r["source_record_id"]: r for r in doc["records"]}
    assert set(recs) == {"sb901", "sb902"}
    r = recs["sb901"]
    assert r["event_type"] == "beach_closure" and r["status"] == "advisory_active"
    assert r["started_at"] == "2026-11-14T12:00:00Z" and r["time_precision"] == "poll"
    assert r["raw"]["beach_name"] == "Example Point West" and r["raw"]["unplaced_reason"]
    for s in strings(doc):
        assert "Fixturename" not in s and "555-0142" not in s
    # the next read no longer lists SB902: it ends at that read
    page2 = tmp_path / "p2.html"
    page2.write_text(page.read_text().replace("<li>SB902 &#8211; Sample Cove</li>", ""))
    assert B.main(["--file", str(page2), "--out", str(out), "--at", "2026-11-15T12:00:00Z"]) == 0
    recs = {r["source_record_id"]: r for r in json.loads(out.read_text())["records"]}
    assert recs["sb902"]["status"] == "advisory_lifted" and recs["sb902"]["ended_at"] == "2026-11-15T12:00:00Z"
    assert recs["sb902"]["raw"]["ended_at_precision"] == "poll" and recs["sb901"]["status"] == "advisory_active"
    # a page without the heading ends nothing and fails the run
    page3 = tmp_path / "p3.html"
    page3.write_text("<html><body>Maintenance</body></html>")
    assert B.main(["--file", str(page3), "--out", str(out), "--at", "2026-11-16T12:00:00Z"]) == 1
    doc = json.loads(out.read_text())
    assert doc["ok"] is False and {r["status"] for r in doc["records"]} == {"advisory_active", "advisory_lifted"}


def test_an_unreadable_list_ends_nothing_and_saves_nothing(tmp_path, monkeypatch):
    out = tmp_path / "adh.json"
    page = (FIX / "ar_adh_swim_beaches.html").read_text()
    assert B.main(["--file", str(FIX / "ar_adh_swim_beaches.html"), "--out", str(out), "--at", "2026-11-14T12:00:00Z"]) == 0
    saved = []
    monkeypatch.setattr(B, "save_raw", lambda *a, **k: saved.append(a))
    for bad in (page.replace("<li>SB901 &#8211; Example Point West</li><li>SB902 &#8211; Sample Cove</li>",
                             "<li>Service temporarily unavailable</li>"),
                page.replace("<li>SB902 &#8211; Sample Cove</li>", "<li>Call Jane Fixturename at 501-555-0142</li>")):
        p = tmp_path / "bad.html"
        p.write_text(bad)
        assert B.main(["--file", str(p), "--out", str(out), "--at", "2026-11-15T12:00:00Z"]) == 1
        doc = json.loads(out.read_text())
        assert doc["ok"] is False and {r["status"] for r in doc["records"]} == {"advisory_active"}
    # a contact block after the list, under any heading, is never read or kept
    p = tmp_path / "contact.html"
    p.write_text(page.replace("<h2>Rules</h2>", "<h3>Questions?</h3><p>Jane Fixturename 501-555-0142</p><h2>Rules</h2>"))
    assert B.main(["--file", str(p), "--out", str(out), "--at", "2026-11-16T12:00:00Z"]) == 0
    state = (tmp_path / "adh.state.json").read_text()
    assert "Fixturename" not in state and "555-0142" not in state and not saved
    # a list the page states is empty ends the closures at that read
    p.write_text(page.replace("<li>SB901 &#8211; Example Point West</li><li>SB902 &#8211; Sample Cove</li>", "<li>None</li>"))
    assert B.main(["--file", str(p), "--out", str(out), "--at", "2026-11-17T12:00:00Z"]) == 0
    assert {r["status"] for r in json.loads(out.read_text())["records"]} == {"advisory_lifted"}


def test_a_returning_closure_is_a_new_episode_and_a_cited_point_places_it(tmp_path, monkeypatch):
    out = tmp_path / "adh.json"
    page = FIX / "ar_adh_swim_beaches.html"
    gone = tmp_path / "gone.html"
    gone.write_text(page.read_text().replace("<li>SB902 &#8211; Sample Cove</li>", ""))
    monkeypatch.setattr(B, "BEACH_POINTS", {"SB901": (35.1, -93.1, "a cited point (test)")})
    for f, at in ((page, "2026-11-14T12:00:00Z"), (gone, "2026-11-15T12:00:00Z"), (page, "2026-11-16T12:00:00Z")):
        assert B.main(["--file", str(f), "--out", str(out), "--at", at]) == 0
    recs = {r["source_record_id"]: r for r in json.loads(out.read_text())["records"]}
    assert recs["sb902"]["status"] == "advisory_lifted" and recs["sb902"]["ended_at"] == "2026-11-15T12:00:00Z"
    again = recs["sb902-20261116T1200"]
    assert again["status"] == "advisory_active" and again["started_at"] == "2026-11-16T12:00:00Z"
    p = recs["sb901"]
    assert (p["lat"], p["lon"]) == (35.1, -93.1) and "_placement" not in p["raw"] and "unplaced_reason" not in p["raw"]


@pytest.mark.parametrize("bad", [
    "<h2>Closed Swim Beaches</h2><ul></ul><h2>Rules</h2>",                    # an empty list
    "<h2>Closed Swim Beaches</h2><h2>Rules</h2><ul><li>SB901 - Example Point West</li></ul>",  # moved past a heading
    "<h2>Closed Swim Beaches</h2>",                                           # truncated at the heading
    "<h2>Closed Swim Beaches</h2><ul>",                                       # truncated inside the list
])
def test_an_empty_truncated_or_moved_list_ends_nothing(tmp_path, monkeypatch, bad):
    out = tmp_path / "adh.json"
    assert B.main(["--file", str(FIX / "ar_adh_swim_beaches.html"), "--out", str(out), "--at", "2026-11-14T12:00:00Z"]) == 0
    saved = []
    monkeypatch.setattr(B, "save_raw", lambda *a, **k: saved.append(a))
    p = tmp_path / "bad.html"
    p.write_text(f"<html><body><main>{bad}</main></body></html>")
    assert B.main(["--file", str(p), "--out", str(out), "--at", "2026-11-15T12:00:00Z"]) == 1
    doc = json.loads(out.read_text())
    assert doc["ok"] is False and {r["status"] for r in doc["records"]} == {"advisory_active"} and not saved
    with pytest.raises(ValueError):
        B.read(B.list_lines(bad))
    # an explicit statement ends the closures, at that read (poll precision)
    p.write_text("<html><body><main><h2>Closed Swim Beaches</h2><ul><li>None</li></ul><h2>Rules</h2></main></body></html>")
    assert B.main(["--file", str(p), "--out", str(out), "--at", "2026-11-16T12:00:00Z"]) == 0
    recs = json.loads(out.read_text())["records"]
    assert {r["status"] for r in recs} == {"advisory_lifted"}
    assert all(r["ended_at"] == "2026-11-16T12:00:00Z" and r["raw"]["ended_at_precision"] == "poll" for r in recs)


def _ar_status(tmp_path, monkeypatch, rows, area):
    """A full status build with Arkansas live over invented lakes: each `area` is a lake's km² (None: unknown)."""
    from datetime import UTC, datetime
    from build import status as S
    recs, out = habs(monkeypatch, tmp_path, {"updated": "November 1, 2026", "advisories": rows})
    d = tmp_path / "events"
    d.mkdir(exist_ok=True)
    doc = json.loads(out.read_text())
    (d / f"{H.SOURCE_ID}.json").write_text(json.dumps({**doc, "last_ok_at": "2026-11-01T12:00:00Z"}))

    def lake(slug, name, x, y):
        ring = [[x, y], [x + 0.05, y], [x + 0.05, y + 0.05], [x, y + 0.05], [x, y]]
        return slug, {"slug": slug, "name": name, "kind": "lake", "state": "AR", "area_km2": area,
                      "bbox": [x, y, x + 0.05, y + 0.05], "geometry": {"type": "Polygon", "coordinates": [ring]}}
    waters = dict([lake("lake-specimen-ar", "Lake Specimen", -93.0, 34.5),
                   lake("lake-exemplar-ar", "Lake Exemplar", -93.52, 35.48)])
    S._GEOM_CACHE.clear()
    S._REACH_WATERS.clear()
    rules = json.loads((R.ROOT / "data" / "rules.json").read_text())
    rules["live_states"] = sorted(set(rules["live_states"]) | {"AR"})
    rules["rain_likely"] = {**rules["rain_likely"], "enabled": False}
    st, _ = S.build(now=datetime(2026, 11, 2, 12, tzinfo=UTC), write=False, events_dir=d, waters=waters, outfalls=[],
                    registry={}, reaches={}, flows=({}, {}), rules=rules, placement_cache=False)
    return st


@pytest.mark.parametrize("area", [5.0, 500.0, None])
def test_a_bay_advisory_never_colours_its_lake_in_a_full_status_build(tmp_path, monkeypatch, area):
    rows = [{"waterbody": "Lake Specimen - Example Bay", "county": "Sample County", "area": "Exampleville, AR",
             "date": "October 20, 2026", "lifted": ""},
            {"waterbody": "Lake Exemplar", "county": "LaSample County", "area": "Sampletown, AR",
             "date": "October 20, 2026", "lifted": ""}]
    st = _ar_status(tmp_path, monkeypatch, rows, area)
    spec = st["waters"].get("lake-specimen-ar") or {}
    assert spec.get("status") == "grey", spec          # the lake keeps no colour from an advisory for one bay
    # control: DEQ's advisory for the whole lake still colours a small or unknown-area lake
    if area != 500.0:
        assert st["waters"]["lake-exemplar-ar"]["status"] == "red"
    # the bay's marker is never drawn at the parent lake's point: it has none until DEQ or a cited source gives one
    bay = [r for r in json.loads((tmp_path / "events" / f"{H.SOURCE_ID}.json").read_text())["records"]
           if r["raw"].get("_water_qualifier")][0]
    assert bay.get("lat") is None and bay["raw"]["advisory_extent"] == "part_of_water"


def test_the_part_of_water_extent_is_written_only_by_arkansas():
    """build/status.py part_of_water changes only records carrying this value; no other state's code or data writes
    it, so every other state's status output is unchanged."""
    root = R.ROOT
    hits = [p for d in ("pipeline/ingest", "data/sources") for p in (root / d).rglob("*")
            if p.is_file() and p.suffix in (".py", ".yaml", ".json") and "part_of_water" in p.read_text(errors="ignore")]
    assert {p.name for p in hits} == {"ar_transforms.py"}, hits
