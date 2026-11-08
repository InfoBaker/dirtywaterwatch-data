"""Kentucky's other feeds: Louisville MSD's Overflow Advisory Level banner (ingest/ky_louisville_msd.py; fixtures from
the Internet Archive's copies of the page, an MSD-02 notice with its house number replaced, and the live page of
2026-11-07), the Division of Water's HAB Viewer through the generic ArcGIS block (tests/fixtures/ky_dow_hab.json: the
layer's five points of 2026-11-07), and SD1's own rain trigger in the rain caution (rules.json
rain_likely.fallback.by_permit)."""
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import common
from build import rain_likely as RL
from ingest import ky_louisville_msd as K

FIX = Path(__file__).parent / "fixtures"
MSD = FIX / "ky_louisville_msd"
ROOT = Path(__file__).resolve().parents[2]
OUTFALLS = [{"npdes_permit": "KY0022411", "outfall": "019", "outfall_status": "CSO|DSW", "lat": 38.2601,
             "lon": -85.7591, "water_slug": "ohio-river-ky", "water_name": "Ohio River"},
            {"npdes_permit": "KY0022411", "outfall": "210", "outfall_status": "CSO", "lat": 38.2372, "lon": -85.695,
             "receiving_water_echo": "OHIO RIVER"}]


def _snap(name):
    return K.parse((MSD / name).read_text())


# ---------------------------------------------------------------- the page

def test_the_three_levels_are_read_from_the_block():
    one = _snap("msd01-2025-09-04.html")
    assert K.code_of(one) == "MSD-01" and one["level"] == "level-1" and one["title"] == "MSD-01 Wet Weather Overflows."
    assert "until 48 hours after the rain has stopped" in one["text"]
    assert K.code_of(_snap("msd01-2024-02-29.html")) == "MSD-01"                  # the older layout
    two = _snap("msd02-2025-02-19.html")
    assert K.code_of(two) == "MSD-02" and two["level"] == "level-2"
    f = K.fields(two["text"])
    assert f["THIS REPORT CREATED AS OF"] == "2/18/2025 at 5:45 PM"               # its value on the next line
    assert f["DATE AND TIME DISCHARGE BEGAN"] == "2/18/2025 3:15 PM" and f["RECEIVING STREAM"] == "PENNSYLVANIA RUN"
    normal = _snap("normal-2026-11-07.html")
    assert K.code_of(normal) == "normal" and normal["level"] == "level-3"


def test_a_page_without_the_block_is_an_error_never_a_withdrawal():
    try:
        K.parse("<html><body>maintenance</body></html>")
    except ValueError as e:
        assert "no Overflow Advisory Level block" in str(e)
    else:
        raise AssertionError("expected ValueError")


def _history():
    st = {}
    K.update(st, _snap("normal-2026-11-07.html"), "2026-04-01T10:00:00Z")
    K.update(st, _snap("msd02-2025-02-19.html"), "2026-04-01T11:00:00Z")
    K.update(st, _snap("msd01-2025-09-04.html"), "2026-04-01T12:00:00Z")
    K.update(st, _snap("msd01-2024-02-29.html"), "2026-04-01T13:00:00Z")     # the same banner (text reflowed)
    K.update(st, _snap("normal-2026-11-07.html"), "2026-04-01T20:00:00Z")
    return st


def test_snapshots_open_confirm_and_close_each_notice():
    st = _history()
    apps = st["appearances"]
    assert [a["code"] for a in apps] == ["MSD-02", "MSD-01"]
    assert apps[0]["first_seen"] == "2026-04-01T11:00:00Z" and apps[0]["left_at"] == "2026-04-01T12:00:00Z"
    assert apps[1]["first_seen"] == "2026-04-01T12:00:00Z" and apps[1]["last_seen"] == "2026-04-01T13:00:00Z"
    assert apps[1]["left_at"] == "2026-04-01T20:00:00Z"


