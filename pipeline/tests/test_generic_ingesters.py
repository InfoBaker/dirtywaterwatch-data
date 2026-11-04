"""The generic ingesters (docs/generic-ingesters.md): the field map, each platform's reader on a saved response,
the runner's events file, the block checks, the three times kept apart, and privacy: a personal field never
reaches the records. No network; names in the fixtures are placeholders."""
from __future__ import annotations

import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml

from ingest.generic import arcgis, csv_json, rss, runner, socrata
from ingest.generic import fieldmap as F

FETCHED = "2026-11-04T12:00:00Z"
TZ = "America/Chicago"


def block(**kw):
    b = {"platform": "csv", "url": "https://example.invalid/reports.csv", "time_zone": TZ,
         "safe_fields": ["report_id", "start", "end", "kind", "water", "gallons", "notes"],
         "free_text": ["notes", "water"],
         "record": {"source_record_id": "report_id", "started_at": "start", "ended_at": "end",
                    "event_type": {"field": "kind", "map": {"Sanitary Sewer Overflow": "sso", "CSO": "cso"}},
                    "waterbody_text": "water", "volume": {"field": "gallons"}}}
    b.update(kw)
    return b


CSV = ("Report ID,Start,End,Kind,Water,Gallons,Notes,Reporter Name,Contact Email,Contact Phone\n"
       "A1,10/02/2026 14:30,10/02/2026 16:00,Sanitary Sewer Overflow,Mill Creek,\"1,200\","
       "\"Inspector Placeholder found a blockage; call 312-555-0142 or ops.person@example.org. Mr. Placeholder said so.\","
       "Pat Example,pat.example@example.org,312-555-0199\n"
       "A2,10/03/2026,,CSO,none,,Rain.,Pat Example,pat.example@example.org,312-555-0199\n"
       "A3,not a date,,Pump station failure,Mill Creek,2 MG,,Pat Example,pat.example@example.org,312-555-0199\n")


def build_csv(b=None, text=CSV, prev=()):
    b = b or block()
    return runner.build("x-test", b, csv_json.parse(b, text.encode()), FETCHED, list(prev))


# ---------------------------------------------------------------- privacy

def test_a_personal_field_never_reaches_the_records():
    recs, _ = build_csv()
    dump = json.dumps(recs)
    for s in ("Pat Example", "pat.example@example.org", "312-555-0199", "312-555-0142", "ops.person@example.org",
              "Placeholder", "reporter_name", "contact_email", "contact_phone"):
        assert s not in dump, s
    a1 = next(r for r in recs if r["source_record_id"] == "A1")
    assert set(a1["raw"]["row"]) <= set(block()["safe_fields"])
    assert "[email removed]" in a1["raw"]["row"]["notes"] and "[phone removed]" in a1["raw"]["row"]["notes"]


def test_a_personal_field_named_safe_is_refused_and_a_reviewed_one_still_leaves_raw():
    b = block(safe_fields=block()["safe_fields"] + ["reporter_name"])
    assert any("reporter_name" in e for e in runner.validate_block(b))
    with pytest.raises(F.SpecError):
        build_csv(b)
    # a reviewer may let a field through (an operator's office line, say); strip_personal still drops it from raw
    b = block(safe_fields=block()["safe_fields"] + ["contact_phone"],
              reviewed_fields={"contact_phone": "test: the office line of the utility"})
    recs, _ = build_csv(b)
    assert "312-555-0199" not in json.dumps(recs) and all("contact_phone" not in r["raw"]["row"] for r in recs)


def test_a_record_field_must_read_a_safe_field():
    b = block()
    b["record"]["discharger_name"] = "reporter_name"
    errs = runner.validate_block(b)
    assert any("not a safe field" in e for e in errs)


# ---------------------------------------------------------------- times, types, never invented

def test_times_precision_and_types_from_the_field_map():
    recs, stats = build_csv()
    by = {r["source_record_id"]: r for r in recs}
    a1, a2, a3 = by["A1"], by["A2"], by["A3"]
    assert (a1["started_at"], a1["ended_at"], a1["time_precision"]) == ("2026-10-02T14:30:00-05:00",
                                                                         "2026-10-02T16:00:00-05:00", "minute")
    assert a1["status"] == "ended" and a1["event_type"] == "sso" and a1["volume_gal"] == 1200
    assert (a2["started_at"], a2["time_precision"], a2["ended_at"], a2["status"]) == ("2026-10-03T00:00:00-05:00",
                                                                                       "day", None, "unknown")
    assert a2["water_slugs"] == [] and a2["raw"]["_water"]["why_none"].startswith("receiving water given as 'none'")
    # what cannot be read is kept, unknown, with the reason
    assert a3["event_type"] == "unknown" and a3["started_at"] is None and "unreadable" in a3["parse_error"]
    assert a3["raw"]["_source_type"] == "Pump station failure" and a3["volume_gal"] == 2_000_000
    # the three clocks stay apart: no source or publication time is made up from the fetch
    for r in recs:
        assert r["fetched_at"] == FETCHED and r["reported_at"] is None and r["published_at"] is None
        assert r["source_updated_at"] is None
    assert stats["by_type"] == {"sso": 1, "cso": 1, "unknown": 1}


