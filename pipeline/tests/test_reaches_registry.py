"""build/reaches.py: outfalls from the whole registry (live states, open outfalls), the per-run request
budget, the trace order, failure back-off, closed-outfall retirement and the per-outfall index."""
from datetime import UTC, datetime, timedelta

import pytest

import common
from build import reaches as R

NOW = datetime(2026, 11, 3, 20, 0, tzinfo=UTC)

WATERS = {
    "delaware-river-pa": {"slug": "delaware-river-pa", "kind": "river", "state": "PA"},
    "shamokin-creek-pa": {"slug": "shamokin-creek-pa", "kind": "stream", "state": "PA"},
    "newark-bay-nj": {"slug": "newark-bay-nj", "kind": "bay", "state": "NJ"},
    "hudson-river-ny": {"slug": "hudson-river-ny", "kind": "river", "state": "NY"},
    "fox-river-wi": {"slug": "fox-river-wi", "kind": "river", "state": "WI"},
}


def row(permit, outfall, state, slug=None, status="CSO", lat=40.0, lon=-75.0, **kw):
    return {"npdes_permit": permit, "outfall": outfall, "state": state, "water_slug": slug, "outfall_status": status,
            "lat": lat, "lon": lon, "outfall_name": f"{permit} {outfall}", **kw}


REGISTRY = [
    row("PA0026689", "042", "PA", "delaware-river-pa", reach_id="02040105000123", _file="data/outfalls-mid-atlantic.json"),
    row("PA0026689", "042", "PA", "shamokin-creek-pa", _file="data/outfalls-us.json"),          # duplicate: first wins
    row("PA0027456", "037", "PA", "shamokin-creek-pa", reach_id=None),
    row("PA0027456", "038", "PA", "shamokin-creek-pa", status="CLS"),
    row("PA0027456", "039", "PA", "shamokin-creek-pa", status="CLS|NPD"),                        # closed, reported
    row("NJ0108880", "029", "NJ", "newark-bay-nj"),
    row("NY0026280", "004", "NY", "hudson-river-ny", lat=None, lon=None, coords_problem="334 km from the river"),
    row("NY0027081", "060M", "NY", None),                                                         # no water record yet
    row("NY0027081", "061", "NY", None, lat=None, lon=None, reach_id=None),                       # nothing to trace from
    row("NY0027081", "062", "NY", "hudson-river-ny", lat=None, lon=None, reach_id=None),          # a water is no start
    row("NY0027081", "063", "NY", None, lat=None, lon=None, reach_id="02020006000045"),           # NLDI npdes may know it
    row("WI0024597", "001", "WI", "fox-river-wi"),                                                # not a live state
    row("PA0099999", "001", "PA", "delaware-river-pa", outfall_kind="plant"),
]
LIVE = {"PA", "NJ", "NY"}


def cands(reported=frozenset(), skipped=None, plants=True):
    return R.candidate_outfalls(waters=WATERS, registry=[dict(r) for r in REGISTRY], live=LIVE, skipped=skipped,
                                reported=set(reported), plants=plants)


# ---------------------------------------------------------------- reading the registry

def test_candidates_come_from_every_registry_file_in_live_states_open_outfalls_only():
    skipped = {}
    got = {c["key"]: c for c in cands(skipped=skipped)}
    assert set(got) == {"PA0026689-042", "PA0027456-037", "NY0027081-060M", "NY0027081-063", "PA0099999-001"}
    a = got["PA0026689-042"]
    assert a["water_slug"] == "delaware-river-pa" and a["state"] == "PA" and a["sources"] == ["echo"]
    assert a["file"] == "data/outfalls-mid-atlantic.json" and a["outfall_kind"] == "cso"
    assert got["NY0027081-060M"]["water_slug"] is None          # no water record: still traced from its point
    assert got["PA0099999-001"]["outfall_kind"] == "plant"
    why = {k: v["why"] for k, v in skipped.items()}
    assert why == {"PA0027456-038": "closed", "PA0027456-039": "closed", "NJ0108880-029": "not_river",
                   "NY0026280-004": "coords_problem", "NY0027081-061": "no_location", "NY0027081-062": "no_location"}
    assert skipped["NJ0108880-029"]["state"] == "NJ" and skipped["PA0027456-038"]["permit"] == "PA0027456"
    assert "WI0024597-001" not in skipped                         # not live: neither traced nor listed


