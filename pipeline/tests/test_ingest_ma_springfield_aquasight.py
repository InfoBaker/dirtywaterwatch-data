"""Springfield Water and Sewer Commission's live CSO map (ingest/ma_springfield_aquasight.py). The rows below are cut
from the map's answers of 2026-11-28 (outfall, times, the map's own point and average volume; no staff name), with a few
rows invented for the edge cases (an open overflow, the clock changes, a garbled end). The app's shell and scripts are
synthetic and the keys in them are made up. No network."""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime

import pytest

import common
from common import read_json, write_json
from ingest import ma_massdep as M
from ingest import ma_springfield_aquasight as S

NOW = datetime(2026, 11, 28, 1, 30, 32, tzinfo=UTC)       # 2026-11-27 20:30 in Springfield
FAKE_KEY = "Zq" * 32                                        # 64 letters, the shape of the real key
OTHER_KEY = "Xy" * 32


def cfg(asset, lat, lon, water, avg, when="2026-01-12 14:23:47", **kw):
    return {"asset": asset, "description": f"{asset[:3]}-{asset[3:]} Overflow Volume", "address": "Example Street",
            "latitude": lat, "longitude": lon, "discharge_to": water,
            "affected_locations": "Springfield, West Springfield, Agawam, Longmeadow", "avg_volume": avg,
            "row_create_time": when, "note": "3 year average update", "community_id": S.COMMUNITY,
            "latest_flag": 1, "stat": 1, "not_monitored": None, "flow_rate": None, **kw}


CONFIG = [
    cfg("CSO010", 42.1047, -72.6023, "Connecticut River", 2009573),
    cfg("CSO042", 42.0881, -72.587, "Connecticut River", 4350337),
    cfg("CSO015A", 42.0957, -72.5883, "Connecticut River", 779915),
    cfg("CSO015B", 42.0958, -72.5883, "Connecticut River", 62458),
    cfg("CSO036A", 42.1609, -72.5013, "Chicopee River, Connecticut River", 325364),
    cfg("CSO046", 42.0903, -72.5769, "Mill River, Connecticut River", 122975),
]


def row(rid, asset, start, end, checked=None):
    return {"id": rid, "asset": asset, "start_timestamp": start, "end_timestamp": end,
            "community_id": S.COMMUNITY, "checked": checked, "remarks": None}


LOG = [
    row(70749, "CSO042", "2026-11-26 21:10:00", "2026-11-26 21:40:00", "2026-11-26 22:40:10"),
    row(70970, "CSO010", "2026-11-26 20:15:00", "2026-11-27 00:20:00", "2026-11-27 00:55:07"),
    row(70551, "CSO010", "2026-11-06 11:10:00", "2026-11-06 12:25:00", "2026-11-06 13:00:19"),
    row(60001, "CSO015A", "2025-07-04 10:00:00", "2025-07-04 10:30:00", "2025-07-04 11:00:00"),
    row(18466, "CSO046", "2023-05-20 18:45:00", "0023-05-20 20:45:00", "2023-05-20 20:24:55"),
    row(323, "CSO036A", "2022-03-19 22:35:00", "2022-03-19 23:10:00"),
]

STATUS = [{"asset": "CSO010", "last_updated": "2026-11-27 14:45:00", "status": "noOverflow", "community_id": S.COMMUNITY},
          {"asset": "CSO042", "last_updated": "2026-11-27 20:20:00", "status": "noOverflow", "community_id": S.COMMUNITY},
          {"asset": "CSO015A", "last_updated": "2026-11-27 20:15:00", "status": "noOverflow", "community_id": S.COMMUNITY},
          {"asset": "CSO015B", "last_updated": "2026-11-27 01:15:00", "status": "noOverflow", "community_id": S.COMMUNITY},
          {"asset": "CSO046", "last_updated": "2026-11-27 20:05:00", "status": "Overflowing", "community_id": S.COMMUNITY}]


@pytest.fixture(scope="module")
def ctx():
    return {"echo": M.load_echo(), "layer": {}, "crosswalk": M.load_crosswalk(), "waters": M.load_waters()}


def build(ctx, log=LOG, config=CONFIG):
    by = {c["asset"]: c for c in config}
    return {r["source_record_id"]: r for r in
            (S.to_record(x, by.get(x["asset"]), ctx, "2026-11-28T01:30:32Z") for x in log)}


# ---------------------------------------------------------------- the key

