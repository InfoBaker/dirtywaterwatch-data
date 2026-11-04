"""Status rules (docs/plan.md §2) in build/status.py, the fixture flag, and the export's file names.

Run from pipeline/: python -m pytest tests -q
"""
from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from build import status as S  # noqa: E402
from common import event  # noqa: E402
from export.build import event_file_name, event_id_from_file  # noqa: E402

import pytest  # noqa: E402

NOW = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
H = timedelta(hours=1)

# The advisory windows the tests run under (the shape of data/rules.json; values as of 2026-11-02),
# so an owner's edit to the real file does not break the rule tests.
TEST_RULES = {
    "version": "test",
    "red": {"by_state": {
        "MA": {"hours": 48, "clock": "end_of_discharge", "basis": "314 CMR 16.04(10)(g)", "source": "ma"},
        "VT": {"hours": 48, "basis": "10 V.S.A. 1295(e)", "source": "vt"},
        "CT": {"hours": 48, "basis": "CT DEEP", "source": "ct"},
        "RI": {"hours": 48, "basis": "NBC", "source": "ri"},
        "NH": {"hours": 72, "basis": "RSA 485-A:8 III", "source": "nh"},
        "ME": {"hours": None, "basis": "no stated period", "source": "me"},
        "NY": {"hours": None, "basis": "no stated period", "source": "ny"}}},
    "yellow": {
        "default_hours": 72, "default_rationale": "about three days",
        "by_event_type": {
            "cso": {"hours": 72, "rationale": "default applies", "source": "s"},
            "blended": {"hours": 48, "rationale": "disinfected", "source": "s"},
            "beach_advisory": {"hours": None, "rationale": "follows the authority", "source": "s"},
            "hab_advisory": {"hours": None, "rationale": "follows the authority", "source": "s"},
            "rain_advisory": {"hours": None, "rationale": "follows the authority", "source": "s"}},
        "by_water_kind": {k: {"hours": 96, "rationale": "still water", "source": "s"} for k in ("lake", "pond", "reservoir")},
        "by_water": {"_example": {"enabled": False, "hours": 500, "rationale": "example", "source": ""}}},
    "unresolved": {"ongoing_red_days": 7, "unresolved_yellow_days": 30, "unknown_status_yellow_days": 14},
    "reach": {"cap_km": 40},
}


@pytest.fixture(autouse=True)
def _rules(monkeypatch):
    monkeypatch.setattr(S, "_RULES", TEST_RULES)


def iso(t):
    return t.isoformat()


def ev(rid="1", **kw):
    kw.setdefault("event_type", "cso")
    kw.setdefault("water_slugs", ["test-river-ma"])
    return event(source_id=kw.pop("source_id", "ma-test"), source_record_id=rid, **kw)


def colour(e, t, state="MA", now=None):
    c, ivs = S.status_at(S.event_intervals(e, state, now or t), t)
    return c, [iv["rule"] for iv in ivs]


# ---------------------------------------------------------------- ongoing

def test_ongoing_cso_is_red():
    e = ev(status="ongoing", started_at=iso(NOW - 2 * H))
    assert colour(e, NOW) == ("red", ["ongoing"])


def test_ongoing_is_red_for_7_days_then_unresolved_to_day_30():
    start = NOW - timedelta(days=40)
    e = ev(status="ongoing", started_at=iso(start))
    assert colour(e, start + timedelta(days=6, hours=23)) == ("red", ["ongoing"])
    assert colour(e, start + timedelta(days=7, hours=1)) == ("unresolved", ["unresolved"])
    assert colour(e, start + timedelta(days=29, hours=23))[0] == "unresolved"
    ivs = S.event_intervals(e, "MA", NOW)
    assert ivs[0]["rule_applied"]["rule"] == "unresolved.ongoing_red_days"
    assert ivs[1]["rule_applied"]["rule"] == "unresolved.unresolved_yellow_days"


def test_ongoing_after_30_days_leaves_the_map_but_stays_flagged():
    start = NOW - timedelta(days=31)
    e = ev(status="ongoing", started_at=iso(start))
    c, rules = colour(e, NOW)
    assert c == "grey" and rules == ["end_never_reported"]
    st, hist = S.build(now=NOW, write=False, **world(tmp_events([e])))
    w = st["waters"]["test-river-ma"]
    assert w["status"] == "grey"
    assert [r["rule"] for r in w["reasons"]] == ["end_never_reported"]
    assert "unresolved, no end reported (off the map)" in w["reason_short"]
    assert w["unresolved_events"] == ["ma-test:1"]
    strip = hist["waters"]["test-river-ma"]
    assert strip[-25] == "g" and strip[-26] == "u" and "r" in strip      # history keeps the u state
    assert st["legend"]["u"].startswith("unresolved")


def test_ongoing_record_with_an_end_uses_the_end_windows():
    start, end = NOW - 30 * H, NOW - 20 * H
    e = ev(status="ongoing", started_at=iso(start), ended_at=iso(end))
    assert colour(e, NOW) == ("red", ["authority_window"])
    assert colour(e, end + 50 * H) == ("yellow", ["caution"])
    assert colour(e, end + 73 * H)[0] == "grey"


# ---------------------------------------------------------------- ended

def test_ended_red_48h_yellow_to_72h_then_grey():
    start, end = NOW - 10 * H, NOW - 8 * H
    e = ev(status="ended", started_at=iso(start), ended_at=iso(end), advice_window_hours=48)
    assert colour(e, start + H) == ("red", ["discharge"])
    assert colour(e, end + 47 * H) == ("red", ["authority_window"])
    assert colour(e, end + 49 * H) == ("yellow", ["caution"])
    assert colour(e, end + 71 * H) == ("yellow", ["caution"])
    assert colour(e, end + 73 * H) == ("grey", [])


def test_state_default_window_and_none():
    end = NOW - 30 * H
    e = ev(status="ended", started_at=iso(end - 2 * H), ended_at=iso(end))
    assert colour(e, NOW, state="MA")[0] == "red"          # MA default 48 h (314 CMR 16)
    assert colour(e, NOW, state="ME") == ("yellow", ["caution"])   # no authority window stated


def test_event_window_overrides_state_default():
    end = NOW - 30 * H
    e = ev(status="ended", started_at=iso(end - H), ended_at=iso(end), advice_window_hours=24)
    assert colour(e, NOW, state="MA") == ("yellow", ["caution"])


def test_unknown_status_no_end_is_yellow_14_days_from_its_report_then_unresolved():
    start = NOW - timedelta(days=13)
    e = ev(status="unknown", started_at=iso(start), reported_at=iso(start + timedelta(days=1)))
    assert colour(e, NOW) == ("yellow", ["no_end"])
    assert colour(e, start + timedelta(days=14, hours=12))[0] == "yellow"      # 14 days from the report
    assert colour(e, start + timedelta(days=15, hours=1)) == ("unresolved", ["unresolved"])
    assert colour(e, start + timedelta(days=31, hours=1)) == ("grey", ["end_never_reported"])


# ---------------------------------------------------------------- advisories

def test_advisory_active_is_red():
    e = ev(event_type="hab_advisory", status="advisory_active", started_at=iso(NOW - timedelta(days=20)),
           source_updated_at=iso(NOW - timedelta(days=1)))      # re-confirmed yesterday
    assert colour(e, NOW) == ("red", ["advisory_active"])


def test_advisory_active_on_a_discharge_record_is_red():
    e = ev(event_type="cso", status="advisory_active", started_at=iso(NOW - 3 * H))
    assert colour(e, NOW)[0] == "red"


def test_advisory_lifted_is_grey_after_its_end():
    e = ev(event_type="beach_closure", status="advisory_lifted", started_at=iso(NOW - 50 * H), ended_at=iso(NOW - 2 * H))
    assert colour(e, NOW - 10 * H)[0] == "red"
    assert colour(e, NOW)[0] == "grey"


def test_rain_advisory_is_yellow():
    e = ev(event_type="rain_advisory", status="advisory_active", started_at=iso(NOW - 3 * H))
    assert colour(e, NOW) == ("yellow", ["rain_advisory"])


