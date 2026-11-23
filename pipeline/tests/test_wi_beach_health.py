"""Wisconsin DNR's Beach Health map layer (ingest/wi_dnr_beach_health.py). Fixture: eleven of the 441 beaches of the
GitHub runner's read of 2026-11-16 (run 43788371768, 01:48Z), as returned with the eight fields asked for: the two in
effect (Gile Flowage Beach, Advisory / Algae, ISSUED "17-SEP-26 - "; Lake Kegonsa State Park Beach, Closed / Algae,
"11-SEP-26 - ") and nine "End" / "Closed for season" beaches. No network."""
import copy
import json
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ingest import wi_dnr_beach_health as W

ROOT = Path(__file__).resolve().parents[2]
FIX = Path(__file__).resolve().parent / "fixtures" / "wi" / "dnr_beach_layer.json"
T0, T1, T2 = "2026-11-16T01:48:00Z", "2026-11-16T02:48:00Z", "2026-11-16T03:48:00Z"
GILE, KEGONSA = 474, 309


@pytest.fixture(autouse=True)
def small_floor(monkeypatch):
    monkeypatch.setattr(W, "MIN_BEACHES", 5)          # the fixture is trimmed; the floor itself is tested below
    monkeypatch.setattr(W, "MIN_TABLE_ROWS", 5)


def layer():
    return json.loads(FIX.read_text())


def feats(mutate=None, drop=()):
    d = layer()
    fs = d["layer"]["features"]
    for f in fs:
        if mutate and f["attributes"]["BEACH_SEQ_NO"] in mutate:
            f["attributes"].update(mutate[f["attributes"]["BEACH_SEQ_NO"]])
    fs[:] = [f for f in fs if f["attributes"]["BEACH_SEQ_NO"] not in drop]
    return W.safe_features(W.check_read(d["layer"], {"count": len(fs)}))


def by_seq(recs):
    out = {}
    for r in recs:
        out.setdefault(r["raw"]["beach_seq_no"], []).append(r)
    return out


def test_todays_read_shows_the_two_algae_listings_as_blooms_with_the_departments_dates():
    recs, state, n = W.records(feats(), {}, T0)
    assert n["in_effect"] == 2 and n["by_action"] == {"Advisory": 1, "Closed": 1, "End": 9}
    assert n["by_map_status"] == {"No Data Available": 11}
    r = {k: v[0] for k, v in by_seq(recs).items()}
    assert set(r) == {GILE, KEGONSA}                      # "End" / "Closed for season" make no record
    g, k = r[GILE], r[KEGONSA]
    assert g["event_type"] == k["event_type"] == "hab_advisory"
    assert g["raw"]["bloom_action"] == "advisory" and k["raw"]["bloom_action"] == "closure"
    assert (g["started_at"], k["started_at"]) == ("2026-09-17", "2026-09-11")
    assert g["time_precision"] == k["time_precision"] == "day"
    assert g["source_record_id"] == "474-advisory-2026-09-17" and k["source_record_id"] == "309-closure-2026-09-11"
    assert (g["lat"], g["lon"]) == (46.425, -90.224) and (k["lat"], k["lon"]) == (42.972, -89.229)
    for x in recs:
        assert x["status"] == "advisory_active" and x["ended_at"] is None
        assert x["waterbody_text"] is None and x["raw"]["_point_extent_only"] is True
        assert x["raw"]["_last_seen_in_source"] == T0 and x["source_id"] == "wi-dnr-beach-health"
        assert x["reported_at"] is None and x["published_at"] is None
        assert "issued_end_text" not in x["raw"]
        assert not re.search(r"\b(safe|clean)\b", json.dumps(x), re.I)


@pytest.mark.parametrize("action,reason,etype", [("Advisory", "E. coli", "beach_advisory"),
                                                 ("Closed", "E. coli", "beach_closure"),
                                                 ("Closed", "Blue-green algae", "hab_advisory"),
                                                 ("Advisory", "Pollution event", "beach_advisory")])
