"""An authority's advisory for a named stretch of a river colours that stretch as a modeled reach of its own kind
("advisory_stretch"), not the whole river (review 2026-11-07, Mississippi final audit, finding P1-1): the reach builder
traces it from the start point to the stop point (build/reaches.py), the status build colours only it
(build/status.py), the export labels it in its own words and category (export/build.py), and the sewage reaches'
export is byte-identical with or without it (tests/sewage_reach_golden.py)."""
import copy
import json
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from build import reaches as R
from build import status as S
from export import build as X
from ingest import ms_mdeq_water_contact as W
from tests import sewage_reach_golden as G

FIX = Path(__file__).resolve().parent / "fixtures"
PEARL = json.loads((FIX / "pearl-river-nldi-dm.json").read_text())
LINES = PEARL["lines"]
ATTRS = {int(k): v for k, v in PEARL["attrs"].items()}
BRIDGE = (-90.24366, 32.17657)          # NRHP 79003427, UTM 15 759900 E 3563150 N (NAD 1927)
MOUTH = (-90.112036, 32.351817)         # GNIS 670883, Streams (Mouth)


def standing() -> dict:
    s = W.STANDING[0]
    r = W.water_fields(W.standing_record(s), s)
    r["source_updated_at"] = "2026-11-07T12:00:00Z"           # a feed read re-confirms it (ingest's run())
    return r


@pytest.fixture
def no_requests(monkeypatch):
    """trace() on the recorded NLDI answer: no network, every navigation request counted."""
    calls = []

    def start(o, rec, npdes_id, prev, dist):
        calls.append(dist)
        rec["method"], rec["start_comid"] = "nldi_position", LINES[0]["comid"]
        return copy.deepcopy(LINES)
    monkeypatch.setattr(R, "_start_nldi", start)
    monkeypatch.setattr(R, "fetch_attrs", lambda comids: {c: ATTRS[c] for c in comids if c in ATTRS})
    monkeypatch.setitem(R.MODE, "walk", False)
    return calls


def pearl_trace(no_requests, rec=None) -> dict:
    return R.trace(R.stretch_candidate(rec or standing()), 40.0)


# ---------------------------------------------------------------- the record's stretch (ingest)

def test_the_standing_pearl_river_record_carries_a_stretch_with_both_points_and_their_citations():
    r = standing()
    st = r["stretch"]
    assert st["water"] == "Pearl River"
    assert (st["start"]["lat"], st["start"]["lon"]) == (MOUTH[1], MOUTH[0]) and "670883" in st["start"]["basis"]
    assert (st["end"]["lat"], st["end"]["lon"]) == (BRIDGE[1], BRIDGE[0]) and "79003427" in st["end"]["source"]
    assert st["end"]["url"].startswith("https://npgallery.nps.gov/") and "NAD 1927" in st["end"]["basis"]


def test_a_release_whose_downstream_end_has_no_point_has_no_stretch():
    r = W.water_fields(W.issue_record({"title": "Water Contact Advisory Issued for Section of Trahon Creek",
                                       "link": "https://x/", "date": "Wed, 02 Sep 2026 15:00:00 +0000"},
                                      ["Trahon Creek"],
                                      ["The advisory covers Trahon Creek from the culvert at the Interstate 55 frontage "
                                       "road (32.194572 N, 90.250330 W) to its confluence with the Pearl River."]))
    assert r["raw"]["stretch"]["from"]["lat"] == 32.194572 and "stretch" not in r


# ---------------------------------------------------------------- the trace (build/reaches.py)

def test_the_pearl_river_stretch_runs_from_the_creek_mouth_to_the_bridge(no_requests):
    rec = pearl_trace(no_requests)
    assert rec["kind"] == R.ADVISORY_KIND and rec["cut_reason"] == "stretch_end" and rec["error"] is None
    assert 38.5 < rec["length_km"] < 39.4                    # the bridge's flowline ends at about 39.4 km (review)
    info = rec["stretch_trace"]
    assert info["left_out"]["names"] == ["Hanging Moss Creek"] and info["left_out"]["km"] < 0.1
    assert info["end"]["reached"] and info["end"]["offset_m"] < 100 and "beyond_cap" not in info["end"]
    assert info["start"]["offset_m"] < 150
    assert all(s["gnis_name"] == "Pearl River" for s in rec["segments"])
    assert rec["segments"][-1]["coords"][-1] == info["end"]["path_point"]
    assert rec["segments"][0]["km_start"] == 0.0 and rec["river"] == "Pearl River"
    # what the record cites: the advisory, both ends with their basis and source, the rule; never a rain target
    assert rec["advisory"]["event_id"].endswith("pearl-river-hanging-moss-creek-to-byram-swinging-bridge")
    assert rec["advisory"]["authority"].startswith("Mississippi Department of Environmental Quality")
    assert rec["stretch"]["end"]["source"].startswith("National Register") and rec["rule"] == R.STRETCH_RULE
    assert rec["state"] == "MS" and rec["permit"] is None and rec["rain_caution"] is False
    assert no_requests == [85]                                # one navigation request, looking past the cap