def test_plant_outfalls_wait_unless_asked_for():
    skipped = {}
    got = {c["key"] for c in cands(skipped=skipped, plants=False)}
    assert "PA0099999-001" not in got and skipped["PA0099999-001"]["why"] == "plant_deferred"
    assert R.TRACE_PLANTS is False


def test_a_closed_outfall_a_recent_report_names_is_traced():
    got = {c["key"]: c for c in cands(reported={("PA0027456", (39, ""))})}
    assert got["PA0027456-039"]["reported_while_closed"] is True
    assert "PA0027456-038" not in got
    got = {c["key"]: c for c in cands(reported={"PA0027456-038"})}     # a reach key the last status build used
    assert "PA0027456-038" in got


def test_registry_reader_prefers_the_common_loader_without_provisional_places(monkeypatch):
    calls = []

    def fake(data_dir=None, provisional=True):
        calls.append(provisional)
        return [row("PA1", "001", "PA", "delaware-river-pa")]
    monkeypatch.setattr(common, "load_outfall_registry", fake, raising=False)
    assert [r["npdes_permit"] for r in R.registry_outfalls()] == ["PA1"] and calls == [False]
    monkeypatch.delattr(common, "load_outfall_registry", raising=False)
    from build import status as S
    monkeypatch.setattr(S, "load_registry_outfalls", lambda *a, **k: [row("PA2", "001", "PA")])
    assert [r["npdes_permit"] for r in R.registry_outfalls()] == ["PA2"]


def test_live_states_are_the_status_build_states(monkeypatch):
    from build import status as S
    monkeypatch.delattr(common, "live_states", raising=False)
    monkeypatch.setattr(S, "states", lambda: {"PA", "ny"})
    assert R.live_states() == {"PA", "NY"}


def test_npdes_is_asked_only_where_epa_reach_indexed_the_outfall():
    assert R.try_npdes({"reach_id": "02040105000123"}) is True
    assert R.try_npdes({}) is True                                  # a state layer row: not known, ask
    assert R.try_npdes({"reach_id": None}) is False
    assert R.try_npdes({"reach_id": None}, {"method": "nldi_npdes"}) is True


# ---------------------------------------------------------------- order, freshness, back-off

def rec(key, fetched, cut="cap_km", segs=True, lat=40.0, lon=-75.0, **kw):
    return {"key": key, "fetched_at": fetched.isoformat(), "cut_reason": cut, "lat": lat, "lon": lon,
            "segments": [{"km_start": 0, "km_end": 1}] if segs else [], **kw}


def test_plan_orders_event_points_new_cso_new_plant_failures_then_stale():
    cs = [{"key": k, "permit": "PA1", "outfall": k, "lat": 40.0, "lon": -75.0, "sources": ["echo"],
           "outfall_kind": kind, "water_slug": "w"} for k, kind in
          (("a-fresh", "cso"), ("b-new", "cso"), ("c-plant", "plant"), ("d-failed", "cso"), ("e-stale", "cso"),
           ("f-stale-older", "cso"), ("g-moved", "cso"), ("h-renamed", "cso"))]
    cs.append({"key": "pt-1", "permit": None, "outfall": None, "lat": 40, "lon": -75, "sources": ["event-point"]})
    same = {"water_slug": "w", "sources": ["echo"], "outfall_kind": "cso"}
    cached = {"a-fresh": rec("a-fresh", NOW - timedelta(days=2), **same),
              "d-failed": rec("d-failed", NOW - timedelta(days=2), cut="no_trace", segs=False, failures=1),
              "e-stale": rec("e-stale", NOW - timedelta(days=31), water_slug="w"),
              "f-stale-older": rec("f-stale-older", NOW - timedelta(days=40), water_slug="w"),
              "g-moved": rec("g-moved", NOW - timedelta(days=2), lat=40.01, water_slug="w"),
              "h-renamed": rec("h-renamed", NOW - timedelta(days=2), **{**same, "water_slug": "old-slug"})}
    todo, touch = R.plan(cs, cached, NOW)
    assert [c["key"] for c in todo] == ["pt-1", "b-new", "g-moved", "c-plant", "d-failed", "f-stale-older", "e-stale"]
    assert [c["key"] for c, _ in touch] == ["h-renamed"]