def test_duration_status_map_end_before_start_and_epoch_wall_clock():
    b = {"platform": "json", "url": "https://example.invalid/x.json", "time_zone": "America/New_York",
         "json": {"records_path": "data.items"},
         "safe_fields": ["id", "began", "mins", "state", "ends", "loc.lat", "loc.lon"],
         "record": {"source_record_id": "id", "started_at": {"field": "began", "parse": "epoch_ms_wallclock"},
                    "ended_at": {"duration": {"minutes": "mins"}},
                    "status": {"field": "state", "map": {"open": "ongoing"}, "otherwise": "from_end"},
                    "event_type": {"const": "sso"},
                    "lat": {"field": "loc.lat", "parse": "number"}, "lon": {"field": "loc.lon", "parse": "number"}}}
    doc = {"data": {"items": [
        {"id": 1, "began": 1791717300000, "mins": "45", "state": "closed", "loc": {"lat": 39.3, "lon": -76.6}},
        {"id": 2, "began": 1791717300000, "mins": "45", "state": "OPEN", "loc": {"lat": 39.3}},
        {"id": 3, "began": 1791717300000, "mins": "-5", "state": "closed"}]}}
    recs, _ = runner.build("x-json", b, csv_json.parse(b, json.dumps(doc).encode()), FETCHED, [])
    by = {r["source_record_id"]: r for r in recs}
    assert (by["1"]["started_at"], by["1"]["ended_at"], by["1"]["status"]) == (
        "2026-10-11T11:15:00-04:00", "2026-10-11T12:00:00-04:00", "ended")
    assert by["1"]["lat"] == 39.3 and by["1"]["coord_source"] == "source"
    assert by["2"]["status"] == "ongoing" and by["2"]["ended_at"] is None and by["2"]["raw"]["_end_while_ongoing"]
    assert by["2"]["lat"] is None and by["2"]["lon"] is None            # one coordinate is no point
    assert by["3"]["ended_at"] is None and by["3"]["status"] == "unknown"   # a negative duration gives no end


def test_templates_filters_and_value_maps():
    ctx = F.Ctx("x", {"record": {}}, ZoneInfo(TZ), FETCHED)
    row = {"permit": "md0021555", "addr": "428 East Preston Street", "code": "jf", "v": 672000.07, "empty": ""}
    rec = {"started_at": "2026-05-23T02:05:00-04:00", "time_precision": "minute"}
    assert F.render("{permit|upper|slug}-{@started_at|compact}-{addr|address|slug}", row, rec, ctx) == \
        "md0021555-20260523T0205-428-e-preston-st"
    assert F.render("{empty|default:none}/{v|num}", row, rec, ctx) == "none/672,000.07"
    assert F.render("{empty} gallons", row, rec, ctx) is None
    assert F.value({"field": "code", "map": {"JF": "Jones Falls"}}, row, rec, ctx) == "Jones Falls"
    assert F.value({"field": "code", "map": {"X": "y"}, "unmapped": None}, row, rec, ctx) is None
    assert F.value({"field": "addr", "regex": r"(\d+) East", "replace": r"No. \1"}, row, rec, ctx) == "No. 428"
    assert F.value({"field": "code", "match": "regex", "map": {"^j": "starts with j"}}, row, rec, ctx) == "starts with j"


def test_dedupe_suffix_and_history_across_runs():
    b = block(dedupe={"repeats": "suffix", "order": ["-volume_gal"]}, history={"revisions": True, "track": ["kind"]})
    text = CSV + "A1,10/02/2026 14:30,10/02/2026 16:00,Sanitary Sewer Overflow,Mill Creek,\"5,000\",,,,\n"
    first, stats = build_csv(b, text)
    by = {r["event_id"]: r for r in first}
    assert by["x-test:A1"]["volume_gal"] == 5000 and by["x-test:A1~2"]["duplicate_of"] == "x-test:A1"
    assert stats["duplicates"]["repeated_rows"] == 1
    second, stats = runner.build("x-test", b, csv_json.parse(b, CSV.replace("Rain.", "Heavy rain.").encode()),
                                 "2026-11-05T12:00:00Z", first)
    by = {r["event_id"]: r for r in second}
    assert by["x-test:A2"]["raw"]["_first_seen_at"] == FETCHED
    assert by["x-test:A2"]["raw"]["_revisions"][0]["old_values"] == {"notes": "Rain."}
    assert by["x-test:A1~2"]["raw"]["_missing_from_source_since"] == "2026-11-05T12:00:00Z"
    assert stats["history"]["kept_missing"] == 1


