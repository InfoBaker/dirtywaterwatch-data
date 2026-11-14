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
    assert "ar-deq-overflow-incidents" not in R.live_ids()


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

def habs():
    _, block = R.load_source("ar-deq-hab-advisories")
    rows = R.platform("json").parse(block, (FIX / "ar_deq_hab_advisories.json").read_bytes())
    recs, stats = R.build("ar-deq-hab-advisories", block, rows, FETCHED, (), None)
    return {r["waterbody_text"] + r["started_at"][:10]: r for r in recs}, stats


def test_hab_advisories_keep_deqs_dates_and_lift():
    recs, stats = habs()
    assert stats["rows"] == 6
    june = recs["Lake June2026-07-31"]
    assert june["event_type"] == "hab_advisory" and june["status"] == "advisory_active" and june["ended_at"] is None
    assert june["started_at"] == "2026-07-31T00:00:00-05:00" and june["time_precision"] == "day"
    assert june["raw"]["county"] == "Lafayette County"
    assert (june["lat"], june["lon"], june["coord_source"]) == (33.355, -93.492, "gnis")
    desoto = recs["Lake Desoto2026-07-22"]
    assert desoto["status"] == "advisory_lifted" and desoto["ended_at"] == "2026-08-07T00:00:00-05:00"
    assert desoto["raw"]["ended_at_precision"] == "day" and desoto["raw"]["counties"] == ["Garland County", "Saline County"]
    # "N/A": DEQ shows it as no longer in effect but gives no lift date; none is invented
    river = recs["Sample River2020-08-07"]
    assert river["status"] == "advisory_lifted" and river["ended_at"] is None
    assert river["raw"]["_water_qualifier"] == "near Exampleville" and "_lift_date_not_given" in river["raw"]
    # a starred row is not DEQ's own advisory: the site's caution, never red
    star = recs["Example Lake2019-07-29"]
    assert star["status"] == "unknown" and star["raw"]["_agency_label_only"] is True
    rules = json.loads((R.ROOT / "data" / "rules.json").read_text())
    assert "ar-deq-hab-advisories" in rules["unresolved"]["sample_caution"]["sources"]
    cath = recs["Lake Catherine2019-10-29"]
    assert cath["raw"]["_water_qualifier"] == "Spencer Bay" and cath["raw"]["counties"][1] == "Hot Spring County"
    # DEQ's own coordinates, rounded to 0.001 degree
    stream = recs["Stream by Example Trail2026-06-24"]
    assert (stream["lat"], stream["lon"], stream["coord_source"]) == (35.507, -94.217, "source")


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