def test_failed_traces_back_off_one_two_four_days_to_the_cache_age():
    assert R.retry_days({"cut_reason": "cap_km"}) == R.CACHE_DAYS
    assert [R.retry_days({"cut_reason": "no_trace", "failures": n}) for n in (None, 1, 2, 3, 6)] == [1, 1, 2, 4, 30]
    assert not R.fresh_rec(rec("x", NOW - timedelta(days=3), cut="no_trace", segs=False, failures=2), NOW)
    assert R.fresh_rec(rec("x", NOW - timedelta(days=3), cut="no_trace", segs=False, failures=3), NOW)


# ---------------------------------------------------------------- the budget

@pytest.fixture()
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "REACH_DIR", tmp_path / "reaches")
    monkeypatch.setattr(R, "RETIRED_DIR", tmp_path / "reaches" / "retired")
    monkeypatch.setattr(R, "REACH_INDEX", tmp_path / "reach-outfalls.json")
    monkeypatch.setattr(R, "LOCK_FILE", tmp_path / "reaches.lock")
    (tmp_path / "reaches").mkdir()
    R.STATS.clear()
    R.RATE.update({"nav_remaining": None, "nldi_remaining": None})
    yield tmp_path / "reaches"
    R.STATS.clear()
    R.RATE.update({"nav_remaining": None, "nldi_remaining": None})


def outfalls(n):
    return [{"key": f"PA{i:07d}-001", "permit": f"PA{i:07d}", "outfall": "001", "lat": 40.0, "lon": -75.0,
             "sources": ["echo"], "water_slug": "w", "state": "PA", "outfall_kind": "cso"} for i in range(n)]


def fake_trace(navs=1, cut="cap_km"):
    def f(o, cap, prev=None):
        R.STATS["nav"] += navs
        R.STATS["nldi"] += navs
        return {**o, "fetched_at": datetime.now(UTC).isoformat(), "method": "nldi_npdes", "cut_reason": cut,
                "segments": [{"km_start": 0, "km_end": 2}] if cut != "no_trace" else [], "length_km": 2.0,
                "error": "no flowlines" if cut == "no_trace" else None}
    return f


def test_a_run_stops_at_its_navigation_request_budget_and_the_rest_waits(cache, monkeypatch):
    monkeypatch.setattr(R, "trace", fake_trace(navs=2))
    run, cached = R.run_traces(outfalls(20), 40, R.Budget(nav=10, seconds=0), log=lambda m: None)
    assert run["traced"] == 5 and run["left"] == 15 and run["requests"]["nldi_navigation"] == 10
    assert run["stopped"].startswith("request budget")
    assert len(list(cache.glob("*.json"))) == 5
    run, _ = R.run_traces(outfalls(20), 40, R.Budget(nav=10, seconds=0), log=lambda m: None)
    assert run["due"] == 15                              # the next run picks up where this one stopped