def test_the_type_follows_the_action_and_an_algae_reason_is_a_bloom(action, reason, etype):
    recs, _, _ = W.records(feats({GILE: {"BEACH_ACTION": action, "STATUS": reason}}), {}, T0)
    assert by_seq(recs)[GILE][0]["event_type"] == etype


@pytest.mark.parametrize("attrs", [{"BEACH_ACTION": "End", "STATUS": "E. coli"},
                                   {"BEACH_ACTION": "Open", "STATUS": "Open", "MAP_STATUS": "Open"},
                                   {"BEACH_ACTION": "Closed", "STATUS": "Closed for season"},
                                   {"BEACH_ACTION": "End", "MAP_STATUS": "Closed for season"},
                                   {"BEACH_ACTION": "End", "MAP_STATUS": "Other Status"},
                                   {"BEACH_ACTION": "End", "MAP_STATUS": "No Data Available"}])
def test_open_season_closing_unknown_and_no_data_are_no_record_and_never_clean(attrs):
    recs, _, _ = W.records(feats({GILE: attrs}), {}, T0)
    assert GILE not in by_seq(recs)


def test_the_map_symbol_alone_still_shows_an_advisory_the_stricter_reading():
    recs, _, _ = W.records(feats({GILE: {"BEACH_ACTION": "End", "STATUS": "E. coli", "MAP_STATUS": "Advisory"}}), {},
                           T0)
    r = by_seq(recs)[GILE][0]
    assert r["event_type"] == "beach_advisory" and r["raw"]["read_from"] == "MAP_STATUS"


def test_an_unknown_action_is_kept_with_caution_never_dropped():
    recs, _, _ = W.records(feats({GILE: {"BEACH_ACTION": "Posted", "STATUS": "E. coli"}}), {}, T0)
    r = by_seq(recs)[GILE][0]
    assert r["status"] == "unknown" and r["raw"]["_agency_label_only"] is True and r["raw"]["_agency_label"] == "Posted"


@pytest.mark.parametrize("issued", ["2026-09-17", "17-SEP-2026 - ", "17-XYZ-26 - ", "31-SEP-26 - ", "17-DEC-26 - ",
                                    "", None, "Sept 17"])
def test_an_issued_text_that_is_not_unambiguous_gives_the_first_read_and_keeps_the_text(issued):
    recs, _, _ = W.records(feats({GILE: {"ISSUED": issued}}), {}, T0)
    r = by_seq(recs)[GILE][0]
    assert r["started_at"] == T0 and r["time_precision"] == "poll"   # 17-DEC-26 is after the read: not a start
    assert r["raw"]["issued_text"] == ((issued or "").strip() or None)
    assert "first read" in r["raw"]["start_basis"]


def test_an_end_date_while_the_action_is_in_effect_is_kept_as_text_and_no_end_is_invented():
    recs, _, _ = W.records(feats({GILE: {"ISSUED": "17-SEP-26 - 20-SEP-26"}}), {}, T0)
    r = by_seq(recs)[GILE][0]
    assert r["status"] == "advisory_active" and r["ended_at"] is None and r["started_at"] == "2026-09-17"
    assert r["raw"]["issued_end_text"] == "20-SEP-26"


def test_the_local_day_decides_a_date_at_the_read_day():
    # 05:30Z on November 17 is still November 16 in Wisconsin: "17-NOV-26" is after that day, not a start
    recs, _, _ = W.records(feats({GILE: {"ISSUED": "17-NOV-26 - "}}), {}, "2026-11-17T05:30:00Z")
    assert by_seq(recs)[GILE][0]["time_precision"] == "poll"
    recs, _, _ = W.records(feats({GILE: {"ISSUED": "17-NOV-26 - "}}), {}, "2026-11-17T06:30:00Z")
    assert by_seq(recs)[GILE][0]["started_at"] == "2026-11-17"