def test_filter_keeps_only_matching_rows():
    b = block(filter=[{"field": "kind", "regex": "overflow|cso"}])
    recs, stats = build_csv(b)
    assert sorted(r["source_record_id"] for r in recs) == ["A1", "A2"] and stats["rows_kept_by_filter"] == 2


# ---------------------------------------------------------------- platforms on saved responses

RSS = """<?xml version="1.0"?><rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/"><channel><title>News</title>
<item><title>Beach closed after sewage overflow</title><link>https://example.invalid/n/1</link><guid>n-1</guid>
<pubDate>Tue, 03 Nov 2026 15:20:00 -0600</pubDate><description>&lt;p&gt;The county closed Example Beach.
Contact &lt;b&gt;press@example.org&lt;/b&gt;.&lt;/p&gt;</description><author>pat.example@example.org (Pat Example)</author>
<category>Health</category></item>
<item><title>Road work</title><link>https://example.invalid/n/2</link><pubDate>Mon, 02 Nov 2026 09:00:00 -0600</pubDate></item>
</channel></rss>"""
ATOM = """<?xml version="1.0" encoding="utf-8"?><feed xmlns="http://www.w3.org/2005/Atom"><title>Alerts</title>
<entry><id>urn:alert:7</id><title>Overflow advisory lifted</title><link href="https://example.invalid/a/7"/>
<published>2026-11-03T08:00:00Z</published><updated>2026-11-03T09:30:00Z</updated>
<author><name>Pat Example</name></author><summary>Lifted for Example Creek.</summary></entry></feed>"""


def rss_block(**kw):
    b = {"platform": "rss", "url": "https://example.invalid/feed.xml", "time_zone": TZ,
         "safe_fields": ["id", "title", "link", "published", "updated", "summary", "categories"],
         "free_text": ["title", "summary"],
         "filter": [{"field": "title", "regex": "sewage|overflow"}],
         "record": {"source_record_id": "id", "published_at": "published", "source_updated_at": "updated",
                    "event_type": {"field": "title", "match": "regex",
                                   "map": {"beach closed": "beach_closure", "advisory": "beach_advisory"}},
                    "status": {"field": "title", "match": "regex", "map": {"lifted": "advisory_lifted"},
                               "otherwise": "unknown"},
                    "advice_text": "summary", "source_url": "link"}}
    b.update(kw)
    return b


def test_rss_and_atom_items_keep_publication_time_apart_and_drop_authors():
    b = rss_block()
    recs, _ = runner.build("x-rss", b, rss.parse(b, RSS.encode()), FETCHED, [])
    assert len(recs) == 1
    r = recs[0]
    assert r["published_at"] == "2026-11-03T15:20:00-06:00" and r["started_at"] is None and r["fetched_at"] == FETCHED
    assert r["event_type"] == "beach_closure" and r["source_url"] == "https://example.invalid/n/1"
    assert "Pat Example" not in json.dumps(recs) and "press@example.org" not in json.dumps(recs)
    assert r["advice_text"].startswith("The county closed Example Beach.")
    a = runner.build("x-atom", b, rss.parse(b, ATOM.encode()), FETCHED, [])[0][0]
    assert (a["published_at"], a["source_updated_at"]) == ("2026-11-03T08:00:00+00:00", "2026-11-03T09:30:00+00:00")
    assert a["status"] == "advisory_lifted" and a["event_type"] == "beach_advisory" and "Pat Example" not in json.dumps(a)


def test_socrata_json_pages_and_metadata_time():
    b = {"platform": "socrata", "domain": "https://data.example.invalid", "dataset": "abcd-1234", "time_zone": TZ,
         "safe_fields": ["case_no", "start_date", "start_time", "type"],
         "record": {"source_record_id": "case_no", "started_at": {"field": "start_date", "time": "start_time"},
                    "event_type": {"field": "type", "map": {"SSO": "sso"}}}}
    pages = {"pages": [[{"case_no": "1", "start_date": "2026-11-01T00:00:00.000", "start_time": "07:00:00", "type": "SSO",
                         "contact_name": "Pat Example"}], [{"case_no": "2", "start_date": "2026-11-02T00:00:00.000"}]]}
    rows = socrata.parse(b, json.dumps(pages).encode())
    recs, stats = runner.build("x-soda", b, rows, FETCHED, [], {"rowsUpdatedAt": 1793634953})
    by = {r["source_record_id"]: r for r in recs}
    assert by["1"]["started_at"] == "2026-11-01T07:00:00-06:00" and by["1"]["time_precision"] == "minute"
    assert by["2"]["started_at"] == "2026-11-02T00:00:00-06:00" and by["2"]["time_precision"] == "day"
    assert by["1"]["source_updated_at"] == "2026-11-02T09:55:53-06:00" == stats["source_updated_at"]
    assert "Pat Example" not in json.dumps(recs)
    assert socrata.urls(b)["json"] == "https://data.example.invalid/resource/abcd-1234.json"


