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
    # the sites are now shown as DES's listing (fix/sc-swimming-advisories): the title is still DES's own
    assert 'map layer titled "Swimming Advisory" listed 23 river and lake sites' in t
    assert "not coloured here" not in t
    assert "freshwater swimming sites" not in t


# ---------------------------------------------------------------- P2-2: records lying on other records (REMAINDER_ON)

def _lake_existing():
    lake = [[-81.05, 35.0], [-80.95, 35.0], [-80.95, 35.1], [-81.05, 35.1], [-81.05, 35.0]]
    return {"example-lake-xx": {"slug": "example-lake-xx", "name": "Example Lake", "kind": "reservoir", "state": "SC",
                                "geometry": {"type": "Polygon", "coordinates": [lake]}},
            "example-river-xx": {"slug": "example-river-xx", "name": "Example River", "kind": "river", "state": "SC",
                                 "geometry": {"type": "LineString", "coordinates": [[-82.0, 34.0], [-82.0, 34.45]]}}}


def _nhd_rulings_setup(monkeypatch, tmp_path, rulings):
    from build import status as S
    from ingest import waters_from_nhd as N
    S._GEOM_CACHE.clear()
    monkeypatch.setattr(S, "OBL_WATER_DIR", tmp_path / "none")
    monkeypatch.setattr(N, "REMAINDER_ON", rulings)
    return N


def test_a_river_drawn_through_a_reservoir_is_dropped_and_its_rows_go_to_the_lake(monkeypatch, tmp_path):
    N = _nhd_rulings_setup(monkeypatch, tmp_path, {("SC", 555): {"to": "example-lake-xx", "on": ["example-lake-xx"],
                                                                  "why": "invented"}})
    # no covers_part_of: an NHD record of its own, lying through the lake
    rows = [{"slug": "example-creek-sc", "name": "Example Creek", "kind": "river", "state": "SC", "gnis_id": "555",
             "geometry": {"type": "LineString", "coordinates": [[-81.0, 35.01], [-81.0, 35.09]]}},
            {"slug": "other-creek-sc", "name": "Other Creek", "kind": "river", "state": "SC", "gnis_id": "556",
             "geometry": {"type": "LineString", "coordinates": [[-81.0, 35.01], [-81.0, 35.09]]}}]
    t = {"state": "SC", "name": "Example Creek", "slugs": ["example-creek-sc"], "reach_slugs": {"1": "example-creek-sc"}}
    acts = N.recheck_remainders(rows, [t], _lake_existing(), "2026-11-15")
    assert [a["action"] for a in acts] == ["dropped"] and acts[0]["to"] == "example-lake-xx"
    assert [w["slug"] for w in rows] == ["other-creek-sc"]                 # a record no ruling names is untouched
    assert t["slugs"] == ["example-lake-xx"] and t["reach_slugs"] == {"1": "example-lake-xx"}


def test_an_unnamed_water_is_ruled_by_its_slug(monkeypatch, tmp_path):
    N = _nhd_rulings_setup(monkeypatch, tmp_path, {("SC", "unnamed-tributary-to-example-sc"): {
        "to": "example-lake-xx", "on": ["example-lake-xx"], "why": "invented"}})
    rows = [{"slug": "unnamed-tributary-to-example-sc", "name": "Unnamed tributary", "kind": "stream", "state": "SC",
             "gnis_id": None, "geometry": {"type": "LineString", "coordinates": [[-81.0, 35.04], [-81.0, 35.05]]}}]
    t = {"state": "SC", "name": "Unnamed", "slugs": ["unnamed-tributary-to-example-sc"]}
    assert [a["action"] for a in N.recheck_remainders(rows, [t], _lake_existing(), "2026-11-15")] == ["dropped"]
    assert rows == [] and t["slugs"] == ["example-lake-xx"]


def test_a_ruled_copy_of_a_river_drops_its_part_on_the_river_and_side_channels(monkeypatch, tmp_path):
    N = _nhd_rulings_setup(monkeypatch, tmp_path, {("SC", 777): {"to": "example-river-xx", "on": ["example-river-xx"],
                                                                  "why": "invented"}})
    rows = [{"slug": "example-river-town-sc", "name": "Example River", "kind": "river", "state": "SC",
             "gnis_id": "777", "covers_part_of": "example-river-stub-sc",
             "geometry": {"type": "MultiLineString", "coordinates": [[[-82.0, 34.0], [-82.0, 34.45]],
                                                                     [[-82.0055, 34.1], [-82.0055, 34.11]]]}}]
    t = {"state": "SC", "name": "Example River", "slugs": ["example-river-town-sc"]}
    assert [a["action"] for a in N.recheck_remainders(rows, [t], _lake_existing(), "2026-11-15")] == ["dropped"]
    assert t["slugs"] == ["example-river-xx"]


def test_without_a_ruling_a_record_that_is_no_remainder_is_never_measured(monkeypatch, tmp_path):
    N = _nhd_rulings_setup(monkeypatch, tmp_path, {})
    rows = [{"slug": "example-creek-sc", "name": "Example Creek", "kind": "river", "state": "SC", "gnis_id": "555",
             "geometry": {"type": "LineString", "coordinates": [[-81.0, 35.01], [-81.0, 35.09]]}}]
    assert N.recheck_remainders(rows, [], _lake_existing()) == [] and len(rows) == 1


def test_the_south_carolina_rulings_are_recorded_and_applied_to_the_files():
    from ingest import waters_from_nhd as N
    gone = {"lynches-river-tradesville-sc": "lynches-river-sc", "seneca-river-sc": "lake-hartwell-sc",
            "unnamed-tributary-to-catawba-river-sc": "lake-wylie-sc"}
    assert N.REMAINDER_ON[("SC", 1246493)]["to"] == "lynches-river-sc"
    assert N.REMAINDER_ON[("SC", 1250834)]["to"] == "lake-hartwell-sc"
    assert N.REMAINDER_ON[("SC", "unnamed-tributary-to-catawba-river-sc")]["to"] == "lake-wylie-sc"
    nhd = json.loads((ROOT / "data" / "waters-nhd.json").read_text())
    assert not set(gone) & {w["slug"] for w in nhd["waters"]} and nhd["count"] == len(nhd["waters"])
    for t in nhd["targets"]:
        assert not set(gone) & (set(t.get("slugs") or []) | set((t.get("reach_slugs") or {}).values()))
    plants = [json.loads(x.rstrip(",\n")) for x in (ROOT / "data" / "outfalls-plants-us.json").read_text().splitlines()
              if x.startswith('{"') and '"state": "SC"' in x]
    tied = {(r["npdes_permit"], r["outfall"]): r.get("water_slug") for r in plants}
    assert not set(gone) & set(tied.values())
    assert tied[("SC0020010", "001")] == "lake-hartwell-sc"
    assert tied[("SC0026751", "001")] == tied[("SC0026751", "002")] == "lake-wylie-sc"
    assert tied[("SC0025933", "001")] == tied[("SC0035378", "001")] == tied[("SC0042676", "001")] == "lynches-river-sc"
