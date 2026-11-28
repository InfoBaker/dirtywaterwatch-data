"""NH beach reason and bloom regression tests, using synthetic source attributes."""
import csv
from datetime import UTC, datetime

import pytest

import common
from build import beach_reason as BR, redact, status as S
from export import build as X, csv as csv_export
from ingest import nh_des_swimming as NH

AT = "2026-11-25T01:34:00Z"
NOW = datetime(2026, 11, 25, tzinfo=UTC)


def record(monkeypatch, label, **extra):
    monkeypatch.setattr(NH, "match_waters", lambda *args: ([], []))
    attrs = {"EPA_ID": "TEST", "Beach_Name": "Example Beach", "Status": label,
             "SampleDate": 1795478400000, "DateIssued": 1795478400000, **extra}
    return NH.beach_records([{"attributes": attrs}], AT, AT)


@pytest.mark.parametrize("label", ["Closed", "Unrecognized status"])
def test_reasonless_status_is_listed_without_colour(monkeypatch, label):
    r, = record(monkeypatch, label)
    rules = S.load_rules()
    assert r["raw"]["Status"] == label
    assert BR.judge(r, rules)["stated"] is False
    assert S.event_intervals(r, "NH", NOW, rules=rules) == []
    assert r["status"] != "advisory_active"
    assert BR.label(r, BR.config(rules)) == "Beach status listed; the source gives no water-quality reason"


def test_completed_season_is_a_monitoring_listing_with_the_existing_id(monkeypatch):
    current, history = record(monkeypatch, "Monitoring Season Completed", Advisory_history="7/3-7/5")
    assert current["event_id"] == "nh-des-swimming:beach:TEST:monitoring-season-completed:2026-11-23"
    assert current["event_type"] == current["status"] == "unknown"
    assert current["parse_error"] is None
    assert current["started_at"] is current["ended_at"] is current["material"] is None
    assert current["advice_text"] == 'NHDES Healthy Swimming Mapper status: "Monitoring Season Completed".'
    assert current["raw"]["Status"] == "Monitoring Season Completed"
    assert S.event_intervals(current, "NH", NOW, rules={}) == []
    assert history["event_type"] == "beach_advisory"
    assert history["status"] == "advisory_lifted"
    assert history["advice_text"] == NH.BEACH_ADVICE
    assert history["material"] == "fecal indicator bacteria"


def test_saved_completed_seasons_are_corrected_without_changing_identity(monkeypatch):
    current, history = record(monkeypatch, "Monitoring Season Completed", Advisory_history="7/3-7/5")
    # An old season retained by main(), even after the source has moved on to another state.
    current.update(event_type="beach_advisory", status="advisory_lifted",
                   advice_text=NH.BEACH_ADVICE, material="fecal indicator bacteria")
    ids = (current["event_id"], current["source_record_id"])
    times = {k: current[k] for k in ("reported_at", "source_updated_at", "fetched_at")}
    NH.chain([current, history])
    assert current["event_type"] == current["status"] == "unknown"
    assert (current["event_id"], current["source_record_id"]) == ids
    assert {k: current[k] for k in times} == times
    assert current["raw"]["Status"] == "Monitoring Season Completed"
    assert current["parse_error"] is None
    assert history["event_type"] == "beach_advisory"


def test_program_advisory_and_dated_history_keep_their_reason(monkeypatch):
    current, = record(monkeypatch, "Advisory")
    seasonal, history = record(monkeypatch, "Monitoring Season Completed", Advisory_history="7/3-7/5")
    rules = S.load_rules()
    assert BR.judge(current, rules)["stated"] is True
    assert BR.judge(history, rules)["stated"] is True
    assert history["status"] == "advisory_lifted"
    assert S.event_intervals(current, "NH", NOW, rules=rules)
    assert S.event_intervals(history, "NH", NOW, rules=rules)
    assert not S.event_intervals(seasonal, "NH", NOW, rules=rules)


def test_blooms_stay_in_the_bloom_category(monkeypatch):
    monkeypatch.setattr(NH, "match_waters", lambda *args: ([], []))
    r, = NH.hab_records([{"attributes": {"WB_ID": "TEST", "WB_NAME": "Example Lake",
        "Bloom_status": "Warning", "LatestAdvisory": "Warning", "StatusDate": 1795478400000}}], AT, AT)
    assert r["event_type"] == "hab_advisory" and S.category_of(r["event_type"]) == "bloom"
    assert BR.judge(r, S.load_rules()) is None