SHELL = ('<!DOCTYPE html><html><head><base href="/"><link rel="stylesheet" href="styles.abc.css"></head><body>'
         '<script src="runtime.1a2b.js" type="module"></script><script src="polyfills.3c4d.js" type="module"></script>'
         '<script src="https://cdn.example.com/evil.js"></script><script src="main.5e6f.js" type="module"></script>'
         '</body></html>')


def bundle(*pairs):
    env = ",".join(f'{{production:!0,serverUrl:"{u}",apiKey:"{k}",mapboxKey:"pk.notakey"}}' for u, k in pairs)
    return f'(self.webpackChunk=[]).push([[179],{{2340:(e,t,n)=>{{const a={env};}}}}]);'


def test_script_addresses_come_from_the_shell_on_the_app_host_main_first():
    urls = S.script_urls(SHELL)
    assert urls[0] == "https://external.aquasight.io/main.5e6f.js"
    assert set(urls) == {"https://external.aquasight.io/main.5e6f.js", "https://external.aquasight.io/runtime.1a2b.js",
                         "https://external.aquasight.io/polyfills.3c4d.js"}


def test_the_key_is_found_next_to_the_api_address():
    assert S.find_key(["var x=1;", bundle(("https://api2.aquasight.io", FAKE_KEY))]) == FAKE_KEY
    # the same key twice is one key; a key for another host is not the API's
    assert S.find_key([bundle(("https://api2.aquasight.io", FAKE_KEY), ("https://other.example.com", OTHER_KEY)),
                       bundle(("https://api2.aquasight.io", FAKE_KEY))]) == FAKE_KEY


def test_no_key_is_a_failed_read_never_a_guess():
    with pytest.raises(S.ReadError, match="no API key"):
        S.find_key(["const e={production:!0,serverUrl:\"https://api2.aquasight.io\"}", bundle()])
    with pytest.raises(S.ReadError, match="no API key"):
        S.find_key([bundle(("https://other.example.com", FAKE_KEY))])


def test_two_different_keys_are_a_failed_read_and_the_error_names_neither():
    with pytest.raises(S.ReadError) as e:
        S.find_key([bundle(("https://api2.aquasight.io", FAKE_KEY)), bundle(("https://api2.aquasight.io", OTHER_KEY))])
    assert "2 different API keys" in str(e.value)
    assert FAKE_KEY not in str(e.value) and OTHER_KEY not in str(e.value)


# ---------------------------------------------------------------- a whole read, without the network

class Resp:
    def __init__(self, status, text=None, data=None):
        self.status_code, self._data = status, data
        self.text = text if text is not None else json.dumps(data)

    def json(self):
        if self._data is None:
            raise ValueError("not JSON")
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"{self.status_code} Client Error for url")


class FakeSession:
    """The app's shell, its scripts and the three tables; every request is recorded."""

    def __init__(self, scripts=None, log=LOG, status=STATUS, config=CONFIG):
        self.calls = []
        self.scripts = scripts or {"main.5e6f.js": bundle(("https://api2.aquasight.io", FAKE_KEY)),
                                   "runtime.1a2b.js": "/*runtime*/", "polyfills.3c4d.js": "/*polyfills*/"}
        self.tables = {"ads_us_config": [dict(c, row_create_user="Pat Example") for c in config],
                       "cso_status": status, "cso_status_log": log}

    def get(self, url, headers=None, timeout=None, allow_redirects=True):
        self.calls.append({"url": url, "headers": dict(headers or {}), "allow_redirects": allow_redirects})
        if url == S.APP_URL:
            return Resp(200, SHELL)
        name = url.rsplit("/", 1)[-1]
        if name in self.scripts:
            return Resp(200, self.scripts[name])
        m = re.match(r"https://api2\.aquasight\.io/api/v2/ace_ads/_table/([a-z_]+)\?", url)
        if m:
            if (headers or {}).get("X-Dreamfactory-API-Key") != FAKE_KEY:
                return Resp(400, data={"error": {"code": 400}})
            return Resp(200, data={"resource": self.tables[m.group(1)]})
        return Resp(404, "")


@pytest.fixture
def raw_dir(tmp_path, monkeypatch):
    d = tmp_path / "raw"
    monkeypatch.setattr(common, "RAW_DIR", d)
    return d