def test_annual_total_sets_no_colour():
    e = ev(event_type="annual_total", status="ended", started_at="2025-01-01T00:00:00-05:00",
           ended_at="2025-12-31T23:59:00-05:00")
    assert S.event_intervals(e, "ME", NOW) == []


# ---------------------------------------------------------------- build: files, fixtures, history

def tmp_events(records, fixture_records=(), _dir=[]):
    import tempfile
    d = Path(tempfile.mkdtemp())
    (d / "ma-test.json").write_text(json.dumps({"source_id": "ma-test", "ok": True, "last_ok_at": iso(NOW),
                                                "meta": {}, "records": list(records)}))
    if fixture_records:
        (d / "fixture-ma.json").write_text(json.dumps({"source_id": "fixture-ma", "ok": True, "last_ok_at": iso(NOW),
                                                       "meta": {"fixture": True}, "records": list(fixture_records)}))
    return d


def world(events_dir):
    S._GEOM_CACHE.clear()
    line = {"type": "LineString", "coordinates": [[-72.0, 42.0], [-71.9, 42.0]]}
    pond = {"type": "Polygon", "coordinates": [[[-72.0, 42.1], [-71.99, 42.1], [-71.99, 42.11], [-72.0, 42.1]]]}
    bay = {"type": "Polygon", "coordinates": [[[-71.0, 42.0], [-70.9, 42.0], [-70.9, 42.1], [-71.0, 42.0]]]}
    waters = {"test-river-ma": {"slug": "test-river-ma", "name": "Test River", "kind": "river", "state": "MA",
                                "bbox": [-72, 42, -71.9, 42.0], "geometry": line},
              "other-pond-ma": {"slug": "other-pond-ma", "name": "Other Pond", "kind": "pond", "state": "MA",
                                "area_km2": 0.5, "bbox": [-72, 42.1, -71.99, 42.11], "geometry": pond},
              "big-lake-ma": {"slug": "big-lake-ma", "name": "Big Lake", "kind": "lake", "state": "MA",
                              "area_km2": 120, "bbox": [-72, 42.1, -71.99, 42.11], "geometry": pond},
              "test-bay-ma": {"slug": "test-bay-ma", "name": "Test Bay", "kind": "bay", "state": "MA",
                              "bbox": [-71, 42, -70.9, 42.1], "geometry": bay}}
    S._REACH_WATERS.clear()
    return {"events_dir": events_dir, "waters": waters, "outfalls": [], "registry": {}, "reaches": {},
            "flows": ({}, {})}


def test_fixtures_are_labelled_and_excluded_with_the_flag():
    live = ev("live", status="ended", started_at=iso(NOW - 200 * H), ended_at=iso(NOW - 199 * H))
    fx = ev("fx", source_id="fixture-ma", status="ongoing", started_at=iso(NOW - H), water_slugs=["other-pond-ma"])
    d = tmp_events([live], [fx])
    st, hist = S.build(include_fixtures=True, now=NOW, write=False, **world(d))
    assert st["waters"]["other-pond-ma"]["status"] == "red"
    assert st["waters"]["other-pond-ma"]["reasons"][0]["fixture"] is True
    assert st["sources"]["fixture-ma"]["fixture"] is True and st["sources"]["fixture-ma"]["stale"] is False
    st, hist = S.build(include_fixtures=False, now=NOW, write=False, **world(d))
    assert "other-pond-ma" not in st["waters"]
    assert "fixture-ma:fx" not in st["placements"]
    assert st["fixtures_included"] is False
    assert st["waters"]["test-river-ma"]["status"] == "grey"


def test_fixture_dropped_when_the_live_record_exists():
    live = ev("9694", status="ended", started_at=iso(NOW - 5 * H), ended_at=iso(NOW - 4 * H))
    fx = ev("ct-trace", source_id="fixture-ma", status="ended", started_at=iso(NOW - 5 * H), ended_at=iso(NOW - 4 * H),
            raw={"_match_ids": ["9694"]})
    st, _ = S.build(include_fixtures=True, now=NOW, write=False, **world(tmp_events([live], [fx])))
    assert st["dropped_fixtures"] == ["fixture-ma:ct-trace"]


def test_history_strip_and_since():
    e = ev(status="ended", started_at=iso(NOW - 10 * H), ended_at=iso(NOW - 8 * H))
    st, hist = S.build(now=NOW, write=False, **world(tmp_events([e])))
    strip = hist["waters"]["test-river-ma"]
    assert len(strip) == len(hist["hours"]) == 90 * 24
    assert strip[-11:] == "r" * 11 and strip[-12] == "g"
    w = st["waters"]["test-river-ma"]
    assert w["status"] == "red" and w["since"] == "2026-08-10T02:00:00Z"
    assert w["reasons"][0]["rule"] == "authority_window" and w["reasons"][0]["window_hours"] == 48


def test_revision_with_a_start_supersedes_its_parent():
    parent = ev("p", status="ongoing", started_at=iso(NOW - 2 * H))
    child = ev("c", status="ended", started_at=iso(NOW - 200 * H), ended_at=iso(NOW - 199 * H), parent_event_id="ma-test:p")
    st, _ = S.build(now=NOW, write=False, **world(tmp_events([parent, child])))
    assert st["waters"]["test-river-ma"]["status"] == "grey"
    assert st["placements"]["ma-test:p"]["superseded"].startswith("revised by")


def test_lifted_child_inherits_the_parent_start_and_ends_it():
    parent = ev("p", event_type="hab_advisory", status="advisory_active", started_at=iso(NOW - 50 * H),
                water_slugs=["other-pond-ma"])
    child = ev("c", event_type="hab_advisory", status="advisory_lifted", reported_at=iso(NOW - 10 * H),
               parent_event_id="ma-test:p", water_slugs=["other-pond-ma"])
    st, hist = S.build(now=NOW, write=False, **world(tmp_events([parent, child])))
    assert st["waters"]["other-pond-ma"]["status"] == "grey"
    strip = hist["waters"]["other-pond-ma"]
    assert strip[-51:-11] == "B" * 40 and strip[-11:] == "g" * 11 and strip[-52] == "g"     # a bloom hour (§2.z)


def test_notice_child_without_times_leaves_the_parent_in_charge():
    parent = ev("incident", status="ended", started_at=iso(NOW - 5 * H), ended_at=iso(NOW - 4 * H))
    alert = ev("alert", status="unknown", reported_at=iso(NOW - 3 * H), parent_event_id="ma-test:incident")
    st, _ = S.build(now=NOW, write=False, **world(tmp_events([parent, alert])))
    w = st["waters"]["test-river-ma"]
    assert w["status"] == "red" and [r["event_id"] for r in w["reasons"]] == ["ma-test:incident"]
    assert st["placements"]["ma-test:alert"]["superseded"].startswith("notice about")


def test_lifted_report_without_a_start_sets_no_colour():
    e = ev("x", event_type="hab_advisory", status="advisory_lifted", reported_at=iso(NOW - 30 * H),
           source_updated_at=iso(NOW - H))
    assert S.event_intervals(e, "VT", NOW) == []


def test_stale_source_flagged():
    e = ev(status="ended", started_at=iso(NOW - 300 * H), ended_at=iso(NOW - 299 * H))
    d = tmp_events([e])
    p = d / "ma-test.json"
    f = json.loads(p.read_text())
    f.update(ok=False, error="HTTP 500", last_ok_at=iso(NOW - 48 * H))
    p.write_text(json.dumps(f))
    st, _ = S.build(now=NOW, write=False, **world(d))
    w = st["waters"]["test-river-ma"]
    assert w["stale"] and w["stale_sources"][0]["source_id"] == "ma-test"


def test_placement_by_outfall_registry_and_name():
    a = ev("a", status="ended", water_slugs=[], npdes_permit="MA0101613", outfall_id="SPR010",
           started_at=iso(NOW - 300 * H), ended_at=iso(NOW - 299 * H))
    b = ev("b", status="ended", water_slugs=[], waterbody_text="OTHER POND", npdes_permit="MA0000001",
           started_at=iso(NOW - 300 * H), ended_at=iso(NOW - 299 * H))
    w = world(tmp_events([a, b]))
    w["outfalls"] = [{"npdes_permit": "MA0101613", "outfall": "010", "state": "MA", "water_slug": "test-river-ma"}]
    st, _ = S.build(now=NOW, write=False, **w)
    assert st["placements"]["ma-test:a"]["water_match"] == "outfall_registry"
    assert st["placements"]["ma-test:a"]["water_slugs"] == ["test-river-ma"]
    assert st["placements"]["ma-test:b"] == {"water_slugs": ["other-pond-ma"], "water_match": "name", "note": None}