def test_low_nldi_allowance_switches_to_the_nhdplus_walk_and_time_stops_a_run(cache, monkeypatch):
    monkeypatch.setattr(R, "trace", fake_trace())
    R.RATE["nav_remaining"] = 50
    run, _ = R.run_traces(outfalls(3), 40, R.Budget(nav=0, seconds=0, reserve=100), log=lambda m: None)
    assert run["traced"] == 3 and R.MODE["walk"] is True and not R.nldi_low()
    R.RATE.update({"nav_remaining": None, "nldi_remaining": 20})
    R.run_traces(outfalls(4)[3:], 40, R.Budget(nav=0, seconds=0, reserve=100), log=lambda m: None)
    assert R.MODE["walk"] is True and R.nldi_low() and R.RATE["nldi_remaining"] is None
    R.RATE.update({"nav_remaining": None, "nldi_remaining": None})
    run, _ = R.run_traces(outfalls(8)[4:], 40, R.Budget(nav=0, seconds=1e-9), log=lambda m: None)
    assert run["traced"] == 0 and run["stopped"].startswith("time budget")
    run, _ = R.run_traces(outfalls(8)[4:], 40, R.Budget(nav=0, seconds=0, limit=2), log=lambda m: None)
    assert run["traced"] == 2


def test_a_rate_limited_trace_is_never_cached_as_a_failure(cache, monkeypatch):
    calls = []

    def limited(o, cap, prev=None):
        calls.append(o["key"])
        if len(calls) == 2:
            raise R.RateLimited("429")
        return fake_trace()(o, cap, prev)
    monkeypatch.setattr(R, "trace", limited)
    run, _ = R.run_traces(outfalls(5), 40, R.Budget(nav=0, seconds=0), log=lambda m: None)
    assert run["traced"] == 1 and "rate limit" in run["stopped"]
    assert [p.stem for p in cache.glob("*.json")] == ["PA0000000-001"]


def test_failures_count_up_and_never_replace_a_good_trace(cache, monkeypatch):
    o = outfalls(1)
    monkeypatch.setattr(R, "trace", fake_trace(cut="no_trace"))
    R.run_traces(o, 40, R.Budget(0, 0), force=True, log=lambda m: None)
    R.run_traces(o, 40, R.Budget(0, 0), force=True, log=lambda m: None)
    assert R.read_json(cache / "PA0000000-001.json")["failures"] == 2
    monkeypatch.setattr(R, "trace", fake_trace())
    R.run_traces(o, 40, R.Budget(0, 0), force=True, log=lambda m: None)
    monkeypatch.setattr(R, "trace", fake_trace(cut="no_trace"))
    R.run_traces(o, 40, R.Budget(0, 0), force=True, log=lambda m: None)
    d = R.read_json(cache / "PA0000000-001.json")
    assert d["segments"] and d["last_attempt"]["error"] == "no flowlines"
    R.write_json(cache / "PA0000000-001.json", {**d, "segments": [], "cut_reason": "tidal_at_outfall"})
    R.run_traces(o, 40, R.Budget(0, 0), force=True, log=lambda m: None)
    assert R.read_json(cache / "PA0000000-001.json")["cut_reason"] == "tidal_at_outfall"


def test_a_changed_water_is_written_without_a_request(cache, monkeypatch):
    o = outfalls(1)
    monkeypatch.setattr(R, "trace", fake_trace())
    R.run_traces(o, 40, R.Budget(0, 0), log=lambda m: None)
    monkeypatch.setattr(R, "trace", lambda *a, **k: pytest.fail("traced again"))
    o[0]["water_slug"] = "new-slug"
    run, _ = R.run_traces(o, 40, R.Budget(0, 0), log=lambda m: None)
    assert run["metadata_updates"] == 1 and R.read_json(cache / "PA0000000-001.json")["water_slug"] == "new-slug"


# ---------------------------------------------------------------- requests

class Resp:
    def __init__(self, code, body=None, headers=None):
        self.status_code, self._body, self.headers = code, body or {}, headers or {}

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(str(self.status_code))


class Sess:
    def __init__(self, answers):
        self.answers, self.urls = list(answers), []

    def get(self, url, timeout=None, params=None):
        self.urls.append(url)
        return self.answers.pop(0)