def test_an_end_past_the_cap_is_cut_at_the_cap_and_the_record_says_so(no_requests):
    r = standing()
    r["stretch"]["end"].update(lat=32.1360, lon=-90.2476, name="a point below")        # about 46 km down
    rec = pearl_trace(no_requests, r)
    assert rec["cut_reason"] == "cap_km" and rec["length_km"] == 40.0
    end = rec["stretch_trace"]["end"]
    assert end["beyond_cap"] is True and end["reached"] is False and end["km"] > 45 and "40.0 km" in end["why"]


def test_an_end_off_the_path_draws_nothing_and_says_why(no_requests):
    r = standing()
    r["stretch"]["end"].update(lat=32.30, lon=-90.30)                                   # miles off the river
    rec = pearl_trace(no_requests, r)
    assert rec["segments"] == [] and rec["cut_reason"] == "stretch_end_off_path"
    assert "from the traced path" in rec["error"]
    assert R.outcome(rec) == "no_trace"


def test_a_lake_before_the_end_stops_the_stretch_there():
    attrs = copy.deepcopy(ATTRS)
    lines = R.ordered(LINES, attrs)
    attrs[lines[10]["comid"]].update(wbareacomid=1, wbarea_ftype=390)
    segs, why, info = R.stretch_segments(LINES, attrs, 40.0, "Pearl River", BRIDGE, MOUTH)
    assert why == "lake_or_reservoir" and not info["end"]["reached"] and segs[-1]["km_end"] < 20


def test_stretch_points_reads_any_source_and_keys_on_the_record(tmp_path):
    now = datetime(2026, 11, 7, 13, tzinfo=UTC)
    rec = standing()
    other = copy.deepcopy(rec)
    other.update(event_id="xx-any-feed:7", source_id="xx-any-feed", status="advisory_lifted",
                 ended_at=(now - timedelta(days=100)).isoformat())                     # lifted long ago: not traced
    lifted = copy.deepcopy(other)
    lifted.update(event_id="xx-any-feed:8", ended_at=(now - timedelta(days=3)).isoformat())    # in the history: traced
    plain = copy.deepcopy(rec)
    plain.update(event_id="xx-any-feed:9")
    plain.pop("stretch")
    (tmp_path / "a.json").write_text(json.dumps({"records": [rec, other, lifted, plain]}))
    (tmp_path / "b.json").write_text(json.dumps({"records": [{"event_id": "x:1", "event_type": "cso"}]}))
    pts = R.stretch_points(tmp_path, now)
    assert sorted(p["event_ids"][0] for p in pts) == sorted([rec["event_id"], "xx-any-feed:8"])
    assert all(p["key"] == R.stretch_key(p["event_ids"][0]) and p["sources"] == ["advisory-stretch"] for p in pts)


def test_one_trace_per_advisory_cached_like_the_discharge_traces(no_requests, tmp_path, monkeypatch):
    monkeypatch.setattr(R, "REACH_DIR", tmp_path)
    c = R.stretch_candidate(standing())
    R.run_traces([c], 40.0, R.Budget(0, 0), log=lambda m: None)
    R.run_traces([c], 40.0, R.Budget(0, 0), log=lambda m: None)
    assert len(no_requests) == 1                              # the second run reads the cache
    moved = copy.deepcopy(c)
    moved["stop"]["lat"] += 0.01
    todo, _ = R.plan([moved], R.load_reaches(), datetime.now(UTC))
    assert todo == [moved]                                    # an end that moves is traced again
    renamed = copy.deepcopy(c)
    renamed["advisory"]["source_url"] = "https://example.org/new"
    todo, touch = R.plan([renamed], R.load_reaches(), datetime.now(UTC))
    assert todo == [] and len(touch) == 1                     # a citation change needs no request
    assert R.retire_stretches([], R.load_reaches()) == [c["key"]] and R.load_reaches() == {}