def test_event_file_name_is_safe_and_reversible():
    for eid in ["ma-massdep:8e8d6584-83e7", "fixture-ct:ct-2025/x~y", "vt-dec:alert:4300", "ü:1"]:
        f = event_file_name(eid)
        assert ":" not in f and "/" not in f
        assert event_id_from_file(f) == eid


def test_research_fixtures_convert():
    from build import fixtures
    root = Path(__file__).resolve().parents[2] / "research"
    n = 0
    dis = fixtures.load_dischargers()
    for area in fixtures.AREAS:
        p = root / area / "events.json"
        if not p.exists():
            continue
        d = json.loads(p.read_text())
        for r in d["events"] if isinstance(d, dict) else d:
            rec = fixtures.convert(area, r, dis, "2026-11-02T00:00:00Z")
            assert rec["event_id"].startswith(f"fixture-{area}:")
            n += 1
    assert n == 0 or n > 20


# ---------------------------------------------------------------- placement guard

def test_name_match_too_far_is_set_aside():
    # the test river's record spans 8.3 km: a named match is kept up to that extent plus 2 km (12.4 km here)
    far = ev("far", status="ongoing", started_at=iso(NOW - H), water_match="name", lat=42.12, lon=-71.95)
    mid = ev("mid", status="ongoing", started_at=iso(NOW - H), water_match="name", lat=42.05, lon=-71.95)
    near = ev("near", status="ongoing", started_at=iso(NOW - H), water_match="name", lat=42.01, lon=-71.95)
    st, _ = S.build(now=NOW, write=False, **world(tmp_events([far, mid, near])))
    p = st["placements"]["ma-test:far"]
    assert p["water_slugs"] == [] and p["unplaced_reason"].startswith("name match too far (13.")
    assert st["placements"]["ma-test:near"]["water_slugs"] == ["test-river-ma"]
    m = st["placements"]["ma-test:mid"]
    assert m["water_slugs"] == ["test-river-ma"] and "within the river record's extent (8.3 km) plus 2 km" in m["note"]
    assert sorted(r["event_id"] for r in st["waters"]["test-river-ma"]["reasons"]) == ["ma-test:mid", "ma-test:near"]


def test_bays_allow_5_km_and_registry_matches_are_not_guarded():
    bay = ev("b", status="ongoing", started_at=iso(NOW - H), water_slugs=["test-bay-ma"], water_match="inferred",
             lat=42.0, lon=-71.04)                       # ~3.3 km west of the bay
    reg = ev("r", status="ongoing", started_at=iso(NOW - H), water_match="outfall_registry", lat=43.0, lon=-71.0)
    st, _ = S.build(now=NOW, write=False, **world(tmp_events([bay, reg])))
    assert st["placements"]["ma-test:b"]["water_slugs"] == ["test-bay-ma"]
    assert st["placements"]["ma-test:r"]["water_slugs"] == ["test-river-ma"]


def test_name_match_across_state_lines_is_rejected():
    e = ev("x", status="ongoing", started_at=iso(NOW - H), npdes_permit="NH0100001", water_match="name")
    st, _ = S.build(now=NOW, write=False, **world(tmp_events([e])))
    p = st["placements"]["ma-test:x"]
    assert p["water_slugs"] == [] and "another state" in p["unplaced_reason"]


def test_waters_extra_are_read_for_names_and_geometry(tmp_path, monkeypatch):
    (tmp_path / "waters-ne.json").write_text(json.dumps({"waters": [
        {"slug": "test-river-ma", "name": "Test River", "kind": "river", "state": "MA", "bbox": [-72, 42, -71.9, 42.0]}]}))
    (tmp_path / "waters-extra.json").write_text(json.dumps({"waters": [
        {"slug": "woonasquatucket-river-ri", "name": "Woonasquatucket River", "kind": "river", "state": "RI",
         "bbox": [-71.5, 41.8, -71.4, 41.9],
         "geometry": {"type": "LineString", "coordinates": [[-71.5, 41.85], [-71.4, 41.85]]}}]}))
    monkeypatch.setattr(S, "DATA_DIR", tmp_path)
    S._GEOM_CACHE.clear()
    waters = S.load_waters()
    assert waters["woonasquatucket-river-ri"]["extra"] is True and not waters["test-river-ma"].get("extra")
    r = S.Resolver(waters, [])
    e = ev("w", status="ended", water_slugs=[], npdes_permit="RI0100315", waterbody_text="WOONASQUATUCKET RIVER",
           lat=41.851, lon=-71.45, started_at=iso(NOW - H), ended_at=iso(NOW))
    pl = r.resolve(e)
    assert pl["water_slugs"] == ["woonasquatucket-river-ri"] and pl["water_match"] == "name"
    assert S.water_geometry("woonasquatucket-river-ri", waters) is not None


def test_waters_nhd_are_read_like_waters_extra(tmp_path, monkeypatch):
    """data/waters-nhd.json (ingest/waters_from_nhd.py) is read after waters-extra.json, tagged extra, its
    aliases match names and its inline geometry is the water's geometry; include_nhd=False leaves it out."""
    (tmp_path / "waters-ne.json").write_text(json.dumps({"waters": [
        {"slug": "test-river-ma", "name": "Test River", "kind": "river", "state": "MA", "bbox": [-72, 42, -71.9, 42.0]}]}))
    (tmp_path / "waters-extra.json").write_text(json.dumps({"waters": [
        {"slug": "mill-river-springfield-ma", "name": "Mill River", "kind": "river", "state": "MA", "source": "osm",
         "bbox": [-72.6, 42.0, -72.5, 42.1], "geometry": {"type": "LineString", "coordinates": [[-72.6, 42.05], [-72.5, 42.05]]}}]}))
    (tmp_path / "waters-nhd.json").write_text(json.dumps({"waters": [
        {"slug": "mill-river-springfield-ma", "name": "Mill River", "kind": "river", "state": "MA", "source": "nhd",
         "bbox": [0, 0, 0, 0], "geometry": {"type": "LineString", "coordinates": [[0, 0], [0.1, 0]]}},
        {"slug": "twomile-creek-ny", "name": "Twomile Creek", "kind": "stream", "state": "NY", "source": "nhd",
         "aliases": ["2 Mile Creek"], "bbox": [-78.92, 42.97, -78.88, 43.0], "gnis_id": "968091",
         "geometry": {"type": "LineString", "coordinates": [[-78.92, 42.98], [-78.88, 42.99]]}}]}))
    monkeypatch.setattr(S, "DATA_DIR", tmp_path)
    S._GEOM_CACHE.clear()
    waters = S.load_waters()
    assert waters["twomile-creek-ny"]["extra"] is True and waters["twomile-creek-ny"]["source"] == "nhd"
    assert waters["mill-river-springfield-ma"]["source"] == "osm"      # waters-extra keeps a shared slug
    assert "twomile-creek-ny" not in S.load_waters(include_nhd=False)
    (tmp_path / "waters-dc.json").write_text(json.dumps({"waters": [
        {"slug": "potomac-river-dc", "name": "Potomac River", "kind": "river", "state": "DC", "source": "nhd"}]}))
    assert S.load_waters()["potomac-river-dc"]["extra"] is True
    assert "potomac-river-dc" in S.load_waters(include_nhd=False)
    r = S.Resolver(waters, [])
    e = ev("t", status="ended", water_slugs=[], npdes_permit="NY0000001", waterbody_text="2 Mile Creek",
           lat=42.985, lon=-78.90, started_at=iso(NOW - H), ended_at=iso(NOW))
    pl = r.resolve(e)
    assert pl["water_slugs"] == ["twomile-creek-ny"] and pl["water_match"] == "name"
    assert S.water_geometry("twomile-creek-ny", waters) is not None