def test_a_later_read_confirms_and_a_complete_read_that_shows_end_ends_it_at_that_read():
    _, st, _ = W.records(feats(), {}, T0)
    recs, st, _ = W.records(feats(), st, T1)
    assert all(r["raw"]["_last_seen_in_source"] == T1 and r["status"] == "advisory_active" for r in recs)
    recs, st, _ = W.records(feats({GILE: {"BEACH_ACTION": "End", "STATUS": "Closed for season",
                                          "ISSUED": "17-SEP-26 - 15-NOV-26"}}), st, T2)
    g = by_seq(recs)[GILE][0]
    assert g["status"] == "advisory_lifted" and g["ended_at"] == "2026-11-15" and g["raw"]["ended_at_precision"] == "day"
    assert g["raw"]["_last_seen_in_source"] == T1 and g["raw"]["source_end_text"] == "15-NOV-26"
    assert "second ISSUED date" in g["raw"]["end_basis"]
    assert by_seq(recs)[KEGONSA][0]["status"] == "advisory_active"


def test_a_beach_gone_from_a_complete_read_ends_and_a_blank_action_holds():
    _, st, _ = W.records(feats(), {}, T0)
    recs, st, _ = W.records(feats(drop={GILE}, mutate={KEGONSA: {"BEACH_ACTION": None}}), st, T1)
    g, k = by_seq(recs)[GILE][0], by_seq(recs)[KEGONSA][0]
    assert g["status"] == "advisory_lifted" and g["ended_at"] == T1 and "no longer listed" in g["raw"]["end_basis"]
    assert k["status"] == "advisory_active" and k["ended_at"] is None
    assert k["raw"]["_missing_from_source_since"] == T1 and k["raw"]["_last_seen_in_source"] == T0


def test_a_new_date_or_a_change_of_type_is_a_new_record_and_the_earlier_one_is_unchanged():
    _, st, _ = W.records(feats(), {}, T0)
    recs, st, _ = W.records(feats({GILE: {"BEACH_ACTION": "Closed"}}), st, T1)
    rows = by_seq(recs)[GILE]
    assert len(rows) == 2
    old = [r for r in rows if r["source_record_id"] == "474-advisory-2026-09-17"][0]
    new = [r for r in rows if r is not old][0]
    assert old["status"] == "advisory_lifted" and old["ended_at"] == T1 and old["started_at"] == "2026-09-17"
    assert new["status"] == "advisory_active" and new["raw"]["bloom_action"] == "closure"


def test_a_beach_that_returns_is_a_new_record():
    _, st, _ = W.records(feats(), {}, T0)
    recs1, st, _ = W.records(feats({GILE: {"BEACH_ACTION": "End"}}), st, T1)
    before = copy.deepcopy(by_seq(recs1)[GILE][0])
    recs2, st, _ = W.records(feats({GILE: {"ISSUED": "02-JUN-27 - "}}), st,
                             "2027-06-02T15:00:00Z")
    rows = by_seq(recs2)[GILE]
    assert len(rows) == 2
    old = [r for r in rows if r["source_record_id"] == before["source_record_id"]][0]
    assert {k: v for k, v in old.items() if k != "fetched_at"} == {k: v for k, v in before.items() if k != "fetched_at"}
    new = [r for r in rows if r["source_record_id"] != before["source_record_id"]][0]
    assert new["source_record_id"] == "474-advisory-2027-06-02" and new["status"] == "advisory_active"
    # the same date listed again after an end: its own record, never the old one reopened, starting at its return
    # (the Department's date is before the end we saw; Astra review P1-3)
    _, st, _ = W.records(feats(), {}, T0)
    _, st, _ = W.records(feats({GILE: {"BEACH_ACTION": "End"}}), st, T1)
    recs3, _, _ = W.records(feats(), st, T2)
    ids = sorted(r["source_record_id"] for r in by_seq(recs3)[GILE])
    assert ids == ["474-advisory-2026-09-17", "474-advisory-p20261116T0348"]