def test_arcgis_geometry_and_layer_edit_time():
    b = {"platform": "arcgis", "url": "https://example.invalid/arcgis/rest/services/X/FeatureServer/0", "time_zone": TZ,
         "safe_fields": ["OBJECTID", "STATUS", "_x", "_y"], "geometry": True, "metadata": True,
         "record": {"source_record_id": "OBJECTID", "event_type": {"const": "cso"},
                    "status": {"field": "STATUS", "map": {"Active": "ongoing"}, "otherwise": "unknown"},
                    "lat": "_y", "lon": "_x"}}
    page = {"features": [{"attributes": {"OBJECTID": 5, "STATUS": "Active", "EDITOR": "pexample"},
                          "geometry": {"x": -87.62, "y": 41.88}}]}
    recs, _ = runner.build("x-arc", b, arcgis.parse(b, json.dumps(page).encode()), FETCHED, [],
                           {"editingInfo": {"lastEditDate": 1793634953000}})
    r = recs[0]
    assert (r["lat"], r["lon"], r["status"]) == (41.88, -87.62, "ongoing")
    assert r["source_updated_at"] == "2026-11-02T09:55:53-06:00" and "pexample" not in json.dumps(recs)


# ---------------------------------------------------------------- the runner and the registry

def write_source(d: Path, sid: str, b: dict, **row):
    (d / f"{sid}.yaml").write_text(yaml.safe_dump({"id": sid, "name": sid, "enabled": True, "registry_ids": ["r1"],
                                                   **row, "fetch": b}))


def test_runner_writes_the_events_file_as_a_module_does(tmp_path, monkeypatch):
    src = tmp_path / "sources"
    src.mkdir()
    write_source(src, "x-live", {**block(), "live": True})
    write_source(src, "x-port", {**block(), "live": False})
    saved = tmp_path / "saved.csv"
    saved.write_text(CSV)
    monkeypatch.setattr(runner, "EVENTS_DIR", tmp_path / "events")
    assert runner.live_ids(src) == ["x-live"]
    # a block that is not live never writes the module's events file
    assert runner.run("x-port", file=str(saved), sources_dir=src) == 2
    out = tmp_path / "out.json"
    assert runner.run("x-port", file=str(saved), out=str(out), sources_dir=src) == 0
    d = json.loads(out.read_text())
    assert d["source_id"] == "x-port" and d["ok"] and d["count"] == 3 and len(d["records"]) == 3
    assert d["meta"]["generic"] is True and d["meta"]["registry_ids"] == ["r1"] and d["meta"]["platform"] == "csv"
    # a failed fetch keeps the previous records and says why
    assert runner.run("x-port", file=str(tmp_path / "missing.csv"), out=str(out), sources_dir=src) == 1
    d2 = json.loads(out.read_text())
    assert d2["ok"] is False and d2["count"] == 3 and "FileNotFoundError" in d2["error"]


def test_every_fetch_block_in_the_registry_is_valid():
    assert runner.check_all() == {}
    assert {"md-mde-overflows", "md-baltimore-sso"} <= set(runner.blocks())
    assert "md-mde-overflows" not in runner.live_ids()        # the ports stay off until they are switched over


def test_the_makefile_runs_the_live_generic_sources_after_the_modules():
    mk = (Path(__file__).resolve().parents[2] / "Makefile").read_text()
    ingest = mk.split("\ningest:", 1)[1].split("\n\n", 1)[0]
    assert "ingest.generic --list" in ingest
    assert ingest.index("INGEST_MODULES") < ingest.index("ingest.generic") < ingest.index("for m in $(INGEST_SNAPSHOTS)")


def test_every_example_in_the_documentation_is_a_valid_block():
    import re
    doc = (Path(__file__).resolve().parents[2] / "docs" / "generic-ingesters.md").read_text()
    examples = [yaml.safe_load(m)["fetch"] for m in re.findall(r"```yaml\n(.*?)```", doc, re.S)]
    assert {b["platform"] for b in examples} == {"socrata", "arcgis", "csv", "json", "rss", "snapshot"}
    for b in examples:
        assert runner.validate_block(b) == [], b["platform"]


def test_block_checks_catch_yaml_booleans_foreign_code_and_floating_midnight():
    b = yaml.safe_load("""
platform: csv
url: https://example.invalid/x.csv
safe_fields: [id, flag]
record:
  source_record_id: id
  status: {field: flag, map: {Yes: ongoing, No: ended}}
transform: os.system
""")
    errs = runner.validate_block(b)
    assert any("quote it" in e for e in errs) and any("is not in ingest.generic.transforms" in e for e in errs)
    tz = ZoneInfo(TZ)
    assert F.parse_datetime("2026-11-01T00:00:00.000", tz)[1] == "day"
    assert F.parse_datetime("2026-11-01T00:05:00", tz)[1] == "minute"
    assert F.parse_datetime("2026-11-01T00:00:00Z", tz)[1] == "minute"      # an instant with an offset is a time