def _alias_data(tmp_path, aliases):
    """A data dir with a Springfield (extra) and a Twomile Creek (NHD) record, and data/water-aliases.json."""
    (tmp_path / "waters-ne.json").write_text(json.dumps({"waters": [
        {"slug": "test-river-ma", "name": "Test River", "kind": "river", "state": "MA", "bbox": [-72, 42, -71.9, 42.0]}]}))
    (tmp_path / "waters-extra.json").write_text(json.dumps({"waters": [
        {"slug": "mill-river-springfield-ma", "name": "Mill River", "kind": "river", "state": "MA", "source": "osm",
         "aliases": ["Mill R."], "bbox": [-72.6, 42.0, -72.5, 42.1],
         "geometry": {"type": "LineString", "coordinates": [[-72.6, 42.05], [-72.5, 42.05]]}}]}))
    (tmp_path / "waters-nhd.json").write_text(json.dumps({"waters": [
        {"slug": "otter-kill-ny", "name": "Otter Kill", "kind": "stream", "state": "NY", "source": "nhd",
         "bbox": [-74.3, 41.4, -74.2, 41.5],
         "geometry": {"type": "LineString", "coordinates": [[-74.3, 41.45], [-74.2, 41.46]]}}]}))
    if aliases is not None:
        (tmp_path / "water-aliases.json").write_text(aliases if isinstance(aliases, str) else json.dumps(aliases))


def test_hand_aliases_are_merged_into_the_records_at_load(tmp_path, monkeypatch):
    """data/water-aliases.json ({slug: [texts]}) adds to the records' own aliases (theirs first, no repeats),
    whichever file holds the record, and the resolver matches a text by them."""
    _alias_data(tmp_path, {"otter-kill-ny": ["Otterkill River"], "test-river-ma": ["The Test"],
                           "mill-river-springfield-ma": ["Mill R.", "Mill Rv Springfield"]})
    monkeypatch.setattr(S, "DATA_DIR", tmp_path)
    S._GEOM_CACHE.clear()
    waters = S.load_waters()
    assert waters["otter-kill-ny"]["aliases"] == ["Otterkill River"] and waters["otter-kill-ny"]["extra"] is True
    assert waters["test-river-ma"]["aliases"] == ["The Test"]
    assert waters["mill-river-springfield-ma"]["aliases"] == ["Mill R.", "Mill Rv Springfield"]      # no repeat of "Mill R."
    assert S.ALIAS_PROBLEMS == []
    r = S.Resolver(waters, [])
    e = ev("a", status="ended", water_slugs=[], npdes_permit="NY0000001", waterbody_text="Otterkill River",
           lat=41.455, lon=-74.25, started_at=iso(NOW - H), ended_at=iso(NOW))
    pl = r.resolve(e)
    assert pl["water_slugs"] == ["otter-kill-ny"] and pl["water_match"] == "name"
    # without the file the record has no such alias and the name does not place the report (its point still does)
    (tmp_path / "water-aliases.json").unlink()
    assert not S.load_waters()["otter-kill-ny"].get("aliases")
    assert S.Resolver(S.load_waters(), []).resolve(e)["water_match"] != "name"


def test_hand_aliases_leave_the_record_files_alone(tmp_path, monkeypatch):
    """The merge builds a copy of the record: the dict read from the file (and a second load) is not changed."""
    _alias_data(tmp_path, {"test-river-ma": ["The Test"]})
    monkeypatch.setattr(S, "DATA_DIR", tmp_path)
    first = S.load_waters()
    assert first["test-river-ma"]["aliases"] == ["The Test"]
    (tmp_path / "water-aliases.json").write_text(json.dumps({"test-river-ma": ["Other"]}))
    assert S.load_waters()["test-river-ma"]["aliases"] == ["Other"]          # not ["The Test", "Other"]
    assert json.loads((tmp_path / "waters-ne.json").read_text())["waters"][0].get("aliases") is None


def test_hand_alias_for_an_unknown_slug_is_a_build_problem_not_an_error(tmp_path, monkeypatch):
    _alias_data(tmp_path, {"no-such-water-ny": ["X Creek", "Y Creek"], "otter-kill-ny": ["Otterkill River"],
                           "test-river-ma": "not a list"})
    monkeypatch.setattr(S, "DATA_DIR", tmp_path)
    waters = S.load_waters()
    assert waters["otter-kill-ny"]["aliases"] == ["Otterkill River"]                # the rest is still applied
    assert any("no-such-water-ny is not a water record" in p and "2 alias(es) not applied" in p
               for p in S.ALIAS_PROBLEMS)
    assert any("test-river-ma" in p and "not a list" in p for p in S.ALIAS_PROBLEMS)
    # a load without the NHD records does not call their slugs unknown
    S.load_waters(include_nhd=False)
    assert not any("otter-kill-ny" in p for p in S.ALIAS_PROBLEMS) and S.ALIAS_PROBLEMS == []
    # and a build that loads the waters itself carries the problems into status.json
    st, _ = S.build(now=NOW, write=False, **{**world(tmp_events([ev("p")])), "waters": None})
    assert any("no-such-water-ny is not a water record" in p for p in st["problems"])


@pytest.mark.parametrize("text", ["{not json", "[1, 2]", "null"])
def test_a_bad_hand_alias_file_is_a_problem_and_loads_the_records_unchanged(tmp_path, monkeypatch, text):
    _alias_data(tmp_path, text)
    monkeypatch.setattr(S, "DATA_DIR", tmp_path)
    waters = S.load_waters()
    assert set(waters) == {"test-river-ma", "mill-river-springfield-ma", "otter-kill-ny"}
    assert waters["mill-river-springfield-ma"]["aliases"] == ["Mill R."]
    assert bool(S.ALIAS_PROBLEMS) == (text != "null")           # "null" is an empty file, not a problem


# ---------------------------------------------------------------- coarse records, duplicates, point advisories

def test_month_and_year_records_never_colour():
    m = ev("m", status="ended", started_at="2026-07-01", ended_at="2026-07-31", time_precision="month")
    y = ev("y", event_type="annual_total", status="ended", started_at="2025-01-01", ended_at="2025-12-31",
           time_precision="year")
    assert S.event_intervals(m, "MA", NOW) == [] and S.event_intervals(y, "MA", NOW) == []
    st, _ = S.build(now=datetime(2026, 7, 15, tzinfo=UTC), write=False, **world(tmp_events([m])))
    assert st["waters"]["test-river-ma"]["status"] == "monthly"        # its own mark, never red or yellow (§2.x)


def _echo_world(records_by_source):
    import tempfile
    d = Path(tempfile.mkdtemp())
    for sid, recs in records_by_source.items():
        (d / f"{sid}.json").write_text(json.dumps({"source_id": sid, "ok": True, "last_ok_at": iso(NOW), "meta": {},
                                                    "records": recs}))
    return world(d)


def test_echo_duplicates_prefer_the_state_notice_then_more_fields():
    day = NOW - 10 * H
    state = ev("s", status="ended", npdes_permit="MA0101613", started_at=iso(day), ended_at=iso(day + 2 * H))
    echo1 = ev("e1", source_id="echo-sewer-overflow", event_type="sso", status="ended", npdes_permit="MA0101613",
               started_at=iso(day - 2 * H), ended_at=iso(day + 3 * H), time_precision="day")   # same local day
    echo2 = ev("e2", source_id="ri-echo-dfr", event_type="bypass", status="ended", npdes_permit="RI0100072",
               started_at=iso(day), ended_at=iso(day + H), volume_gal=500, water_slugs=["test-bay-ma"])
    echo3 = ev("e3", source_id="echo-sewer-overflow", event_type="bypass", status="ended", npdes_permit="RI0100072",
               started_at=iso(day), ended_at=iso(day + H), water_slugs=["test-bay-ma"])
    w = _echo_world({"ma-test": [state], "echo-sewer-overflow": [echo1, echo3], "ri-echo-dfr": [echo2]})
    st, _ = S.build(now=NOW, write=False, **w)
    assert st["duplicates"] == {"echo-sewer-overflow:e1": "ma-test:s", "echo-sewer-overflow:e3": "ri-echo-dfr:e2"}
    assert st["placements"]["echo-sewer-overflow:e1"]["duplicate_of"] == "ma-test:s"
    reasons = st["waters"]["test-bay-ma"]["reasons"]
    assert {r["event_id"] for r in reasons} == {"ri-echo-dfr:e2"}