def test_a_read_after_an_unread_gap_opens_a_new_listing_period():
    _, st, _ = W.records(feats(), {}, T0)
    _, st, _ = W.records(feats(), st, T1)
    recs, _, _ = W.records(feats(), st, "2026-12-20T12:00:00Z")
    p = by_seq(recs)[GILE][0]["raw"]["listed_periods"]
    assert p == [{"from": "2026-09-17T05:00:00Z", "to": T1}, {"from": "2026-12-20T12:00:00Z",
                                                               "to": "2026-12-20T12:00:00Z"}]


@pytest.mark.parametrize("bad", ["cut_off", "error", "empty", "count", "field", "seq", "dup", "not_json", "text"])
def test_a_partial_failed_or_malformed_read_is_refused(bad):
    d = layer()
    js, cnt = d["layer"], d["count"]
    if bad == "cut_off":
        js["exceededTransferLimit"] = True
    elif bad == "error":
        js = {"error": {"code": 500, "message": "Unable to complete operation."}}
    elif bad == "empty":
        js["features"], cnt = [], {"count": 0}
    elif bad == "count":
        cnt = {"count": 441}                                   # the layer holds more than came back
    elif bad == "field":
        for f in js["features"]:
            f["attributes"]["ACTION"] = f["attributes"].pop("BEACH_ACTION")
    elif bad == "seq":
        js["features"][0]["attributes"]["BEACH_SEQ_NO"] = None
    elif bad == "dup":
        js["features"][1]["attributes"]["BEACH_SEQ_NO"] = js["features"][0]["attributes"]["BEACH_SEQ_NO"]
    elif bad == "not_json":
        js = "<html>Service unavailable</html>"
    elif bad == "text":
        js["features"][0]["attributes"]["BEACH_ACTION"] = 3
    with pytest.raises(ValueError):
        W.check_read(js, cnt)


def test_the_floor_and_a_sharp_drop_against_the_last_complete_read_fail(monkeypatch):
    monkeypatch.setattr(W, "MIN_BEACHES", 200)
    d = layer()
    with pytest.raises(ValueError, match="fewer than 200"):
        W.check_read(d["layer"], d["count"])
    monkeypatch.setattr(W, "MIN_BEACHES", 5)
    with pytest.raises(ValueError, match="last complete read"):
        W.check_read(d["layer"], d["count"], last_count=441)
    assert len(W.check_read(d["layer"], d["count"], last_count=12)) == 11


class Resp:
    def __init__(self, js=None):
        self._js = js

    def raise_for_status(self):
        pass

    def json(self):
        if self._js is None:
            raise ValueError("not JSON")
        return self._js


def run_with(monkeypatch, tmp_path, js, cnt, at):
    import common
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path)
    monkeypatch.setattr(W, "STATE_PATH", tmp_path / "state.json")
    saved, urls = [], []
    monkeypatch.setattr(W, "save_raw", lambda name, body, ext: saved.append(body))

    def fake_get(url, **k):
        urls.append(url)
        if "beachhealth" in url:
            r = Resp()
            r.text = (FIX.parent / "dnr_beach_report_table.html").read_text()
            return r
        return Resp(cnt if "returnCountOnly" in url else js)
    monkeypatch.setattr(W.requests, "get", fake_get)
    rc = W.main(["--at", at])
    return rc, json.loads((tmp_path / "wi-dnr-beach-health.json").read_text()), saved, urls