@pytest.mark.parametrize("child_source,stated", [(NH.SOURCE_ID, False), ("md-aa-health-closings", True)])
def test_parent_inheritance_depends_on_the_child_source(child_source, stated):
    parent = {"event_id": "test:parent", "source_id": NH.SOURCE_ID, "event_type": "beach_advisory",
              "raw": {"Status": "Advisory"}}
    child = {"event_id": "test:child", "source_id": child_source, "event_type": "beach_advisory",
             "parent_event_id": parent["event_id"], "raw": {}}
    by_id = {r["event_id"]: r for r in (parent, child)}
    rules = S.load_rules()
    S.annotate_beach_reasons([child, parent], by_id, {}, rules)
    assert child["_beach_reason"]["stated"] is stated
    if not stated:
        # Duplicate evidence about this same record still applies; only parent inheritance is disabled.
        S.annotate_beach_reasons([child, parent], by_id, {parent["event_id"]: child["event_id"]}, rules)
        assert child["_beach_reason"]["stated"] is True
        assert child["_beach_reason"]["how"] == "linked"


@pytest.mark.parametrize("earlier", ["No advisory", "Advisory"])
@pytest.mark.parametrize("label", ["Closed", "Monitoring Season Completed", "Unrecognized status"])
def test_successive_refreshes_do_not_lend_a_parent_reason(tmp_path, monkeypatch, earlier, label):
    """Persist and re-read NH's chronological links, including a repeated refresh and dated history."""
    events = tmp_path / "events"
    events.mkdir()
    for mod in (common, NH):
        monkeypatch.setattr(mod, "EVENTS_DIR", events)
    monkeypatch.setattr(NH, "match_waters", lambda *args: (["example-lake-nh"], []))
    monkeypatch.setattr(NH, "_licence", lambda sess: (NH.LICENCE_FALLBACK, "NHDES"))
    monkeypatch.setattr(NH, "_layer_info", lambda *args: {})
    monkeypatch.setattr(NH, "fetch_hab", lambda *args: [])
    monkeypatch.setattr(S, "_STATES", {"NH"})
    waters = {"example-lake-nh": {"slug": "example-lake-nh", "name": "Example Lake",
                                   "kind": "lake", "state": "NH", "area_km2": 1}}
    rules = S.load_rules()
    parent_id = None
    child_id = None
    for step, status in enumerate((earlier, label, label)):
        fetched = f"2026-11-{22 + step}T12:00:00Z"
        day = 21 if step == 0 else 23
        stamp = int(datetime(2026, 11, day, 12, tzinfo=UTC).timestamp() * 1000)
        attrs = {"EPA_ID": "TEST", "Beach_Name": "Example Beach", "Waterbody_Name": "Example Lake",
                 "Status": status, "SampleDate": stamp, "DateIssued": stamp,
                 "Advisory_history": "11/21-11/22" if step else ""}
        monkeypatch.setattr(NH, "now_iso", lambda: fetched)
        monkeypatch.setattr(common, "now_iso", lambda: fetched)
        monkeypatch.setattr(NH, "_query_all", lambda *args: [{"attributes": attrs}])
        assert NH.main([]) == 0
        _, records, problems = S.load_events(events)
        assert not problems
        by_id = {r["event_id"]: r for r in records}
        current, = [r for r in records if r["raw"].get("Status") == status]
        if step == 0:
            parent_id = current["event_id"]
        else:
            assert len(records) == 3  # previous state, current state, dated history; no repeat copies
            assert current["parent_event_id"] == parent_id
            if child_id:
                assert current["event_id"] == child_id
            child_id = current["event_id"]
        S.annotate_beach_reasons(records, by_id, {}, rules)
        st, _ = S.build(now=NOW, write=False, events_dir=events, waters=waters, outfalls=[], registry={},
                           reaches={}, flows=({}, {}), rules=rules, placement_cache=False)
        redactor = redact.redactor_for(records, tmp_path)
        exported = {r["event_id"]: X.public_record(r, st["placements"][r["event_id"]], redactor)
                    for r in records}
        if step == 0:
            assert current["_beach_reason"]["stated"] is True
            assert "no_stated_reason" not in exported[parent_id]
            continue
        if label == "Monitoring Season Completed":
            assert current.get("_beach_reason") is None
            assert exported[child_id]["event_type"] == exported[child_id]["status"] == "unknown"
            assert exported[child_id]["advice_text"] == current["advice_text"]
        else:
            assert current["_beach_reason"]["stated"] is False
        assert S.event_intervals(current, "NH", NOW, rules=rules) == []
        assert not [p for p in st["advisory_points"] if p["event_id"] == child_id]
        assert not [r for r in st["waters"]["example-lake-nh"]["reasons"] if r["event_id"] == child_id]
        history, = [r for r in records if r["raw"].get("season_from")]
        assert history["_beach_reason"]["stated"] is True
        assert history["_beach_reason"]["how"] == "program_value"
        assert S.event_intervals(history, "NH", NOW, rules=rules)
        assert "no_stated_reason" not in exported[history["event_id"]]
        if earlier == "Advisory":
            assert history["parent_event_id"] == parent_id
        if label == "Monitoring Season Completed":
            assert "no_stated_reason" not in exported[child_id]
            assert st["waters"]["example-lake-nh"]["status"] == "grey"
            assert st["beach_reason"]["listed_without_colour"] == {}
            out = tmp_path / f"csv-{step}"
            csv_export.write_csvs(list(exported.values()), [], [], out, page_ids=set())
            with (out / "all-reports-2026.csv").open(newline="", encoding="utf-8") as f:
                rows = {r["record_id"]: r for r in csv.DictReader(f)}
            assert rows[current["source_record_id"]]["event_type"] == "unknown"
            assert rows[current["source_record_id"]]["listed_without_colour"] == ""
            assert rows[history["source_record_id"]]["listed_without_colour"] == ""