def test_a_live_read_asks_only_the_two_hosts_and_no_key_reaches_any_file(tmp_path, raw_dir, ctx):
    sess = FakeSession()
    assert S.live(sess, NOW, events_dir=tmp_path, ctx=ctx) == 0
    hosts = {re.match(r"https://([^/]+)/", c["url"]).group(1) for c in sess.calls}
    assert hosts == {"external.aquasight.io", "api2.aquasight.io"}
    assert all(c["allow_redirects"] is False for c in sess.calls)
    api = [c for c in sess.calls if "api2" in c["url"]]
    assert sorted(re.search(r"_table/([a-z_]+)", c["url"]).group(1) for c in api) == sorted(S.TABLES)
    assert all("springfield_ma_ads_us" in c["url"] and FAKE_KEY not in c["url"] for c in api)
    assert not any("cdn.example.com" in c["url"] for c in sess.calls)
    written = [tmp_path / f"{S.SOURCE_ID}.json"] + sorted(p for p in raw_dir.rglob("*") if p.is_file())
    assert len(written) == 4                    # the events file and the three answers; never a script
    for p in written:
        text = p.read_text()
        assert FAKE_KEY not in text and "apiKey" not in text and "Pat Example" not in text, p
        assert not re.search(r"(?<![A-Za-z0-9])[A-Za-z0-9]{48,}(?![A-Za-z0-9])", text), p
    doc = read_json(tmp_path / f"{S.SOURCE_ID}.json")
    assert doc["ok"] is True and doc["count"] == len(LOG)


def test_a_missing_key_keeps_the_previous_records(tmp_path, raw_dir, ctx):
    assert S.live(FakeSession(), NOW, events_dir=tmp_path, ctx=ctx) == 0
    sess = FakeSession(scripts={"main.5e6f.js": "const e={production:!0}", "runtime.1a2b.js": "",
                                "polyfills.3c4d.js": ""})
    assert S.live(sess, NOW, events_dir=tmp_path, ctx=ctx) == 1
    doc = read_json(tmp_path / f"{S.SOURCE_ID}.json")
    assert doc["ok"] is False and doc["count"] == len(LOG) and "no API key" in doc["error"]
    assert not any("api2" in c["url"] for c in sess.calls)


def test_two_keys_fail_and_the_error_carries_neither(tmp_path, raw_dir, ctx):
    sess = FakeSession(scripts={"main.5e6f.js": bundle(("https://api2.aquasight.io", FAKE_KEY)),
                                "runtime.1a2b.js": bundle(("https://api2.aquasight.io", OTHER_KEY)),
                                "polyfills.3c4d.js": ""})
    assert S.live(sess, NOW, events_dir=tmp_path, ctx=ctx) == 1
    text = (tmp_path / f"{S.SOURCE_ID}.json").read_text()
    assert FAKE_KEY not in text and OTHER_KEY not in text and "different API keys" in text


def test_a_row_of_another_community_is_a_failed_read(tmp_path, raw_dir, ctx):
    sess = FakeSession(log=LOG + [dict(LOG[0], id=1, community_id="somerville_ma_ads_us")])
    assert S.live(sess, NOW, events_dir=tmp_path, ctx=ctx) == 1
    assert read_json(tmp_path / f"{S.SOURCE_ID}.json")["ok"] is False


def test_the_staff_name_is_dropped_from_the_config():
    out = S.clean_config([dict(CONFIG[0], row_create_user="Pat Example")])
    assert "row_create_user" not in out[0] and out[0]["avg_volume"] == 2009573


# ---------------------------------------------------------------- the crosswalk

def test_the_crosswalk_gives_the_portals_ids(ctx):
    assert S.outfall_of("CSO010")[0] == "SPR010"
    assert S.outfall_of("CSO015A") == ("SPR015A", 15, "A")
    assert S.outfall_of("CSO015B") == ("SPR015B", 15, "B")
    assert S.outfall_of("CSO036A") == ("SPR036A", 36, "A")
    assert S.outfall_of("CSO037")[0] == "SPR037"
    assert S.outfall_of("CSO042")[0] == "SPR042"
    assert S.outfall_of("CSO036")[0] is None            # not an id the map or the portal uses: never guessed
    assert len(S.CROSSWALK) == 24


def test_every_crosswalk_id_is_in_the_echo_registry(ctx):
    assert ctx["echo"], "the ECHO registry did not load"
    check = S.crosswalk_check(ctx)
    assert check["echo_checked"] and check["not_found"] == []


def test_an_asset_not_in_the_crosswalk_keeps_the_maps_own_id_and_point(ctx):
    c = cfg("CSO050", 42.1, -72.6, "Connecticut River", 1000)
    r = S.to_record(row(9, "CSO050", "2026-11-26 21:10:00", "2026-11-26 21:40:00"), c, ctx, "2026-11-28T01:30:32Z")
    assert r["outfall_id"] == "CSO050" and "not in the crosswalk" in r["raw"]["_outfall_note"]
    assert (r["lat"], r["lon"], r["coord_source"]) == (42.1, -72.6, "source")
    assert r["raw"]["_coords"] == "the map's own point for the outfall"