def test_a_bad_read_keeps_every_held_record_and_marks_the_feed_not_ok(monkeypatch, tmp_path):
    d = layer()
    rc, out, _, _ = run_with(monkeypatch, tmp_path, d["layer"], d["count"], T0)
    assert rc == 0 and out["ok"] is True and out["count"] == 2
    held, state = out["records"], json.loads((tmp_path / "state.json").read_text())
    assert state["last_count"] == 11
    for js, cnt in ((dict(d["layer"], exceededTransferLimit=True), d["count"]),
                    (dict(d["layer"], features=d["layer"]["features"][2:]), d["count"]),
                    ({"error": {"code": 400}}, d["count"]),
                    (None, d["count"]),
                    (d["layer"], {"error": {"code": 500}})):
        rc, out, _, _ = run_with(monkeypatch, tmp_path, js, cnt, T1)
        assert rc == 1 and out["ok"] is False and out["error"]
        assert out["records"] == held                                     # nothing lifted, greyed or dropped
        assert json.loads((tmp_path / "state.json").read_text()) == state
    rc, out, _, _ = run_with(monkeypatch, tmp_path, d["layer"], d["count"], T2)
    assert rc == 0 and all(r["raw"]["_last_seen_in_source"] == T2 for r in out["records"])


def test_only_the_needed_fields_are_asked_for_and_saved_rounded(monkeypatch, tmp_path):
    d = layer()
    for f in d["layer"]["features"]:
        f["attributes"].update(STATIONNAME="Pat Example", ECOLIVALUE="12")   # a server that sends more than asked
    rc, out, raw, urls = run_with(monkeypatch, tmp_path, d["layer"], d["count"], T0)
    assert rc == 0 and urls[0] == W.QUERY and "returnCountOnly=true" in urls[1]
    assert "outFields=OBJECTID,BEACH_SEQ_NO,OGW_BEACH_NAME_TEXT,STATUS,BEACH_ACTION,MAP_STATUS,ISSUED,SAMPLEDATE,ECOLIVALUE&" \
        in W.QUERY and "BEACH_MONITORING_LOCATIONS/MapServer/1/" in W.QUERY
    body = json.loads(raw[0])
    assert {k for f in body["beaches"] for k in f["attributes"]} == set(W.FIELDS)
    assert all(len(str(f["geometry"]["x"]).split(".")[1]) <= 3 for f in body["beaches"] if f["geometry"])
    blob = json.dumps(out) + raw[0] + (tmp_path / "state.json").read_text()
    assert "Pat Example" not in blob


def test_a_beach_without_a_point_is_listed_not_mapped():
    recs, _, n = W.records(feats({GILE: {}}), {}, T0)
    d = layer()
    d["layer"]["features"][0]["geometry"] = {"x": "NaN", "y": "NaN"}      # as one beach on the Ext layer
    f = W.safe_features(W.check_read(d["layer"], d["count"]))
    recs, _, n = W.records(f, {}, T0)
    g = by_seq(recs)[GILE][0]
    assert g["lat"] is None and g["coord_source"] is None and n["without_point"] == 1
    assert "listed, not mapped" in g["raw"]["point_basis"]


def _status(recs, w, now):
    from build import status as S
    from tests.test_status import TEST_RULES
    S._GEOM_CACHE.clear()
    S._REACH_WATERS.clear()
    d = Path(tempfile.mkdtemp())
    (d / "wi-dnr-beach-health.json").write_text(json.dumps(
        {"source_id": "wi-dnr-beach-health", "ok": True, "last_ok_at": T0, "meta": {}, "records": copy.deepcopy(recs)}))
    st, _ = S.build(now=now, write=False, events_dir=d, waters={w["slug"]: w}, outfalls=[], registry={},
                    reaches={}, flows=({}, {}), rules=TEST_RULES, placement_cache=None)
    return st