def test_beach_advisories_colour_small_lakes_only_and_are_points_elsewhere():
    on_bay = ev("bay", event_type="beach_advisory", status="advisory_active", started_at=iso(NOW - 5 * H),
                water_slugs=["test-bay-ma"], lat=42.05, lon=-70.95)
    on_pond = ev("pond", event_type="hab_advisory", status="advisory_active", started_at=iso(NOW - 5 * H),
                 water_slugs=["other-pond-ma"], lat=42.105, lon=-71.995)
    on_big = ev("big", event_type="hab_advisory", status="advisory_active", started_at=iso(NOW - 5 * H),
                water_slugs=["big-lake-ma"], lat=42.105, lon=-71.995)
    rain = ev("rain", event_type="rain_advisory", status="advisory_active", started_at=iso(NOW - 5 * H),
              water_slugs=["test-river-ma"], lat=42.0, lon=-71.95)
    st, _ = S.build(now=NOW, write=False, **world(tmp_events([on_bay, on_pond, on_big, rain])))
    assert st["waters"]["test-bay-ma"]["status"] == "grey"
    assert st["waters"]["other-pond-ma"]["status"] == "red"
    assert st["waters"]["big-lake-ma"]["status"] == "grey"
    assert st["waters"]["test-river-ma"]["status"] == "grey"
    pts = {p["event_id"]: p for p in st["advisory_points"]}
    assert set(pts) == {"ma-test:bay", "ma-test:big", "ma-test:rain"}
    assert pts["ma-test:bay"]["status"] == "red" and pts["ma-test:rain"]["status"] == "yellow"


# ---------------------------------------------------------------- advisory aging, withheld sources

def test_active_advisory_ages_out_after_14_days_without_confirmation():
    old = ev("old", event_type="hab_advisory", status="advisory_active", started_at=iso(NOW - timedelta(days=20)),
             source_updated_at=iso(NOW - timedelta(days=15)), water_slugs=["other-pond-ma"])
    st, _ = S.build(now=NOW, write=False, **world(tmp_events([old])))
    w = st["waters"]["other-pond-ma"]
    assert w["status"] == "grey" and w["reasons"][0]["rule"] == "not_reconfirmed"
    assert "last confirmed Jul 26; not re-confirmed" in w["reason_short"]
    fresh = ev("fresh", event_type="hab_advisory", status="advisory_active", started_at=iso(NOW - timedelta(days=20)),
               source_updated_at=iso(NOW - timedelta(days=3)))
    assert colour(fresh, NOW)[0] == "red"


def test_closures_keep_an_explicit_end_and_age_out_without_one():
    with_end = ev("e", event_type="shellfish_closure", status="advisory_active", started_at=iso(NOW - timedelta(days=30)),
                  ended_at=iso(NOW + timedelta(days=2)))
    assert colour(with_end, NOW) == ("red", ["advisory_active"])
    no_end = ev("n", event_type="beach_closure", status="advisory_active", started_at=iso(NOW - timedelta(days=15)))
    assert colour(no_end, NOW) == ("grey", ["not_reconfirmed"])
    assert colour(no_end, NOW - timedelta(days=2))[0] == "red"


def test_distribution_discouraged_files_are_withheld_unless_asked():
    d = tmp_events([])
    (d / "nh-des-swimming.json").write_text(json.dumps({
        "source_id": "nh-des-swimming", "ok": True, "last_ok_at": iso(NOW), "meta": {"distribution_discouraged": True},
        "records": [ev("b", source_id="nh-des-swimming", event_type="beach_advisory", status="advisory_active",
                       started_at=iso(NOW - H), water_slugs=["other-pond-ma"])]}))
    st, _ = S.build(now=NOW, write=False, **world(d))
    assert "other-pond-ma" not in st["waters"] and st["withheld_sources"] == ["nh-des-swimming"]
    st, _ = S.build(now=NOW, write=False, include_restricted=True, **world(d))
    assert st["waters"]["other-pond-ma"]["status"] == "red" and st["restricted_included"] is True


# ---------------------------------------------------------------- advisory windows (data/rules.json)

RIVER = {"slug": "test-river-ma", "kind": "river", "state": "MA"}
POND = {"slug": "other-pond-ma", "kind": "pond", "state": "MA"}


def ended(rid="w", hours_ago=0, **kw):
    end = NOW - hours_ago * H
    return ev(rid, status="ended", started_at=iso(end - 2 * H), ended_at=iso(end), **kw)


def at(e, t, water, state="MA"):
    c, ivs = S.status_at(S.event_intervals(e, state, NOW, water=water), t)
    return c, [iv["rule"] for iv in ivs]


def test_yellow_default_level():
    e = ended(event_type="sso")                      # no by_event_type entry for sso in TEST_RULES
    r = S.yellow_rule_for(e, RIVER, TEST_RULES)
    assert r["rule"] == "yellow.default" and r["hours"] == 72
    assert at(e, NOW + 60 * H, RIVER) == ("yellow", ["caution"])
    assert at(e, NOW + 73 * H, RIVER)[0] == "grey"


def test_yellow_by_event_type_level():
    e = ended(event_type="blended")                  # 48 h: no caution beyond MA's 48 h red
    r = S.yellow_rule_for(e, RIVER, TEST_RULES)
    assert r["rule"] == "yellow.by_event_type.blended" and r["hours"] == 48
    assert at(e, NOW + 47 * H, RIVER)[0] == "red"
    assert at(e, NOW + 49 * H, RIVER)[0] == "grey"


def test_yellow_by_water_kind_level_and_advisories_follow_the_authority():
    e = ended(event_type="cso")
    r = S.yellow_rule_for(e, POND, TEST_RULES)
    assert r["rule"] == "yellow.by_water_kind.pond" and r["hours"] == 96
    assert at(e, NOW + 90 * H, POND) == ("yellow", ["caution"])
    assert at(e, NOW + 97 * H, POND)[0] == "grey"
    hab = ev("h", event_type="hab_advisory", status="advisory_lifted", started_at=iso(NOW - 9 * H), ended_at=iso(NOW))
    assert S.yellow_rule_for(hab, POND, TEST_RULES)["rule"] == "yellow.by_event_type.hab_advisory"
    assert at(hab, NOW + H, POND)[0] == "grey"


def test_yellow_by_water_level_and_disabled_entries():
    rules = json.loads(json.dumps(TEST_RULES))
    rules["yellow"]["by_water"]["test-river-ma"] = {"hours": 120, "rationale": "sampling series", "source": "x"}
    e = ended(event_type="cso")
    r = S.yellow_rule_for(e, RIVER, rules)
    assert r["rule"] == "yellow.by_water.test-river-ma" and r["hours"] == 120
    c, _ = S.status_at(S.event_intervals(e, "MA", NOW, water=RIVER, rules=rules), NOW + 100 * H)
    assert c == "yellow"
    rules["yellow"]["by_water"]["test-river-ma"]["enabled"] = False
    assert S.yellow_rule_for(e, RIVER, rules)["rule"] == "yellow.by_event_type.cso"
    assert S.yellow_rule_for(e, {"slug": "_example", "kind": "river"}, rules)["rule"] == "yellow.by_event_type.cso"


def test_red_by_state_levels_and_event_window():
    e = ended(event_type="cso")
    nh = S.red_rule_for(e, "NH", TEST_RULES)
    assert nh["rule"] == "red.by_state.NH" and nh["hours"] == 72
    assert at(e, NOW + 70 * H, RIVER, state="NH") == ("red", ["authority_window"])
    me = S.red_rule_for(e, "ME", TEST_RULES)
    assert me["rule"] == "red.by_state.ME" and me["hours"] is None
    assert at(e, NOW + H, RIVER, state="ME") == ("yellow", ["caution"])     # red only while it ran
    assert S.red_rule_for(e, "PA", TEST_RULES)["rule"] == "red.none"
    stated = ended(event_type="cso", advice_window_hours=24, advice_window_basis="notice: 24 hours")
    assert S.red_rule_for(stated, "MA", TEST_RULES)["rule"] == "red.event"