def test_a_record_is_placed_as_the_portal_places_the_outfall(ctx):
    r = build(ctx)["70749"]
    assert r["outfall_id"] == "SPR042" and r["event_type"] == "cso" and r["npdes_permit"] == "MA0101613"
    assert r["water_slugs"] == ["connecticut-river-ma"] and r["coord_source"] == "outfall_layer"
    assert r["discharger_id"] == "ma-springfield-wsc" and r["source_url"] == S.PAGE_URL
    assert r["authority"] == "Springfield Water and Sewer Commission (CSO map, Aquasight)"
    assert r["raw"]["row"] == {k: LOG[0][k] for k in ("asset", "start_timestamp", "end_timestamp", "checked", "remarks")}
    assert r["raw"]["discharge_to"] == "Connecticut River" and r["raw"]["time_basis"].startswith("local clock")


# ---------------------------------------------------------------- times, status, volume

def test_times_are_eastern_and_reported_at_is_the_check_time(ctx):
    r = build(ctx)["70970"]
    assert (r["started_at"], r["ended_at"]) == ("2026-11-26T20:15:00-05:00", "2026-11-27T00:20:00-05:00")
    assert r["reported_at"] == "2026-11-27T00:55:07-05:00" and r["published_at"] is None
    assert r["status"] == "ended" and r["time_precision"] == "minute"
    assert r["advice_window_hours"] == 48 and r["advice_text"].startswith("Avoid contact with these water bodies")


def test_a_row_with_no_end_is_ongoing(ctx):
    r = build(ctx, log=[row(1, "CSO010", "2026-11-27 19:55:00", None, "2026-11-27 20:10:00")])["1"]
    assert r["status"] == "ongoing" and r["ended_at"] is None and r["parse_error"] is None


def test_a_garbled_end_is_not_read_and_not_guessed(ctx):
    r = build(ctx)["18466"]
    assert r["ended_at"] is None and r["status"] == "ended" and "end not read" in r["parse_error"]
    assert r["raw"]["row"]["end_timestamp"] == "0023-05-20 20:45:00"


def test_the_clock_changes(ctx):
    recs = build(ctx, log=[
        row(1, "CSO010", "2024-03-10 01:00:00", "2024-03-10 03:35:00"),     # across the spring change
        row(2, "CSO010", "2024-03-10 02:30:00", "2024-03-10 03:10:00"),     # a time that does not exist
        row(3, "CSO010", "2025-11-02 00:50:00", "2025-11-02 03:10:00"),     # across the autumn change
        row(4, "CSO010", "2025-11-02 01:50:00", "2025-11-02 01:10:00"),     # ends in the repeated hour
    ])
    assert (recs["1"]["started_at"], recs["1"]["ended_at"]) == ("2024-03-10T01:00:00-05:00", "2024-03-10T03:35:00-04:00")
    assert recs["2"]["started_at"] is None and "does not exist" in recs["2"]["parse_error"]
    assert (recs["3"]["started_at"], recs["3"]["ended_at"]) == ("2025-11-02T00:50:00-04:00", "2025-11-02T03:10:00-05:00")
    assert (recs["4"]["started_at"], recs["4"]["ended_at"]) == ("2025-11-02T01:50:00-04:00", "2025-11-02T01:10:00-05:00")
    assert "second occurrence" in recs["4"]["raw"]["_time_note"] and recs["4"]["parse_error"] is None


def test_volume_only_after_the_average_was_set(ctx):
    recs = build(ctx)
    after, before = recs["70970"], recs["60001"]
    assert (after["volume_gal"], after["volume_text"], after["estimate_flag"]) == (2009573, "2,009,573 gallons", "estimated")
    assert "three-year average" in after["raw"]["volume_method"] and "not a measurement" in after["raw"]["volume_method"]
    assert (before["volume_gal"], before["volume_text"], before["estimate_flag"]) == (None, None, "unknown")
    assert "no volume is carried" in before["raw"]["_volume_note"]
    # the boundary itself: an event that starts the minute the average was set carries it
    edge = build(ctx, log=[row(5, "CSO010", "2026-01-12 14:25:00", "2026-01-12 14:40:00"),
                           row(6, "CSO010", "2026-01-12 14:20:00", "2026-01-12 14:40:00")])
    assert edge["5"]["volume_gal"] == 2009573 and edge["6"]["volume_gal"] is None


# ---------------------------------------------------------------- the shrink guard

