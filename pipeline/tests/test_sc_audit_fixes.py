"""South Carolina's final go-live audit (2026-11-15): a bloom watch listed only in DES's table gets a marker at its
water's record point (P2-1); Florence's advice records are not counted as reports (P2-3); EPA's overflow tables read
South Carolina's rows and leave every other state's records unchanged (P2-4); the state text quotes DES's layer title
(P1-1). Invented data only. No network."""
import copy
import json
import tempfile
from datetime import datetime
from pathlib import Path

from ingest import echo_sewer_overflow_events as E
from ingest import sc_des_advisories as A
from ingest import sc_florence_sso as F

ROOT = Path(__file__).resolve().parents[2]
FIX = Path(__file__).resolve().parent / "fixtures"
T0 = "2026-07-05T12:00:00Z"


def _status(records_by_source, waters, now, monkeypatch):
    from build import status as S
    from tests.test_status import TEST_RULES
    monkeypatch.setattr(S, "_RULES", TEST_RULES)
    S._GEOM_CACHE.clear()
    S._REACH_WATERS.clear()
    d = Path(tempfile.mkdtemp())
    for sid, recs in records_by_source.items():
        (d / f"{sid}.json").write_text(json.dumps({"source_id": sid, "ok": True, "last_ok_at": T0, "meta": {},
                                                   "records": copy.deepcopy(recs)}))
    st, _ = S.build(now=datetime.fromisoformat(now), write=False, events_dir=d, waters=waters, outfalls=[],
                    registry={}, reaches={}, flows=({}, {}), rules=TEST_RULES, placement_cache=None)
    return st


LAKE = {"slug": "lake-example-sc", "name": "Lake Example", "kind": "reservoir", "state": "SC",
        "bbox": [-81.2, 34.0, -81.0, 34.2],
        "geometry": {"type": "Polygon", "coordinates": [[[-81.2, 34.0], [-81.0, 34.0], [-81.0, 34.2], [-81.2, 34.2],
                                                         [-81.2, 34.0]]]}}


def test_a_table_only_bloom_watch_gets_one_red_marker_at_its_waters_record_point(monkeypatch):
    from build import status as S
    row = {"level": "Watch", "area": "Example Cove", "water": "Lake Example", "issued": "07/04/2026"}
    recs, _, _ = A.hab_records([], [row], {}, T0)
    assert len(recs) == 1 and recs[0]["lat"] is None and recs[0]["raw"]["_point_extent_only"] is True
    recs[0]["water_slugs"] = ["lake-example-sc"]
    st = _status({A.HAB_ID: recs}, {"lake-example-sc": LAKE}, "2026-07-06T12:00:00+00:00", monkeypatch)
    lake = st["waters"]["lake-example-sc"]
    assert recs[0]["event_id"] in lake["events"] and lake["status"] == "grey"     # listed, never filled whole
    pts = [p for p in st["advisory_points"] if p["event_id"] == recs[0]["event_id"]]
    assert len(pts) == 1
    p = pts[0]
    assert p["status"] == "red" and p["water_slugs"] == ["lake-example-sc"]
    assert p["point_basis"] == S.TABLE_RECORD_POINT_BASIS and "no delineation" in p["point_basis"]
    assert 34.0 <= p["lat"] <= 34.2 and -81.2 <= p["lon"] <= -81.0                  # on the water's own record