# ---------------------------------------------------------------- the status build

def _status(recs, now, reaches):
    from tests.test_status import TEST_RULES
    S._GEOM_CACHE.clear()
    S._REACH_WATERS.clear()
    d = Path(tempfile.mkdtemp())
    (d / f"{W.SOURCE_ID}.json").write_text(json.dumps({"source_id": W.SOURCE_ID, "ok": True, "last_ok_at": now,
                                                       "meta": {}, "records": recs}))
    line = {"type": "LineString", "coordinates": [list(MOUTH), [-90.14, 32.32], [-90.20, 32.24], list(BRIDGE),
                                                  [-90.24, 32.0]]}
    waters = {"pearl-river-ms": {"slug": "pearl-river-ms", "name": "Pearl River", "kind": "river", "state": "MS",
                                 "bbox": [-90.25, 32.0, -90.11, 32.36], "geometry": line}}
    st, hist = S.build(now=datetime.fromisoformat(now.replace("Z", "+00:00")), write=False, events_dir=d,
                       waters=waters, outfalls=[], registry={}, reaches=reaches, flows=({}, {}), rules=TEST_RULES,
                       placement_cache=None)
    return st, hist


@pytest.fixture
def traced(no_requests, monkeypatch):
    from tests.test_status import TEST_RULES
    monkeypatch.setattr(S, "_RULES", TEST_RULES)
    rec = pearl_trace(no_requests)
    return {rec["key"]: rec}


def test_the_advisory_colours_its_stretch_not_the_whole_river(traced):
    rec = standing()
    key = next(iter(traced))
    st, hist = _status([rec], "2026-11-07T13:00:00Z", traced)
    pr = st["waters"]["pearl-river-ms"]
    assert pr["status"] == "red" and pr["status_by_category"]["beach"] == "red"
    r0 = pr["reasons"][0]
    assert r0["placement"] == "reach" and r0["reach"] == key and "stretch_fallback" not in r0
    assert pr["reason_short"].endswith("to the Byram Swinging Bridge · on the stretch the advisory names")
    assert pr["summary"] == S.STRETCH_SUMMARY and pr["reaches"] == [key]
    assert rec["event_id"] in pr["events"]                    # the water's page still lists the advisory
    assert st["placements"][rec["event_id"]]["reach"] == key
    sr = st["reaches"][key]
    assert sr["status"] == "red" and sr["kind"] == "advisory_stretch" and sr["category"] == "beach"
    assert sr["stretch"]["end"]["name"] == "Byram Swinging Bridge" and sr["rule_applied"] == R.STRETCH_RULE
    assert {x[5] for x in hist["reach_intervals"][key]} == {"beach"} and "R" in hist["reaches"][key]
    (a,) = st["reach_events_active"]
    assert a["kind"] == "advisory_stretch" and a["category"] == "beach" and a["gauge"] is None
    assert all(s["hours_typical"] is None and s["reached_typical"] is None for s in a["segments"])
    pt = next(p for p in st["advisory_points"] if p["event_id"] == rec["event_id"])
    assert pt["why"].startswith("the advisory covers the stretch it names")
    assert st["needs_reach"] == []


def test_a_lifted_advisory_leaves_its_stretch_grey(traced):
    rec = standing()
    rec.update(status="advisory_lifted", ended_at="2026-11-10")
    st, _ = _status([rec], "2026-11-12T13:00:00Z", traced)
    key = next(iter(traced))
    assert st["reaches"][key]["status"] == "grey" and st["waters"]["pearl-river-ms"]["status"] == "grey"
    assert st["reach_events_active"] == []


def test_with_no_stretch_traced_the_whole_water_reads_the_advisory_and_says_why(no_requests, monkeypatch):
    from tests.test_status import TEST_RULES
    monkeypatch.setattr(S, "_RULES", TEST_RULES)
    r = standing()
    r["stretch"]["end"].update(lat=32.30, lon=-90.30)
    off = pearl_trace(no_requests, r)
    for reaches, why in (({}, "not traced yet"), ({off["key"]: off}, "could not be traced")):
        st, _ = _status([r], "2026-11-07T13:00:00Z", reaches)
        pr = st["waters"]["pearl-river-ms"]
        assert pr["status"] == "red" and pr["reasons"][0]["placement"] == "stretch_unmodeled"
        assert why in pr["reasons"][0]["stretch_fallback"] and pr["reaches"] == []
        assert pr["reason_short"].endswith("· stretch not traced: shown on the whole water")
        assert st["reaches"] == {}