def test_an_empty_or_shrunken_log_keeps_the_previous_records(tmp_path, ctx):
    out = tmp_path / f"{S.SOURCE_ID}.json"
    assert S.run(CONFIG, STATUS, LOG, NOW, events_dir=tmp_path, out=out, ctx=ctx)[0] == 0
    assert S.run(CONFIG, STATUS, [], NOW, events_dir=tmp_path, out=out, ctx=ctx)[0] == 1
    doc = read_json(out)
    assert doc["ok"] is False and doc["count"] == len(LOG) and "no rows" in doc["error"]
    assert S.run(CONFIG, STATUS, LOG[:2], NOW, events_dir=tmp_path, out=out, ctx=ctx)[0] == 1
    doc = read_json(out)
    assert doc["ok"] is False and doc["count"] == len(LOG) and "2 rows against 6" in doc["error"]
    assert S.run(CONFIG, STATUS, LOG[:3], NOW, events_dir=tmp_path, out=out, ctx=ctx)[0] == 0      # half is enough
    assert read_json(out)["count"] == 3


def test_a_failed_status_read_writes_the_records_with_health_false(tmp_path, ctx):
    out = tmp_path / f"{S.SOURCE_ID}.json"
    code, recs, meta = S.run(CONFIG, None, LOG, NOW, events_dir=tmp_path, out=out, ctx=ctx,
                             status_error="HTTPError: HTTP 500 at api2.aquasight.io")
    doc = read_json(out)
    assert code == 1 and doc["ok"] is False and doc["count"] == len(LOG) and "HTTP 500" in doc["error"]


# ---------------------------------------------------------------- one event, not two

def portal_rec(rid, outfall, start, cls="Public Notification Report", rtype="Initial-Ceased", parent=None,
               published="2026-11-27T09:00:00-05:00"):
    return common.event(source_id="ma-massdep", source_record_id=rid, event_type="cso", status="ended",
                        npdes_permit="MA0101613", outfall_id=outfall, started_at=start, time_precision="minute",
                        published_at=published, parent_event_id=parent,
                        raw={"_report_class": cls, "reportingType": rtype})


def test_a_row_is_the_duplicate_of_the_portals_shown_record(tmp_path, ctx):
    portal = [
        portal_rec("n1", "SPR042", "2026-11-26T21:10:00-05:00"),
        portal_rec("v1", "SPR042", "2026-11-26T21:10:00-05:00", cls="Verified Data Report", rtype=None,
                   parent="ma-massdep:n1", published="2026-12-10T09:00:00-05:00"),
        portal_rec("n2", "SPR010", "2026-11-26T20:40:00-05:00"),            # 25 min from the row: not the same
        portal_rec("n3", "SPR015B", "2025-07-04T10:00:00-04:00"),           # the other outfall at the same point
        portal_rec("n4", "SPR010", "2026-11-06T11:15:00-05:00"),            # 5 min: the same overflow
        portal_rec("x", "SPR010", "2026-11-06T11:10:00-05:00"),
    ]
    portal[-1]["duplicate_of"] = "ma-massdep:n4"                            # a portal copy is never linked to
    write_json(tmp_path / "ma-massdep.json", {"source_id": "ma-massdep", "ok": True, "records": portal})
    code, recs, meta = S.run(CONFIG, STATUS, LOG, NOW, events_dir=tmp_path, out=tmp_path / "out.json", ctx=ctx)
    by = {r["source_record_id"]: r for r in recs}
    assert by["70749"]["duplicate_of"] == "ma-massdep:v1"                   # the family's shown record
    assert "starts 0 min apart" in by["70749"]["raw"]["_link_basis"]
    assert by["70551"]["duplicate_of"] == "ma-massdep:n4"
    assert by["70970"]["duplicate_of"] is None
    assert by["60001"]["duplicate_of"] is None                              # 015A is not 015B
    assert meta["links"]["linked_to_portal"] == 2 and meta["links"]["standing_alone"] == len(LOG) - 2


def test_with_no_portal_file_every_row_stands_alone(tmp_path, ctx):
    code, recs, meta = S.run(CONFIG, STATUS, LOG, NOW, events_dir=tmp_path, out=tmp_path / "out.json", ctx=ctx)
    assert all(r["duplicate_of"] is None for r in recs)
    assert meta["links"]["linked_to_portal"] == 0 and "no ma-massdep events file" in meta["links"]["portal"]


# ---------------------------------------------------------------- current status (meta)