def test_msd01_is_msds_advisory_at_each_open_outfall_red_while_it_stands():
    st = {}
    K.update(st, _snap("msd01-2025-09-04.html"), "2026-04-01T12:00:00Z")
    recs = K.records(st, OUTFALLS)
    assert len(recs) == 2
    r = next(x for x in recs if x["outfall_id"] == "019")
    assert r["event_type"] == "cso" and r["status"] == "advisory_active" and r["npdes_permit"] == "KY0022411"
    assert r["lat"] == 38.2601 and r["coord_source"] == "outfall_registry" and r["water_slugs"] == ["ohio-river-ky"]
    assert r["started_at"] == "2026-04-01T12:00:00Z" and r["time_precision"] == "poll" and r["ended_at"] is None
    # the source gives no time: never the fetch time in the source's fields
    assert r["reported_at"] is None and r["published_at"] is None and r["source_updated_at"] is None
    assert r["raw"]["_last_seen_in_source"] == "2026-04-01T12:00:00Z" and r["raw"]["advisory_scope"] == "system-wide"
    assert r["advice_text"].startswith("MSD: “Recent rainfall") and "48 hours after the rain" in r["advice_text"]
    assert "Customer Relations" not in r["advice_text"] and "502" not in json.dumps(r)
    assert r["raw"]["time_zone"] == "America/New_York"
    other = next(x for x in recs if x["outfall_id"] == "210")
    assert other["water_slugs"] == [] and other["waterbody_text"] == "OHIO RIVER"


def test_msd01_withdrawn_ends_at_the_poll_that_no_longer_shows_it():
    recs = [r for r in K.records(_history(), OUTFALLS) if r["raw"].get("advisory_code") == "MSD-01"]
    assert {r["status"] for r in recs} == {"advisory_lifted"}
    r = recs[0]
    assert r["ended_at"] == "2026-04-01T20:00:00Z" and r["raw"]["ended_at_precision"] == "poll"
    assert r["source_record_id"].startswith("MSD-01:2026-04-01T12:00:00Z:")       # stable across runs


def test_msd02_is_a_dated_report_with_msds_times_and_no_invented_end():
    r = next(x for x in K.records(_history(), OUTFALLS) if x["raw"].get("advisory_code") == "MSD-02")
    assert r["event_type"] == "sso" and r["status"] == "ongoing" and r["ended_at"] is None   # COMPLETED: ONGOING
    assert r["started_at"] == "2025-02-18T15:15:00-05:00" and r["time_precision"] == "minute"
    assert r["reported_at"] == "2025-02-18T17:45:00-05:00" and r["published_at"] is None
    assert r["waterbody_text"] == "Pennsylvania Run" and r["lat"] is None and r["npdes_permit"] is None
    assert r["volume_gal"] is None and r["volume_text"].startswith("UNKNOWN AT THIS TIME")
    assert r["raw"]["asset_address"] == "[house number removed] EXAMPLE DR LOUISVILLE KY 40229"
    assert "1234" not in json.dumps(r) and r["raw"]["left_page_at"] == "2026-04-01T12:00:00Z"
    assert r["raw"]["county"] == "Jefferson" and r["raw"]["time_zone"] == "America/New_York"


def test_msd02_with_a_completion_time_has_an_exact_end():
    snap = _snap("msd02-2025-02-19.html")
    snap["text"] = snap["text"].replace("COMPLETED DATE/TIME: ONGOING", "COMPLETED DATE/TIME: 2/18/2025 9:40 PM") \
                               .replace("GREATER THAN 10,000 GALLONS", "").replace(
        "DISCHARGED AMOUNT: UNKNOWN AT THIS TIME BUT ", "DISCHARGED AMOUNT: 12,500 GALLONS")
    st = K.update({}, snap, "2026-04-01T11:00:00Z")
    r = K.records(st, OUTFALLS)[0]
    assert r["status"] == "ended" and r["ended_at"] == "2025-02-18T21:40:00-05:00"
    assert r["raw"]["ended_at_precision"] == "minute" and r["volume_gal"] == 12500


def test_an_unknown_wording_is_kept_with_a_parse_error():
    st = K.update({}, {"level": "level-1", "title": "MSD-03 Example Advisory", "text": "Example"}, "2026-04-01T11:00:00Z")
    r = K.records(st, OUTFALLS)[0]
    assert r["event_type"] == "unknown" and "not recognised" in r["parse_error"]