# ---------------------------------------------------------------- the export

def _with_advisory(traced):
    rec = standing()
    st, _ = _status([rec], "2026-11-07T13:00:00Z", traced)
    key = next(iter(traced))
    base = G.status()
    merged = copy.deepcopy(base)
    merged["waters"]["pearl-river-ms"] = {"state": "MS", "reaches": [key]}
    merged["reaches"][key] = st["reaches"][key]
    merged["reach_events_active"].append(st["reach_events_active"][0])
    cache = {**G.cached(), **traced}
    by_event = {**G.BY_EVENT, rec["event_id"]: {"started_at": rec["started_at"], "raw": rec["raw"]}}
    return merged, by_event, cache, key


def test_the_export_labels_the_stretch_as_the_advisorys_never_a_travel_time(traced, monkeypatch):
    monkeypatch.setattr(R, "cap_km", lambda rules=None: 40.0)
    st, by_event, cache, key = _with_advisory(traced)
    feats, paths = X.reach_features(st, by_event, cache)
    mine = [f for f in feats if f["properties"]["reach"] == key]
    segs = [f for f in mine if f["properties"]["feature"] == "segment"]
    (stop,) = [f for f in mine if f["properties"]["feature"] == "stop"]
    assert len(segs) == len(traced[key]["segments"])
    for f in mine:
        p = f["properties"]
        assert p["reach_kind"] == "advisory_stretch" and p["category"] == "beach" and p["status"] == "red"
        assert p["authority"] == "Mississippi Department of Environmental Quality"
        assert p["stretch"]["end"]["source"].startswith("National Register") and p["stretch"]["end_reached"]
    p = segs[0]["properties"]
    assert p["arrival_hours_typical"] is None and p["gauge"] is None and p["line_text"] == X.ADVISORY_LINE_TEXT
    label = p["label"]
    assert label.startswith("Mississippi Department of Environmental Quality's water contact advisory covers the "
                            "Pearl River from the mouth of Hanging Moss Creek to the Byram Swinging Bridge.")
    assert "670883" in label and "79003427" in label
    for bad in ("travel", "would typically reach", "hour", "safe", "clean"):
        assert bad not in label.lower() and bad not in stop["properties"]["label"].lower()
    assert stop["properties"]["label"].startswith("The advisory's stretch ends here, at the Byram Swinging Bridge")
    (path,) = [f for f in paths if f["id"] == key]
    assert path["properties"]["reach_kind"] == "advisory_stretch" and path["properties"]["status"] == "red"
    assert path["properties"]["stop_label"] == stop["properties"]["label"]
    by_state, homeless = X.reaches_by_state(feats, paths, st, cache, G.LIVE | {"MS"})
    assert homeless == []
    ms = by_state["MS"]
    assert [f["properties"]["feature"] for f in ms] == ["path"] + ["segment"] * len(segs) + ["stop"]
    assert all(f["properties"]["states"] == ["MS"] and f["properties"]["reach_kind"] == "advisory_stretch" for f in ms)


def test_a_stretch_not_in_the_status_build_is_not_exported(traced, monkeypatch):
    monkeypatch.setattr(R, "cap_km", lambda rules=None: 40.0)
    feats, paths = X.reach_features(G.status(), G.BY_EVENT, {**G.cached(), **traced})
    assert not [f for f in feats + paths if f["properties"].get("reach_kind")]


def test_the_sewage_reaches_are_byte_identical_with_and_without_an_advisory_stretch(traced):
    gold = json.loads(G.GOLDEN.read_text())
    assert G.render(G.status(), G.BY_EVENT, G.cached()) == gold          # the code before advisory stretches
    st, by_event, cache, key = _with_advisory(traced)
    out = G.render(st, by_event, cache, G.LIVE | {"MS"})
    for state_file in ("reaches/pa.geojson", "reaches/ny.geojson", "reaches/il.geojson", "reaches/ma.geojson"):
        assert out[state_file] == gold[state_file]
    for name in ("reaches.geojson", "reach-paths.geojson"):
        got = json.loads(out[name])["features"]
        assert json.dumps([f for f in got if f["properties"]["reach"] != key]) == \
            json.dumps(json.loads(gold[name])["features"])