def test_the_current_status_goes_to_meta_with_the_maps_own_rules(tmp_path, ctx):
    code, recs, meta = S.run(CONFIG, STATUS, LOG, NOW, events_dir=tmp_path, out=tmp_path / "out.json", ctx=ctx)
    by = {o["asset"]: o for o in meta["outfalls"]}
    assert by["CSO010"]["map_status"] == "overflowed"           # noOverflow, but an overflow in the last 56 hours
    assert by["CSO010"]["map_label"] == "Overflow in Last 48 Hours"
    assert by["CSO015A"]["map_status"] == "noOverflow"
    assert by["CSO015B"]["map_status"] == "notActive"           # not updated in 12 hours
    assert by["CSO036A"]["map_status"] == "notActive"           # missing from the status answer
    assert by["CSO046"]["map_label"] == "Overflow Occurring"
    assert meta["data_not_received"] == ["SPR015B", "SPR036A"]
    assert all(r["event_type"] == "cso" for r in recs)          # status rows never become events
    text = json.dumps(meta).lower()
    assert "clean" not in text and "not a finding that the water is safe" in text


# ---------------------------------------------------------------- Astra 2026-11-28

def test_an_ongoing_row_is_never_linked(tmp_path, ctx):
    """P1 (a): an overflow the map shows as going on stands on its own, never behind a portal record."""
    write_json(tmp_path / "ma-massdep.json", {"source_id": "ma-massdep", "ok": True,
                                              "records": [portal_rec("n9", "SPR010", "2026-11-27T19:55:00-05:00")]})
    log = [row(1, "CSO010", "2026-11-27 19:55:00", None, "2026-11-27 20:10:00")]
    code, recs, meta = S.run(CONFIG, STATUS, log, NOW, events_dir=tmp_path, out=tmp_path / "out.json", ctx=ctx)
    assert recs[0]["status"] == "ongoing" and recs[0]["duplicate_of"] is None
    assert meta["links"]["linked_to_portal"] == 0


def test_a_portal_record_that_starts_after_the_rows_end_is_another_overflow(tmp_path, ctx):
    """P2: the map's 10:00-10:05 and the portal's 10:10 at the same outfall are two overflows."""
    write_json(tmp_path / "ma-massdep.json", {"source_id": "ma-massdep", "ok": True,
                                              "records": [portal_rec("n8", "SPR010", "2026-11-20T10:10:00-05:00")]})
    log = [row(1, "CSO010", "2026-11-20 10:00:00", "2026-11-20 10:05:00"),
           row(2, "CSO010", "2026-11-20 10:10:00", "2026-11-20 10:15:00")]
    code, recs, meta = S.run(CONFIG, STATUS, log, NOW, events_dir=tmp_path, out=tmp_path / "out.json", ctx=ctx)
    by = {r["source_record_id"]: r for r in recs}
    assert by["1"]["duplicate_of"] is None and by["2"]["duplicate_of"] == "ma-massdep:n8"


def test_one_row_that_does_not_build_keeps_its_previous_record(tmp_path, ctx, monkeypatch):
    """P3: a far-future end is read as out of range (the record stays, with a parse error); a row that raises keeps
    the previous version of its record, and the run's health is false."""
    out = tmp_path / "out.json"
    log = LOG + [row(100 + i, "CSO042", f"2026-10-{10 + i} 10:00:00", f"2026-10-{10 + i} 10:30:00") for i in range(6)]
    assert S.run(CONFIG, STATUS, log, NOW, events_dir=tmp_path, out=out, ctx=ctx)[0] == 0
    bad = [dict(LOG[0], end_timestamp="9999-12-31 23:59:00")] + log[1:]
    code, recs, meta = S.run(CONFIG, STATUS, bad, NOW, events_dir=tmp_path, out=out, ctx=ctx)
    r = {x["source_record_id"]: x for x in recs}["70749"]
    assert code == 0 and len(recs) == len(log) and r["ended_at"] is None and "out of range" in r["parse_error"]
    real = S.to_record

    def boom(row, *a, **k):
        if row.get("id") == 70970:
            raise OverflowError("date value out of range")
        return real(row, *a, **k)
    monkeypatch.setattr(S, "to_record", boom)
    code, recs, meta = S.run(CONFIG, STATUS, log, NOW, events_dir=tmp_path, out=out, ctx=ctx)
    doc = read_json(out)
    assert code == 1 and doc["ok"] is False and doc["count"] == len(log) and meta["kept_previous"] == 1
    kept = {x["source_record_id"]: x for x in doc["records"]}["70970"]
    assert kept["ended_at"] == "2026-11-27T00:20:00-05:00" and kept["raw"]["_kept_previous_since"]