def test_water_status_records_the_rules_applied():
    on_pond = ended("p", hours_ago=60, event_type="cso", water_slugs=["other-pond-ma"])
    st, _ = S.build(now=NOW, write=False, **world(tmp_events([on_pond])))
    w = st["waters"]["other-pond-ma"]
    assert w["status"] == "yellow"
    assert w["yellow_rule"]["rule"] == "yellow.by_water_kind.pond" and w["yellow_rule"]["hours"] == 96
    assert w["yellow_rule"]["applied"] is True and w["yellow_rule"]["rationale"] == "still water"
    assert w["red_rule"]["rule"] == "red.by_state.MA" and w["red_rule"]["hours"] == 48
    assert w["reasons"][0]["yellow_rule"]["rule"] == "yellow.by_water_kind.pond"
    grey = ended("g", hours_ago=500, event_type="cso")
    st, _ = S.build(now=NOW, write=False, **world(tmp_events([grey])))
    g = st["waters"]["test-river-ma"]
    assert g["status"] == "grey" and g["yellow_rule"]["applied"] is False
    assert g["yellow_rule"]["rule"] == "yellow.by_event_type.cso"


# ---------------------------------------------------------------- modeled reaches (build/reaches.py)

from build import reaches as R  # noqa: E402


def fl(comid, x0, x1, y=42.0):
    return {"comid": comid, "coords": [[x0, y], [x1, y]]}      # along a parallel: ~82.7 km per degree at 42N


def attrs(comid, hydroseq, tidal=0, wb=0, ftype=None):
    return {"comid": comid, "hydroseq": hydroseq, "tidal": tidal, "wbareacomid": wb, "wbarea_ftype": ftype,
            "totdasqkm": 25000, "qe_ma": 18000, "slope": 2.6e-4, "gnis_name": "Test River"}


def test_reach_cuts_at_tidal_lake_estuary_and_the_cap():
    lines = [fl(1, -72.0, -71.9), fl(2, -71.9, -71.8), fl(3, -71.8, -71.7)]
    segs, why = R.build_segments(lines, {1: attrs(1, 30), 2: attrs(2, 20, tidal=1), 3: attrs(3, 10)}, 40)
    assert why == "tidal" and [x["comid"] for x in segs] == [1]
    segs, why = R.build_segments(lines, {1: attrs(1, 30), 2: attrs(2, 20, wb=99, ftype=436), 3: attrs(3, 10)}, 40)
    assert why == "lake_or_reservoir" and len(segs) == 1
    segs, why = R.build_segments(lines, {1: attrs(1, 30), 2: attrs(2, 20, wb=99, ftype=493), 3: attrs(3, 10)}, 40)
    assert why == "estuary"
    segs, why = R.build_segments(lines, {1: attrs(1, 30, tidal=1), 2: attrs(2, 20), 3: attrs(3, 10)}, 40)
    assert why == "tidal_at_outfall" and segs == []
    segs, why = R.build_segments(lines, {1: attrs(1, 30), 2: attrs(2, 20), 3: attrs(3, 10)}, 12)
    assert why == "cap_km" and abs(segs[-1]["km_end"] - 12) < 0.01 and len(segs) == 2
    # NLDI order is not trusted: hydroseq (upstream first) orders the flowlines
    segs, why = R.build_segments(list(reversed(lines)), {1: attrs(1, 30), 2: attrs(2, 20), 3: attrs(3, 10)}, 40)
    assert [x["comid"] for x in segs] == [1, 2, 3] and why == "end_of_trace"


def test_jobson_matches_the_springfield_worked_example():
    # downstream-approach.md 5.4: Thompsonville DA 25,019 km2, Qa 18,254 cfs, slope 2.56e-4;
    # downtown outfall 013 to the state line 8.6 km: ~5.0 h (3.0) at 6,920 cfs, ~2.6 h (1.7) at 30,000 cfs
    vp, vmp = R.jobson(25019.3, 18254, 6920, 2.5568e-4)
    assert round(vp, 2) == 0.48 and round(vmp, 2) == 0.78
    assert round(8570 / vp / 3600, 1) == 5.0 and round(8570 / vmp / 3600, 1) == 3.0
    vp, vmp = R.jobson(25019.3, 18254, 30000, 2.5568e-4)
    assert round(8570 / vp / 3600, 1) == 2.6 and round(8570 / vmp / 3600, 1) == 1.7
    # travel(): cumulative, leading edge 0.89 x peak, flow scaled by Q/Qa per flowline
    segs = [{"km_start": 0, "km_end": 8.57, "totdasqkm": 25019.3, "qe_ma": 18254, "slope": 2.5568e-4}]
    t = R.travel(segs, 6920 / 18254)[0]
    assert round(t["hours_typical"], 1) == 5.0 and round(t["hours_fast"], 1) == 3.0
    assert t["hours_leading_edge"] == round(0.89 * t["hours_typical"], 2)


def _reach(key="MA0101613-13", slug="test-river-ma"):
    return {"key": key, "permit": "MA0101613", "outfall": "013", "water_slug": slug, "lat": 42.0, "lon": -72.0,
            "river": "Test River", "cut_reason": "cap_km", "length_km": 8.3,
            "segments": [{"comid": 1, "km_start": 0.0, "km_end": 8.3, "totdasqkm": 25000, "qe_ma": 18000,
                          "slope": 2.6e-4, "gnis_name": "Test River", "coords": [[-72.0, 42.0], [-71.9, 42.0]]}]}


def test_river_status_comes_from_its_modeled_reach():
    e = ev("r", status="ongoing", started_at=iso(NOW - 2 * H), npdes_permit="MA0101613", outfall_id="SPR013")
    w = world(tmp_events([e]))
    w["reaches"] = {"MA0101613-13": _reach()}
    gauges = {"rivers": {"Test River": [{"id": "USGS-1", "site": "1", "name": "gauge", "lat": 42.0, "lon": -71.95,
                                         "qe_ma_cfs": 18000}]}}
    latest = {"sites": {"USGS-1": {"value": 9000.0, "time": iso(NOW - H)}}}
    w["flows"] = (gauges, latest)
    st, hist = S.build(now=NOW, write=False, **w)
    river = st["waters"]["test-river-ma"]
    assert river["status"] == "red" and river["fill"] is False and river["status_basis"] == "modeled reaches"
    assert river["summary"] == "part of this water is on a modeled reach" and river["reaches"] == ["MA0101613-13"]
    assert river["reasons"][0]["placement"] == "reach"
    assert st["reaches"]["MA0101613-13"]["status"] == "red"
    a = st["reach_events_active"][0]
    assert a["event_id"] == "ma-test:r" and a["gauge"] == "USGS-1" and a["flow_cfs"] == 9000.0
    assert a["segments"][0]["hours_typical"] > a["segments"][0]["hours_fast"] > 0
    assert hist["reaches"]["MA0101613-13"][-1] == "r"


def test_river_event_without_a_reach_is_unmodeled_and_bays_are_not_filled():
    e = ev("n", status="ongoing", started_at=iso(NOW - 2 * H))
    b = ev("b", status="ongoing", started_at=iso(NOW - 2 * H), water_slugs=["test-bay-ma"])
    p = ev("p", status="ongoing", started_at=iso(NOW - 2 * H), water_slugs=["other-pond-ma"])
    st, _ = S.build(now=NOW, write=False, **world(tmp_events([e, b, p])))
    assert st["waters"]["test-river-ma"]["reasons"][0]["placement"] == "unmodeled"
    assert "downstream path not modeled" in st["waters"]["test-river-ma"]["reason_short"]
    bay = st["waters"]["test-bay-ma"]
    assert bay["fill"] is False and "tidal or estuary: movement not modeled" in bay["reason_short"]
    assert st["waters"]["other-pond-ma"]["fill"] is True and st["waters"]["other-pond-ma"]["status"] == "red"