def test_snapshot_runner_keeps_its_history_between_runs(tmp_path, monkeypatch):
    from ingest.generic import snapshot
    from tests.test_generic_parity import CSOCAST_BLOCK, polls
    src = tmp_path / "sources"
    src.mkdir()
    write_source(src, "x-snap", {**CSOCAST_BLOCK, "live": True})
    monkeypatch.setattr(snapshot, "state_path", lambda sid: tmp_path / "state" / f"{sid}-snapshot.json")
    out = tmp_path / "events.json"
    for i, (_, rows) in enumerate(polls()):
        f = tmp_path / f"poll{i}.json"
        f.write_text(json.dumps({"features": [{"attributes": r} for r in rows]}))
        assert runner.run("x-snap", file=str(f), out=str(out), sources_dir=src) == 0
    d = json.loads(out.read_text())
    assert d["meta"]["polls_total"] == 5 and d["count"] == 4
    # a snapshot that lost most of its units is a failed fetch: the records stay
    f = tmp_path / "short.json"
    f.write_text(json.dumps({"features": [{"attributes": polls()[0][1][0]}]}))
    assert runner.run("x-snap", file=str(f), out=str(out), sources_dir=src) == 1
    assert json.loads(out.read_text())["count"] == 4



# ---------------------------------------------------------------- review 2026-11-04: P1 and P2 fixes

def csv_block(**kw):
    b = block(**kw)
    return b


def test_phone_rule_leaves_number_ranges_with_units():
    from common import scrub_text
    for t in ("Hammond Branch, about 500-1000 feet away", "spilled 100-1500 gallons", "from 830-1030 am",
              "10-20 gallons", "between 100-2000 ft of pipe"):
        assert scrub_text(t) == t, t
    for t in ("call 312-555-0142", "call 555-0142 now", "(312) 555-0142", "312.555.0142"):
        assert "[phone removed]" in scrub_text(t), t
    recs, _ = build_csv(text=CSV.replace("Rain.", "Spilled 500-1000 gallons; call 312-555-0142."))
    a2 = next(r for r in recs if r["source_record_id"] == "A2")
    assert a2["raw"]["row"]["notes"] == "Spilled 500-1000 gallons; call [phone removed]."


def test_a_failing_transform_keeps_the_record_and_its_key_and_too_many_fail_the_run(tmp_path, monkeypatch):
    from ingest.generic import transforms

    @F.hook
    def boom(row, rec, notes, ctx):
        if row.get("report_id") != "A2":
            raise KeyError("CT")
    monkeypatch.setattr(transforms, "boom", boom, raising=False)
    b = block(transform="ingest.generic.transforms.boom", max_error_share=1.0)
    recs, stats = build_csv(b)
    a1 = next(r for r in recs if r["source_record_id"] == "A1")
    assert a1["started_at"] == "2026-10-02T14:30:00-05:00" and a1["event_type"] == "sso" and a1["volume_gal"] == 1200
    assert "KeyError" in a1["parse_error"] and a1["raw"]["_hook_errors"] and stats["hook_errors"] == 2
    # over the share (20% by default) the run fails and the previous file stays
    with pytest.raises(runner.RunFailed):
        build_csv(block(transform="ingest.generic.transforms.boom"))
    src = tmp_path / "s"
    src.mkdir()
    write_source(src, "x-boom", {**block(transform="ingest.generic.transforms.boom"), "live": False})
    saved = tmp_path / "saved.csv"
    saved.write_text(CSV)
    out = tmp_path / "out.json"
    out.write_text(json.dumps({"ok": True, "records": [{"event_id": "x-boom:old"}], "meta": {}}))
    assert runner.run("x-boom", file=str(saved), out=str(out), sources_dir=src) == 1
    d = json.loads(out.read_text())
    assert d["ok"] is False and d["records"] == [{"event_id": "x-boom:old"}] and "RunFailed" in d["error"]


def test_a_state_without_a_water_matcher_and_unregistered_code_are_refused():
    b = block(waters={"matcher": "ingest.generic.transforms.state_waters", "state": "CT"})
    assert any("waters.state 'CT' has no water matcher" in e for e in runner.validate_block(b))
    assert not any("waters.state" in e for e in runner.validate_block(block(
        waters={"matcher": "ingest.generic.transforms.state_waters", "state": "NY"})))
    import sys
    sys.modules.pop("ingest.generic.__main__", None)
    for fn in ("ingest.generic.__main__.main", "ingest.generic.runner.write_json", "ingest.md_waters.match_waters"):
        assert any("hook" in e for e in runner.validate_block(block(transform=fn))), fn
    assert "ingest.generic.__main__" not in sys.modules          # never imported by a check