def test_many_rows_that_do_not_build_are_a_failed_read(tmp_path, ctx, monkeypatch):
    out = tmp_path / "out.json"
    assert S.run(CONFIG, STATUS, LOG, NOW, events_dir=tmp_path, out=out, ctx=ctx)[0] == 0
    before = read_json(out)["records"]

    def boom(row, *a, **k):
        raise OverflowError("date value out of range")
    monkeypatch.setattr(S, "to_record", boom)
    assert S.run(CONFIG, STATUS, LOG, NOW, events_dir=tmp_path, out=out, ctx=ctx)[0] == 1
    doc = read_json(out)
    assert doc["ok"] is False and doc["records"] == before and "did not build" in doc["error"]


def test_the_volume_basis_reaches_the_public_detail_and_the_csv(ctx):
    """P5: the reader is told the figure is the outfall's three-year average, the operator's estimate."""
    from export import csv as C
    from export import detail as D
    r = build(ctx)["70970"]
    det = D.detail_of(r)
    assert det["volume_qualifier"] == "estimated"
    for words in ("Springfield Water and Sewer Commission", "three-year average", "not a measurement of this event"):
        assert words in det["volume_method"], words
    e = {**r, "detail": det}
    row_ = dict(zip(C.COLUMNS, C.event_row(e, C._Context([], [], {}, C.SiteLinks([e], [], [], set())))[0]))
    assert row_["volume_gal"] == "2009573" and row_["volume_qualifier"] == "estimated"
    assert "three-year average" in row_["volume_method"] and "not a measurement" in row_["volume_method"]
    assert "volume_method" not in D.detail_of(build(ctx)["60001"])       # no volume, no method


# ---------------------------------------------------------------- the map's end on the portal record (build/status.py)

def _load(tmp_path, portal, mapped):
    from build import status as ST
    d = tmp_path / "events"
    d.mkdir(exist_ok=True)
    for sid, rs in (("ma-massdep", portal), (S.SOURCE_ID, mapped)):
        (d / f"{sid}.json").write_text(json.dumps({"source_id": sid, "fetched_at": "2026-11-28T01:00:00Z", "ok": True,
                                                    "count": len(rs), "records": rs}))
    _, events, problems = ST.load_events(d)
    return ST, {e["event_id"]: e for e in events}


def _mapped(ctx, start, end, dup):
    r = build(ctx, log=[row(7, "CSO010", start, end)])["7"]
    r["duplicate_of"] = dup
    return r


def test_a_portal_record_with_no_end_takes_the_maps_end(tmp_path, ctx):
    p = portal_rec("n1", "SPR010", "2026-11-26T20:15:00-05:00")
    p["status"] = "ongoing"
    m = _mapped(ctx, "2026-11-26 20:15:00", "2026-11-27 00:20:00", p["event_id"])
    ST, ev = _load(tmp_path, [p], [m])
    t = ev[p["event_id"]]
    assert t["ended_at"] == "2026-11-27T00:20:00-05:00" and t["status"] == "ended"
    assert t["raw"]["_ended_at_from"] == m["event_id"] and t["raw"]["_ended_at_precision"] == "minute"
    assert t["raw"]["_ended_at_basis"].startswith("end time from the operator's CSO map, record ")
    assert "so this record is ended" in t["raw"]["_ended_at_basis"]
    rules = ST.read_json(ST.DATA_DIR / "rules.json")
    ivs = ST._event_intervals(t, "MA", datetime(2026, 11, 27, 12, 0, tzinfo=UTC), None, rules)
    assert ivs and min(iv["start"] for iv in ivs) <= datetime(2026, 11, 27, 1, 15, tzinfo=UTC)
    assert all(iv["end"] <= datetime(2026, 11, 27, 5, 20, tzinfo=UTC) + ST.timedelta(hours=73) for iv in ivs)


def test_the_maps_end_replaces_a_bound(tmp_path, ctx):
    p = portal_rec("n2", "SPR010", "2026-11-26T20:15:00-05:00")
    p.update(time_precision="bound")
    p["raw"].update(_ended_before="2026-11-27T09:00:00-05:00", _ended_before_basis="the portal's ceased report")
    m = _mapped(ctx, "2026-11-26 20:15:00", "2026-11-27 00:20:00", p["event_id"])
    _, ev = _load(tmp_path, [p], [m])
    t = ev[p["event_id"]]
    assert t["ended_at"] == "2026-11-27T00:20:00-05:00" and t["time_precision"] == "minute"
    assert "_ended_before" not in t["raw"] and t["raw"]["_ended_before_replaced"] == "2026-11-27T09:00:00-05:00"
    assert "replaces the latest possible end" in t["raw"]["_ended_at_basis"]