def test_nldi_get_retries_server_errors_reads_the_allowance_and_reuses_navigation(cache, monkeypatch):
    monkeypatch.setattr(R.time, "sleep", lambda s: None)
    R._NAV_MEMO.clear()
    s = Sess([Resp(503), Resp(200, {"features": [1]}, {"X-RateLimit-Remaining": "640"})])
    monkeypatch.setattr(R, "session", lambda: s)
    url = f"{R.NLDI}/comid/1/navigation/DM/flowlines?distance=45"
    assert R.nldi_get(url) == {"features": [1]} and R.nldi_get(url) == {"features": [1]}
    assert len(s.urls) == 2 and R.STATS["retries"] == 1 and R.STATS["nav_memo"] == 1
    assert R.RATE["nav_remaining"] == 640
    s.answers = [Resp(404)]
    assert R.nldi_get(f"{R.NLDI}/npdes/PA1001/navigation/DM/flowlines") is None
    s.answers = [Resp(429, headers={"Retry-After": "5"})]
    with pytest.raises(R.RateLimited):
        R.nldi_get(f"{R.NLDI}/comid/position?coords=POINT(1 2)")
    assert R.RATE["nldi_remaining"] == 0
    R._NAV_MEMO.clear()


# ---------------------------------------------------------------- closed outfalls, the index, the lock

def test_cached_traces_of_closed_outfalls_are_retired_unless_a_state_layer_lists_them(cache):
    for k in ("PA0027456-038", "PA0027456-037"):
        R.write_json(cache / f"{k}.json", rec(k, NOW))
    skipped = {"PA0027456-038": {"why": "closed", "note": "outfall_status CLS"},
               "PA0027456-037": {"why": "closed", "note": "outfall_status CLS"}}
    out = R.retire_closed(skipped, [{"key": "PA0027456-037"}])
    assert out == ["PA0027456-038"]
    assert not (cache / "PA0027456-038.json").exists() and (cache / "PA0027456-037.json").exists()
    moved = R.read_json(cache / "retired" / "PA0027456-038.json")
    assert "closed" in moved["retired"]["why"]
    assert set(R.load_reaches()) == {"PA0027456-037"}


def test_the_index_lists_every_live_outfall_with_its_trace_state_by_state(cache):
    skipped = {}
    cs = cands(skipped=skipped)
    cached = {"PA0026689-042": rec("PA0026689-042", NOW, method="nldi_npdes"),
              "PA0027456-037": rec("PA0027456-037", NOW, cut="tidal_at_outfall", segs=False),
              "NY0027081-060M": rec("NY0027081-060M", NOW, cut="no_trace", segs=False, error="no flowlines")}
    idx = R.write_index(cs, skipped, cached, LIVE, {"at": "now", "traced": 3})
    by = idx["counts"]["by_state"]
    assert by["PA"] == {"traced": 1, "tidal_at_outfall": 1, "pending": 1, "closed": 2}
    assert by["NY"] == {"no_trace": 1, "pending": 1, "coords_problem": 1, "no_location": 2}
    assert by["NJ"] == {"not_river": 1}
    assert idx["outfalls"]["NY0027081-060M"]["error"] == "no flowlines" and idx["runs"][-1]["traced"] == 3
    assert R.read_json(R.REACH_INDEX)["live_states"] == ["NJ", "NY", "PA"]


def test_only_one_run_traces_at_a_time(cache):
    a, b = R.TraceLock(), R.TraceLock()
    assert a.acquire() is True
    assert b.acquire() is False
    a.release()
    assert b.acquire() is True
    b.release()


def test_repeated_service_errors_stop_a_run(cache, monkeypatch):
    def broken(o, cap, prev=None):
        return {**fake_trace(cut="no_trace")(o, cap, prev), "error": "ConnectionError: refused"}
    monkeypatch.setattr(R, "trace", broken)
    run, _ = R.run_traces(outfalls(20), 40, R.Budget(0, 0), log=lambda m: None)
    assert run["traced"] == R.SERVICE_ERRORS and "service error" in run["stopped"]


# ---------------------------------------------------------------- the NHDPlus walk

def fl_feature(comid, hs, dn, lp, pathlength, km=1.0, terminal=0, x=0.0):
    return {"attributes": {"comid": comid, "hydroseq": hs, "dnhydroseq": dn, "levelpathid": lp, "pathlength": pathlength,
                           "lengthkm": km, "terminalflag": terminal, "tidal": 0, "gnis_name": "Test River"},
            "geometry": {"paths": [[[x, 40.0], [x + 0.01, 40.0]]]}}