def test_check_writes_nothing(tmp_path, monkeypatch):
    src = tmp_path / "s"
    src.mkdir()
    write_source(src, "x-a", {**block(), "live": True})
    write_source(src, "x-b", {**block(transform="ingest.generic.__main__.main"), "live": True})
    monkeypatch.setattr(runner, "EVENTS_DIR", tmp_path / "events")
    monkeypatch.setattr(runner, "STATE_DIR", tmp_path / "state")
    before = sorted(p for p in tmp_path.rglob("*"))
    bad = runner.check_all(src)
    assert set(bad) == {"x-b"}
    assert sorted(p for p in tmp_path.rglob("*")) == before


def test_duration_is_elapsed_across_clock_changes_in_the_generic_and_the_module():
    from common import end_after
    from datetime import datetime as D, timedelta as T
    ny = ZoneInfo("America/New_York")
    end, _ = end_after(D(2026, 2, 20, 21, 30, tzinfo=ny), T(days=31, hours=10, minutes=30), "minute")
    assert end.isoformat() == "2026-03-24T09:00:00-04:00"          # spring forward: the elapsed end, not 08:00
    end, _ = end_after(D(2026, 10, 31, 22, 0, tzinfo=ny), T(hours=6), "minute")
    assert end.isoformat() == "2026-11-01T03:00:00-05:00"          # fall back: 6 elapsed hours, not 04:00
    b = block(time_zone="America/New_York", safe_fields=["report_id", "start", "hours"], free_text=[],
              record={"source_record_id": "report_id", "started_at": "start",
                      "ended_at": {"duration": {"hours": "hours"}}, "event_type": {"const": "sso"}})
    text = "Report ID,Start,Hours\nD1,03/07/2026 22:00,6\nD2,11/03/2026,5\n"
    recs, _ = runner.build("x-dst", b, csv_json.parse(b, text.encode()), FETCHED, [])
    by = {r["source_record_id"]: r for r in recs}
    assert by["D1"]["ended_at"] == "2026-03-08T05:00:00-04:00"
    # a start known only to the day: the day of the latest end it allows, at day precision, no clock time invented
    assert (by["D2"]["ended_at"], by["D2"]["time_precision"]) == ("2026-11-04T00:00:00-05:00", "day")
    assert "known only to the day" in by["D2"]["raw"]["_basis"]["ended_at"]
    from ingest import md_mde_overflows as M
    r = M.build([{"overflow_type": "SSO", "npdes_no": "MD0000001", "start_date": "02/20/2026", "start_time": "21:30",
                  "duration_day": "31", "duration_hour": "10", "duration_minute": "30", "overflow_address": "1 Example St",
                  "owner_name": "", "discharge_volume": "", "overflow_cause": "", "receiving_water": "", "county": "",
                  "overflow_latitude": "", "overflow_longitude": "", "id": "1"}], {}, FETCHED, [], [], {})[0][0]
    assert r["ended_at"] == "2026-03-24T09:00:00-04:00"


def test_date_only_epochs_and_midnight_text_are_day_precision():
    tz = ZoneInfo("America/New_York")
    assert F.parse_epoch(1793491200000, "epoch_ms", tz) == (F.datetime(2026, 11, 1, tzinfo=tz), "day")
    assert F.parse_epoch(1793491200000, "epoch_ms_wallclock", tz)[1] == "day"
    assert F.parse_epoch(1793491260000, "epoch_ms", tz)[1] == "minute"
    for t in ("11/01/2026 12:00:00 AM", "11/01/2026 00:00:00", "2026-11-01T00:00:00.000"):
        dt, prec = F.parse_datetime(t, tz)
        assert (dt.date().isoformat(), prec) == ("2026-11-01", "day"), t
    assert F.parse_datetime("11/01/2026 12:00:00 PM", tz)[1] == "minute"


def test_time_zone_is_required_and_clock_change_times_are_noted():
    b = block()
    b.pop("time_zone")
    assert any("time_zone is missing" in e for e in runner.validate_block(b))
    b2 = {**block(time_zone="UTC"), "record": {**block()["record"], "started_at": {"field": "start", "parse": "epoch_ms"}}}
    assert not any("time_zone" in e for e in runner.validate_block(b2))
    b3 = block(time_zone="America/New_York")
    text = "Report ID,Start,End,Kind\nF1,11/01/2026 01:30,,CSO\nS1,03/08/2026 02:30,,CSO\n"
    recs, _ = runner.build("x-tz", b3, csv_json.parse(b3, text.encode()), FETCHED, [])
    by = {r["source_record_id"]: r for r in recs}
    assert "happened twice" in by["F1"]["raw"]["_time_notes"]["started_at"]
    assert "does not exist" in by["S1"]["raw"]["_time_notes"]["started_at"]