def test_reach_features_carry_the_band_and_the_section_4_label(monkeypatch):
    from export import build as X
    r = _reach()
    monkeypatch.setattr(R, "load_reaches", lambda: {r["key"]: r})
    monkeypatch.setattr(R, "cap_km", lambda rules=None: 40.0)
    seg = {"i": 0, "km_start": 0.0, "km_end": 8.3, "hours_typical_start": 0, "hours_typical": 4.8,
           "hours_fast_start": 0, "hours_fast": 2.9, "hours_leading_edge": 4.27, "reached_fast": True,
           "reached_typical": False}
    st = {"reach_events_active": [{"event_id": "ma-test:r", "reach": r["key"], "status": "red", "rule": "ongoing",
                                   "short": "CSO ongoing", "hours_since_start": 3.0, "gauge": "USGS-1",
                                   "gauge_name": "Test gauge", "flow_cfs": 9000.0, "flow_time": "2026-08-10T11:00Z",
                                   "flow_basis": "x", "segments": [seg]}],
          "reaches": {r["key"]: {"status": "red"}}}
    feats, paths = X.reach_features(st, {"ma-test:r": {"started_at": iso(NOW - 3 * H)}})
    segf = [f for f in feats if f["properties"]["feature"] == "segment"][0]["properties"]
    assert segf["arrival_hours_typical"] == 4.8 and segf["arrival_hours_fast"] == 2.9 and segf["km_from_outfall"] == 8.3
    assert "would typically reach here in about 5 hours (it could be as soon as about 3 hours)" in segf["label"]
    assert "Test gauge (9000 cfs)" in segf["label"] and "not necessarily safe outside the line" in segf["label"]
    stop = [f for f in feats if f["properties"]["feature"] == "stop"][0]["properties"]
    assert stop["label"].startswith("Model stops here (40 km")
    assert paths[0]["properties"]["status"] == "red" and paths[0]["geometry"]["type"] == "MultiLineString"


def test_a_sewer_break_is_traced_from_its_own_point():
    e = ev("brk", status="ongoing", started_at=iso(NOW - 2 * H), lat=42.0, lon=-71.99)
    w = world(tmp_events([e]))
    st, _ = S.build(now=NOW, write=False, **w)
    assert st["needs_reach"][0]["event_id"] == "ma-test:brk"
    r = {**_reach("pt-abc"), "permit": None, "outfall": None, "event_ids": ["ma-test:brk"]}
    w = world(tmp_events([e]))
    w["reaches"] = {"pt-abc": r}
    st, _ = S.build(now=NOW, write=False, **w)
    assert st["waters"]["test-river-ma"]["reasons"][0]["placement"] == "reach" and st["needs_reach"] == []


def test_an_ingesters_duplicate_of_is_honoured():
    dash = ev("dash", status="ended", started_at=iso(NOW - 300 * H), ended_at=iso(NOW - 299 * H))
    sheet = ev("sheet", status="ongoing", started_at=iso(NOW - 2 * H), duplicate_of="ma-test:dash")
    st, _ = S.build(now=NOW, write=False, **world(tmp_events([dash, sheet])))
    w = st["waters"]["test-river-ma"]
    assert w["status"] == "grey" and "ma-test:sheet" in w["events"]          # kept in the history, no colour
    assert st["duplicates"]["ma-test:sheet"] == "ma-test:dash" and st["counts"]["duplicates"] == 1


def test_a_reach_does_not_flag_a_tributary_at_its_mouth():
    trib = {"slug": "trib-river-ma", "name": "Trib River", "kind": "river", "state": "MA",
            "bbox": [-71.96, 42.0, -71.94, 42.02],
            "geometry": {"type": "LineString", "coordinates": [[-71.95, 42.02], [-71.95, 42.0001]]}}
    w = world(tmp_events([]))
    waters = {**w["waters"], "trib-river-ma": trib}
    named = _reach("k1")
    named["segments"][0]["coords"] = [[-72.0, 42.0], [-71.95, 42.0], [-71.9, 42.0]]   # midpoint at the mouth
    assert S.reach_waters(named, waters) == ["test-river-ma"]
    unnamed = _reach("k2")
    unnamed["segments"][0]["coords"] = named["segments"][0]["coords"]
    unnamed["segments"][0]["gnis_name"] = None
    assert set(S.reach_waters(unnamed, waters)) == {"test-river-ma", "trib-river-ma"}


# ---------------------------------------------------------------- ECHO duplicates and dry-land records (GA review P2-11)

def _same_day(day, **state_kw):
    st = ev("s", source_id="ga-epd-spills", event_type="sso", status="ended", npdes_permit="GA0000001",
            started_at=iso(day), ended_at=iso(day + 2 * H), volume_gal=1200, **state_kw)
    epa = ev("e1", source_id="echo-sewer-overflow", event_type="sso", status="ended", npdes_permit="GA0000001",
             started_at=iso(day + H), ended_at=iso(day + 2 * H), waterbody_text="Test Creek")
    return st, epa


def test_a_dry_land_state_record_does_not_absorb_an_epa_report_that_names_a_water():
    """A report that reached a water never loses its colour to a same-day record of the permit saying it did not:
    the dry-land record is the duplicate, EPA's report stays primary."""
    day = NOW - 10 * H
    for flag in ({"raw": {"reached_water": False}},                                # GA EPD
                 {"raw": {"Reach Waterbody": "No"}},                               # CT DEEP
                 {"raw": {"row": {"surfaceWater": "No"}}},                         # NY Sewage Pollution Right to Know
                 {"raw": {"report": {"water_threatened": "N"}}},                   # VA DEQ
                 {"raw": {"_water": {"why_none": "receiving water given as 'none': no surface water named "
                                                 "(decision 3)"}}},              # MD MDE
                 {"waterbody_text": "Did not reach state waters"}):               # any state's own words
        st, epa = _same_day(day, **flag)
        assert S.find_duplicates([st, epa]) == {st["event_id"]: epa["event_id"]}, flag
    st, epa = _same_day(day, raw={"reached_water": False})
    st["outfall_id"], epa["outfall_id"] = "001", "002"          # different outfalls: two discharges, no link
    assert S.find_duplicates([st, epa]) == {}


def test_a_state_record_and_an_epa_report_naming_different_waters_are_not_linked():
    day = NOW - 10 * H
    st, epa = _same_day(day, waterbody_text="Other Creek")
    assert S.find_duplicates([st, epa]) == {}
    for same in ("Test Creek", "unnamed tributary to Test Creek", "UT to Test Cr", "creek",
                 "sewage left the manhole near the bridge and ran down the hill toward the river"):
        st, epa = _same_day(day, waterbody_text=same)
        assert S.find_duplicates([st, epa]) == {epa["event_id"]: st["event_id"]}, same
    st, epa = _same_day(day, waterbody_text="Mill River")
    epa["waterbody_text"] = "Test Creek; Mill River"             # EPA names two, one is the state's
    assert S.find_duplicates([st, epa]) == {epa["event_id"]: st["event_id"]}


def test_a_dry_land_record_beside_an_epa_report_keeps_the_water_coloured():
    day = NOW - 10 * H
    st = ev("s", status="ended", event_type="sso", npdes_permit="MA0101613", started_at=iso(day),
            ended_at=iso(day + 2 * H), raw={"Reach Waterbody": "No"}, water_slugs=[])
    epa = ev("e1", source_id="echo-sewer-overflow", event_type="sso", status="ended", npdes_permit="MA0101613",
             started_at=iso(day + H), ended_at=iso(day + 2 * H), waterbody_text="Test River",
             water_slugs=["test-river-ma"])
    w = _echo_world({"ma-test": [st], "echo-sewer-overflow": [epa]})
    out, _ = S.build(now=NOW, write=False, **w)
    assert out["duplicates"] == {"ma-test:s": "echo-sewer-overflow:e1"}
    assert out["waters"]["test-river-ma"]["status"] == "red"
    assert {r["event_id"] for r in out["waters"]["test-river-ma"]["reasons"]} == {"echo-sewer-overflow:e1"}


# ---------------------------------------------------------------- an end far after the fetch (re-check R6)

BOUND_RULES = {**TEST_RULES, "unresolved": {**TEST_RULES["unresolved"], "implausible_end": {
    "days_after_fetch": 7, "rationale": "an end more than 7 days after we read the report is not used"}}}