def test_main_reads_a_saved_page_and_keeps_its_state(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path / "events")
    monkeypatch.setattr(K, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(K, "msd_outfalls", lambda: OUTFALLS)
    monkeypatch.setattr(K, "write_events", lambda sid, recs, **kw: common.write_events(
        sid, recs, path=tmp_path / "events" / f"{sid}.json", **kw))
    assert K.main(["--file", str(MSD / "msd01-2025-09-04.html"), "--at", "2026-04-01T12:00:00Z"]) == 0
    assert K.main(["--file", str(MSD / "normal-2026-11-07.html"), "--at", "2026-04-01T14:00:00Z"]) == 0
    doc = json.loads((tmp_path / "events" / f"{K.SOURCE_ID}.json").read_text())
    assert doc["count"] == 2 and {r["status"] for r in doc["records"]} == {"advisory_lifted"}
    assert K.main(["--file", str(FIX / "ky_sobe_rows.json")]) == 1                # not the page: ok false, kept
    doc = json.loads((tmp_path / "events" / f"{K.SOURCE_ID}.json").read_text())
    assert doc["ok"] is False and doc["count"] == 2


def test_msds_outfalls_come_from_the_registry_open_rows_only():
    rows = K.msd_outfalls()
    assert len(rows) >= 100 and all(r["npdes_permit"] == "KY0022411" for r in rows)
    assert not any(str(r.get("outfall_status")).upper().startswith("CLS") for r in rows)


# ---------------------------------------------------------------- the HAB Viewer (generic ArcGIS block)

def _habs(rows_extra=()):
    from ingest.generic import arcgis, runner
    _, block = runner.load_source("ky-dow-hab-viewer")
    rows = arcgis.parse(block, (FIX / "ky_dow_hab.json").read_bytes()) + list(rows_extra)
    return block, runner.build("ky-dow-hab-viewer", block, rows, "2026-11-07T23:00:00Z", [])


def test_hab_block_keeps_advisory_levels_only_with_the_points_clock():
    from ingest.generic import runner
    block, (recs, stats) = _habs()
    assert block["live"] is True and not runner.validate_block(block)
    assert stats["rows"] == 5 and stats["records_written"] == 1                 # Below and NoDetect are grey
    r = recs[0]
    assert r["event_type"] == "hab_advisory" and r["status"] == "advisory_active"
    assert r["waterbody_text"] == "Old Springfield Reservoir" and r["started_at"] == "2026-10-28"
    assert r["time_precision"] == "day" and r["raw"]["time_zone"] == "America/New_York"
    assert r["lat"] == 37.68857400038352 and "Recreational Public Health Advisory issued" in r["advice_text"]


def test_hab_point_in_a_central_county_and_the_divisions_end():
    from ingest.generic import arcgis
    block, _ = _habs()
    raw = json.loads((FIX / "ky_dow_hab.json").read_text())
    row = arcgis.parse(block, json.dumps(raw).encode())[0]                      # Caneyville Reservoir, Grayson County
    row.update(HABSTATUS="Warning", OBJECTID=1, HABEND=1790553600000)           # 2026-09-28
    _, (recs, _) = _habs([row])
    r = next(x for x in recs if x["source_record_id"].startswith("1-"))
    assert r["raw"]["time_zone"] == "America/Chicago" and r["status"] == "advisory_lifted"
    assert r["started_at"] == "2026-09-09" and r["ended_at"] == "2026-09-28"


# ---------------------------------------------------------------- SD1's rain trigger

def test_sd1s_own_rule_applies_in_its_season_with_its_72_hours():
    rules = json.loads((ROOT / "data" / "rules.json").read_text())
    june = RL.threshold_for("KY0021466", "KY", {}, rules, datetime(2026, 6, 15, tzinfo=UTC))
    assert june["threshold_in"] == 0.25 and june["tail_hours"] == 72 and june["kind"] == "operator_rule"
    assert june["trigger_basis"] == "operator" and "0.25 inches" in june["text"]
    assert june["rule"] == "rain_likely.fallback.by_permit.KY0021466"
    dec = RL.threshold_for("KY0021466", "KY", {}, rules, datetime(2026, 12, 15, tzinfo=UTC))
    assert dec["threshold_in"] == 0.1 and dec["kind"] == "site_default" and "tail_hours" not in dec
    other = RL.threshold_for("KY0022411", "KY", {}, rules, datetime(2026, 6, 15, tzinfo=UTC))   # Louisville MSD
    assert other["kind"] == "site_default"
    # without a time the rule applies (the season is the operator's; callers that know the time pass it)
    assert RL.threshold_for("KY0021466", "KY", {}, rules)["threshold_in"] == 0.25


def test_kentucky_rules_row_cites_the_regulation_and_the_operators():
    rules = json.loads((ROOT / "data" / "rules.json").read_text())
    ky = rules["red"]["by_state"]["KY"]
    assert ky["hours"] is None and ky["clock"] == "end_of_discharge"
    assert "401 KAR 5:065" in ky["source"] and "49 CFR 71.5(c)" in ky["source"]
    for word in ("safe", "clean"):
        assert word not in ky["basis"].lower()
    assert "KY" in rules["live_states"]   # live since 2026-11-08 (final audit docs/checklists/2026-11-08-ky-final.md)


# ---------------------------------------------------------------- review 2026-11-08: MSD-01 is one advisory

def _msd01(lifted=False):
    st = {}
    K.update(st, _snap("msd01-2025-09-04.html"), "2026-04-01T12:00:00Z")
    if lifted:
        K.update(st, _snap("normal-2026-11-07.html"), "2026-04-01T14:00:00Z")
    outs = [{"npdes_permit": "KY0022411", "outfall": f"00{i}", "outfall_status": "CSO", "lat": 38.25 + i / 100,
             "lon": -85.7, "water_slug": "ohio-river-ky"} for i in range(3)]
    return K.records(st, outs)


def test_msd01_is_no_discharge_in_the_charts_and_one_advisory_per_water():
    """P2-1: a banner at three outfalls was three CSO discharge events; now 0 events and the advisory once."""
    from build import charts as C

    class D:
        pass
    d = D()
    d.events, d.superseded, d.duplicates, d.effective, d.dropped = _msd01(), set(), {}, {}, {}
    d.waters = {"ohio-river-ky": {"state": "KY", "kind": "river", "name": "Ohio River"}}
    d.status, d.slugs = {}, (lambda ev: ["ohio-river-ky"])
    buckets, stats, _ = C.gather(d)
    assert not any(bk.events for bk in buckets.values())
    assert len(buckets[("water", "ohio-river-ky")].advisories) == 1
    assert not any(k.startswith("counted") for k in stats)


def test_msd01_never_absorbs_an_echo_report_of_the_same_day():
    from build import status as S
    echo = {"event_id": "echo-sewer-overflow:KY0022411:X:1", "source_id": "echo-sewer-overflow",
            "event_type": "sso", "status": "ended", "npdes_permit": "KY0022411", "outfall_id": None,
            "started_at": "2026-04-01T09:00:00-04:00", "ended_at": "2026-04-01T10:00:00-04:00",
            "time_precision": "minute", "waterbody_text": "Beargrass Creek", "water_slugs": [], "raw": {}}
    dup = S.find_duplicates(_msd01() + [echo])
    assert echo["event_id"] not in dup and not any(k.startswith(K.SOURCE_ID) for k in dup)


def test_after_msds_lift_the_sites_caution_follows_and_the_rain_caution_is_never_held_back():
    """P2-2: the water went grey at the lift and the rain caution read 'suppressed' for 24 hours."""
    from build import status as S
    r = _msd01(lifted=True)[0]
    ivs = S.event_intervals(r, "KY", datetime(2026, 4, 1, 20, tzinfo=UTC), None, S.load_rules())
    red = [iv for iv in ivs if iv["color"] == "red"]
    after = [iv for iv in ivs if iv["color"] == "yellow"]
    assert red and red[0]["end"] == datetime(2026, 4, 1, 14, tzinfo=UTC)
    assert after and after[0]["start"] == red[0]["end"] and (after[0]["end"] - after[0]["start"]).total_seconds() >= 72 * 3600
    assert RL.discharge_starts(_msd01(lifted=True)) == {}


def test_a_banner_no_read_confirms_ages_out_after_48_hours():
    from build import status as S
    r = _msd01()[0]                                   # active, last read 2026-04-01T12:00Z
    ivs = S.event_intervals(r, "KY", datetime(2026, 4, 10, tzinfo=UTC), None, S.load_rules())
    red = [iv for iv in ivs if iv["color"] == "red"]
    assert red and red[0]["end"] == datetime(2026, 4, 3, 12, tzinfo=UTC)


def test_the_state_file_and_the_raw_save_keep_no_house_number(tmp_path, monkeypatch):
    """P2-6: the MSD-02 asset's house number was kept in the state file saved to R2."""
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path / "events")
    monkeypatch.setattr(K, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(K, "msd_outfalls", lambda: OUTFALLS)
    monkeypatch.setattr(K, "write_events", lambda sid, recs, **kw: common.write_events(
        sid, recs, path=tmp_path / "events" / f"{sid}.json", **kw))
    saved = []
    monkeypatch.setattr(K, "save_raw", lambda sid, content, ext: saved.append(content))
    monkeypatch.setattr(K, "fetch", lambda: (MSD / "msd02-2025-02-19.html").read_text())
    assert K.main(["--at", "2026-04-01T12:00:00Z"]) == 0
    state = (tmp_path / "state.json").read_text()
    assert "1234" not in state and "[house number removed] EXAMPLE DR" in state
    assert saved and all(b"1234" not in s for s in saved)


# ---------------------------------------------------------------- review 2026-11-08 P2-3: SD1's season per episode

def _sd1_world(now, values):
    from build import status as S
    from tests import test_rain_likely as T
    w = T.rain_world(values=values, now=now)
    w["rain"]["thresholds"] = {}                       # no history: the published rules decide
    fb = w["rules"]["rain_likely"]["fallback"]
    w["rules"] = {**w["rules"], "rain_likely": {**w["rules"]["rain_likely"], "fallback": {**fb, "by_permit": {
        T.PERMIT: {"inches": 0.25, "tail_hours": 72, "time_zone": "America/New_York", "months": [5, 6, 7, 8, 9, 10],
                   "basis": "the operator's rule", "source": "the operator"}}}}}
    return S, w


def test_sd1s_season_is_read_by_the_episodes_start_in_local_time(monkeypatch):
    from build import status as S0
    from tests import test_rain_likely as T
    monkeypatch.setattr(S0, "_RULES", T.TEST_RULES)
    H = timedelta(hours=1)
    # 22:00 on 31 October in Kentucky (02:00Z on 1 November): an October storm that fell below 54 hours ago is
    # still under SD1's 72 hours (the build's UTC month had switched to the default 48 hours: grey)
    now = datetime(2026, 11, 1, 2, tzinfo=UTC)
    S, w = _sd1_world(now, T.wet(range(55, 61), v=1.2))
    st, _ = S.build(now=now, write=False, **w)
    pond = st["waters"]["other-pond-ma"]
    assert pond["status"] == "yellow" and pond["reasons"][0]["rain"]["threshold_in"] == 0.25
    assert pond["reasons"][0]["until"].startswith(S.iso(now - 54 * H + 72 * H)[:16])
    # an April 30 rain of 0.2 inch is under the default 0.1 inch, also once May has begun (it went grey)
    now = datetime(2026, 5, 1, 12, tzinfo=UTC)
    S, w = _sd1_world(now, T.wet(range(14, 21), v=0.2))
    st, _ = S.build(now=now, write=False, **w)
    pond = st["waters"]["other-pond-ma"]
    assert pond["status"] == "yellow" and pond["reasons"][0]["rain"]["threshold_in"] == 0.1


def test_the_operator_rule_reads_its_months_in_its_own_zone():
    rule = {"inches": 0.25, "months": [5, 6, 7, 8, 9, 10], "time_zone": "America/New_York"}
    assert RL.in_season(rule, datetime(2026, 11, 1, 2, tzinfo=UTC))           # 31 October, 22:00 local
    assert not RL.in_season(rule, datetime(2026, 5, 1, 3, tzinfo=UTC))        # 30 April, 23:00 local


def test_sd1s_published_rule_comes_before_a_history_row():
    """Review 2026-11-08 P3-5: a history row would have replaced SD1's rule silently."""
    rules = json.loads((ROOT / "data" / "rules.json").read_text())
    hist = {"permits": {"KY0021466": {"threshold_in": 0.4, "basis": "history", "rule": "rain_likely.percentile"}}}
    june = RL.threshold_for("KY0021466", "KY", hist, rules, datetime(2026, 6, 15, tzinfo=UTC))
    assert june["kind"] == "operator_rule" and june["threshold_in"] == 0.25
    dec = RL.threshold_for("KY0021466", "KY", hist, rules, datetime(2026, 12, 15, tzinfo=UTC))
    assert dec["kind"] == "operator_history" and dec["threshold_in"] == 0.4


def test_a_bloom_on_a_named_reservoir_is_never_placed_on_a_stream_near_its_point(tmp_path):
    """Final audit 2026-11-08 P2-3: Old Springfield Reservoir's advisory sat on road-run-ky."""
    from build import status as S
    block, (recs, _) = _habs()
    r = recs[0]
    assert r["waterbody_text"] == "Old Springfield Reservoir" and r["raw"]["_placement"] == "named_water_only"
    d = tmp_path / "events"
    d.mkdir()
    (d / "ky-dow-hab-viewer.json").write_text(json.dumps({"source_id": "ky-dow-hab-viewer", "ok": True,
                                                         "last_ok_at": "2026-11-07T23:00:00Z", "meta": {},
                                                         "records": recs}))
    lat, lon = r["lat"], r["lon"]
    road = {"slug": "road-run-ky", "name": "Road Run", "kind": "stream", "state": "KY",
            "bbox": [lon - 0.002, lat - 0.002, lon + 0.002, lat + 0.002],
            "geometry": {"type": "LineString", "coordinates": [[lon - 0.002, lat - 0.001], [lon + 0.002, lat + 0.001]]}}
    rules = json.loads((ROOT / "data" / "rules.json").read_text())
    rules["live_states"] = list(rules["live_states"]) + ["KY"]
    rules["rain_likely"] = {**rules["rain_likely"], "enabled": False}
    S._GEOM_CACHE.clear()
    S._REACH_WATERS.clear()
    st, _ = S.build(now=datetime(2026, 11, 8, tzinfo=UTC), write=False, events_dir=d, waters={"road-run-ky": road},
                    outfalls=[], registry={}, reaches={}, flows=({}, {}), rules=rules, placement_cache=False)
    pts = [p for p in st["advisory_points"] if p["event_id"].startswith("ky-dow-hab-viewer")]
    assert len(pts) == 1 and pts[0]["water_slugs"] == [] and pts[0]["status"] == "red"
    assert (st["waters"].get("road-run-ky") or {}).get("status", "grey") == "grey"


def test_msd01_rationale_says_its_own_age_out():
    """Final audit 2026-11-08 P3-1."""
    from build import status as S
    r = _msd01()[0]
    ivs = S.event_intervals(r, "KY", datetime(2026, 4, 1, 13, tzinfo=UTC), None, S.load_rules())
    red = next(iv for iv in ivs if iv["color"] == "red")
    assert "48 hours after the last read" in red["rule_applied"]["rationale"] and "14 days" not in red["rule_applied"]["rationale"]


def test_msd_outfalls_ignore_the_kentucky_corrections_file():
    assert len(K.msd_outfalls()) == 121


# ---------------------------------------------------------------- the HAB Viewer's back-end failure (2026-11-08)

class _Resp:
    def __init__(self, body):
        self.content = json.dumps(body).encode()
        self.headers = {"content-type": "application/json"}

    def raise_for_status(self):
        pass

    def json(self):
        return json.loads(self.content)


class _Sess:
    """Answers the layer's query with the server's error first, then the saved page; the layer's description after."""
    def __init__(self, errors):
        self.errors, self.calls = errors, 0

    def get(self, url, params=None, timeout=None):
        if url.endswith("/query"):
            self.calls += 1
            if self.calls <= self.errors:
                return _Resp({"error": {"code": 400, "message": "Failed to execute query.", "details": []}})
            return _Resp(json.loads((FIX / "ky_dow_hab.json").read_text()))
        return _Resp({"name": "Observation Points"})


def test_the_hab_viewers_query_error_is_asked_again_and_other_layers_are_unchanged(monkeypatch):
    """Refresh run 42440292355: the server answered 'Failed to execute query.' (400) to a query it answered with all
    five rows minutes later; the block asks again, other ArcGIS blocks fail at once as before."""
    from ingest.generic import arcgis, runner
    monkeypatch.setattr(arcgis.time, "sleep", lambda s: None)
    _, block = runner.load_source("ky-dow-hab-viewer")
    assert block["query_retries"] == 3 and not runner.validate_block(block)
    sess = _Sess(errors=2)
    rows = arcgis.parse(block, arcgis.fetch(block, sess).content)
    assert sess.calls == 3 and len(rows) == 5
    _, recs = None, runner.build("ky-dow-hab-viewer", block, rows, "2026-11-08T04:00:00Z", [])[0]
    assert len(recs) == 1 and recs[0]["waterbody_text"] == "Old Springfield Reservoir"
    other = {k: v for k, v in block.items() if k not in ("query_retries", "retry_wait_s")}
    try:
        arcgis.fetch(other, _Sess(errors=1))
    except RuntimeError as e:
        assert "Failed to execute query" in str(e)
    else:
        raise AssertionError("a block without query_retries fails at once")
    try:
        arcgis.fetch(block, _Sess(errors=9))
    except RuntimeError as e:
        assert "Failed to execute query" in str(e)
    else:
        raise AssertionError("a layer that keeps failing still fails the fetch")