def test_a_future_end_is_not_ended_and_impossible_times_are_not_used():
    text = ("Report ID,Start,End,Kind\nU1,10/02/2026 14:30,11/30/2026 16:00,CSO\n"
            "U2,01/21/1970 00:00,,CSO\nU3,10/02/2027 14:30,,CSO\n")
    recs, _ = build_csv(text=text)
    by = {r["source_record_id"]: r for r in recs}
    assert by["U1"]["status"] == "unknown" and "after the fetch" in by["U1"]["parse_error"]
    assert by["U1"]["ended_at"] == "2026-11-30T16:00:00-06:00"        # the source's end is kept, not counted
    for k in ("U2", "U3"):
        assert by[k]["started_at"] is None and "outside 1990" in by[k]["parse_error"]
        assert by[k]["raw"]["_unused_times"]["started_at"]
    b = {**block(time_zone="UTC"), "record": {**block()["record"], "started_at": {"field": "start", "parse": "epoch_ms"}}}
    r = runner.build("x-ep", b, csv_json.parse(b, b"Report ID,Start\nE1,1793491260\n"), FETCHED, [])[0][0]
    assert r["started_at"] is None and "outside 1990" in r["parse_error"]          # seconds read as milliseconds


def test_personal_field_rule_covers_names_owners_callers_and_nested_objects():
    for f in ("Name", "Owner", "OwnerName", "Caller", "ReportedBy", "reported_by", "Complainant", "Resident",
              "site.owner", "PropertyOwner", "Submitter", "caller.phone"):
        assert F.personal_field(f), f
    for f in ("OBJECTID", "STATUS", "receiving_water", "overflow_address", "LOCATION", "site.lat"):
        assert not F.personal_field(f), f
    b = {"platform": "json", "url": "https://example.invalid/x.json", "time_zone": TZ, "json": {"records_path": "items"},
         "safe_fields": ["id", "site", "site.lat"], "record": {"source_record_id": "id", "discharger_name": "site.owner"}}
    errs = runner.validate_block(b)
    assert any("'site.owner', which is not a safe field" in e for e in errs)
    b["record"] = {"source_record_id": "id", "lat": {"field": "site.lat", "parse": "number"}}
    doc = {"items": [{"id": 1, "site": {"owner": "Pat Example", "caller": "Lee Example", "lat": 39.1}}]}
    r = runner.build("x-nest", b, csv_json.parse(b, json.dumps(doc).encode()), FETCHED, [])[0][0]
    assert "Example" not in json.dumps(r) and r["raw"]["_dropped_objects"] == ["site"] and r["lat"] is None
    # a discharger name read from a field is scrubbed as free text
    b2 = block(safe_fields=block()["safe_fields"] + ["filer"], reviewed_fields={"filer": "test: the utility"})
    b2["record"]["discharger_name"] = "filer"
    text = "Report ID,Start,Kind,Filer\nP1,10/02/2026 14:30,CSO,Mr. Placeholder (312-555-0142)\n"
    r = runner.build("x-filer", b2, csv_json.parse(b2, text.encode()), FETCHED, [])[0][0]
    assert r["discharger_name"] == "[name removed] ([phone removed])"


def test_snapshot_replays_never_touch_the_live_archive_and_units_compare_with_the_last_snapshot(tmp_path, monkeypatch):
    from ingest.generic import snapshot
    from tests.test_generic_parity import CSOCAST_BLOCK, polls
    src = tmp_path / "sources"
    src.mkdir()
    write_source(src, "x-snap", {**CSOCAST_BLOCK, "live": True})
    live_state = tmp_path / "live" / "x-snap-snapshot.json"
    monkeypatch.setattr(snapshot, "state_path", lambda sid: live_state)
    monkeypatch.setattr(runner, "EVENTS_DIR", tmp_path / "events")
    f = tmp_path / "poll.json"
    f.write_text(json.dumps({"features": [{"attributes": r} for r in polls()[0][1]]}))
    assert runner.run("x-snap", file=str(f), sources_dir=src) == 2           # a replay needs --out
    out = tmp_path / "replay.json"
    assert runner.run("x-snap", file=str(f), out=str(out), sources_dir=src) == 0
    assert not live_state.exists() and out.with_suffix(".snapshot.json").exists()
    # units are compared with the last snapshot, not with every unit ever seen
    assert not snapshot.too_few(2, {"units": {str(i): {} for i in range(10)}, "last_units_n": 3})
    assert snapshot.too_few(1, {"last_units_n": 3}) and snapshot.too_few(0, {})