def test_the_nhdplus_walk_follows_level_paths_downstream_to_the_distance(monkeypatch):
    # level path 7: comids 1 (start), 2; it drains (dnhydroseq 50) into level path 9: 3, 4, 5 (5 beyond 45 km)
    net = [fl_feature(1, 100, 90, 7, 60), fl_feature(2, 90, 50, 7, 59), fl_feature(3, 50, 40, 9, 58),
           fl_feature(4, 40, 30, 9, 30), fl_feature(5, 30, 0, 9, 10, terminal=1)]
    asked = []

    def where(w):
        asked.append(w)
        import re as _re
        if w.startswith("comid = "):
            return [f for f in net if f["attributes"]["comid"] == int(w.split("= ")[1])]
        if w.startswith("hydroseq = "):
            return [f for f in net if f["attributes"]["hydroseq"] == int(w.split("= ")[1])]
        lp, hs, floor = _re.match(r"levelpathid = (\d+) AND hydroseq <= (\d+) AND pathlength \+ lengthkm >= ([-\d.]+)", w).groups()
        return [f for f in net if f["attributes"]["levelpathid"] == int(lp) and f["attributes"]["hydroseq"] <= int(hs)
                and f["attributes"]["pathlength"] + f["attributes"]["lengthkm"] >= float(floor)]
    monkeypatch.setattr(R, "flowlines_where", where)
    lines = R.nhdplus_walk(1, 45)
    assert [ln["comid"] for ln in lines] == [1, 2, 3, 4] and 4 in R._ATTR_MEMO      # 5 lies beyond 45 km
    assert lines[0]["coords"] == [[0.0, 40.0], [0.01, 40.0]]
    assert R.nhdplus_walk(1, 100)[-1]["comid"] == 5                                  # to the terminal flowline


def test_a_trace_walks_nhdplus_once_nldi_navigation_is_spent(cache, monkeypatch):
    def nldi(url, timeout=60):
        if "/navigation/" in url:
            R.RATE["nav_remaining"] = 0
            raise R.RateLimited("429")
        if "/npdes/PA0026689042" in url:
            return {"features": [{"geometry": {"coordinates": [-75.0, 40.0]}, "properties": {"comid": 11}}]}
        raise AssertionError(url)
    walked = []

    def walk(comid, dist):
        walked.append(comid)
        R._ATTR_MEMO[11] = {"comid": 11, "hydroseq": 5, "tidal": 0, "wbareacomid": 0, "gnis_name": "Delaware River"}
        return [{"comid": 11, "coords": [[-75.01, 40.0], [-74.9, 40.0]]}]
    monkeypatch.setattr(R, "nldi_get", nldi)
    monkeypatch.setattr(R, "nhdplus_walk", walk)
    monkeypatch.setattr(R, "fetch_attrs", lambda comids: {c: R._ATTR_MEMO[c] for c in comids})
    R.MODE.update(walk=False, nldi_low_until=0.0)
    o = {"key": "PA0026689-042", "permit": "PA0026689", "outfall": "042", "lat": 40.0, "lon": -75.0,
         "reach_id": "02040105000123"}
    rec = R.trace(o, 40)
    assert R.MODE["walk"] is True and walked == [11]
    assert rec["navigation"] == "nhdplus_walk" and rec["method"] == "nldi_npdes" and rec["start_comid"] == 11
    assert rec["segments"][0]["coords"][0] == [-75.0, 40.0] and rec["river"] == "Delaware River"
    # NLDI's whole allowance spent too: the start comes from EPA's catchment layer
    R.set_nldi_low()
    monkeypatch.setattr(R, "catchment_comid", lambda lon, lat: 11)
    rec = R.trace({**o, "reach_id": None}, 40)
    assert rec["method"] == "nhdplus_catchment" and rec["segments"]
    R.MODE.update(walk=False, nldi_low_until=0.0)
    R._ATTR_MEMO.pop(11, None)
