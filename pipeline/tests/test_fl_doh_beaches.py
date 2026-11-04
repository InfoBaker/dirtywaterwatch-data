"""Florida Healthy Beaches: the Caspio result rows and per-sample advisories (no network; a trimmed page)."""
from pathlib import Path

from ingest import fl_doh_beaches as B

PAGE = (Path(__file__).resolve().parent / "fixtures" / "fl_doh_beach_page.html").read_text()
POINT = {"County": "Bay", "EPAbeachID": "FL289095", "SPLocation": "8TH STREET", "SPLat": 29.93689167,
         "SPLong": -85.40334143, "Link": "https://www.floridahealth.gov/x/beach-detail/?County=Bay&SPLocation=8TH+STREET"}


def test_rows_parse():
    rows = B.parse_page(PAGE)
    assert [r["date"] for r in rows] == ["2026-10-26", "2026-10-12", "2026-09-28", "2026-09-21"]
    assert rows[1] == {"period": "1317", "location": "8TH STREET", "date": "2026-10-12", "enterococcus": "122",
                       "advisory": "Yes"}


def test_advisory_opens_on_a_yes_sample_and_lifts_on_the_next_no():
    recs, stats = B.build([POINT], {B.point_key(POINT): PAGE}, [], "2026-11-04T00:00:00Z")
    assert len(recs) == 1 and stats["samples_read"] == 4
    r = recs[0]
    assert r["event_type"] == "beach_advisory" and r["status"] == "advisory_lifted"
    assert r["started_at"] == "2026-10-12T00:00:00-04:00" and r["ended_at"] == "2026-10-26T00:00:00-04:00"
    assert r["time_precision"] == "day" and r["event_id"] == "fl-doh-beaches:FL289095-8th-street:1317"
    # the same advisory is one record across runs
    again, _ = B.build([POINT], {B.point_key(POINT): PAGE}, recs, "2026-11-05T00:00:00Z")
    assert [x["event_id"] for x in again] == [r["event_id"]]


def test_open_advisory_is_active():
    page = PAGE.split("</tr>", 1)[1]          # drop the newest (Advisory No) row
    recs, _ = B.build([POINT], {B.point_key(POINT): "<table>" + page}, [], "x")
    assert recs[0]["status"] == "advisory_active" and recs[0]["ended_at"] is None
    assert recs[0]["source_updated_at"] == "2026-10-12T00:00:00-04:00"


# ---------------------------------------------------------------- review 2026-11-04

def test_a_corrected_sample_replaces_the_kept_copy_and_drops_the_advisory():
    recs, _ = B.build([POINT], {B.point_key(POINT): PAGE}, [], "2026-11-04T00:00:00Z")
    assert len(recs) == 1
    corrected = PAGE.replace('<span style="color:#FF0000">Yes</span>', '<span style="color:#218429">No</span>')
    assert corrected != PAGE and not any(r["advisory"] == "Yes" for r in B.parse_page(corrected))
    again, _ = B.build([POINT], {B.point_key(POINT): corrected}, recs, "2026-11-05T00:00:00Z")
    assert again == []                    # the fresh rows win over the copy kept from the earlier run


def test_lifted_advisory_says_how_its_end_was_set():
    recs, _ = B.build([POINT], {B.point_key(POINT): PAGE}, [], "x")
    assert "lifts the advisory when" in recs[0]["raw"]["end_basis"]


def test_no_rows_on_any_page_is_a_failure_that_keeps_the_records(tmp_path, monkeypatch):
    import json

    import common
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path)
    monkeypatch.setattr(B, "EVENTS_DIR", tmp_path)
    monkeypatch.setattr(B, "STATE_FILE", tmp_path / "state.json")
    pts = [{**POINT, "SPLocation": f"P{i}"} for i in range(12)]
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"points": [POINT], "pages": {B.point_key(POINT): PAGE}}))
    assert B.main(["--file", str(good)]) == 0
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"points": pts, "pages": {B.point_key(p): "<p>No records found.</p>" for p in pts}}))
    assert B.main(["--file", str(empty)]) == 1
    d = json.loads((tmp_path / f"{B.SOURCE_ID}.json").read_text())
    assert d["ok"] is False and d["count"] == 1


# ---------------------------------------------------------------- 2026-11-04: a pass bounded per run, resumed next run