class FakeSess:
    def __init__(self, pages, ignore_cursor=False):
        self.pages, self.calls, self.ignore = pages, [], ignore_cursor

    def get(self, url, params=None, timeout=None):
        self.calls.append(params)
        import re as _re
        m = _re.search(r"OBJECTID > (\d+)", (params or {}).get("where", ""))
        last = int(m.group(1)) if m and not self.ignore else -1
        feats = [f for f in self.pages if f["attributes"]["OBJECTID"] > last][:2]
        body = {"features": feats, "exceededTransferLimit": len(feats) == 2}

        class R:
            status_code, headers, content = 200, {}, json.dumps(body).encode()

            def raise_for_status(self):
                pass

            def json(self):
                return body
        return R()


def test_arcgis_pages_by_a_cursor_and_fails_loudly():
    feats = [{"attributes": {"OBJECTID": i, "STATUS": "x"}} for i in range(1, 6)]
    b = {"platform": "arcgis", "url": "https://example.invalid/FeatureServer/0", "safe_fields": ["OBJECTID", "STATUS"],
         "page_size": 2, "record": {"source_record_id": "OBJECTID"}}
    got = arcgis.fetch(b, FakeSess(feats))
    assert [r["OBJECTID"] for r in arcgis.parse(b, got.content)] == [1, 2, 3, 4, 5]
    with pytest.raises(RuntimeError, match="not moving"):
        arcgis.fetch(b, FakeSess(feats, ignore_cursor=True))     # a server that ignores the paging
    with pytest.raises(RuntimeError, match="max_rows"):
        arcgis.fetch({**b, "max_rows": 3}, FakeSess(feats))


def test_every_failure_is_written_and_every_setting_checked(tmp_path, monkeypatch):
    for bad in ({"wher": "1=1"}, {"filter": [{"field": "kind", "regex": "("}]},
                {"record": {**block()["record"], "status": {"field": "kind", "otherwise": "active"}}},
                {"record": {**block()["record"], "outfall_id": {"template": "{report_id|bogus}"}}},
                {"record": {**block()["record"], "volume": {"field": "gallons", "unit": "barrels"}}},
                {"history": {"keep_missing": True, "tracks": []}}):
        assert runner.validate_block(block(**bad)), bad
    src = tmp_path / "s"
    src.mkdir()
    write_source(src, "x-bad", {**block(wher="1=1"), "live": False})
    out = tmp_path / "out.json"
    assert runner.run("x-bad", file=str(tmp_path / "none.csv"), out=str(out), sources_dir=src) == 2
    d = json.loads(out.read_text())
    assert d["ok"] is False and "cannot run" in d["error"]
    (src / "broken.yaml").write_text("id: x\nfetch: [unclosed\n")
    problems = []
    runner.live_ids(src, problems)
    assert any("broken.yaml" in p for p in problems)


def test_a_live_block_and_its_module_never_both_write_one_events_file(tmp_path, monkeypatch):
    src = tmp_path / "s"
    src.mkdir()
    write_source(src, "md-mde-overflows", {**block(), "live": True})
    write_source(src, "x-free", {**block(), "live": True, "after": ["x-alpha"]})
    write_source(src, "x-alpha", {**block(), "live": True})
    problems = []
    assert runner.live_ids(src, problems) == ["x-alpha", "x-free"]       # after: x-alpha runs first
    assert any("md_mde_overflows.py still writes" in p for p in problems)
    monkeypatch.setattr(runner, "EVENTS_DIR", tmp_path / "events")
    saved = tmp_path / "saved.csv"
    saved.write_text(CSV)
    assert runner.run("md-mde-overflows", file=str(saved), sources_dir=src) == 2
    assert not (tmp_path / "events").exists()
    # --out inside the events directory would be read as a feed
    assert runner.run("x-free", file=str(saved), out=str(tmp_path / "events" / "x.json"), sources_dir=src) == 2


def test_a_short_response_fails_and_the_meta_uses_the_published_names(tmp_path, monkeypatch):
    src = tmp_path / "s"
    src.mkdir()
    write_source(src, "x-m", {**block(meta={"credit": "Example", "caveat": "As filed.", "time_basis": "Local time."}),
                              "live": False})
    out = tmp_path / "out.json"
    saved = tmp_path / "saved.csv"
    saved.write_text(CSV)
    assert runner.run("x-m", file=str(saved), out=str(out), sources_dir=src) == 0
    m = json.loads(out.read_text())["meta"]
    assert (m["disclaimer"], m["time_note"], m["timezone"]) == ("As filed.", "Local time.", TZ)
    short = tmp_path / "short.csv"
    short.write_text(CSV.splitlines()[0] + "\n")
    assert runner.run("x-m", file=str(short), out=str(out), sources_dir=src) == 1
    d = json.loads(out.read_text())
    assert d["ok"] is False and d["count"] == 3 and "rows in the response" in d["error"]


def test_honorifics_in_capitals_are_scrubbed():
    assert F.scrub_people("MR. PLACEHOLDER reported it") == "[name removed] reported it"