def test_a_beach_is_a_marker_and_never_colours_its_lake_whole(monkeypatch):
    from build import status as S
    from tests.test_status import TEST_RULES
    monkeypatch.setattr(S, "_RULES", TEST_RULES)
    recs, _, _ = W.records(feats(), {}, T0)
    rec = [r for r in recs if r["raw"]["beach_seq_no"] == KEGONSA]
    lat, lon = rec[0]["lat"], rec[0]["lon"]
    box = {"type": "Polygon", "coordinates": [[[lon - .05, lat - .05], [lon + .05, lat - .05], [lon + .05, lat + .05],
                                               [lon - .05, lat + .05], [lon - .05, lat - .05]]]}
    w = {"slug": "lake-kegonsa-wi", "name": "Lake Kegonsa", "kind": "lake", "state": "WI", "area_km2": 13,
         "bbox": [lon - .05, lat - .05, lon + .05, lat + .05], "geometry": box}
    st = _status(rec, w, datetime(2026, 11, 16, 2, tzinfo=timezone.utc))
    assert st["waters"]["lake-kegonsa-wi"]["status"] != "red"            # never the whole lake for one beach
    pts = {a["event_id"]: a for a in st["advisory_points"]}
    assert pts[rec[0]["event_id"]]["status"] == "red"                    # the Department's closure, at the beach


def test_an_end_seen_weeks_later_never_colours_the_unread_weeks(monkeypatch):
    from build import status as S
    from tests.test_status import TEST_RULES
    monkeypatch.setattr(S, "_RULES", TEST_RULES)
    _, st, _ = W.records(feats(), {}, T0)
    recs, _, _ = W.records(feats({GILE: {"BEACH_ACTION": "End"}}), st, "2027-03-01T12:00:00Z")
    rec = [r for r in by_seq(recs)[GILE] if r["status"] == "advisory_lifted"][0]
    ivs = S.event_intervals(rec, "WI", datetime(2027, 3, 2, tzinfo=timezone.utc), None, TEST_RULES)
    red = [i for i in ivs if i["color"] == "red"]
    cap = datetime(2026, 11, 30, 1, 48, tzinfo=timezone.utc)                # 14 days after the last read
    assert red and max(i["end"] for i in red) == cap
    assert min(i["start"] for i in red) == datetime(2026, 9, 17, 5, tzinfo=timezone.utc)   # the Department's date


def test_the_feed_is_in_the_ingest_list_and_its_source_file_and_register_row_name_it():
    src = (ROOT / "data" / "sources" / "wi-dnr-beach-health.yaml").read_text()
    assert 'id: "wi-dnr-beach-health"' in src and "BEACH_MONITORING_LOCATIONS/MapServer/1" in src
    reg = {c["id"]: c for c in json.loads((ROOT / "data" / "notice-channels" / "wi.json").read_text())["channels"]}
    row = reg["wi-dnr-beach-layer"]
    assert row["feed_source_id"] == "wi-dnr-beach-health" and row["unmonitored_reason"] == "feed_ingested"
    assert row["barrier"] is None
    assert "wi_dnr_beach_health" in (ROOT / "Makefile").read_text()


def test_the_record_no_longer_calls_a_runner_readable_wisconsin_source_unreachable():
    bad = re.compile(r"timed out|refused|did not answer|could not be reached|reset the connection", re.I)
    t = (ROOT / "research" / "wi" / "state-text.md").read_text()
    assert not bad.search(t) and "not shown yet" not in t
    assert "one algae advisory, at Gile Flowage Beach from September 17" in t and "shown as an algal bloom" in t
    assert not re.search(r"\b(safe|clean)\b", t, re.I)
    for s in json.loads((ROOT / "research" / "wi" / "sources.json").read_text()):
        assert not bad.search(json.dumps(s)), s["id"]
        if s["status"] == "unreachable":
            assert "GitHub's runner" in s["status_reason"] and "403" in s["status_reason"], s["id"]
    rules = json.loads((ROOT / "data" / "rules.json").read_text())["red"]["by_state"]["WI"]
    assert "Wisconsin Beach Health" in rules["source"] and "algal bloom" in rules["basis"]
    for p in (ROOT / "data" / "sources").glob("wi-*.yaml"):
        assert not bad.search(p.read_text()), p.name