def _live(tmp_path, monkeypatch, n=6, empty=(), step=100.0, refuse_after=None, broken=()):
    """main() against fake points and result pages: every page is the fixture page (another location), except the
    points in `empty`, whose pages carry no sample row; each request takes `step` seconds. refuse_after: the
    data page answers every request after that many with "No records found" (how it refused a GitHub runner);
    broken: points whose request always fails."""
    import common
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path)
    monkeypatch.setattr(B, "EVENTS_DIR", tmp_path)
    monkeypatch.setattr(B, "STATE_FILE", tmp_path / "state.json")
    pts = [{**POINT, "SPLocation": f"P{i}", "EPAbeachID": f"FL{i}", "Link": None} for i in range(n)]
    monkeypatch.setattr(B, "fetch_points", lambda limit=None: list(pts))
    asked = []

    class Resp:
        def __init__(self, loc):
            self.text = ("<p>No records found.</p>" if loc in empty or loc == "__refused__"
                         else PAGE.replace("8TH STREET", loc))

        def raise_for_status(self):
            pass

    def get(url, params=None, **kw):
        asked.append(params["SPLocation"])
        clock[0] += step
        if params["SPLocation"] in broken:
            raise B.requests.ConnectionError("reset")
        sent[0] += 1                                       # all requests, across runs (asked is cleared)
        if refuse_after is not None and sent[0] > refuse_after:
            return Resp(next(iter(empty)) if empty else "__refused__")
        return Resp(params["SPLocation"])

    monkeypatch.setattr(B.requests, "get", get)
    monkeypatch.setattr(B.time, "sleep", lambda s: None)
    clock, sent = [0.0], [0]
    monkeypatch.setattr(B.time, "monotonic", lambda: clock[0])
    return pts, asked


def _feed(tmp_path):
    import json
    return json.loads((tmp_path / f"{B.SOURCE_ID}.json").read_text())


def test_the_cadence_stamp_lives_in_the_saved_build_state():
    import common
    assert B.STATE_FILE.parent == common.BUILD_DIR      # data/build: the workflow saves and restores it whole


def test_a_pass_stops_at_its_time_budget_and_the_next_run_continues_where_it_stopped(tmp_path, monkeypatch):
    import json
    pts, asked = _live(tmp_path, monkeypatch, n=6, step=100.0)
    # 100 s a request: with 250 s, P0, P1 and P2 are started (P2 at 200 s), P3 is not (300 s)
    assert B.main(["--budget-s", "250"]) == 0
    assert asked == ["P0", "P1", "P2"]
    st = json.loads((tmp_path / "state.json").read_text())
    assert "full_pass_at" not in st and st["pass"]["done"] == ["Bay|P0", "Bay|P1", "Bay|P2"]
    d = _feed(tmp_path)
    assert d["ok"] is True and d["meta"]["pass"]["points_read_in_pass"] == 3 and d["meta"]["pass"]["points"] == 6
    assert d["meta"]["pass"]["complete"] is False and "time budget" in d["meta"]["pass"]["this_run_stopped"]
    first = {r["event_id"]: r for r in d["records"]}
    assert len(first) == 3
    started = st["pass"]["started_at"]

    asked.clear()
    assert B.main(["--budget-s", "1000"]) == 0
    assert asked == ["P3", "P4", "P5"]                    # the points not read yet, nothing asked twice
    st = json.loads((tmp_path / "state.json").read_text())
    assert st["full_pass_at"] == started and "pass" not in st     # 20 hours count from the start of the pass
    d = _feed(tmp_path)
    assert d["meta"]["pass"]["complete"] is True and d["meta"]["pass"]["runs"] == 2
    recs = {r["event_id"]: r for r in d["records"]}
    assert len(recs) == 6
    for k, r in first.items():                            # the points not read this run keep their records as they were
        assert recs[k] == r

    asked.clear()
    assert B.main([]) == 0                                # within 20 hours of the pass's start: nothing asked
    assert asked == []


def test_a_run_of_answers_without_rows_stops_the_run_and_those_points_wait(tmp_path, monkeypatch):
    """The data page refuses after a number of requests (every answer "No records found"): five points in a row
    without a row, and the last point that had rows (the probe) without one too: the run stops; the five are not
    counted read and are asked again, after the others, on the next run."""
    import json
    pts, asked = _live(tmp_path, monkeypatch, n=10, step=0.0, refuse_after=2)
    assert B.main([]) == 0
    # P2..P6 answered without a row (each asked twice), then the probe P1 without one: the run stops
    assert asked == ["P0", "P1"] + [f"P{i}" for i in range(2, 2 + B.REFUSED_RUN) for _ in range(2)] + ["P1", "P1"]
    st = json.loads((tmp_path / "state.json").read_text())
    assert st["pass"]["done"] == ["Bay|P0", "Bay|P1"]     # the refused points are not counted read
    d = _feed(tmp_path)
    assert d["meta"]["points_read"] == 2 and "in a row" in d["meta"]["pass"]["this_run_stopped"]
    assert d["meta"]["pass"]["this_run_set_aside"] == B.REFUSED_RUN

    asked.clear()
    # the next run, still refused: it starts with the points not asked yet (P7..), the set-aside ones last; nothing
    # is read: a failing run that keeps the records and the pass as they were
    assert B.main([]) == 1
    assert asked[0] == "P7"
    d = _feed(tmp_path)
    assert d["ok"] is False and d["count"] == 2 and d["meta"]["pass"]["complete"] is False
    st = json.loads((tmp_path / "state.json").read_text())
    assert st["pass"]["done"] == ["Bay|P0", "Bay|P1"] and st["pass"]["runs"] == 2