def test_an_end_years_after_the_fetch_is_not_quoted_as_a_red_window(monkeypatch):
    """A mistyped year (2036 for 2026) is not red for ten years: the end is not used, the record follows the rules
    for one with no end (yellow 14 days from its report time, then unresolved to day 30), and the published value
    stays in the record and on the interval with the reason."""
    monkeypatch.setattr(S, "_RULES", BOUND_RULES)
    start = NOW - 2 * H
    e = ev(status="ended", event_type="sso", started_at=iso(start), ended_at="2036-08-10T11:00:00+00:00",
           fetched_at=iso(NOW - H), published_at=iso(NOW - H))
    assert colour(e, NOW)[0] == "yellow" and colour(e, NOW)[1] == ["no_end"]
    assert colour(e, NOW + timedelta(days=20))[0] == "unresolved"
    assert colour(e, NOW + timedelta(days=31))[0] is None or colour(e, NOW + timedelta(days=31))[0] == "grey"
    assert colour(e, NOW + timedelta(days=400))[0] in (None, "grey")
    ivs = S.event_intervals(e, "MA", NOW)
    assert all(iv["end_not_used"]["published_end"] == "2036-08-10T11:00:00+00:00" for iv in ivs)
    assert all(iv["end_not_used"]["rule"] == "unresolved.implausible_end" for iv in ivs)
    assert "more than 7 days after the report was read" in ivs[0]["end_not_used"]["why"]
    assert e["ended_at"] == "2036-08-10T11:00:00+00:00"
    # ongoing with that end: red for its 7 days, then unresolved (the source's own status, no confirmed end)
    o = {**e, "status": "ongoing"}
    assert colour(o, NOW)[0] == "red" and colour(o, NOW + timedelta(days=8))[0] == "unresolved"


def test_an_end_within_the_bound_and_an_advisorys_long_end_are_quoted(monkeypatch):
    monkeypatch.setattr(S, "_RULES", BOUND_RULES)
    soon = ev(status="ongoing", started_at=iso(NOW - 2 * H), ended_at=iso(NOW + timedelta(days=6)),
              fetched_at=iso(NOW - H))
    assert colour(soon, NOW + timedelta(days=5)) == ("red", ["discharge"])
    assert not any("end_not_used" in iv for iv in S.event_intervals(soon, "MA", NOW))
    closure = ev(event_type="shellfish_closure", status="advisory_active", started_at=iso(NOW - 2 * H),
                 ended_at=iso(NOW + timedelta(days=200)), fetched_at=iso(NOW - H), water_slugs=["other-pond-ma"])
    assert colour(closure, NOW + timedelta(days=100))[0] == "red"
    # the fetch time, not the build time, is what the end is measured from
    late = ev(status="ended", started_at=iso(NOW - 30 * H), ended_at=iso(NOW - 20 * H),
              fetched_at=iso(NOW - timedelta(days=60)))
    assert S.end_not_credible(late, NOW, BOUND_RULES) is not None
    assert S.end_not_credible({**late, "fetched_at": iso(NOW - 25 * H)}, NOW, BOUND_RULES) is None


def test_an_end_before_the_start_or_far_ahead_is_noted_and_the_build_shows_no_window(monkeypatch):
    monkeypatch.setattr(S, "_RULES", BOUND_RULES)
    ahead = ev("ahead", status="unknown", event_type="sso", started_at=iso(NOW - 3 * H),
               ended_at="2036-08-10T11:00:00+00:00", fetched_at=iso(NOW - H))
    before = ev("before", status="ended", event_type="sso", started_at=iso(NOW - 3 * H), ended_at=iso(NOW - 5 * H),
                fetched_at=iso(NOW - H), water_slugs=["other-pond-ma"])
    st, _ = S.build(now=NOW, write=False, rules=BOUND_RULES, **world(tmp_events([ahead, before])))
    pa, pb = st["placements"]["ma-test:ahead"], st["placements"]["ma-test:before"]
    assert "is more than 7 days after the report was read" in pa["validation_error"]
    assert "is before started_at" in pb["validation_error"]
    r = st["waters"]["test-river-ma"]["reasons"][0]
    assert st["waters"]["test-river-ma"]["status"] == "yellow" and r["rule"] == "no_end"
    assert r["end_not_used"]["published_end"] == "2036-08-10T11:00:00+00:00" and "published end not used" in r["short"]
    # thirty days on, the site assumes the discharge ended, as for any record with no end
    later = NOW + timedelta(days=31)
    st2, _ = S.build(now=later, write=False, rules=BOUND_RULES, **world(tmp_events([ahead])))
    assert st2["placements"]["ma-test:ahead"].get("end_assumed_at")
    note = st2["placements"]["ma-test:ahead"]["note"]
    assert "the published end (2036-08-10T11:00:00+00:00) is not used" in note and "never reported" not in note
    assert st2["waters"]["test-river-ma"]["status"] == "grey"


def test_charts_do_not_count_red_days_from_an_end_not_used(monkeypatch):
    """The charts cap a long event at 31 days; an end not used is not capped into a credible one."""
    from collections import Counter
    from build import charts as C
    monkeypatch.setattr(S, "_RULES", BOUND_RULES)
    start = NOW - timedelta(days=30)
    e = ev(status="ended", started_at=iso(start), ended_at="2036-08-10T11:00:00+00:00", fetched_at=iso(NOW - H))
    reds = C.red_intervals(e, "MA", NOW, Counter(), rules=BOUND_RULES)
    assert sum((z - a for a, z in reds), timedelta()) == timedelta(0)


def test_a_state_record_that_names_no_water_does_not_absorb_an_epa_report_of_a_water():
    """A same-day state record whose receiving water is only a placeholder, the ground or a storm drain (no water
    named: no_receiving_water) colours nothing; an EPA report of the permit that names a water is not made its
    duplicate, or the water would lose its colour. The state record is the duplicate instead."""
    day = NOW - 10 * H
    for text in ("Storm drain", "N/A", "ground", "Unknown"):
        st, epa = _same_day(day, waterbody_text=text)
        assert S.find_duplicates([st, epa]) == {st["event_id"]: epa["event_id"]}, text
    st, epa = _same_day(day, waterbody_text="storm drain to Test Creek")       # names the water: the state wins
    assert S.find_duplicates([st, epa]) == {epa["event_id"]: st["event_id"]}
    st, epa = _same_day(day)                                                     # gives no water text at all
    assert S.find_duplicates([st, epa]) == {epa["event_id"]: st["event_id"]}


def test_a_month_or_year_record_for_a_period_not_yet_over_has_no_time_problem(monkeypatch):
    """A month or year record ends at the period's end by construction: an end after the fetch is not a typing
    error and puts no validation error on the record."""
    monkeypatch.setattr(S, "_RULES", BOUND_RULES)
    m = ev(status="ended", event_type="cso", started_at="2026-08-01T00:00:00-04:00", ended_at="2026-08-31T23:59:00-04:00",
           time_precision="month", fetched_at=iso(NOW - H))
    y = ev(status="ended", event_type="annual_total", started_at="2026-01-01", ended_at="2026-12-31",
           time_precision="year", fetched_at=iso(NOW - H))
    for e in (m, y):
        assert S.end_not_credible(e, NOW, BOUND_RULES) is None and S.time_problem(e, NOW, BOUND_RULES) is None


def test_a_planned_window_of_some_weeks_keeps_the_authoritys_end():
    """A notice of a planned bypass from today to three weeks on (notification pages read the window from the text)
    is the authority's own window: red to its end, not the site's caution until the read comes within the bound.
    The bound in data/rules.json catches a mistyped year, not a window of some weeks."""
    rules = json.loads((S.DATA_DIR / "rules.json").read_text())
    start = NOW - 2 * H
    e = ev(status="ended", event_type="bypass", started_at=iso(start), ended_at=iso(start + timedelta(days=21)),
           time_precision="minute", fetched_at=iso(NOW - H))
    ivs = S.event_intervals(e, "PA", NOW, None, rules)
    assert ivs[0]["rule"] == "discharge" and not any("end_not_used" in iv for iv in ivs)
    assert S.end_not_credible({**e, "ended_at": "2036-08-10T11:00:00+00:00"}, NOW, rules)