def flaky_run(monkeypatch, tmp_path, at, fail, exc=None):
    """run_with's transport, with the first `fail` attempts of each request raising `exc` (a ConnectTimeout by
    default); returns rc, the events file, the attempts per address and the pauses taken."""
    import common
    import requests
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path)
    monkeypatch.setattr(W, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(W, "save_raw", lambda name, body, ext: None)
    pauses, tries = [], {}
    monkeypatch.setattr(W, "_pause", pauses.append)
    d = layer()

    def fake_get(url, **k):
        assert k["timeout"] == (20, 300)
        tries[url] = tries.get(url, 0) + 1
        if tries[url] <= fail:
            raise (exc or requests.exceptions.ConnectTimeout)(f"connect timeout to {url[:30]}")
        if "beachhealth" in url:
            r = Resp()
            r.text = (FIX.parent / "dnr_beach_report_table.html").read_text()
            return r
        return Resp(d["count"] if "returnCountOnly" in url else d["layer"])
    monkeypatch.setattr(W.requests, "get", fake_get)
    rc = W.main(["--at", at])
    return rc, json.loads((tmp_path / "wi-dnr-beach-health.json").read_text()), tries, pauses


def test_a_connection_made_on_the_second_try_gives_a_normal_read(monkeypatch, tmp_path):
    rc, out, tries, pauses = flaky_run(monkeypatch, tmp_path, T0, fail=1)
    assert rc == 0 and out["ok"] is True and out["count"] == 2
    assert tries == {W.QUERY: 2, W.COUNT: 2, W.REPORT_URL: 2}          # each request retried on its own
    assert pauses == [30, 30, 30]
    import requests
    rc, out, tries, pauses = flaky_run(monkeypatch, tmp_path, T1, fail=2, exc=requests.exceptions.ConnectionError)
    assert rc == 0 and out["ok"] is True and tries[W.QUERY] == 3


def test_three_failed_connections_fail_the_read_and_keep_what_is_held(monkeypatch, tmp_path):
    rc, out, _, _ = flaky_run(monkeypatch, tmp_path, T0, fail=0)
    held, state = out["records"], (tmp_path / "state.json").read_text()
    assert rc == 0 and len(held) == 2
    rc, out, tries, pauses = flaky_run(monkeypatch, tmp_path, T1, fail=3)
    assert rc == 1 and out["ok"] is False and out["error"].startswith("ConnectTimeout")
    assert tries == {W.QUERY: 3} and pauses == [30, 30]                 # three tries, then the run stops
    assert out["records"] == held and (tmp_path / "state.json").read_text() == state


def test_an_http_error_or_a_read_timeout_is_not_retried(monkeypatch, tmp_path):
    import common
    import requests
    import urllib3
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path)
    monkeypatch.setattr(W, "STATE_PATH", tmp_path / "state.json")
    pauses, calls = [], []
    monkeypatch.setattr(W, "_pause", pauses.append)

    class Forbidden(Resp):
        status_code = 403

        def raise_for_status(self):
            raise requests.exceptions.HTTPError("403 Client Error: Forbidden")
    for answer in (lambda: Forbidden(), lambda: (_ for _ in ()).throw(requests.exceptions.ReadTimeout("read")),
                   lambda: (_ for _ in ()).throw(requests.exceptions.ConnectionError(
                       urllib3.exceptions.ReadTimeoutError(None, "/", "read timed out")))):
        calls.clear()
        monkeypatch.setattr(W.requests, "get", lambda url, **k: (calls.append(url), answer())[1])
        rc = W.main(["--at", T0])
        out = json.loads((tmp_path / "wi-dnr-beach-health.json").read_text())
        assert rc == 1 and out["ok"] is False and calls == [W.QUERY] and pauses == []