def test_florences_advice_records_stay_unmapped(monkeypatch):
    nid, title, paras = F.article((FIX / "sc" / "florence_notice.html").read_text())
    parsed = F.parse_notice(title, paras)
    st = {"notices": {}}
    F.update_notice(st, "/news/x", nid, parsed, "2025-08-16T12:00:00Z")
    recs = F.records(st, "2025-08-16T12:00:00Z")
    advice = [r for r in recs if (r.get("raw") or {}).get("_advice_not_a_discharge")]
    assert advice
    creek = {"slug": "jeffries-creek-sc", "name": "Jeffries Creek", "kind": "stream", "state": "SC",
             "bbox": [-79.80, 34.15, -79.70, 34.20],
             "geometry": {"type": "LineString", "coordinates": [[-79.80, 34.15], [-79.75, 34.18], [-79.70, 34.20]]}}
    out = _status({F.SOURCE_ID: recs}, {"jeffries-creek-sc": creek}, "2025-08-20T12:00:00+00:00", monkeypatch)
    marked = {p["event_id"] for p in out["advisory_points"]}
    assert not marked & {r["event_id"] for r in advice}


def _cov(events):
    from export import coverage as C
    feeds = [{"source_id": "sc-florence-sso", "registry_ids": ["sc-florence-sso"]}]
    reg = [{"id": "sc-florence-sso", "level": "operator", "states": ["SC"], "event_types": ["sso"]}]
    return C.coverage(events, [], feeds, reg, [], {}, "2026-11-15T12:00:00Z")["states"]["SC"]


def test_an_advice_notice_is_not_counted_as_a_report():
    overflow = {"event_id": "sc-florence-sso:9999", "source_id": "sc-florence-sso", "event_type": "sso",
                "status": "unknown", "started_at": None, "ended_at": None, "time_precision": None,
                "published_at": "2026-10-14T12:00:00-04:00", "reported_at": "2026-10-13", "raw": {"state": "SC"},
                "water_slugs": []}
    advice = {**overflow, "event_id": "sc-florence-sso:9999-advice", "status": "advisory_active",
              "started_at": "2026-10-14", "time_precision": "day",
              "raw": {"state": "SC", "_advice_not_a_discharge": True, "overflow_record": "sc-florence-sso:9999"}}
    alone = _cov([copy.deepcopy(overflow)])
    both = _cov([copy.deepcopy(overflow), copy.deepcopy(advice)])
    assert both["records_12m"] == alone["records_12m"] == 1
    assert both["dated"] == alone["dated"] and both["dated_share"] == alone["dated_share"]


def _sc_tables():
    t = {k: v for k, v in json.loads((FIX / "mn" / "sobe_rows.json").read_text()).items() if isinstance(v, list)}
    t = json.loads(json.dumps(t).replace("MN0061310", "SC0020010"))
    for w in t["waters"]:
        w["name_receiving_water"] = "Example Creek"
    return t


def test_epa_reads_a_south_carolina_row():
    recs = E.build(_sc_tables(), {"extract_date": "2026-11-13"})[0]
    assert len(recs) == 1 and recs[0]["npdes_permit"] == "SC0020010"


def test_adding_south_carolina_leaves_other_states_records_unchanged(monkeypatch):
    ut = {k: v for k, v in json.loads((FIX / "ut" / "sobe_rows.json").read_text()).items() if isinstance(v, list)}
    mn = {k: v for k, v in json.loads((FIX / "mn" / "sobe_rows.json").read_text()).items() if isinstance(v, list)}

    def strip(rs):
        return [{k: v for k, v in r.items() if k != "fetched_at"} for r in rs]
    with_sc = [strip(E.build(copy.deepcopy(t), {"extract_date": "2026-11-04"})[0]) for t in (ut, mn)]
    monkeypatch.setattr(E, "STATES", E.STATES - {"SC"})
    without = [strip(E.build(copy.deepcopy(t), {"extract_date": "2026-11-04"})[0]) for t in (ut, mn)]
    assert with_sc == without and all(with_sc)
    assert not E.build(_sc_tables(), {"extract_date": "2026-11-13"})[0]          # SC out: its row is not read


def test_the_state_text_quotes_the_departments_layer_title():
    t = (ROOT / "research" / "sc" / "state-text.md").read_text()
    assert 'map layer titled "Swimming Advisory" lists 23 river and lake sites' in t
    assert "a site on that list is not a water found safe" in t
    assert "freshwater swimming sites" not in t