@pytest.mark.parametrize("legacy_closed", [False, True])
def test_season_refresh_without_history_does_not_close_or_extend_advisory(tmp_path, monkeypatch, legacy_closed):
    """A Nov. 23 sample cannot lift or reconfirm the Nov. 1 advisory across an unread gap."""
    events = tmp_path / "events"
    events.mkdir()
    for mod in (common, NH):
        monkeypatch.setattr(mod, "EVENTS_DIR", events)
    monkeypatch.setattr(NH, "match_waters", lambda *args: (["example-lake-nh"], []))
    monkeypatch.setattr(NH, "_licence", lambda sess: (NH.LICENCE_FALLBACK, "NHDES"))
    monkeypatch.setattr(NH, "_layer_info", lambda *args: {})
    monkeypatch.setattr(NH, "fetch_hab", lambda *args: [])
    monkeypatch.setattr(S, "_STATES", {"NH"})
    waters = {"example-lake-nh": {"slug": "example-lake-nh", "name": "Example Lake",
                                   "kind": "lake", "state": "NH", "area_km2": 1}}
    parent_id = "nh-des-swimming:beach:TEST:advisory:2026-11-01"
    season_id = "nh-des-swimming:beach:TEST:monitoring-season-completed:2026-11-23"
    saved_parent = None
    for step, day in enumerate((1, 23, 24)):
        fetched = f"2026-11-{day:02}T12:00:00Z"
        sample_day = 1 if step == 0 else 23
        stamp = int(datetime(2026, 11, sample_day, 12, tzinfo=UTC).timestamp() * 1000)
        attrs = {"EPA_ID": "TEST", "Beach_Name": "Example Beach", "Waterbody_Name": "Example Lake",
                 "Status": "Advisory" if step == 0 else "Monitoring Season Completed",
                 "SampleDate": stamp, "DateIssued": stamp if step == 0 else None}
        monkeypatch.setattr(NH, "now_iso", lambda: fetched)
        monkeypatch.setattr(common, "now_iso", lambda: fetched)
        monkeypatch.setattr(NH, "_query_all", lambda *args: [{"attributes": attrs}])
        assert NH.main([]) == 0
        path = events / f"{NH.SOURCE_ID}.json"
        doc = common.read_json(path)
        if step == 0:
            saved_parent, = doc["records"]
            if legacy_closed:
                # A retained record already closed by the old chain() must be repaired too.
                doc["records"][0] = {**saved_parent, "status": "advisory_lifted",
                                     "ended_at": "2026-11-23T07:00:00-05:00"}
                common.write_json(path, doc)
            continue
        _, records, problems = S.load_events(events)
        assert not problems
        by_id = {r["event_id"]: r for r in records}
        assert set(by_id) == {parent_id, season_id}
        parent, season = by_id[parent_id], by_id[season_id]
        assert season["event_type"] == season["status"] == "unknown"
        assert season["parent_event_id"] == parent_id
        assert season["started_at"] is season["ended_at"] is None
        assert parent["ended_at"] is None
        assert parent["status"] == "advisory_active"  # last source advisory, no confirmed lift
        for key in ("source_record_id", "started_at", "reported_at", "source_updated_at", "fetched_at"):
            assert parent[key] == saved_parent[key]
        st, hist = S.build(now=NOW, write=False, events_dir=events, waters=waters, outfalls=[], registry={},
                           reaches={}, flows=({}, {}), rules=S.load_rules(), placement_cache=False)
        assert st["waters"]["example-lake-nh"]["status"] == "grey"
        strip = hist["waters"]["example-lake-nh"]
        # The first confirmed window remains; the unconfirmed Nov. 16–23 gap stays grey.
        early = hist["hours"].index("2026-11-02T12:00:00Z")
        gap = hist["hours"].index("2026-11-16T12:00:00Z")
        assert strip[early] == "R"
        assert set(strip[gap:]) == {"g"}
        exported = X.public_record(parent, st["placements"][parent_id], redact.redactor_for(records, tmp_path))
        assert exported["ended_at"] is None