def test_five_points_that_really_have_no_samples_do_not_stop_the_pass(tmp_path, monkeypatch):
    """Five points in a row with no sample (the page answers "No records found" for them, as it does when it refuses):
    the last point with rows is asked again; it still has rows, so the page is answering, the five are read (without
    samples) and the pass goes on. Before 2026-11-04's review the run stopped there, and every later run stopped at the
    same five points: the pass never completed and the points after them were never read again."""
    import json
    empty = {f"P{i}" for i in range(2, 2 + B.REFUSED_RUN)}
    pts, asked = _live(tmp_path, monkeypatch, n=10, empty=empty, step=0.0)
    assert B.main([]) == 0
    assert asked[-3:] == ["P7", "P8", "P9"] and asked.count("P1") == 2          # P1 asked again as the probe
    st = json.loads((tmp_path / "state.json").read_text())
    assert "pass" not in st and st["full_pass_at"]
    d = _feed(tmp_path)
    assert d["meta"]["pass"]["complete"] is True and d["meta"]["points_without_samples"] == B.REFUSED_RUN
    assert d["meta"]["points_read"] == 10


def test_five_empty_points_first_in_the_order_wait_for_a_probe_and_the_pass_completes(tmp_path, monkeypatch):
    """No point with rows yet to ask again: the run stops to be safe; the next run asks the others first and the five
    last, with a probe by then."""
    import json
    empty = {f"P{i}" for i in range(B.REFUSED_RUN)}
    pts, asked = _live(tmp_path, monkeypatch, n=8, empty=empty, step=0.0)
    assert B.main([]) == 1                    # nothing read: a failing run (the records stay)
    assert json.loads((tmp_path / "state.json").read_text())["pass"]["done"] == []
    asked.clear()
    assert B.main([]) == 0
    assert asked[:3] == ["P5", "P6", "P7"]
    st = json.loads((tmp_path / "state.json").read_text())
    assert "pass" not in st and st["full_pass_at"]
    assert _feed(tmp_path)["meta"]["pass"]["complete"] is True


def test_a_point_that_always_fails_is_given_up_for_the_pass_and_the_pass_completes(tmp_path, monkeypatch):
    """A point whose request always fails is asked again on the next runs (after the others), and after
    GIVE_UP_RUNS runs it is left for this pass, keeping its records; before the review such a point held the pass open
    for ever (every later run asked only it, failed, and no point was read again)."""
    import json
    pts, asked = _live(tmp_path, monkeypatch, n=4, step=0.0, broken={"P1"})
    assert B.main([]) == 0
    assert json.loads((tmp_path / "state.json").read_text())["pass"]["done"] == ["Bay|P0", "Bay|P2", "Bay|P3"]
    for _ in range(B.GIVE_UP_RUNS - 1):
        assert B.main([]) == 1                # only P1 left, failing: a failing run
    st = json.loads((tmp_path / "state.json").read_text())
    assert "pass" not in st and st["full_pass_at"], st
    d = _feed(tmp_path)
    assert d["meta"]["pass"]["complete"] is True and d["meta"]["pass"]["points_given_up"] == ["Bay|P1"]
    asked.clear()
    assert B.main([]) == 0 and asked == []     # the next pass waits 20 hours from the start of this one


def test_a_single_point_without_rows_is_read_and_the_pass_goes_on(tmp_path, monkeypatch):
    import json
    pts, asked = _live(tmp_path, monkeypatch, n=4, empty={"P1"}, step=0.0)
    assert B.main([]) == 0
    assert asked == ["P0", "P1", "P1", "P2", "P3"]
    st = json.loads((tmp_path / "state.json").read_text())
    assert "pass" not in st and st["full_pass_at"]
    assert _feed(tmp_path)["meta"]["points_without_samples"] == 1


def test_an_empty_points_layer_is_a_failing_run_not_a_pass(tmp_path, monkeypatch):
    import json
    pts, asked = _live(tmp_path, monkeypatch, n=3, step=0.0)
    assert B.main([]) == 0
    monkeypatch.setattr(B, "fetch_points", lambda limit=None: [])
    assert B.main(["--force"]) == 1
    d = _feed(tmp_path)
    assert d["ok"] is False and d["count"] == 3 and "no active point" in d["error"]
    assert "pass" in json.loads((tmp_path / "state.json").read_text())   # the new pass waits for a good answer