def test_an_end_the_portal_record_has_is_kept(tmp_path, ctx):
    p = portal_rec("n3", "SPR010", "2026-11-26T20:15:00-05:00")
    p["ended_at"] = "2026-11-27T01:00:00-05:00"                         # a verified duration's end
    m = _mapped(ctx, "2026-11-26 20:15:00", "2026-11-27 00:20:00", p["event_id"])
    early = portal_rec("n4", "SPR010", "2026-11-27T02:00:00-05:00")       # the map's end is before this start
    m2 = _mapped(ctx, "2026-11-26 20:15:00", "2026-11-27 00:20:00", early["event_id"])
    m2["event_id"] = m2["event_id"] + "b"
    _, ev = _load(tmp_path, [p, early], [m, m2])
    assert ev[p["event_id"]]["ended_at"] == "2026-11-27T01:00:00-05:00"
    assert "_ended_at_from" not in ev[p["event_id"]]["raw"]
    assert ev[early["event_id"]]["ended_at"] is None and "_ended_at_from" not in ev[early["event_id"]]["raw"]


def test_an_ongoing_map_record_gives_no_end(tmp_path, ctx):
    p = portal_rec("n5", "SPR010", "2026-11-27T19:55:00-05:00")
    p["status"] = "ongoing"
    m = _mapped(ctx, "2026-11-27 19:55:00", None, p["event_id"])        # as if linked by an older run
    _, ev = _load(tmp_path, [p], [m])
    assert ev[p["event_id"]]["status"] == "ongoing" and ev[p["event_id"]]["ended_at"] is None


# ---------------------------------------------------------------- Astra 2026-11-28, pass 2

def test_overflows_that_do_not_overlap_are_not_linked(tmp_path, ctx):
    """A portal overflow that starts as the row ends, and a portal record over before the row began, are others."""
    ended = portal_rec("n7", "SPR012", "2026-11-20T09:52:00-05:00")
    ended["ended_at"] = "2026-11-20T09:58:00-05:00"                      # over before the map's row began
    write_json(tmp_path / "ma-massdep.json", {"source_id": "ma-massdep", "ok": True, "records": [
        portal_rec("n6", "SPR010", "2026-11-20T10:05:00-05:00"), ended]})
    log = [row(1, "CSO010", "2026-11-20 10:00:00", "2026-11-20 10:05:00"),
           row(2, "CSO012", "2026-11-20 10:00:00", "2026-11-20 10:30:00")]
    code, recs, meta = S.run(CONFIG, STATUS, log, NOW, events_dir=tmp_path, out=tmp_path / "out.json", ctx=ctx)
    assert [r["duplicate_of"] for r in recs] == [None, None] and meta["links"]["linked_to_portal"] == 0


def test_a_map_end_after_the_map_was_read_changes_nothing(tmp_path, ctx):
    """A mistyped end (2036) must not turn an ongoing portal record into an ended one."""
    p = portal_rec("n9", "SPR010", "2026-11-27T19:55:00-05:00")
    p["status"] = "ongoing"
    m = _mapped(ctx, "2026-11-27 19:55:00", "2026-11-27 20:30:00", p["event_id"])
    m["ended_at"] = "2036-11-27T20:30:00-05:00"
    m["fetched_at"] = "2026-11-28T01:00:00Z"
    _, ev = _load(tmp_path, [p], [m])
    t = ev[p["event_id"]]
    assert t["status"] == "ongoing" and t["ended_at"] is None and "_ended_at_from" not in t["raw"]


def test_springfields_mill_river_outfalls_take_the_mill_river():
    """Outfalls 024, 025 and 048 sit on the dammed Mill River; the registry's nearest water is the lake, by geometry
    alone, which resolve_water sets aside. The crosswalk's NAME@TOWN row places them, in Springfield only."""
    from ingest import ma_massdep as M
    cw = M.load_crosswalk()
    echo = {"water_slug": "lake-massasoit-ma", "water_name": "Lake Massasoit", "match": "geometry"}
    for text in ("Mill River", "Mill River, Connecticut River", "MILL R."):
        slugs, match, note = M.resolve_water([("map", text)], "SPRINGFIELD", echo, cw, {})
        assert slugs == ["mill-river-springfield-ma"] and match == "outfall_registry", (text, slugs, note)
    slugs, match, _ = M.resolve_water([("portal", "MILL RIVER")], "Springfield", None, cw, {})
    assert slugs == ["mill-river-springfield-ma"] and match == "name"
    # another town's Mill River is still left to its permittee's own match
    slugs, match, note = M.resolve_water([("portal", "MILL RIVER")], "TAUNTON", None, cw, {})
    assert slugs == [] and match == "none" and note.get("no_slug")
